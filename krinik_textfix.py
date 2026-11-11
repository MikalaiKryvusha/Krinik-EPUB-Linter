"""Правка текста книги с журналом: каждое изменение — где, было, стало, почему.

Два режима:
  * auto — только однозначные технические ошибки распознавания и конвертации:
      - латинские буквы-двойники внутри русского слова и наоборот («Cтивен» -> «Стивен»,
        «Hаrdy» -> «Hardy»); слово с буквами без двойника (S, F, ...) не трогается;
      - латинское слово из букв-двойников между русскими словами («Ha этом» -> «На этом»);
      - нет пробела после знака препинания («хлеб.Потом», «сказано,сделано»);
  * apply — список правок из JSON, подготовленный человеком (или ИИ) по отчёту proofread:
      [{"file": "OPS/ch1.xhtml", "para": 12, "find": "эпадают", "replace": "впадают",
        "reason": "опечатка распознавания"}]
    Правка применяется, только если фрагмент найден в абзаце ровно один раз
    (внутри одного текстового узла), иначе пропускается и попадает в журнал.
"""
import html
import json
import re

from krinik_proofread import BLOCK_RE

NBSP = ' '
LAT_LOOK = 'ABCEHKMOPTXaceopxy'
CYR_LOOK = 'АВСЕНКМОРТХасеорху'
TO_CYR = str.maketrans(LAT_LOOK, CYR_LOOK)
TO_LAT = str.maketrans(CYR_LOOK, LAT_LOOK)
CYR = 'А-Яа-яЁё'
WORD_RE = re.compile(r'[A-Za-zА-Яа-яЁё]+')
# «Ha этом», «He-ответ», «He знаю»: слово из букв-двойников со строчной буквой (аббревиатуры
# вроде COBE, KH-9, AT и римские цифры XX, DCC не трогаем) между русскими словами
LOOK_WORD_RE = re.compile(r'(?:^|(?<=[%s,.!?»—–:;] )|(?<=[«(]))(?<![A-Za-z])([%s]{2,})(?![A-Za-z])(?=[ -][%s])'
                          % (CYR, LAT_LOOK, CYR))
ROMAN_RE = re.compile(r'[IVXLCDM]+')
# пробел после знака — только между обычными русскими словами (не в формулах вроде «Ea:ПАРА»)
SPACE_AFTER_RE = re.compile(r'(?<=[а-яё]{2})([,;:])(?=[а-яё])|(?<=[а-яё]{2})([.!?])(?=[А-ЯЁ][а-яё])')


def _fix_word(w):
    lat = re.findall(r'[A-Za-z]', w)
    cyr = re.findall(r'[А-Яа-яЁё]', w)
    if not lat or not cyr:
        return w, ''
    only_cyr = [c for c in cyr if c not in CYR_LOOK]               # ы, ф, д… — латинского двойника нет
    if all(c in LAT_LOOK for c in lat) and (len(cyr) > len(lat) or only_cyr):
        return w.translate(TO_CYR), 'латинская буква в русском слове'
    if all(c in CYR_LOOK for c in cyr) and len(lat) > len(cyr):
        return w.translate(TO_LAT), 'русская буква в латинском слове'
    return w, ''


def autofix_text(s):
    """Исправить текстовый узел. Возвращает (новый текст, [(было, стало, причина)])."""
    changes = []

    def word(m):
        if s[m.end():m.end() + 1].isdigit() or s[max(0, m.start() - 1):m.start()].isdigit():
            return m.group(0)                                         # фX174, 4Eа — обозначения
        new, why = _fix_word(m.group(0))
        if why:
            changes.append((m.group(0), new, why))
        return new
    s = WORD_RE.sub(word, s)

    def look(m):
        if ROMAN_RE.fullmatch(m.group(1)) or not re.search('[a-z]', m.group(1)):
            return m.group(1)
        new = m.group(1).translate(TO_CYR)
        changes.append((m.group(1), new, 'латинское слово-двойник среди русского текста'))
        return new
    s = LOOK_WORD_RE.sub(look, s)

    def space(m):
        sign = m.group(1) or m.group(2)
        a, b = max(0, m.start() - 12), m.end() + 12
        changes.append((s[a:b].strip(), (s[a:m.end()] + ' ' + s[m.end():b]).strip(), 'нет пробела после знака'))
        return sign + ' '
    s = SPACE_AFTER_RE.sub(space, s)
    return s, changes


def _body_span(t):
    m = re.search(r'<body\b[^>]*>', t)
    return (m.end() if m else 0), len(t)


def _context(t, pos):
    chunk = re.sub(r'^[^<]*>', '', t[max(0, pos - 400):pos])      # без обрывка тега в начале
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', chunk)))[-80:]


def auto(book):
    """Технические исправления во всех файлах; журнал [(файл, контекст, было, стало, причина)]."""
    log = []
    for fn in sorted(book.text):
        t = book.text[fn]
        start, _ = _body_span(t)
        out, last = [t[:start]], start
        for m in re.finditer(r'>([^<]+)<', t[start:]):
            a, b = start + m.start(1), start + m.end(1)
            raw = t[a:b]
            if '&' in raw:            # сущности не трогаем — правим только чистый текст
                new, ch = raw, []
            else:
                new, ch = autofix_text(raw)
            out.append(t[last:a])
            out.append(new)
            last = b
            for old, nw, why in ch:
                i = raw.find(old)
                ctx = (_context(t, a + i) + raw[i:i + len(old) + 60]) if i >= 0 else _context(t, a)
                log.append((fn, re.sub(r'\s+', ' ', ctx)[-180:], old, nw, why))
        out.append(t[last:])
        book.text[fn] = ''.join(out)
    return log


def apply(book, fixes):
    """Применить список правок. Возвращает (применённые, пропущенные) — списки словарей."""
    done, skipped = [], []
    for fx in fixes:
        fn, n, find, rep = fx['file'], int(fx['para']), fx['find'], fx['replace']
        t = book.text.get(fn)
        blocks = list(BLOCK_RE.finditer(t)) if t is not None else []
        if not 1 <= n <= len(blocks):
            skipped.append(dict(fx, why='нет такого абзаца'))
            continue
        blk = blocks[n - 1]
        inner_a, inner_b = blk.start(2), blk.end(2)
        inner = t[inner_a:inner_b]
        nodes = [(m.start(1), m.end(1)) for m in re.finditer(r'(?:^|>)([^<]*)', inner)]
        variants = [find, find.replace(' ', NBSP), find.replace(NBSP, ' ')]
        hits = []
        for a, b in nodes:
            node = inner[a:b]
            for v in dict.fromkeys(variants):
                i = node.find(v)
                while i >= 0:
                    hits.append((a + i, len(v), v))
                    i = node.find(v, i + 1)
        if len(hits) != 1:
            skipped.append(dict(fx, why='фрагмент найден %d раз' % len(hits)))
            continue
        pos, ln, v = hits[0]
        replacement = rep if v == find else rep.replace(' ', NBSP) if v == find.replace(' ', NBSP) else rep
        inner = inner[:pos] + replacement + inner[pos + ln:]
        book.text[fn] = t[:inner_a] + inner + t[inner_b:]
        done.append(fx)
    return done, skipped


def log_markdown(title, auto_log, done, skipped):
    out = ['# Правка текста: %s' % title, '']
    if auto_log is not None:
        out += ['## Технические исправления (автоматически): %d' % len(auto_log), '',
                '| Файл | Было | Стало | Причина | Контекст |', '|---|---|---|---|---|']
        out += ['| `%s` | %s | %s | %s | %s |' % (fn, old, new, why, ctx.replace('|', '\\|'))
                for fn, ctx, old, new, why in auto_log]
    if done or skipped:
        out += ['', '## Правки по корректуре: применено %d, пропущено %d' % (len(done), len(skipped)), '',
                '| Файл | ¶ | Было | Стало | Почему |', '|---|---|---|---|---|']
        out += ['| `%s` | %s | %s | %s | %s |' % (f['file'], f['para'], f['find'], f['replace'], f.get('reason', ''))
                for f in done]
        if skipped:
            out += ['', '### Пропущено', '']
            out += ['- `%s` ¶%s: «%s» → «%s» — %s' % (f['file'], f['para'], f['find'], f['replace'], f['why'])
                    for f in skipped]
    return '\n'.join(out) + '\n'


def load_fixes(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)
