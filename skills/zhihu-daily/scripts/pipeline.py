"""Incremental daily pipeline: only uncached language work enters model context."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from daily import api, matching_answers, now, plain, question_id, read, render, select_topics, write

EDITOR_VERSION = 'direct-voice-v1'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]


def language_key(kind, value, prefs):
    return fingerprint([EDITOR_VERSION, kind, value, prefs['english_level'], prefs.get('answer_target_words', [120,220]), prefs.get('source_max_chars',5000)])


def load_cache(root):
    path = root / '.private' / 'editor-cache.json'
    return read(path) if path.exists() else {'topics': {}, 'answers': {}, 'labels': {}}


def topic_key(item, prefs):
    return language_key('topic', [item['title'], item['summary']], prefs)


def answer_key(item, answer, prefs):
    return language_key('answer', [item['title'], answer['content']], prefs)


def source_excerpt(text, limit):
    """Keep opening, middle and ending; explicitly disclose omitted source text."""
    if len(text) <= limit:
        return text, False
    first = limit // 2
    last = limit // 4
    middle = limit - first - last
    midstart = max(first, len(text) // 2 - middle // 2)
    return text[:first] + '\n[中间内容省略]\n' + text[midstart:midstart+middle] + '\n[中间内容省略]\n' + text[-last:], True


def make_work(source, prefs, cache):
    work = {'topics': [], 'answers': [], 'questions': {}}
    hits = {'topics': 0, 'answers': 0}
    for index,item in enumerate(source['items'],1):
        key = topic_key(item, prefs)
        if key in cache['topics']:
            hits['topics'] += 1
        else:
            work['topics'].append({'key': key, 'title': item['title'], 'summary': item['summary']})
        for answer in item.get('answers', []):
            key = answer_key(item, answer, prefs)
            if key in cache['answers']:
                hits['answers'] += 1
            else:
                text, shortened = source_excerpt(answer['content'], prefs.get('source_max_chars', 5000))
                q = str(index)
                work['questions'][q] = item['title']
                work['answers'].append({'key': key, 'q': q, 'text': text, 'excerpted': shortened})
    return work, hits


def prepare(root, offline=False, resume=False):
    prefs = read(root / 'preferences.json')
    cache = load_cache(root)
    out = root / 'output'
    if offline:
        source = read(out / 'sources.json')
    else:
        if resume:
            hot_data = read(out / 'hot.json')
            age = dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(hot_data['fetched_at'])
            if not dt.timedelta(minutes=-5) <= age <= dt.timedelta(hours=2):
                raise ValueError('Saved hot list is stale; run prepare without --resume')
            hot = hot_data['items']
        else:
            data = api('hot_list', {'Limit': 30})
            hot, seen = [], set()
            for rank, item in enumerate(data['Items'], 1):
                qid = question_id(item['Url'])
                if qid in seen:
                    continue
                seen.add(qid)
                hot.append({'id': qid, 'rank': rank, 'title': item['Title'], 'summary': plain(item.get('Summary','')), 'url': item['Url']})
            if not hot:
                raise ValueError('Empty live hot list')
            hot_data = {'fetched_at': now(), 'items': hot}
        required = sorted(set(prefs['exclude_topics'] + prefs['prefer_topics']))
        labels, missing = {}, []
        for item in hot:
            key = fingerprint([item['title'], item['summary'], required])
            if not required:
                labels[item['id']] = []
            elif key in cache['labels']:
                labels[item['id']] = cache['labels'][key]
            else:
                missing.append({'key': key, 'id': item['id'], 'title': item['title'], 'summary': item['summary']})
        write(out / 'hot.json', hot_data)
        if missing:
            write(out / 'classification-work.json', {'required_topics':required, 'items':missing})
            print(json.dumps({'status':'classification_needed','file':str(out/'classification-work.json'),'count':len(missing)},ensure_ascii=False))
            return
        source = dict(hot_data, items=select_topics(hot,prefs,labels))
        network_cache_path = root / '.private' / 'answer-fetch-cache.json'
        network_cache = read(network_cache_path) if network_cache_path.exists() else {}
        for item in source['items']:
            cached = network_cache.get(item['id'], {})
            if cached.get('title') == item['title'] and time.time()-cached.get('checked_at',0)<900:
                item['answers'] = cached['answers'][:prefs['answers_per_topic']]
                item['answers_checked_at'] = cached['checked_at']
            else:
                try:
                    data = api('zhihu_search', {'Query':item['title'],'Count':10})
                    answers = matching_answers(data['Items'],item['id'],5)
                    item['answers'] = answers[:prefs['answers_per_topic']]
                    item['answers_checked_at'] = time.time()
                    network_cache[item['id']] = dict(title=item['title'],answers=answers,checked_at=item['answers_checked_at'])
                except ValueError as exc:
                    item['answers'] = []
                    item['answer_status'] = str(exc)
                time.sleep(.4)
        write(network_cache_path, network_cache)
        write(out / 'selected.json', source)
        write(out / 'sources.json', source)
    work, hits = make_work(source,prefs,cache)
    write(out / 'language-work.json', work)
    chars = len(json.dumps(work,ensure_ascii=False,separators=(',',':')))
    report = {'status':'language_needed' if work['topics'] or work['answers'] else 'ready_to_build',
              'file':str(out/'language-work.json'),'topics':len(source['items']),
              'new_topics':len(work['topics']),'new_answers':len(work['answers']),
              'cache_hits':hits,'model_input_chars':chars,'offline':offline}
    write(out / 'work-report.json', report)
    print(json.dumps(report,ensure_ascii=False))


def import_labels(root, edits):
    work = read(root/'output/classification-work.json')
    cache = load_cache(root)
    supplied = read(edits)
    required = set(work['required_topics'])
    for item in work['items']:
        categories = supplied[item['key']]
        if not isinstance(categories,list) or not all(isinstance(c,str) for c in categories) or not set(categories)<=required:
            raise ValueError('Classification labels must be a subset of the requested topics')
        cache['labels'][item['key']] = categories
    write(root/'.private/editor-cache.json',cache)
    print('Classification cached. Run prepare --resume.')


def build(root, edits=None, preview=False):
    prefs = read(root/'preferences.json')
    source = read(root/'output/sources.json')
    cache = load_cache(root)
    changes = read(edits) if edits else {'topics':{},'answers':{}}
    work,_ = make_work(source,prefs,cache)
    expected = {kind:{x['key'] for x in work[kind]} for kind in ('topics','answers')}
    for kind in ('topics','answers'):
        for key,value in changes.get(kind,{}).items():
            if key not in expected[kind]:
                raise ValueError('Unexpected edit key; prepare current sources first')
            cache[kind][key] = value
    glossary_path = Path(__file__).parent/'glossary.json'
    digest = {'fetched_at':source['fetched_at'],'items':[],'glossary':read(glossary_path) if glossary_path.exists() else {}}
    if not source['items']:
        raise ValueError('No topics remain after filtering; do not send an empty daily')
    for item in source['items']:
        key = topic_key(item,prefs)
        if key not in cache['topics']:
            raise ValueError('Missing topic language work')
        edited = cache['topics'][key]
        result = {'id':item['id'],'title_zh':item['title'],'title_en':edited['title_en'],
                  'summary_en':edited['summary_en'],'summary_zh':edited['summary_zh'],'answers':[]}
        digest['glossary'].update(edited.get('glossary',{}))
        for answer in item.get('answers',[]):
            key = answer_key(item,answer,prefs)
            if key not in cache['answers']:
                raise ValueError('Missing answer language work')
            edited = cache['answers'][key]
            paras = edited['paragraphs']
            if any(re.search(r'\b(the author|this author|this answer|the answer|the writer)\b',p['en'],re.I) or re.search(r'作者(认为|指出|强调|表示)|这(条|篇)回答|答主认为',p['zh']) for p in paras):
                raise ValueError('Third-person reporting detected; preserve original voice')
            result['answers'].append({'id':answer['id'],'headline_en':edited['headline_en'],
                                      'paragraphs':paras,'summary_en':'\n\n'.join(p['en'] for p in paras),
                                      'summary_zh':'\n\n'.join(p['zh'] for p in paras)})
            digest['glossary'].update(edited.get('glossary',{}))
        digest['items'].append(result)
    full,email = render(digest,source,preview=preview)
    write(root/'output/digest.json',digest)
    (root/'output/zhihu-daily.html').write_text(full,encoding='utf-8')
    (root/'output/email.html').write_text(email,encoding='utf-8')
    write(root/'.private/editor-cache.json',cache)
    report = {'status':'built','topics':len(digest['items']),'answers':sum(len(x['answers']) for x in digest['items']),
              'reader':str(root/'output/zhihu-daily.html'),'preview':preview}
    write(root/'output/build-report.json',report)
    print(json.dumps(report,ensure_ascii=False))


def mail(root):
    prefs = read(root/'preferences.json')
    if prefs['delivery'] != 'html_attachment' or not prefs.get('recipient'):
        raise ValueError('Mail delivery is not configured')
    if read(root/'output/build-report.json')['preview']:
        raise ValueError('Preview edition cannot be sent as a fresh daily')
    source = read(root/'output/sources.json')
    from daily import validate_digest
    digest = read(root/'output/digest.json')
    validate_digest(digest,source)
    delivery_key = fingerprint([source['fetched_at'][:10],prefs['recipient'],{k:v for k,v in digest.items() if k!='fetched_at'}])
    lastpath = root/'output/last-delivery.json'
    if lastpath.exists() and read(lastpath).get('delivery_key') == delivery_key:
        raise ValueError('This edition was already sent to this recipient')
    write(root/'output/pending-delivery.json',{'delivery_key':delivery_key,'recipient':prefs['recipient'],'source_fetched_at':source['fetched_at']})
    payload={'to':prefs['recipient'],'subject':'知乎日报｜'+source['fetched_at'][:10]+'｜英文精读版',
             'payload':{'mime_type':'multipart/mixed','parts':[
                 {'mime_type':'text/html','charset':'UTF-8','body':{'content':(root/'output/email.html').read_text(encoding='utf-8')}},
                 {'mime_type':'text/html','charset':'UTF-8','filename':'zhihu-daily.html','content_disposition':'attachment','body':{'content':(root/'output/zhihu-daily.html').read_text(encoding='utf-8')}}]},
             'response_fields':['id','thread_id','label_ids']}
    print(json.dumps(payload,ensure_ascii=True,separators=(',',':')))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,default=Path('F:/codexCoding/dailyZhihu'))
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--offline',action='store_true');p.add_argument('--resume',action='store_true')
    p=sub.add_parser('classify');p.add_argument('--edits',type=Path,required=True)
    p=sub.add_parser('build');p.add_argument('--edits',type=Path);p.add_argument('--preview',action='store_true')
    sub.add_parser('mail')
    p=sub.add_parser('record');p.add_argument('--message-id',required=True)
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.workspace,args.offline,args.resume)
    elif args.action=='classify':import_labels(args.workspace,args.edits)
    elif args.action=='build':build(args.workspace,args.edits,args.preview)
    elif args.action=='mail':mail(args.workspace)
    elif args.action=='record':
        pending=read(args.workspace/'output/pending-delivery.json')
        pending.update(message_id=args.message_id,sent_at=now())
        write(args.workspace/'output/last-delivery.json',pending)
        print('Delivery recorded.')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(f'Error: {exc}',file=sys.stderr);sys.exit(1)
