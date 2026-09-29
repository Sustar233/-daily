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

    def test_headline_rule_skips_network_and_language_work(self):
        self.prefs.update(headline_only_topics=['体育比赛'], topic_rules={'体育比赛':{'any':['乒乓球'],'context':['决赛']}})
        write(self.root/'preferences.json',self.prefs)
        hot={'Items':[dict(Title='乒乓球男单决赛，林诗栋4-0夺冠，如何评价本场比赛？',Summary='',Url='https://www.zhihu.com/question/12')]}
        with patch.object(pipeline,'api',return_value=hot) as api,contextlib.redirect_stdout(io.StringIO()):
            pipeline.prepare(self.root)
            work=read(self.root/'output/language-work.json')
            self.assertNotIn('summary',work['topics'][0])
            write(self.root/'output/edits.json',{'topics':{work['topics'][0]['key']:{'title_en':'Lin wins the table tennis final 4–0','title_zh':'林诗栋以4比0赢得乒乓球决赛'}},'answers':{}})
            pipeline.build(self.root,self.root/'output/edits.json',preview=True)
        self.assertEqual(api.call_count,1)
        work=read(self.root/'output/language-work.json')
        self.assertEqual(len(work['topics']),1)
        self.assertEqual(work['answers'],[])
        item=read(self.root/'output/digest.json')['items'][0]
        self.assertEqual(item['title_en'],'Lin wins the table tennis final 4–0')
        self.assertNotIn('如何评价',work['topics'][0]['title'])
        self.assertEqual(item['answers'],[])
        self.assertEqual(item['reading_depth'],'headline')

    def test_depth_invalidation_is_limited_to_preferred_topic(self):
        first=self.source['items'][0]
        other=dict(first,id='99',title='中美关税框架',categories=[])
        keys=[pipeline.answer_key(x,x['answers'][0],self.prefs) for x in (first,other)]
        self.prefs.update(prefer_topics=['中美经贸'],topic_rules={'中美经贸':{'any':['中美'],'context':['关税','贸易']}})
        self.assertEqual(keys[0],pipeline.answer_key(first,first['answers'][0],self.prefs))
        self.assertNotEqual(keys[1],pipeline.answer_key(other,other['answers'][0],self.prefs))
        work,_=pipeline.make_work(dict(items=[other]),self.prefs,pipeline.load_cache(self.root))
        self.assertEqual(work['answers'][0]['target_words'],[220,340])
        self.assertEqual(work['answers'][0]['reading_depth'],'deep')

    def test_offline_preferences_preserve_saved_sources(self):
        self.prefs['headline_only_keywords']=['Question']
        write(self.root/'preferences.json',self.prefs)
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.prepare(self.root,offline=True)
            work=read(self.root/'output/language-work.json')
            write(self.root/'output/edits.json',{'topics':{work['topics'][0]['key']:{'title_en':'Headline','title_zh':'标题'}},'answers':{}})
            pipeline.build(self.root,self.root/'output/edits.json',preview=True)
        self.assertEqual(len(read(self.root/'output/sources.json')['items'][0]['answers']),1)
        self.assertEqual(read(self.root/'output/digest.json')['items'][0]['answers'],[])

    def test_headline_preference_overrides_deep_reading(self):
        self.prefs.update(headline_only_keywords=['Question'],prefer_keywords=['Question'])
        work,_=pipeline.make_work(self.source,self.prefs,pipeline.load_cache(self.root))
        self.assertEqual(work['answers'],[])
        self.assertEqual(work['topics'][0]['reading_depth'],'headline')

    def test_literal_style_invalidates_old_translation_cache(self):
        item=self.source['items'][0]
        old=pipeline.answer_key(item,item['answers'][0],self.prefs)
        self.prefs['translation_style']='literal-aligned-v1'
        self.assertNotEqual(old,pipeline.answer_key(item,item['answers'][0],self.prefs))

    def test_email_is_minimal_with_one_dated_html_attachment(self):
        edits=self.edit_data();write(self.root/'output/edits.json',edits)
        with contextlib.redirect_stdout(io.StringIO()):pipeline.build(self.root,self.root/'output/edits.json')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):pipeline.mail(self.root)
        parts=json.loads(output.getvalue())['payload']['parts']
        self.assertEqual(len(parts),2)
        self.assertLess(len(parts[0]['body']['content']),350)
        self.assertNotIn('<h2',parts[0]['body']['content'])
        attachment=parts[1]
        self.assertEqual(attachment['content_disposition'],'attachment')
        self.assertEqual(attachment['filename'],'zhihu-daily-'+self.source['fetched_at'][:10]+'.html')
        self.assertIn(attachment['filename'],parts[0]['body']['content'])

    def test_preferred_order_survives_mail_validation(self):
        from preferences import apply_reading_preferences
        self.source['items'].append(dict(self.source['items'][0],id='56',title='Trade',rank=2,answers=[]))
        self.prefs['prefer_keywords']=['Trade']
        selected=apply_reading_preferences(self.source,self.prefs)
        self.assertEqual([x['id'] for x in selected['items']],['56','12'])
        self.assertEqual([x['id'] for x in self.source['items']],['12','56'])

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
        self.source['fetched_at']=dt.datetime.fromisoformat(self.source['fetched_at']).replace(microsecond=1).isoformat()
        write(self.root/'output/sources.json',self.source)
        with contextlib.redirect_stdout(io.StringIO()):pipeline.build(self.root)
        with self.assertRaisesRegex(ValueError,'already sent'):pipeline.mail(self.root)


if __name__=='__main__':unittest.main()
