"""English-first, self-contained reader. Native details work without JavaScript."""
import html
import re
from pathlib import Path

CATEGORIES = {'国际': 'World', '经济': 'Economy', '教育': 'Education', '娱乐': 'Culture',
              '体育': 'Sport', '职场': 'Work', '消费': 'Consumer', '社会': 'Society',
              '健康': 'Health', '饮食': 'Food', '文化': 'Culture', '法律': 'Law',
              '科技': 'Technology', '科学': 'Science', 'AI': 'AI'}


def esc(value):
    return html.escape(str(value), quote=True)


def annotated(text, glossary, used):
    terms = [term for term in glossary if term.casefold() not in used]
    if not terms:
        return esc(text)
    pattern = re.compile(r'(?<!\w)(' + '|'.join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r')(?!\w)', re.I)
    lookup = {term.casefold(): meaning for term, meaning in glossary.items()}
    chunks, last = [], 0
    for match in pattern.finditer(text):
        chunks.append(esc(text[last:match.start()]))
        word = match.group()
        chunks.append(esc(word))
        if word.casefold() not in used:
            chunks.append('<span class="gloss">（' + esc(lookup[word.casefold()]) + '）</span>')
            used.add(word.casefold())
        last = match.end()
    chunks.append(esc(text[last:]))
    return ''.join(chunks)


def translation(chinese, label='查看中文翻译'):
    return '<details class="translation"><summary><span class="closed">' + label + '</span><span class="opened">收起中文翻译</span><span class="chevron" aria-hidden="true">⌄</span></summary><div lang="zh-CN">' + esc(chinese) + '</div></details>'


def render_reader(digest, source, *, preview=False):
    originals = {item['id']: item for item in source['items']}
    glossary = digest.get('glossary', {})
    toc, articles, briefs = [], [], []
    total_words = 0
    for index, item in enumerate(digest['items'], 1):
        raw = originals[item['id']]
        anchor = 'q' + item['id']
        categories = ' / '.join(dict.fromkeys(CATEGORIES.get(c, c) for c in raw['categories'])) or 'Discussion'
        toc.append(f'<li><a href="#{anchor}"><span class="nav-number">{index:02}</span><span>{esc(item["title_en"])}</span></a></li>')
        used = set()
        heading = f'<div class="article-meta"><span>{esc(categories)}</span><span>TOPIC {index:02}</span></div>'
        heading += f'<h2>{esc(item["title_en"])}</h2>' + translation(item['title_zh'], '查看中文标题')
        heading += '<div class="intro"><p lang="en">' + annotated(item['summary_en'], glossary, used) + '</p>' + translation(item['summary_zh']) + '</div>'
        total_words += len(item['summary_en'].split())
        answers = {a['id']: a for a in raw.get('answers', [])}
        block = f'<article class="article" id="{anchor}"><div class="chapter">{index:02}</div>' + heading
        for answer_index, answer in enumerate(item['answers'], 1):
            origin = answers[answer['id']]
            used = set()
            paragraphs = answer.get('paragraphs') or [{'en': answer['summary_en'], 'zh': answer['summary_zh']}]
            headline = answer.get('headline_en', f'A closer look · {answer_index:02}')
            block += '<section class="answer"><div class="eyebrow">SELECTED PERSPECTIVE ' + f'{answer_index:02}</div><h3>' + esc(headline) + '</h3>'
            for paragraph in paragraphs:
                block += '<div class="paragraph"><p lang="en">' + annotated(paragraph['en'], glossary, used) + '</p>' + translation(paragraph['zh']) + '</div>'
                total_words += len(paragraph['en'].split())
            if answer.get('note_en'):
                block += '<p class="editor-note">' + esc(answer['note_en']) + '</p>'
            block += '<footer class="answer-source"><span>Original · <span lang="zh-CN">' + esc(origin['author']) + '</span></span><a href="' + esc(origin['url']) + '" target="_blank" rel="noopener noreferrer">Read original ↗</a></footer></section>'
        if not item['answers']:
            block += '<p class="editor-note">No matching answer was available for this topic.</p>'
        block += '<footer class="article-footer"><a href="' + esc(raw['url']) + '" target="_blank" rel="noopener noreferrer">Question on Zhihu ↗</a><a href="#top">Back to top ↑</a></footer></article>'
        articles.append(block)
        briefs.append('<section><h2>' + esc(item['title_en']) + '</h2><p>' + esc(item['summary_en']) + '</p><p lang="zh-CN">' + esc(item['summary_zh']) + '</p></section>')
    minutes = max(1, round(total_words / 160))
    date = source['fetched_at'][:10]
    timestamp = source['fetched_at'][11:16]
    style = (Path(__file__).parent / 'reader.css').read_text(encoding='utf-8')
    preview_banner = '<div class="preview-banner">Design preview · Saved edition from ' + esc(date) + ' ' + esc(timestamp) + ' HKT</div>' if preview else ''
    header = '<header class="masthead" id="top"><a class="brand" href="#top"><span class="brand-mark">知</span><span>THE DAILY<span class="brand-sub">ZHIHU &nbsp; / &nbsp; 知乎日报</span></span></a><div class="edition">' + esc(date.replace('-', '.')) + '<span>ENGLISH READING EDITION</span></div></header>'
    hero = '<div class="hero"><div class="eyebrow"><span class="live-dot"></span> IDEAS, STORIES & PERSPECTIVES</div><h1>A little more of the world.<br><em>A little better at English.</em></h1><p>Your daily read from Zhihu. Clear English, thoughtful answers,<br class="desktop-break"> and Chinese only when you need it.</p><div class="hero-bottom"><span>' + str(len(digest['items'])) + ' topics <span class="meta-dot">·</span> ' + str(minutes) + ' min read <span class="meta-dot">·</span> CET-4 friendly</span><button id="translation-toggle" type="button" aria-pressed="false" hidden>显示全部翻译</button></div></div>'
    sidebar = '<aside class="sidebar"><div class="sidebar-inner"><div class="eyebrow">IN THIS EDITION</div><ol>' + ''.join(toc) + '</ol><div class="reading-tip"><span class="tip-icon">Aa</span><p>Read in English first.</p><span>遇到难词看括号释义，<br>需要时点击段落下方查看翻译。</span></div></div></aside>'
    footer = '<footer class="page-footer"><span>THE DAILY / 知乎日报</span><p>Adapted from Zhihu discussions. Views belong to their authors.<br>Selection favors higher-voted answers among the available search results.</p><span>Saved ' + esc(timestamp) + ' HKT</span></footer>'
    script = '''const toggle=document.getElementById('translation-toggle');toggle.hidden=false;toggle.addEventListener('click',()=>{const open=toggle.getAttribute('aria-pressed')!=='true';document.querySelectorAll('.translation').forEach(d=>d.open=open);toggle.setAttribute('aria-pressed',String(open));toggle.textContent=open?'收起全部翻译':'显示全部翻译';});const links=[...document.querySelectorAll('.sidebar a')];const observer=new IntersectionObserver(entries=>{const hit=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];if(hit)links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+hit.target.id));},{rootMargin:'-8% 0px -65% 0px',threshold:0});document.querySelectorAll('.article').forEach(a=>observer.observe(a));'''
    page = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>The Daily · 知乎日报</title><style>' + style + '</style></head><body>' + preview_banner + '<div class="shell">' + header + hero + '<div class="reading-layout">' + sidebar + '<main>' + ''.join(articles) + '</main></div>' + footer + '</div><script>' + script + '</script></body></html>'
    email = '<div style="max-width:760px;margin:auto;font:16px/1.8 sans-serif;color:#26382f"><h1>The Daily · 知乎日报</h1><p>' + esc(date) + '</p><p>Open the attached reading edition to reveal Chinese translations paragraph by paragraph.</p>' + ''.join(briefs) + '</div>'
    return page, email
