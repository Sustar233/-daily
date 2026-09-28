import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

scripts=Path(__file__).parents[1]/'skills/zhihu-daily/scripts'
sys.path.insert(0,str(scripts))
import pipeline
from daily import read,write,now


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.prefs=dict(english_level='CET-4',answer_target_words=[120,220],max_topics=10,answers_per_topic=2,
                        exclude_topics=[],prefer_topics=[],exclude_keywords=[],prefer_keywords=[],
                        delivery='html_attachment',recipient='test@example.com')
        write(self.root/'preferences.json',self.prefs)
        self.source={'fetched_at':now(),'items':[dict(id='12',title='Question',summary='Background',rank=1,categories=[],url='https://www.zhihu.com/question/12',answers=[dict(id='34',content='原文',author='名字',votes=30,url='https://www.zhihu.com/question/12/answer/34')])]}
        write(self.root/'output/sources.json',self.source)

    def edit_data(self):
        item=self.source['items'][0]
        return {'topics':{pipeline.topic_key(item,self.prefs):dict(title_en='Title',summary_en='Background',summary_zh='背景')},
                'answers':{pipeline.answer_key(item,item['answers'][0],self.prefs):dict(headline_en='What matters',paragraphs=[dict(en='I think practice matters.',zh='我认为练习很重要。')])}}

    def test_cache_hit_and_changed_source_invalidation(self):
        edits=self.edit_data();write(self.root/'output/edits.json',edits)
        with contextlib.redirect_stdout(io.StringIO()):pipeline.build(self.root,self.root/'output/edits.json',True)
        work,hits=pipeline.make_work(self.source,self.prefs,pipeline.load_cache(self.root))
        self.assertEqual(hits,dict(topics=1,answers=1));self.assertEqual(work['answers'],[])
        self.source['items'][0]['answers'][0]['content']='更新后的原文'
        work,hits=pipeline.make_work(self.source,self.prefs,pipeline.load_cache(self.root))
        self.assertEqual(hits,dict(topics=1,answers=0));self.assertEqual(len(work['answers']),1)

    def test_no_preference_skips_model_classification(self):
        def fake_api(endpoint,params):
            if endpoint=='hot_list':return {'Items':[dict(Title='Question',Summary='Background',Url='https://www.zhihu.com/question/12')]}
            return {'Items':[dict(Url='https://www.zhihu.com/question/12/answer/34',ContentText='原文',VoteUpCount=30)]}
        with patch.object(pipeline,'api',side_effect=fake_api),patch.object(pipeline.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):pipeline.prepare(self.root)
        self.assertFalse((self.root/'output/classification-work.json').exists())
        self.assertEqual(read(self.root/'output/work-report.json')['new_answers'],1)

    def test_unknown_preference_pauses_before_answer_requests(self):
        self.prefs['exclude_topics']=['娱乐'];write(self.root/'preferences.json',self.prefs)
        with patch.object(pipeline,'api',return_value={'Items':[dict(Title='Question',Summary='',Url='https://www.zhihu.com/question/12')]}) as api,contextlib.redirect_stdout(io.StringIO()):pipeline.prepare(self.root)
        self.assertEqual(api.call_count,1)
        self.assertTrue((self.root/'output/classification-work.json').exists())

    def test_reading_setting_invalidates_language_cache(self):
        item=self.source['items'][0];key=pipeline.answer_key(item,item['answers'][0],self.prefs)
        self.prefs['english_level']='A2'
        self.assertNotEqual(key,pipeline.answer_key(item,item['answers'][0],self.prefs))

    def test_classification_resume_does_not_refetch_the_hot_list(self):
        self.prefs['exclude_topics']=['娱乐'];write(self.root/'preferences.json',self.prefs)
        with patch.object(pipeline,'api',return_value={'Items':[dict(Title='Question',Summary='',Url='https://www.zhihu.com/question/12')]}) as api,contextlib.redirect_stdout(io.StringIO()):pipeline.prepare(self.root)
        work=read(self.root/'output/classification-work.json')
        write(self.root/'output/labels.json',{work['items'][0]['key']:[]})
        with contextlib.redirect_stdout(io.StringIO()):pipeline.import_labels(self.root,self.root/'output/labels.json')
        with patch.object(pipeline,'api',return_value={'Items':[]}) as api,patch.object(pipeline.time,'sleep'),contextlib.redirect_stdout(io.StringIO()):pipeline.prepare(self.root,resume=True)
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.args[0],'zhihu_search')

    def test_excerpt_preserves_start_middle_end_and_discloses_omission(self):
        text='A'*100+'B'*100+'C'*100
        short,omitted=pipeline.source_excerpt(text,80)
        self.assertTrue(omitted);self.assertTrue(short.startswith('A'));self.assertTrue(short.endswith('C'));self.assertIn('B',short);self.assertIn('省略',short)

    def test_third_person_voice_is_rejected(self):
        edits=self.edit_data()
        next(iter(edits['answers'].values()))['paragraphs'][0]['en']='The author says practice matters.'
        write(self.root/'output/edits.json',edits)
        with self.assertRaisesRegex(ValueError,'Third-person'):pipeline.build(self.root,self.root/'output/edits.json',True)

    def test_preview_cannot_be_sent_as_fresh_daily(self):
        write(self.root/'output/build-report.json',dict(preview=True))
        with self.assertRaisesRegex(ValueError,'Preview'):pipeline.mail(self.root)

    def test_same_day_refresh_does_not_bypass_duplicate_delivery_check(self):
        edits=self.edit_data();write(self.root/'output/edits.json',edits)
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.build(self.root,self.root/'output/edits.json')
            pipeline.mail(self.root)
        pending=read(self.root/'output/pending-delivery.json')
        pending['message_id']='sent123';write(self.root/'output/last-delivery.json',pending)
        import datetime as dt
        self.source['fetched_at']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=1)).isoformat()
        write(self.root/'output/sources.json',self.source)
        with contextlib.redirect_stdout(io.StringIO()):pipeline.build(self.root)
        with self.assertRaisesRegex(ValueError,'already sent'):pipeline.mail(self.root)


if __name__=='__main__':unittest.main()
