"""Compact reader with native, accessible translation controls."""
import html
import re
from pathlib import Path

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

def translation(chinese, label='Chinese translation'):
    return ('<details class="translation"><summary aria-label="' + esc(label) + '" title="' + esc(label) + '">'
            '<span aria-hidden="true">ZH</span><svg class="chevron" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">'
            '<path d="m2 4 3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.2"/></svg></summary>'
            '<div lang="zh-CN">' + esc(chinese) + '</div></details>')

def render_reader(digest, source, *, preview=False):
    originals = {item['id']: item for item in source['items']}
    glossary = digest.get('glossary', {})
    toc, articles, headlines = [], [], []
    total_words = 0
    full_count = sum(i.get('reading_depth') != 'headline' for i in digest['items'])
    for index, item in enumerate(digest['items'], 1):
        raw = originals[item['id']]
        anchor = 'q' + item['id']
        mode = item.get('reading_depth', 'standard')
        navtitle = item['title_en']
        badge = '<span class="nav-tag">Focus</span>' if mode == 'deep' else ''
        toc.append(f'<li><a href="#{anchor}"><span class="nav-number">{index:02}</span><span>{esc(navtitle)}{badge}</span></a></li>')
        if mode == 'headline':
            headlines.append(f'<div class="headline-row" id="{anchor}"><span class="nav-number">{index:02}</span><div><a lang="en" href="{esc(raw["url"])}" target="_blank" rel="noopener noreferrer">{esc(item["title_en"])} ↗</a>' + translation(item['title_zh']) + '</div></div>')
            continue
        used = set()
        label = 'FOCUS' if mode == 'deep' else f'{index:02} / READ'
        block = f'<article class="article {mode}" id="{anchor}"><div class="article-meta"><span>{label}</span><a href="{esc(raw["url"])}" target="_blank" rel="noopener noreferrer">Zhihu ↗</a></div>'
        block += '<h2>' + esc(item['title_en']) + '</h2>' + translation(item['title_zh'], 'Chinese title')
        block += '<div class="intro"><p lang="en">' + annotated(item['summary_en'], glossary, used) + '</p>' + translation(item['summary_zh']) + '</div>'
        total_words += len(item['summary_en'].split())
        if item.get('key_points'):
            block += '<section class="key-points" aria-label="Key points"><h3>At a glance</h3><ul>'
            for point in item['key_points']:
                block += '<li><span lang="en">' + annotated(point['en'], glossary, used) + '</span></li>'
                total_words += len(point['en'].split())
            block += '</ul>' + translation('\n'.join('• ' + p['zh'] for p in item['key_points'])) + '</section>'
        answers = {a['id']: a for a in raw.get('answers', [])}
        for answer_index, answer in enumerate(item['answers'], 1):
            origin = answers[answer['id']]
            used = set()
            paragraphs = answer.get('paragraphs') or [{'en': answer['summary_en'], 'zh': answer['summary_zh']}]
            block += '<section class="answer"><div class="answer-heading"><span class="answer-index">' + f'{answer_index:02}</span><h3>' + esc(answer.get('headline_en', 'A closer look')) + '</h3></div>'
            if answer.get('headline_zh'):
                block += '<div class="heading-translation">' + translation(answer['headline_zh'], 'Chinese heading') + '</div>'
            for paragraph in paragraphs:
                block += '<div class="paragraph"><p lang="en">' + annotated(paragraph['en'], glossary, used) + '</p>' + translation(paragraph['zh']) + '</div>'
                total_words += len(paragraph['en'].split())
            if answer.get('note_en'):
                block += '<p class="editor-note">' + esc(answer['note_en']) + '</p>'
            block += '<footer class="answer-source"><span lang="zh-CN">' + esc(origin['author']) + '</span><a href="' + esc(origin['url']) + '" target="_blank" rel="noopener noreferrer">Read original ↗</a></footer></section>'
        if not item['answers']:
            block += '<p class="editor-note">No matching answer was available.</p>'
        block += '</article>'
        articles.append(block)
    minutes = max(1, round(total_words / 160))
    date, timestamp = source['fetched_at'][:10], source['fetched_at'][11:16]
    style = (Path(__file__).parent / 'reader.css').read_text(encoding='utf-8')
    edition = ('Preview · ' if preview else '') + date.replace('-', '.')
    header = '<header class="masthead" id="top"><h1><a href="#top">Zhihu Daily<span class="brand-dot" aria-hidden="true"></span></a></h1><time datetime="' + esc(date) + '">' + esc(edition) + '</time></header>'
    toolbar = '<div class="toolbar"><span>' + str(full_count) + ' reads' + (' · ' + str(len(headlines)) + ' brief' + ('s' if len(headlines) != 1 else '') if headlines else '') + ' <span class="divider">/</span> ' + str(minutes) + ' min</span><div><span class="level">CET-4</span><button id="translation-toggle" type="button" aria-label="Show all Chinese translations" aria-pressed="false" title="Toggle all Chinese translations" hidden><span aria-hidden="true">ZH</span> <span>All</span></button></div></div>'
    sidebar = '<aside class="sidebar"><div class="sidebar-inner"><details class="toc" open><summary>Contents<span>' + str(len(digest['items'])) + ' topics <span class="toc-arrow" aria-hidden="true">⌄</span></span></summary><ol>' + ''.join(toc) + '</ol></details><p class="reading-tip"><span>ZH</span> Tap for Chinese</p></div></aside>'
    headline_section = '<section class="headlines"><div class="section-label"><h2>Quick look</h2><span>Headlines only</span></div>' + ''.join(headlines) + '</section>' if headlines else ''
    footer = '<footer class="page-footer"><span>Adapted from Zhihu · Views belong to their authors.</span><span>Updated ' + esc(timestamp) + ' HKT <a href="#top" aria-label="Back to top">↑</a></span></footer>'
    script = '''const toggle=document.getElementById('translation-toggle');const translations=[...document.querySelectorAll('.translation')];toggle.hidden=false;const sync=()=>{const all=translations.length>0&&translations.every(d=>d.open);toggle.setAttribute('aria-pressed',String(all));toggle.setAttribute('aria-label',all?'收起全部中文翻译':'显示全部中文翻译');};toggle.addEventListener('click',()=>{const open=toggle.getAttribute('aria-pressed')!=='true';translations.forEach(d=>d.open=open);sync();});translations.forEach(d=>d.addEventListener('toggle',sync));const links=[...document.querySelectorAll('.sidebar a')];const observer=new IntersectionObserver(entries=>{const hit=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];if(hit)links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+hit.target.id));},{rootMargin:'-8% 0px -65% 0px',threshold:0});document.querySelectorAll('.article,.headline-row').forEach(a=>observer.observe(a));'''
    script = script.replace('收起全部中文翻译', 'Hide all Chinese translations').replace('显示全部中文翻译', 'Show all Chinese translations')
    script += '''const toc=document.querySelector('.toc');const smallScreen=window.matchMedia('(max-width:720px)');const sizeToc=()=>{toc.open=!smallScreen.matches;};sizeToc();smallScreen.addEventListener('change',sizeToc);links.forEach(a=>a.addEventListener('click',()=>{if(smallScreen.matches)toc.open=false;}));'''
    page = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Zhihu Daily · ' + esc(date) + '</title><style>' + style + '</style></head><body><div class="shell">' + header + toolbar + '<div class="reading-layout">' + sidebar + '<main>' + ''.join(articles) + headline_section + '</main></div>' + footer + '</div><script>' + script + '</script></body></html>'
    filename = 'zhihu-daily-' + date + '.html'
    email = '<p style="margin:12px 0;font:14px/1.6 Arial,sans-serif;color:#34433d">Open the attached <strong>' + esc(filename) + '</strong>.</p>'
    return page, email
