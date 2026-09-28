"""Zhihu daily data collection and bilingual HTML rendering (stdlib only).

Translation and semantic topic labels are supplied by the invoking Codex skill.
This program never sends mail and never calls a separate model API.
"""
import argparse
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')


def api(endpoint, params):
    secret = os.environ.get('ZHIHU_ACCESS_SECRET', '').strip()
    if not secret:
        raise ValueError('Missing Zhihu credential')
    url = 'https://developer.zhihu.com/api/v1/content/' + endpoint + '?' + urlencode(params)
    req = Request(url, headers={'Authorization': 'Bearer ' + secret,
                               'X-Request-Timestamp': str(int(time.time()))})
    for attempt in range(2):
        try:
            with build_opener(NoRedirect).open(req, timeout=20) as response:
                data = json.load(response)
            if data.get('Code') not in (0, '0'):
                raise ValueError('Zhihu API returned a non-success business status')
            if not isinstance(data.get('Data', {}).get('Items'), list):
                raise ValueError('Unexpected Zhihu response schema')
            return data['Data']
        except HTTPError as exc:
            raise ValueError(f'Zhihu HTTP {exc.code}; no automatic retry') from None
        except (URLError, TimeoutError):
            if attempt:
                raise ValueError('Zhihu network request failed after two attempts') from None
            time.sleep(1)


def question_id(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.zhihu.com', 'zhihu.com'):
        raise ValueError('Expected an HTTPS Zhihu question URL')
    match = re.match(r'^/question/(\d+)(?:/|$)', parsed.path)
    if not match:
        raise ValueError('Question ID not found')
    return match.group(1)


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = TextOnly()
    parser.feed(value or '')
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def select_topics(items, preferences, labels):
    """Semantic categories come from Codex; strict exclusions always win."""
    selected = []
    for item in items:
        qid = item['id']
        if qid not in labels:
            raise ValueError(f'Missing category labels for {qid}')
        categories = labels[qid]
        if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
            raise ValueError('Categories must be lists of strings')
        text = (item['title'] + ' ' + item['summary']).casefold()
        if set(categories) & set(preferences['exclude_topics']):
            continue
        if any(word.casefold() in text for word in preferences['exclude_keywords']):
            continue
        boost = len(set(categories) & set(preferences['prefer_topics']))
        boost += sum(word.casefold() in text for word in preferences['prefer_keywords'])
        selected.append(dict(item, categories=categories, preference_score=boost))
    selected.sort(key=lambda item: (-item['preference_score'], item['rank']))
    return selected[:preferences['max_topics']]


def matching_answers(results, qid, count):
    found = {}
    for result in results:
        url = result.get('Url', '')
        try:
            if question_id(url) != qid:
                continue
        except ValueError:
            continue
        match = re.match(r'^/question/\d+/answer/(\d+)$', urlparse(url).path.rstrip('/'))
        if not match or not result.get('ContentText'):
            continue
        aid = match.group(1)
        try:
            votes = max(0, int(result.get('VoteUpCount') or 0))
        except (ValueError, TypeError):
            votes = 0
        found[aid] = {'id': aid, 'url': url, 'author': result.get('AuthorName') or '匿名用户',
                      'votes': votes, 'content': plain(result['ContentText'])}
    return sorted(found.values(), key=lambda answer: -answer['votes'])[:count]


def validate_digest(digest, source, *, preview=False):
    stamp = dt.datetime.fromisoformat(source['fetched_at'])
    age = dt.datetime.now(dt.timezone.utc) - stamp
    if not preview and not dt.timedelta(minutes=-5) <= age <= dt.timedelta(hours=2):
        raise ValueError('Source is older than two hours; fetch a fresh hot list')
    if digest.get('fetched_at') != source['fetched_at']:
        raise ValueError('Digest timestamp does not match source')
    topics = {item['id']: item for item in source['items']}
    if [item['id'] for item in digest['items']] != [item['id'] for item in source['items']]:
        raise ValueError('Digest must preserve selected topic IDs and order')
    for item in digest['items']:
        raw = topics[item['id']]
        for field in ('title_zh', 'title_en', 'summary_zh', 'summary_en'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f'Missing bilingual field: {field}')
        answers = {a['id']: a for a in raw.get('answers', [])}
        if len({a['id'] for a in item['answers']}) != len(item['answers']):
            raise ValueError('Duplicate answer ID')
        for answer in item['answers']:
            if answer['id'] not in answers:
                raise ValueError('Answer lacks a matching source')
            for field in ('summary_zh', 'summary_en'):
                if not isinstance(answer.get(field), str) or not answer[field].strip():
                    raise ValueError('Missing bilingual answer summary')
            if 'paragraphs' in answer:
                if not isinstance(answer['paragraphs'], list) or not answer['paragraphs']:
                    raise ValueError('Answer paragraphs must be a nonempty list')
                for paragraph in answer['paragraphs']:
                    if not all(isinstance(paragraph.get(lang), str) and paragraph[lang].strip()
                               for lang in ('en', 'zh')):
                        raise ValueError('Each answer paragraph needs English and Chinese')


def render(digest, source, *, preview=False):
    validate_digest(digest, source, preview=preview)
    from reader import render_reader
    return render_reader(digest, source, preview=preview)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, default=Path('F:/codexCoding/dailyZhihu'))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('hot')
    select = sub.add_parser('select')
    select.add_argument('--labels', type=Path, required=True)
    sub.add_parser('answers')
    rendering = sub.add_parser('render')
    rendering.add_argument('--digest', type=Path, required=True)
    rendering.add_argument('--preview', action='store_true', help='Render saved sources for UI review; never treat this output as a fresh daily')
    args = parser.parse_args()
    out = args.workspace / 'output'
    prefs = read(args.workspace / 'preferences.json')
    if not 1 <= prefs['max_topics'] <= 30 or not 1 <= prefs['answers_per_topic'] <= 5:
        raise ValueError('Topic count must be 1–30; answers per topic must be 1–5')
    if args.action == 'hot':
        data = api('hot_list', {'Limit': 30})
        items, seen = [], set()
        for rank, item in enumerate(data['Items'], 1):
            qid = question_id(item['Url'])
            if qid in seen:
                continue
            seen.add(qid)
            items.append({'id': qid, 'rank': rank, 'title': item['Title'],
                          'url': item['Url'], 'summary': plain(item.get('Summary', ''))})
        if not items:
            raise ValueError('Zhihu returned an empty hot list')
        write(out / 'hot.json', {'fetched_at': now(), 'items': items})
        print(f'Saved {len(items)} hot topics to {out / "hot.json"}')
    elif args.action == 'select':
        hot = read(out / 'hot.json')
        hot['items'] = select_topics(hot['items'], prefs, read(args.labels))
        write(out / 'selected.json', hot)
        print(f'Selected {len(hot["items"])} topics')
    elif args.action == 'answers':
        source = read(out / 'selected.json')
        for item in source['items']:
            try:
                data = api('zhihu_search', {'Query': item['title'], 'Count': 10})
                item['answers'] = matching_answers(data['Items'], item['id'], prefs['answers_per_topic'])
                item['answer_status'] = 'ok' if item['answers'] else 'no_matching_answer'
            except ValueError as exc:
                item['answers'] = []
                item['answer_status'] = str(exc)
            print(f'Rank {item["rank"]}: {len(item["answers"])} matching answers', flush=True)
            time.sleep(0.4)
        write(out / 'sources.json', source)
    elif args.action == 'render':
        source = read(out / 'sources.json')
        digest = read(args.digest)
        full, email = render(digest, source, preview=args.preview)
        (out / 'zhihu-daily.html').write_text(full, encoding='utf-8')
        (out / 'email.html').write_text(email, encoding='utf-8')
        print(f'Rendered email and reader in {out}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
