"""Корректура русского текста в EPUB: только отчёт, книга не меняется.

Два уровня проверок:
  * встроенные (без зависимостей) — типичные следы сканирования и конвертации:
    латинские буквы внутри русских слов, повтор слова, пробел перед знаком,
    нет пробела после знака, дефис вместо тире, непарные кавычки и скобки;
  * LanguageTool (если установлен language_tool_python и Java 17+) — орфография,
    грамматика, пунктуация. Работает локально, текст никуда не отправляется.

Авторский замысел не трогаем: отчёт — это список мест «посмотреть глазами».
Слова, которые LanguageTool считает опечатками, но которые встречаются в книге
часто (имена, термины), выносятся в отдельный список, чтобы не засорять отчёт.
"""
import collections
import html
import json
import re

CYR = 'А-Яа-яЁё'
LAT = 'A-Za-z'
REF_RE = re.compile(r' ?<a\b[^>]*>\s*(?:<sup[^>]*>)?\s*[\[{]?(?:[\dIVXLCК]{1,5}|\*{1,3})[\]}]?\s*(?:</sup>)?\s*</a>')
# абзац — <p>, заголовок, пункт списка или <div> без вложенных блоков (у Calibre абзацы — <div class="paragraph">)
BLOCK_RE = re.compile(r'<(p|div|h[1-6]|li|td|th|dt|dd)\b[^>]*>'
                      r'((?:(?!<(?:p|div|h[1-6]|li|table|ul|ol|blockquote)\b).)*?)</\1>', re.S)

# правила LanguageTool, которые на художественной и научной прозе дают в основном шум
LT_DISABLED = {
    'WHITESPACE_RULE',            # двойные пробелы — артефакт вёрстки, не текста
    'UPPERCASE_SENTENCE_START',   # списки, формулы, продолжения цитат
    'DASH_RULE',                  # издательский выбор между – и —
    'RU_COMPOUNDS',
    'EN_QUOTES',
    'TOO_LONG_SENTENCE',
    'Cap_Letters_Name',
}
SPELLING_RULE = 'MORFOLOGIK_RULE_RU_RU'
# категории, которые оценивают стиль автора, а не ошибки: «перегружено местоимениями»,
# «избыточные определения», «лично я — плеоназм». Их не показываем, чтобы не ломать замысел.
LT_SKIP_CATEGORIES = {'STYLE', 'LOGIC', 'REDUNDANCY', 'PLAIN_ENGLISH', 'REPETITIONS_STYLE'}
LT_KIND = {
    'GRAMMAR': 'Грамматика', 'EXTEND': 'Грамматика', 'PUNCTUATION': 'Пунктуация',
    'TYPOGRAPHY': 'Типографика', 'TYPOS': 'Опечатки', 'CASING': 'Регистр букв',
    'CONFUSED_WORDS': 'Путаница слов', 'MISC': 'Разное',
}


def spine_order(book):
    """xhtml-файлы в порядке чтения (spine из OPF), остальные — в конце."""
    opf_name = book.opf_name()
    order = []
    if opf_name:
        opf = book.data[opf_name].decode('utf-8', 'replace')
        items = dict(re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf))
        items.update({i: h for h, i in re.findall(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
        for idref in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf):
            if idref in items:
                name = book.resolve(opf_name, items[idref])
                if name in book.text and name not in order:
                    order.append(name)
    return order + sorted(n for n in book.text if n not in order)


def paragraphs(book):
    """[(файл, номер абзаца, текст)] — текст без разметки и без ссылок-сносок."""
    out = []
    for fn in spine_order(book):
        t = REF_RE.sub('', book.text[fn])
        for i, m in enumerate(BLOCK_RE.finditer(t), 1):
            s = html.unescape(re.sub(r'<[^>]+>', '', m.group(2)))
            s = re.sub(r'[ \t\r\n]+', ' ', s).strip()
            if re.search('[%s]' % CYR, s):
                out.append((fn, i, s))
    return out


def _hit(fn, n, text, start, end, kind, message, suggestion='', rule=''):
    a, b = max(0, start - 50), min(len(text), end + 50)
    ctx = (('…' if a else '') + text[a:start] + '⟦' + text[start:end] + '⟧' + text[end:b]
           + ('…' if b < len(text) else ''))
    return {'file': fn, 'para': n, 'kind': kind, 'rule': rule or kind, 'message': message,
            'found': text[start:end], 'suggestion': suggestion, 'context': ctx}


BUILTIN = [
    # (вид, регулярка, сообщение, подсказка(match) или None)
    ('Смешение алфавитов', re.compile(r'[\w]*(?:[%s][%s]|[%s][%s])[\w]*' % (CYR, LAT, LAT, CYR)),
     'В слове смешаны кириллица и латиница (частая ошибка распознавания: «C», «H», «a», «o», «e»…)', None),
    ('Смешение алфавитов', re.compile(r'(?:^|(?<=[%s,.!?»—–] ))[ABCEHKMOPTXaceopxy]{2,}(?= [%s])' % (CYR, CYR)),
     'Латинское слово из букв-двойников среди русского текста (например, «Ha» вместо «На»)', None),
    ('Повтор слова', re.compile(r'(?<![\w-])([%s]+)\s+\1(?![\w-])' % CYR, re.I),
     'Одно и то же слово два раза подряд', lambda m: m.group(1)),
    ('Пробел перед знаком', re.compile(r'(?<=[%s»)])\s+([,;:!?]|\.(?!\.))(?=\s|$|[»)])' % CYR),
     'Пробел перед знаком препинания', lambda m: m.group(1)),
    ('Нет пробела после знака', re.compile(r'(?<=[а-яё])([,;:])(?=[%s])|(?<=[а-яё»)])([.!?])(?=[А-ЯЁ][а-яё])' % CYR),
     'Нет пробела после знака препинания', lambda m: (m.group(1) or m.group(2)) + ' '),
    ('Дефис вместо тире', re.compile(r'(?<=[%s»,])\s-\s(?=[%s«])' % (CYR, CYR)),
     'Дефис между словами — вероятно, должно быть тире', lambda m: ' — '),
]


def builtin_checks(paras):
    hits = []
    for fn, n, s in paras:
        for kind, rx, msg, sug in BUILTIN:
            for m in rx.finditer(s):
                hits.append(_hit(fn, n, s, m.start(), m.end(), kind, msg, sug(m) if sug else ''))
        for o, c in (('«', '»'), ('(', ')')):
            if s.count(o) != s.count(c) and not (o == '«' and s.startswith('«') and s.count(o) == s.count(c) + 1):
                hits.append(_hit(fn, n, s, 0, 0, 'Непарные %s%s' % (o, c),
                                 'В абзаце %d «%s» и %d «%s»' % (s.count(o), o, s.count(c), c)))
    return hits


def languagetool_checks(paras, chunk=40000, progress=None):
    import language_tool_python  # необязательная зависимость
    tool = language_tool_python.LanguageTool('ru-RU')
    hits = []
    try:
        batch, size = [], 0
        batches = []
        for p in paras:
            if size + len(p[2]) > chunk and batch:
                batches.append(batch)
                batch, size = [], 0
            batch.append(p)
            size += len(p[2]) + 2
        if batch:
            batches.append(batch)
        for k, batch in enumerate(batches, 1):
            if progress:
                progress(k, len(batches))
            text = '\n\n'.join(p[2] for p in batch)
            starts, pos = [], 0
            for p in batch:
                starts.append(pos)
                pos += len(p[2]) + 2
            for m in tool.check(text):
                cat = (m.category or '').upper()
                if m.rule_id in LT_DISABLED or cat in LT_SKIP_CATEGORIES:
                    continue
                i = max(j for j, st in enumerate(starts) if st <= m.offset)
                fn, n, s = batch[i]
                off = m.offset - starts[i]
                kind = 'Орфография' if m.rule_id == SPELLING_RULE else LT_KIND.get(cat, cat.title() or 'Разное')
                hits.append(_hit(fn, n, s, off, off + m.error_length, kind, m.message,
                                 ', '.join(m.replacements[:3]), m.rule_id))
    finally:
        tool.close()
    return hits


def split_frequent_spelling(hits, paras, min_count=3):
    """«Опечатки» в именах (с заглавной) и в часто повторяющихся словах — скорее имена и термины."""
    words = collections.Counter(w.lower() for _, _, s in paras for w in re.findall(r'[\w-]+', s))
    main, frequent = [], collections.Counter()
    for h in hits:
        w = h['found']
        if h['rule'] == SPELLING_RULE and (w[:1].isupper() or words[w.lower()] >= min_count):
            frequent[w] += 1
        else:
            main.append(h)
    return main, frequent


def proofread(book, use_lt=True, progress=None):
    paras = paragraphs(book)
    hits = builtin_checks(paras)
    lt_note = ''
    if use_lt:
        try:
            hits += languagetool_checks(paras, progress=progress)
        except ImportError:
            lt_note = 'LanguageTool не установлен (pip install language_tool_python) — только встроенные проверки.'
    hits, frequent = split_frequent_spelling(hits, paras)
    return {'paragraphs': len(paras), 'hits': hits, 'frequent_words': frequent, 'note': lt_note}


def to_markdown(result, title):
    hits = result['hits']
    by_kind = collections.Counter(h['kind'] for h in hits)
    out = ['# Корректура: %s' % title, '',
           'Отчёт ничего не меняет в книге. Это места, на которые стоит посмотреть глазами: '
           'часть из них — авторский стиль, речь персонажей, цитаты и термины.', '']
    if result['note']:
        out += ['> ' + result['note'], '']
    out += ['Абзацев проверено: %d, замечаний: %d.' % (result['paragraphs'], len(hits)), '',
            '| Вид | Сколько |', '|---|---|']
    out += ['| %s | %d |' % kv for kv in by_kind.most_common()]
    for kind, _ in by_kind.most_common():
        out += ['', '## %s' % kind, '']
        for h in (x for x in hits if x['kind'] == kind):
            sug = ' → **%s**' % h['suggestion'] if h['suggestion'] else ''
            out.append('- `%s` ¶%d — %s%s  \n  %s' % (h['file'], h['para'], h['message'], sug,
                                                     h['context'].replace('|', '\\|')))
    if result['frequent_words']:
        out += ['', '<details><summary>Имена и частые «незнакомые» слова — скорее всего не ошибки (%d)</summary>'
                % len(result['frequent_words']), '',
                ', '.join('%s ×%d' % kv for kv in result['frequent_words'].most_common()), '', '</details>']
    return '\n'.join(out) + '\n'


def to_json(result):
    r = dict(result, frequent_words=dict(result['frequent_words']))
    return json.dumps(r, ensure_ascii=False, indent=1)
