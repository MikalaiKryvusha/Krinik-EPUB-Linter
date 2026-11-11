#!/usr/bin/env python3
"""Krinik EPUB Linter — проверка и починка сносок и русского текста в EPUB-книгах.

Команды:
  survey    BOOK.epub ...            показать, как устроены сноски, разделители, что не так
  fix       BOOK.epub ... -o DIR     привести сноски к виду [N] (крупно, кликабельно в обе стороны)
  check     BOOK.epub ...            проверить исправленную книгу (код возврата 1 при проблемах)
  proofread BOOK.epub ... -o DIR     корректура: орфография, грамматика, пунктуация — только отчёт
  textfix   BOOK.epub ... -o DIR     правка текста с журналом: --auto (техника), --apply правки.json

Понимает сноски: номер отдельным заголовком (fb2 -> epub), «[N] текст» (Calibre и др.),
надстрочные <sup>/{N}/[002], звёздочки «слово*» + «*Текст». Оригиналы не меняются.
Только стандартная библиотека Python 3.8+ (для proofread — опционально LanguageTool).
"""
import argparse
import collections
import html
import os
import re
import sys
import zipfile

__version__ = '1.0.0'

NBSP = ' '
# Ссылки — обычным текстом, крупно: свой класс + явный стиль, перебивающий
# типичное для конвертеров «.a { font-size: 0.7em; vertical-align: super }».
FN_CLASS = 'krinik-fn'
FN_STYLE = 'font-size:1em;vertical-align:baseline;line-height:inherit'
FN_ATTRS = 'class="%s" style="%s"' % (FN_CLASS, FN_STYLE)
FN_CSS = ('\n/* Krinik EPUB Linter: сноски обычным текстом, не надстрочным */\n'
          'a.%s { font-size: 1em !important; vertical-align: baseline !important; '
          'line-height: inherit !important; }\n' % FN_CLASS)
# обёртки, делающие номер мелким: <sup>, <small>, <span class="sup">
SMALL_OPEN = re.compile(r'<(sup|small|span(?=[^>]*\bclass="[^"]*\bsup\b))\b[^>]*>\s*$')
WS = ' \t\r\n' + NBSP
INLINE = {'em', 'strong', 'i', 'b', 'span', 'sup', 'sub', 'u', 's', 'small', 'code', 'a'}
# знаки, которые остаются «приклеенными» сразу после ссылки: «Царств [20], – заметил»
GLUE = set('.,;:!?…»)”"\'’]')
LABEL_RE = re.compile(r'\d+|[IVXLC]+')
# <a .../> (самозакрывающаяся) — не открывающий тег, иначе захватим всё до следующего </a>
A_RE = re.compile(r'<a\b([^>]*?)(?<!/)>(.*?)</a>', re.S)
HREF_RE = re.compile(r'href="([^"#]*)#([^"]+)"')
# формат 1 (fb2 -> epub): номер отдельным заголовком
NOTE_TMPL = (r'<span id="%s">\s*<div class="title\d">\s*<p class="p">([^<]*)</p>\s*</div>\s*'
             r'(<p\b[^>]*>)')
# формат 2 (Calibre и др.): элемент с id, текст которого начинается с «[N]» или ссылки «[N]»
NOTE_LABEL = r'(?:[^\W\d_]{1,3})?\d+|[IVXLC]+|\*{1,3}'
# сноски-звёздочки: «слово*» в тексте и абзац «*Текст сноски» ниже в том же файле
AST_BODY_RE = re.compile(r'<p\b([^>]*)>(\s*(?:<(?:em|strong|i|b)\b[^>]*>\s*)?)(\*{1,3})\s*(?=[^\s*<])')
AST_REF_RE = re.compile(r'(?<=[\w»).,;:!?\]])(\*{1,3})(?=[\s.,;:!?»)\]—–-]|$)')


def is_star(label):
    return bool(re.fullmatch(r'\*+', label))
NOTE_INLINE_TMPL = (r'(<(?!a\b)(\w+)\b[^>]*\bid="%s"[^>]*>(?:\s|<a\b[^>]*?/>|<a\b[^>]*>\s*</a>'
                    r'|<(?:p|span|div)\b[^>]*>)*)'
                    r'(?:<a\b[^>]*>\s*\[(' + NOTE_LABEL + r')\]\s*</a>|\[(' + NOTE_LABEL + r')\])'
                    r'[ \t ]*(?=\S)')


def norm_label(s):
    """[002] -> 2: убрать ведущие нули у номера."""
    return re.sub(r'(?<!\d)0+(?=\d)', '', s)


def plain(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s))


# ---------------------------------------------------------------- книга

class Book:
    """EPUB в памяти: имена файлов zip -> байты; xhtml доступен как текст."""

    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.infos = z.infolist()
            self.data = {i.filename: z.read(i.filename) for i in self.infos}
        self.text = {n: b.decode('utf-8') for n, b in self.data.items()
                     if n.lower().endswith(('.xhtml', '.html', '.htm'))}

    def resolve(self, from_name, href_file):
        """Путь внутри zip для ссылки href_file из файла from_name."""
        if not href_file:
            return from_name
        return os.path.normpath(os.path.join(os.path.dirname(from_name), href_file)).replace(os.sep, '/')

    def rel(self, from_name, to_name):
        if from_name == to_name:
            return ''
        return os.path.relpath(to_name, os.path.dirname(from_name) or '.').replace(os.sep, '/')

    def opf_name(self):
        cont = self.data.get('META-INF/container.xml', b'').decode('utf-8', 'replace')
        m = re.search(r'full-path="([^"]+)"', cont)
        return m.group(1) if m else next((n for n in self.data if n.endswith('.opf')), None)

    def metadata(self):
        opf = self.data.get(self.opf_name() or '', b'').decode('utf-8', 'replace')
        t = re.search(r'<dc:title[^>]*>([^<]*)', opf)
        a = re.search(r'<dc:creator[^>]*>([^<]*)', opf)
        return (html.unescape(a.group(1)).strip() if a else '',
                html.unescape(t.group(1)).strip() if t else '')

    def save(self, path):
        with zipfile.ZipFile(path, 'w') as z:
            if 'mimetype' in self.data:          # по стандарту — первым и без сжатия
                z.writestr(zipfile.ZipInfo('mimetype'), self.data['mimetype'], zipfile.ZIP_STORED)
            for i in self.infos:
                if i.filename == 'mimetype':
                    continue
                body = self.text[i.filename].encode('utf-8') if i.filename in self.text else self.data[i.filename]
                zi = zipfile.ZipInfo(i.filename, i.date_time)
                zi.external_attr = i.external_attr
                z.writestr(zi, body, zipfile.ZIP_DEFLATED)


# ---------------------------------------------------------------- анализ

def _series(fn):
    """Серия файлов: OPS/ch2-67.xhtml и OPS/ch2-68.xhtml -> OPS/ch2-; OPS/ch3.xhtml -> OPS/ch3"""
    s = re.sub(r'([-_])\d+\.x?html?$', r'\1', fn)
    return s if s != fn else re.sub(r'\.x?html?$', '', fn)


def _note_spans(text):
    for m in re.finditer(NOTE_TMPL % '([^"]+)', text):
        lab = plain(m.group(2)).strip()
        if LABEL_RE.fullmatch(lab):
            yield m.group(1), norm_label(lab)


def _link_targets(book):
    for fn, t in book.text.items():
        for m in A_RE.finditer(t):
            h = HREF_RE.search(m.group(1))
            if h:
                yield book.resolve(fn, h.group(1)), h.group(2)


def find_notes(book):
    """{(файл, id): метка} — все примечания книги; book.note_fmt[ключ] = 'title' | 'inline'.

    Формат 'title' — блок «номер заголовком + текст» (fb2 -> epub). Чтобы не спутать
    с нумерованными подзаголовками, берём только серии файлов (ch2-*.xhtml), где хотя бы
    на один такой блок ведёт ссылка: так находятся и примечания, на которые ссылок нет.
    Формат 'inline' — элемент с id, текст которого начинается с «[N]» (Calibre и др.);
    такие берём только если на них ведёт ссылка.
    """
    spans = {fn: dict(_note_spans(t)) for fn, t in book.text.items()}
    targets = set(_link_targets(book))
    series = {_series(tf) for tf, tid in targets if tid in spans.get(tf, ())}
    notes = {(fn, nid): lab for fn, d in spans.items() if _series(fn) in series
             for nid, lab in d.items()}
    book.note_fmt = dict.fromkeys(notes, 'title')
    for key in sorted(targets - set(notes)):
        t = book.text.get(key[0])
        if t is None or 'id="%s"' % key[1] not in t:
            continue
        m = re.search(NOTE_INLINE_TMPL % re.escape(key[1]), t)
        if m:
            notes[key] = norm_label(m.group(3) or m.group(4))
            book.note_fmt[key] = 'inline'
    return notes


def asterisk_notes(text):
    """Сноски-звёздочки в одном файле: пары (ссылка «слово*», абзац «*Текст»).

    Абзац со звёздочкой в начале связывается с ближайшей предшествующей свободной
    ссылкой с тем же числом звёздочек. Возвращает (пары, ссылки без пары, абзацы без пары);
    позиции — смещения в text.
    """
    def framed(s):
        """«* Глава *», «*Глава*», «* * *» — звёздочки как оформление, не сноска."""
        s = plain(s).strip()
        return s.startswith('*') and s.endswith('*')

    def para_at(pos):
        a = text.rfind('<p', 0, pos)
        e = text.find('</p>', pos)
        return text[a:e if e >= 0 else len(text)]

    bodies = [b for b in AST_BODY_RE.finditer(text) if not framed(para_at(b.start(3)))]
    body_pos = {b.start(3) for b in bodies}
    refs = []
    for tm in re.finditer(r'>([^<]+)', text):
        if framed(para_at(tm.start(1))):
            continue
        # «<em>чувства</em>*,—» — звёздочка сразу после закрывающего тега за словом
        lead = re.match(r'\*{1,3}(?=[\s.,;:!?»)\]—–-]|$)', tm.group(1))
        if (lead and tm.start(1) not in body_pos
                and re.search(r'[\w»).,;:!?]</(?:em|strong|i|b|span)>$', text[max(0, tm.start(1) - 80):tm.start(1)])):
            refs.append((tm.start(1), lead.group(0)))
        for m in AST_REF_RE.finditer(tm.group(1)):
            pos = tm.start(1) + m.start(1)
            if pos not in body_pos:
                refs.append((pos, m.group(1)))
    used, pairs, lonely_bodies = set(), [], []
    for b in bodies:
        cands = [r for r in refs if r not in used and r[0] < b.start() and r[1] == b.group(3)]
        if cands:
            used.add(cands[-1])
            pairs.append((cands[-1], b))
        else:
            lonely_bodies.append(b)
    return pairs, [r for r in refs if r not in used], lonely_bodies


def convert_asterisks(book):
    """Пары «слово*» + «*Текст» -> обычные ссылка и примечание «[*] Текст»."""
    report, n = [], 0
    for fn in sorted(book.text):
        t = orig = book.text[fn]
        pairs, lonely_refs, lonely_bodies = asterisk_notes(t)
        edits = []
        for (pos, stars), b in pairs:
            n += 1
            idm = re.search(r'\bid="([^"]+)"', b.group(1))
            nid = idm.group(1) if idm else 'krinik-ast%d' % n
            edits.append((pos, pos + len(stars), '<a href="#%s" class="a">[%s]</a>' % (nid, stars)))
            head = '<p%s%s>[%s] %s' % (b.group(1), '' if idm else ' id="%s"' % nid, stars, b.group(2))
            edits.append((b.start(), b.end(), head))
        for s, e, rep in sorted(edits, reverse=True):
            t = t[:s] + rep + t[e:]
        book.text[fn] = t
        for pos, stars in lonely_refs:
            report.append('ВНИМАНИЕ %s: «%s» без текста сноски — не тронуто: …%s'
                          % (fn, stars, plain(orig[max(0, pos - 300):pos])[-40:].replace('\n', ' ')))
        if len(lonely_bodies) > 3:
            report.append('%s: %d абзацев начинаются со «*» без ссылок в тексте — похоже на список или '
                          'библиографию, не тронуты' % (fn, len(lonely_bodies)))
            lonely_bodies = []
        for b in lonely_bodies:
            report.append('ВНИМАНИЕ %s: абзац «%s…» без ссылки в тексте — не тронут'
                          % (fn, plain(b.group(0) + orig[b.end():b.end() + 200])[:50]))
    if n:
        report.insert(0, 'сносок-звёздочек: %d — оформлены как [*]' % n)
    return report


SEP_BLOCK_RE = re.compile(r'<(p|h[1-6])\b([^>]*)>((?:(?!</\1>).)*)</\1>', re.S)
SEPARATOR = '* * *'


def find_separators(text):
    """Абзацы-разделители из одних звёздочек (3 и больше) или «⁂»: [(match, вид)]."""
    out = []
    for m in SEP_BLOCK_RE.finditer(text):
        shape = re.sub(r'\s+', ' ', plain(m.group(3)).replace(NBSP, ' ')).strip()
        if re.fullmatch(r'\*{3,}|⁂', shape.replace(' ', '')):
            out.append((m, shape))
    return out


def fix_separators(book):
    """Привести разделители к единому виду «* * *» по центру. Включается флагом --separators."""
    changed = collections.Counter()
    for fn in sorted(book.text):
        t = book.text[fn]
        for m, shape in reversed(find_separators(t)):
            attrs = m.group(2)
            if 'style=' not in attrs:
                attrs += ' style="text-align:center;text-indent:0"'
            new = '<%s%s>%s</%s>' % (m.group(1), attrs, SEPARATOR, m.group(1))
            if new != m.group(0):
                t = t[:m.start()] + new + t[m.end():]
                changed[shape] += 1
        book.text[fn] = t
    return ['разделители приведены к «%s»: %s' % (SEPARATOR, ', '.join('«%s» ×%d' % kv for kv in changed.items()))
            ] if changed else []


def note_series_title(text, pos):
    """Заголовок раздела примечаний («Примечания», «Комментарии»…) перед позицией pos."""
    heads = list(re.finditer(r'<div class="title">\s*<p class="p">([^<]+)</p>', text[:pos]))
    return plain(heads[-1].group(1)).strip() if heads else ''


def find_refs(book, notes):
    """Список ссылок на примечания: (файл, match, ключ примечания, видимая метка)."""
    refs = []
    for fn, t in book.text.items():
        for m in A_RE.finditer(t):
            h = HREF_RE.search(m.group(1))
            if not h:
                continue
            key = (book.resolve(fn, h.group(1)), h.group(2))
            if key in notes:
                shown = re.sub(r'[\[\]{}\s]', '', plain(m.group(2)))
                shown = shown if is_star(shown) else norm_label(shown.strip('()*'))
                refs.append((fn, m, key, shown))
    return refs


def plan(book, prefixes=None):
    """Считает итоговые метки и находит, что надо поправить. Ничего не меняет."""
    notes = find_notes(book)
    refs = find_refs(book, notes)
    labels = dict(notes)
    report = []

    # 1. Две серии с одинаковыми номерами (например, «Примечания» и «Комментарии»)
    by_label = collections.defaultdict(list)
    for key, lab in notes.items():
        if not is_star(lab):                  # [*] повторяются в каждой главе — это нормально
            by_label[lab].append(key)
    if prefixes:
        for key in notes:
            if key[0] in prefixes:
                labels[key] = prefixes[key[0]] + notes[key]
    elif any(len(v) > 1 for v in by_label.values()):
        per_series = collections.Counter(_series(k[0]) for k in notes)
        main = per_series.most_common(1)[0][0]
        for ser in per_series:
            if ser == main:
                continue
            fn, nid = min(k for k in notes if _series(k[0]) == ser)
            first = book.text[fn].find('id="%s"' % nid)
            title = note_series_title(book.text[fn], first + 1) or fn
            pref = (re.search(r'\w', title) or re.search('.', 'N')).group(0).upper()
            for key in notes:
                if _series(key[0]) == ser:
                    labels[key] = pref + notes[key]
            report.append('серия примечаний «%s» (%s) пересекается по номерам с основной — метки с приставкой «%s»'
                          % (title, fn, pref))

    # 2. Ссылка ведёт не на то примечание
    referenced = {r[2] for r in refs}
    retarget = {}
    for fn, m, key, shown in refs:
        if shown in (notes[key], labels[key]):
            continue
        cands = [k for k, lab in notes.items() if lab == shown and k not in referenced]
        if len(cands) == 1:
            retarget[(fn, m.start())] = cands[0]
            referenced.add(cands[0])
            report.append('%s: ссылка [%s] вела на примечание %s — перенаправлена на %s#%s'
                          % (fn, shown, notes[key], *cands[0]))
        else:
            report.append('ВНИМАНИЕ %s: ссылка [%s] ведёт на примечание %s, исправить автоматически нельзя'
                          % (fn, shown, notes[key]))
    return notes, refs, labels, retarget, report


# ---------------------------------------------------------------- исправление

def _tag(s):
    m = re.match(r'<(/?)([a-zA-Z0-9]+)', s)
    return (m.group(1) == '/', m.group(2).lower()) if m else (False, '')


def fix_after(seg):
    """Текст сразу после ссылки."""
    rest = seg.lstrip(WS)
    j = 0
    while j < len(rest) and rest[j] == '<':
        e = rest.find('>', j)
        closing, name = _tag(rest[j:e + 1])
        if name not in INLINE or (name == 'a' and not closing):
            return rest                       # конец абзаца или следующая ссылка
        j = e + 1
    if j >= len(rest) or rest[j] in WS:
        return rest
    if rest[j] in GLUE:
        if j == 0:                            # «[177].Сказано» -> «[177]. Сказано»
            m = re.match(r'([.,;:!?…»)”"]+)(?=[A-Za-zА-Яа-яЁё«(])', rest)
            if m and m.group(1)[-1] in '.,;:!?…':
                rest = m.group(1) + ' ' + rest[m.end():]
        return rest
    return ' ' + rest


def fix_before(seg, prev_is_link):
    """Текст сразу перед ссылкой: неразрывный пробел, чтобы [N] не уезжала на новую строку."""
    s = seg.rstrip(WS)
    if not s:
        return NBSP if prev_is_link else s
    if s.endswith('>'):
        closing, name = _tag(s[s.rfind('<'):])
        if not (closing and name in INLINE):
            return s                          # начало абзаца
    return s + NBSP


def fix_book(book, author=None, title=None, prefixes=None, separators=False):
    ast_report = (fix_separators(book) if separators else []) + convert_asterisks(book)
    notes, refs, labels, retarget, report = plan(book, prefixes)
    report = ast_report + report
    by_file = collections.defaultdict(list)
    for r in refs:
        by_file[r[0]].append(r)
    backref, n = {}, 0
    for fn, items in by_file.items():
        t = book.text[fn]
        parts, last = [], 0
        for _, m, key, _shown in sorted(items, key=lambda r: r[1].start()):
            key = retarget.get((fn, m.start()), key)
            n += 1
            rid = 'fnref%d' % n
            backref.setdefault(key, (fn, rid))
            start, end = m.start(), m.end()
            # снять обёртку <sup>/<small> вокруг ссылки — номер должен быть крупным
            w = SMALL_OPEN.search(t[last:start])
            if w:
                close = re.match(r'\s*</%s>' % w.group(1), t[end:])
                if close:
                    start, end = last + w.start(), end + close.end()
            parts.append(t[last:start])
            tip = re.search(r'\stitle="[^"]*"', m.group(1))   # всплывающий текст сноски — сохранить
            parts.append('<a href="%s#%s" id="%s"%s %s>[%s]</a>'
                         % (book.rel(fn, key[0]), key[1], rid, tip.group(0) if tip else '', FN_ATTRS,
                            labels[key]))
            last = end
        parts.append(t[last:])
        for i in range(2, len(parts), 2):
            parts[i] = fix_after(parts[i])
        for i in range(0, len(parts) - 1, 2):
            parts[i] = fix_before(parts[i], i > 0)
        book.text[fn] = ''.join(parts)

    for key, lab in labels.items():
        fn, nid = key
        if key in backref:
            rfn, rid = backref[key]
            link = '<a href="%s#%s" %s>[%s]</a> ' % (book.rel(fn, rfn), rid, FN_ATTRS, lab)
        else:
            report.append('ВНИМАНИЕ %s#%s: на примечание [%s] нет ни одной ссылки' % (fn, nid, lab))
            link = '[%s] ' % lab
        if book.note_fmt[key] == 'title':
            book.text[fn], k = re.subn(NOTE_TMPL % re.escape(nid),
                                       lambda m, nid=nid, link=link: '<span id="%s">%s%s' % (nid, m.group(2), link),
                                       book.text[fn], count=1)
        else:
            book.text[fn], k = re.subn(NOTE_INLINE_TMPL % re.escape(nid),
                                       lambda m, link=link: m.group(1) + link,
                                       book.text[fn], count=1)
        assert k == 1, key

    # пункты оглавления, ведущие на примечания с новой меткой («1» -> «К1»)
    renamed = {k: v for k, v in labels.items() if v != notes[k]}
    for ncx in [n for n in book.data if n.endswith('.ncx')] if renamed else []:
        def nav(m, ncx=ncx):
            key = (book.resolve(ncx, m.group(4)), m.group(5))
            if key in renamed and m.group(2).strip() == notes[key]:
                return m.group(1) + renamed[key] + m.group(3)
            return m.group(0)
        s = book.data[ncx].decode('utf-8')
        s = re.sub(r'(<navLabel>\s*<text>)([^<]*)(</text>\s*</navLabel>\s*<content src="([^"#]*)#([^"]+)")', nav, s)
        book.data[ncx] = s.encode('utf-8')
    for name in [n for n in book.data if n.lower().endswith('.css')]:
        css = book.data[name].decode('utf-8', 'replace')
        if FN_CLASS not in css:
            book.data[name] = (css + FN_CSS).encode('utf-8')
    if author or title:
        set_metadata(book, author, title)
    report.insert(0, 'примечаний: %d, ссылок: %d' % (len(notes), len(refs)))
    return report


def set_metadata(book, author, title):
    def sub(name, pattern, value):
        if value and name in book.data:
            s = book.data[name].decode('utf-8')
            s = re.sub(pattern, lambda m: m.group(1) + html.escape(value, False), s, count=1)
            book.data[name] = s.encode('utf-8')
    opf = book.opf_name()
    sub(opf, r'(<dc:title[^>]*>)[^<]*', title)
    sub(opf, r'(<dc:creator[^>]*>)[^<]*', author)
    for ncx in [n for n in book.data if n.endswith('.ncx')]:
        sub(ncx, r'(<docTitle>\s*<text>)[^<]*', title)
        sub(ncx, r'(<docAuthor>\s*<text>)[^<]*', author)


def safe_filename(s):
    return re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|]+', ' ', s)).strip(' .')


# ---------------------------------------------------------------- обзор и проверка

def survey(book):
    saved = dict(book.text)
    ast = convert_asterisks(book)          # только посмотреть: текст сразу возвращаем
    book.text = saved
    notes, refs, labels, retarget, report = plan(book)
    out = ast + report
    seps = collections.Counter(shape for t in book.text.values() for _, shape in find_separators(t))
    if seps:
        out.append('разделители из звёздочек (fix --separators приведёт к «%s»): %s'
                   % (SEPARATOR, ', '.join('«%s» ×%d' % kv for kv in seps.most_common())))
    out.insert(0, 'примечаний: %d, ссылок на них: %d' % (len(notes), len(refs)))
    shapes = collections.Counter(re.sub(r'\d+', 'N', re.sub(r'<(\w+)[^>]*>', r'<\1>', m.group(2)))[:30]
                                 for _, m, _, _ in refs)
    out.append('вид ссылок: ' + ', '.join('%s ×%d' % kv for kv in shapes.most_common()))
    unref = set(notes) - {r[2] for r in refs} - set(retarget.values())
    if unref:
        out.append('примечаний без ссылок: %d' % len(unref))
    # возможные сноски, не оформленные ссылками
    sus = collections.Counter()
    for t in book.text.values():
        body = re.sub(r'<a\b.*?</a>', '', t, flags=re.S)
        sus['звёздочка после слова'] += len(re.findall(r'[А-Яа-яЁёA-Za-z»)][*]{1,3}(?=[\s<.,;:!?»])', body))
        sus['надстрочная цифра ¹²³'] += len(re.findall(r'[¹²³⁴⁵⁶⁷⁸⁹]', body))
        sus['[N] простым текстом'] += len(re.findall(r'[А-Яа-яЁё»)]\[\d{1,3}\]', plain(body)))
    sus = +sus
    if sus:
        out.append('похоже на сноски без ссылок (проверьте вручную): '
                   + ', '.join('%s ×%d' % kv for kv in sus.items()))
    return out


def check(book):
    """Проверка результата: формат ссылок, пробелы, обратные ссылки."""
    problems = []
    ids = {}
    for fn, t in book.text.items():
        for m in re.finditer(r'\bid="([^"]+)"', t):
            ids[(fn, m.group(1))] = True
    nrefs = nnotes = 0
    note_labels = collections.Counter()
    ref_re = re.compile(r'<a href="([^"]*)" id="fnref\d+"([^>]*)>\[([^\]<]+)\]</a>')
    note_re = re.compile(r'<a href="([^"]*#fnref\d+)" ([^>]*)>\[([^\]<]+)\]</a> ')
    for fn, t in book.text.items():
        for rx, what in ((ref_re, 'ссылка'), (note_re, 'метка примечания')):
            for m in rx.finditer(t):
                href, attrs, lab = m.groups()
                if rx is ref_re:
                    nrefs += 1
                else:
                    nnotes += 1
                    note_labels[lab] += 1
                tf, _, tid = href.partition('#')
                if (book.resolve(fn, tf), tid) not in ids:
                    problems.append('%s: %s [%s] ведёт в никуда' % (fn, what, lab))
                if FN_STYLE not in attrs or SMALL_OPEN.search(t[max(0, m.start() - 200):m.start()]):
                    problems.append('%s: %s [%s] не обычного размера' % (fn, what, lab))
                if rx is not ref_re:
                    continue
                before = t[m.start() - 1:m.start()]
                if before and before != NBSP and before != '>':
                    problems.append('%s: нет пробела перед [%s]' % (fn, lab))
                after = t[m.end():m.end() + 1]
                if after and after not in WS and after not in GLUE and after != '<':
                    problems.append('%s: нет пробела после [%s]' % (fn, lab))
    dup = sorted(lab for lab, n in note_labels.items() if n > 1 and not is_star(lab))
    if dup:
        problems.append('разные примечания с одинаковой меткой: %s' % ', '.join('[%s]' % x for x in dup[:10]))
    if not nrefs:
        problems.append('не найдено ни одной ссылки в формате линтера — книга ещё не исправлена?')
    find_notes(book)
    left = [k for k, f in book.note_fmt.items() if f == 'title']
    if left:
        problems.append('примечаний в старом формате (номер отдельным заголовком): %d' % len(left))
    return ['ссылок: %d, примечаний: %d' % (nrefs, nnotes)] + problems


# ---------------------------------------------------------------- CLI

def main(argv=None):
    p = argparse.ArgumentParser(prog='krinik_epub_linter', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action='version', version='Krinik EPUB Linter ' + __version__)
    sp = p.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('survey', help='показать, как устроены сноски')
    s.add_argument('books', nargs='+')
    c = sp.add_parser('check', help='проверить исправленную книгу')
    c.add_argument('books', nargs='+')
    f = sp.add_parser('fix', help='причесать сноски')
    f.add_argument('books', nargs='+')
    f.add_argument('-o', '--out', required=True, help='папка для результата (оригиналы не трогаются)')
    f.add_argument('--author', help='автор для имени файла и метаданных (только для одной книги)')
    f.add_argument('--title', help='название для имени файла и метаданных (только для одной книги)')
    f.add_argument('--prefix', action='append', default=[], metavar='ФАЙЛ=ПРИСТАВКА',
                   help='вручную задать приставку меток для файла примечаний, напр. OPS/ch2.xhtml=К')
    f.add_argument('--separators', action='store_true',
                   help='привести разделители из звёздочек (***, *****, ⁂) к «* * *» по центру; '
                        'сначала посмотрите survey — в формулах звёздочки бывают частью текста')
    r = sp.add_parser('proofread', help='корректура: орфография, грамматика, пунктуация (только отчёт)')
    r.add_argument('books', nargs='+')
    r.add_argument('-o', '--out', required=True, help='папка для отчётов (.md и .json)')
    r.add_argument('--no-lt', action='store_true', help='без LanguageTool, только встроенные проверки')
    x = sp.add_parser('textfix', help='правка текста с журналом: --auto (техника) и/или --apply правки.json')
    x.add_argument('books', nargs='+')
    x.add_argument('-o', '--out', required=True, help='папка для результата и журналов (оригиналы не трогаются)')
    x.add_argument('--auto', action='store_true',
                   help='латинские буквы-двойники в русских словах и наоборот, пропущенный пробел после знака')
    x.add_argument('--apply', metavar='ПРАВКИ.json', help='список правок по отчёту proofread (только для одной книги)')
    a = p.parse_args(argv)

    rc = 0
    if a.cmd == 'textfix':
        import json as _json

        import krinik_textfix as kt
        if not (a.auto or a.apply):
            p.error('укажите --auto и/или --apply')
        if a.apply and len(a.books) > 1:
            p.error('--apply можно указать только для одной книги')
        os.makedirs(a.out, exist_ok=True)
        for path in a.books:
            print('==', path)
            book = Book(path)
            dst = os.path.join(a.out, os.path.basename(path))
            if os.path.abspath(dst) == os.path.abspath(path):
                p.error('результат совпадает с исходным файлом: %s' % dst)
            auto_log = kt.auto(book) if a.auto else None
            done, skipped = kt.apply(book, kt.load_fixes(a.apply)) if a.apply else ([], [])
            book.save(dst)
            author, title = book.metadata()
            base = os.path.splitext(dst)[0] + '.textfix'
            with open(base + '.md', 'w', encoding='utf-8') as fh:
                fh.write(kt.log_markdown('%s. %s' % (author, title), auto_log, done, skipped))
            with open(base + '.json', 'w', encoding='utf-8') as fh:
                _json.dump({'auto': [dict(zip(('file', 'context', 'old', 'new', 'reason'), r)) for r in auto_log or []],
                            'applied': done, 'skipped': skipped}, fh, ensure_ascii=False, indent=1)
            if auto_log is not None:
                kinds = collections.Counter(r[4] for r in auto_log)
                print('  технических исправлений: %d %s' % (len(auto_log), dict(kinds)))
            if a.apply:
                print('  правок применено: %d, пропущено: %d' % (len(done), len(skipped)))
            print('  сохранено: %s\n  журнал: %s.md' % (dst, base))
        return 0
    if a.cmd == 'proofread':
        import krinik_proofread as kp
        os.makedirs(a.out, exist_ok=True)
        for path in a.books:
            print('==', path)
            book = Book(path)
            author, title = book.metadata()
            res = kp.proofread(book, use_lt=not a.no_lt,
                               progress=lambda k, n: print('  LanguageTool: часть %d из %d' % (k, n), end='\r'))
            base = os.path.join(a.out, safe_filename(os.path.splitext(os.path.basename(path))[0]) + '.proofread')
            with open(base + '.md', 'w', encoding='utf-8') as fh:
                fh.write(kp.to_markdown(res, '%s. %s' % (author, title)))
            with open(base + '.json', 'w', encoding='utf-8') as fh:
                fh.write(kp.to_json(res))
            kinds = collections.Counter(h['kind'] for h in res['hits'])
            print('  абзацев: %d, замечаний: %d %s' % (res['paragraphs'], len(res['hits']), ' ' * 20))
            for k, v in kinds.most_common():
                print('    %-28s %d' % (k, v))
            if res['note']:
                print('  ' + res['note'])
            print('  отчёт: %s.md' % base)
        return 0
    if a.cmd == 'fix':
        if len(a.books) > 1 and (a.author or a.title or a.prefix):
            p.error('--author/--title/--prefix можно указать только для одной книги')
        os.makedirs(a.out, exist_ok=True)
    for path in a.books:
        print('==', path)
        book = Book(path)
        if a.cmd == 'survey':
            lines = survey(book)
        elif a.cmd == 'check':
            lines = check(book)
            rc |= 0 if len(lines) == 1 else 1
        else:
            prefixes = dict(x.split('=', 1) for x in a.prefix) or None
            lines = fix_book(book, a.author, a.title, prefixes, a.separators)
            author, title = book.metadata()
            name = safe_filename('%s. %s' % (author, title)) + '.epub'
            dst = os.path.join(a.out, name)
            if os.path.abspath(dst) == os.path.abspath(path):
                p.error('результат совпадает с исходным файлом: %s' % dst)
            book.save(dst)
            lines.append('сохранено: ' + dst)
        for line in lines:
            print('  ' + line)
    return rc


if __name__ == '__main__':
    sys.exit(main())
