"""Тесты Krinik EPUB Linter на синтетических книгах (структура как у fb2 -> epub)."""
import re
import zipfile

import pytest

import krinik_epub_linter as kel

NBSP = ' '
CSS = '.a {\n\tfont-size: 0.7em;\n\tline-height: 0.1;\n\tvertical-align: super;\n}\n'


def page(body):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml">'
            '<head><title/><link rel="stylesheet" href="style.css" type="text/css"/></head>'
            '<body class="z">%s</body></html>' % body)


def note(nid, label, text):
    return ('<span id="%s"><div class="title6">\n<p class="p">%s</p>\n</div>'
            '<p class="p1">%s</p></span>' % (nid, label, text))


def ref(target, label):
    return '<a href="%s" class="a">%s</a>' % (target, label)


def make_epub(path, files, author='Даглас Р. Автор', title='КНИГА: подзаголовок'):
    manifest = ''.join('<item id="i%d" href="%s" media-type="application/xhtml+xml"/>' % (i, n)
                       for i, n in enumerate(files))
    opf = ('<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>%s</dc:title>'
           '<dc:creator>%s</dc:creator></metadata><manifest>%s</manifest></package>' % (title, author, manifest))
    ncx = '<ncx><docTitle><text>%s</text></docTitle><docAuthor><text>%s</text></docAuthor></ncx>' % (title, author)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml',
                   '<container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>')
        z.writestr('OPS/content.opf', opf)
        z.writestr('OPS/toc.ncx', ncx)
        z.writestr('OPS/style.css', CSS)
        for name, body in files.items():
            z.writestr('OPS/' + name, page(body))
    return path


BODY = ''.join([
    '<p class="p1">После точки.%s Дальше текст.</p>' % ref('notes.xhtml#n1', '[1]'),
    '<p class="p1">Слово%s, а потом запятая.</p>' % ref('notes.xhtml#n2', '[2]'),
    '<p class="p1">«к горе»%s.Сказано – сделано.</p>' % ref('notes.xhtml#n3', '[3]'),
    '<p class="p1">Конец абзаца.%s</p>' % ref('notes.xhtml#n4', '[4]'),
    '<p class="p1">Табуляции \t\t%s \t\t, и всё.</p>' % ref('notes.xhtml#n5', '[5]'),
    '<p class="p1">Надстрочная<sup class="sup">%s</sup> ссылка.</p>' % ref('notes.xhtml#n6', '6'),
    '<p class="p1">Фигурные%s скобки.</p>' % ref('notes.xhtml#n7', '<sup class="sup">{7}</sup>'),
    '<p class="p1"><em>В курсиве%s</em> и дальше.</p>' % ref('notes.xhtml#n8', '[8]'),
    '<p class="p1">Две подряд%s%s конец.</p>' % (ref('notes.xhtml#n9', '[9]'), ref('notes.xhtml#n10', '[10]')),
    # не сноски — трогать нельзя
    '<p class="subtitle">* * *</p>',
    '<p class="p1" id="para">Плотность 10<sup class="sup">26</sup> кг/м<sup class="sup">3</sup>, a*b*c.</p>',
    '<p class="p1"><a class="a">www.example.ru</a> и <a href="text.xhtml#para">см. выше</a>.</p>',
])
NOTES = '<div class="title"><p class="p">Примечания</p></div>' + ''.join(
    note('n%d' % i, str(i), 'Текст примечания %d.' % i) for i in range(1, 11))


@pytest.fixture
def book_path(tmp_path):
    return make_epub(tmp_path / 'in.epub', {'text.xhtml': BODY, 'notes.xhtml': NOTES})


def fixed(book_path, **kw):
    book = kel.Book(str(book_path))
    report = kel.fix_book(book, **kw)
    return book, report


def body_of(book, name='OPS/text.xhtml'):
    return kel.plain(book.text[name])


# ---------------------------------------------------------------- ссылки в тексте

@pytest.mark.parametrize('expected', [
    'После точки.' + NBSP + '[1] Дальше текст.',
    'Слово' + NBSP + '[2], а потом запятая.',            # знак остаётся сразу после ссылки
    '«к горе»' + NBSP + '[3]. Сказано – сделано.',      # добавлен пробел после точки
    'Конец абзаца.' + NBSP + '[4]',
    'Табуляции' + NBSP + '[5], и всё.',
    'Надстрочная' + NBSP + '[6] ссылка.',
    'Фигурные' + NBSP + '[7] скобки.',
    'В курсиве' + NBSP + '[8] и дальше.',
    'Две подряд' + NBSP + '[9]' + NBSP + '[10] конец.',
])
def test_reference_spacing(book_path, expected):
    book, _ = fixed(book_path)
    assert expected in body_of(book)


def test_references_are_full_size(book_path):
    book, _ = fixed(book_path)
    t = book.text['OPS/text.xhtml']
    refs = re.findall(r'<a href="notes\.xhtml#n\d+"[^>]*>', t)
    assert len(refs) == 10
    for a in refs:
        assert 'class="krinik-fn"' in a and kel.FN_STYLE in a and 'class="a"' not in a
    assert not re.search(r'<sup[^>]*>\s*<a href="notes', t), 'обёртка <sup> должна быть снята'
    assert 'a.krinik-fn' in book.data['OPS/style.css'].decode()


def test_non_footnotes_untouched(book_path):
    book, _ = fixed(book_path)
    t = book.text['OPS/text.xhtml']
    assert '<p class="subtitle">* * *</p>' in t
    assert '10<sup class="sup">26</sup> кг/м<sup class="sup">3</sup>, a*b*c.' in t
    assert '<a class="a">www.example.ru</a> и <a href="text.xhtml#para">см. выше</a>.' in t


# ---------------------------------------------------------------- примечания

def test_notes_start_with_label_and_link_back(book_path):
    book, _ = fixed(book_path)
    notes = book.text['OPS/notes.xhtml']
    assert 'title6' not in notes
    for i in range(1, 11):
        m = re.search(r'<span id="n%d"><p class="p1"><a href="text\.xhtml#(fnref\d+)" [^>]*>\[%d\]</a> '
                      r'Текст примечания %d\.' % (i, i, i), notes)
        assert m, i
        assert 'id="%s"' % m.group(1) in book.text['OPS/text.xhtml']


def test_colliding_series_get_prefix(tmp_path):
    body = 'Обычное%s и комментарий%s.' % (ref('notes.xhtml#n1', '[1]'), ref('comments.xhtml#c1', '{1}'))
    comments = '<div class="title"><p class="p">Комментарии</p></div>' + note('c1', '1', 'Комментарий.')
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': '<p class="p1">%s</p>' % body,
                                           'notes.xhtml': note('n1', '1', 'Примечание.'),
                                           'comments.xhtml': comments})
    ncx = ('<ncx><navMap><navPoint id="a"><navLabel><text>1</text></navLabel><content src="comments.xhtml#c1"/>'
           '</navPoint><navPoint id="b"><navLabel><text>1</text></navLabel><content src="notes.xhtml#n1"/>'
           '</navPoint></navMap></ncx>')
    with zipfile.ZipFile(path, 'a') as z:
        z.writestr('OPS/nav.ncx', ncx)
    book, report = fixed(path)
    assert 'Обычное' + NBSP + '[1] и комментарий' + NBSP + '[К1].' in body_of(book)
    nav = book.data['OPS/nav.ncx'].decode()
    assert '<text>К1</text></navLabel><content src="comments.xhtml#c1"/>' in nav
    assert '<text>1</text></navLabel><content src="notes.xhtml#n1"/>' in nav
    assert '[К1] Комментарий.' in kel.plain(book.text['OPS/comments.xhtml'])
    assert any('Комментарии' in r for r in report)


def test_manual_prefix(tmp_path):
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': '<p class="p1">X%s</p>' % ref('c.xhtml#c1', '[1]'),
                                           'c.xhtml': note('c1', '1', 'Т.')})
    book, _ = fixed(path, prefixes={'OPS/c.xhtml': 'Р'})
    assert '[Р1]' in body_of(book)


def test_wrong_target_is_retargeted(tmp_path):
    # как у Лема: ссылка [52] ведёт на примечание 51, на 52 не ссылается никто
    files = {'text.xhtml': '<p class="p1">Раз%s. Два%s.</p>' % (ref('n-1.xhtml#a', '[51]'), ref('n-1.xhtml#a', '[52]')),
             'n-1.xhtml': note('a', '51', 'Пятьдесят первое.'),
             'n-2.xhtml': note('b', '52', 'Пятьдесят второе.')}
    book, report = fixed(make_epub(tmp_path / 'b.epub', files))
    t = book.text['OPS/text.xhtml']
    assert re.search(r'<a href="n-2\.xhtml#b"[^>]*>\[52\]</a>', t)
    assert '[52] Пятьдесят второе.' in kel.plain(book.text['OPS/n-2.xhtml'])
    assert any('перенаправлена' in r for r in report)


def test_numbered_subheadings_are_not_notes(tmp_path):
    files = {'ch1-1.xhtml': '<p class="p1">Текст%s</p>' % ref('ch2-1.xhtml#a', '[1]'),
             'ch1-2.xhtml': note('h', '1', 'Подзаголовок главы, а не сноска'),
             'ch2-1.xhtml': note('a', '1', 'Сноска.')}
    book, _ = fixed(make_epub(tmp_path / 'b.epub', files))
    assert 'title6' in book.text['OPS/ch1-2.xhtml']


# ---------------------------------------------------------------- файл, метаданные, проверка

def test_cli_fix_names_file_and_writes_valid_zip(book_path, tmp_path):
    out = tmp_path / 'out'
    rc = kel.main(['fix', str(book_path), '-o', str(out),
                   '--author', 'Имя Фамилия', '--title', 'Название. Подзаголовок'])
    assert rc == 0
    dst = out / 'Имя Фамилия. Название. Подзаголовок.epub'
    with zipfile.ZipFile(dst) as z:
        first = z.infolist()[0]
        assert first.filename == 'mimetype' and first.compress_type == zipfile.ZIP_STORED
        opf = z.read('OPS/content.opf').decode()
        assert '<dc:title>Название. Подзаголовок</dc:title>' in opf
        assert '<dc:creator>Имя Фамилия</dc:creator>' in opf
    assert kel.main(['check', str(dst)]) == 0


def test_check_fails_on_unfixed_book(book_path):
    assert kel.main(['check', str(book_path)]) == 1


def test_check_detects_small_reference(book_path, tmp_path):
    book, _ = fixed(book_path)
    book.text['OPS/text.xhtml'] = book.text['OPS/text.xhtml'].replace(kel.FN_STYLE, 'x', 1)
    lines = kel.check(book)
    assert any('не обычного размера' in x for x in lines)


def test_cli_refuses_to_overwrite_source(book_path):
    src = book_path.with_name('Имя. Название.epub')
    book_path.rename(src)
    data = src.read_bytes()
    with pytest.raises(SystemExit):
        kel.main(['fix', str(src), '-o', str(src.parent), '--author', 'Имя', '--title', 'Название'])
    assert src.read_bytes() == data


def test_fix_is_idempotent(book_path, tmp_path):
    out = tmp_path / 'o1'
    kel.main(['fix', str(book_path), '-o', str(out)])
    once = next(out.iterdir())
    book = kel.Book(str(once))
    before = dict(book.text)
    kel.fix_book(book)
    assert book.text == before


def test_safe_filename():
    assert kel.safe_filename('А/Б: В?.') == 'А Б В'
    assert kel.safe_filename('Лю Цысинь. Воспоминания о прошлом Земли.') == 'Лю Цысинь. Воспоминания о прошлом Земли'
