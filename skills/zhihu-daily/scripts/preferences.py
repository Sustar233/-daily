"""Deterministic reading preferences; title-only items never need answer work."""
import re


def rule_categories(item, prefs):
    text = (item['title'] + ' ' + item.get('summary', '')).casefold()
    return [label for label, rule in prefs.get('topic_rules', {}).items()
            if any(word.casefold() in text for word in rule['any'])
            and (not rule.get('context') or any(word.casefold() in text for word in rule['context']))]


def reading_mode(item, prefs):
    categories = set(item.get('categories', [])) | set(rule_categories(item, prefs))
    text = (item['title'] + ' ' + item.get('summary', '')).casefold()
    if categories & set(prefs.get('headline_only_topics', [])) or any(
            word.casefold() in text for word in prefs.get('headline_only_keywords', [])):
        return 'headline'
    if categories & set(prefs.get('prefer_topics', [])) or any(
            word.casefold() in text for word in prefs.get('prefer_keywords', [])):
        return 'deep'
    return 'standard'


def clean_headline(title):
    title = re.split(r'[，,。！？!?；;]\s*(?:如何(?:评价|看待|看)|你(?:如何|怎么看)|怎么(?:看|评价)|对此)', title, maxsplit=1)[0]
    title = re.sub(r'^(?:如何评价|如何看待)\s*', '', title)
    return title.strip(' ，,。！？!?；;')


def apply_reading_preferences(source, prefs):
    from daily import select_topics
    labels = {item['id']: list(dict.fromkeys(item.get('categories', []) + rule_categories(item, prefs))) for item in source['items']}
    items = select_topics(source['items'], prefs, labels)
    for item in items:
        item['reading_depth'] = reading_mode(item, prefs)
        if item['reading_depth'] == 'headline':
            item['answers'] = []
            item['answer_status'] = 'skipped_by_preference'
    items.sort(key=lambda item: item['reading_depth'] == 'headline')
    return dict(source, items=items)
