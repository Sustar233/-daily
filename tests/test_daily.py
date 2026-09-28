import importlib.util
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'skills/zhihu-daily/scripts'))

spec = importlib.util.spec_from_file_location('daily', Path(__file__).parents[1] / 'skills/zhihu-daily/scripts/daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


class DailyTests(unittest.TestCase):
    def test_exclusion_wins_and_ranking_is_stable(self):
        items = [dict(id=str(i), title='x', summary='', rank=i) for i in range(1, 5)]
        prefs = dict(exclude_topics=['娱乐'], prefer_topics=['科技'], exclude_keywords=[], prefer_keywords=[], max_topics=10)
        labels = {'1': ['娱乐', '科技'], '2': ['体育'], '3': ['科技'], '4': ['科技']}
        self.assertEqual([x['id'] for x in daily.select_topics(items, prefs, labels)], ['3', '4', '2'])

    def test_answer_matching_and_popularity(self):
        def answer(url, votes):
            return dict(Url=url, VoteUpCount=votes, ContentText='<p>正文</p>')
        results = [answer('https://www.zhihu.com/question/12/answer/1', 3),
                   answer('https://www.zhihu.com/question/123/answer/2', 9999),
                   answer('https://evil.example/question/12/answer/3', 999),
                   answer('https://www.zhihu.com/question/12/answer/4', 20)]
        self.assertEqual([x['id'] for x in daily.matching_answers(results, '12', 2)], ['4', '1'])

    def test_renderer_escapes_and_rejects_unsourced_answers(self):
        stamp = daily.now()
        source = dict(fetched_at=stamp, items=[dict(id='12', rank=1, categories=['科技'], url='https://www.zhihu.com/question/12', answers=[])])
        item = dict(id='12', title_zh='<script>bad</script>', title_en='Test', summary_zh='摘要', summary_en='Summary', answers=[])
        digest = dict(fetched_at=stamp, items=[item])
        full, email = daily.render(digest, source)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', full)
        self.assertNotIn('<script>bad', full)
        self.assertIn('href="#q12"', full)
        self.assertIn('id="q12"', full)
        item['answers'] = [dict(id='fake', summary_zh='x', summary_en='x')]
        with self.assertRaises(ValueError):
            daily.render(digest, source)

    def test_stale_source_is_rejected(self):
        with self.assertRaises(ValueError):
            daily.validate_digest(dict(items=[]), dict(fetched_at='2000-01-01T00:00:00+08:00', items=[]))

    def test_paragraph_pair_is_required(self):
        stamp = daily.now()
        source = dict(fetched_at=stamp, items=[dict(id='1', answers=[dict(id='2')])])
        answer = dict(id='2', summary_en='English', summary_zh='中文', paragraphs=[dict(en='Only English')])
        digest = dict(fetched_at=stamp, items=[dict(id='1', title_en='Title', title_zh='标题', summary_en='Summary', summary_zh='摘要', answers=[answer])])
        with self.assertRaises(ValueError):
            daily.validate_digest(digest, source)

    def test_glossary_escapes_text_and_does_not_repeat(self):
        from reader import annotated
        used = set()
        first = annotated('Tariff and tariff <x>', {'tariff': '关税<script>'}, used)
        self.assertEqual(first.count('class="gloss"'), 1)
        self.assertIn('&lt;script&gt;', first)
        self.assertIn('&lt;x&gt;', first)
        self.assertNotIn('class="gloss"', annotated('Tariff', {'tariff': '关税'}, used))


if __name__ == '__main__':
    unittest.main()
