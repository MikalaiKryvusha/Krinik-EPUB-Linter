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


# ---------------------------------------------------------------- формат «[N] текст» (Calibre и др.)

def test_calibre_style_notes(tmp_path):
    # ссылка с подсказкой title и <span>, примечание — отдельный файл, перед [1] пустые якоря оглавления
    body = ('<p>для paucorum hominum<a href="n1.xhtml#id_1" title="немногих людей (лат.)." class="c10">'
            '<span class="c11">[1]</span></a>и поэтому</p>')
    note = ('<div class="paragraph" id="id_1"><a id="TOC_1" class="c9"></a><a class="c9" id="TOC_2"></a>'
            '[1] немногих людей (<em>лат</em>.).</div>')
    toc = '<ul><li><a href="n1.xhtml#TOC_1">1</a></li></ul>'
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body, 'n1.xhtml': note, 'toc.xhtml': toc}))
    t = book.text['OPS/text.xhtml']
    assert 'hominum' + NBSP + '[1] и поэтому' in kel.plain(t)
    assert 'title="немногих людей (лат.)."' in t
    n = book.text['OPS/n1.xhtml']
    assert re.search(r'<a id="TOC_1" class="c9"></a><a class="c9" id="TOC_2"></a>'
                     r'<a href="text\.xhtml#fnref1" [^>]*>\[1\]</a> немногих людей', n)
    assert '<a href="n1.xhtml#TOC_1">1</a>' in book.text['OPS/toc.xhtml']   # оглавление не трогаем
    assert kel.check(book)[1:] == []


def test_zero_padded_labels_and_existing_backlink(tmp_path):
    body = ('<p class="p" id="id204">judicent (ep. 79) <span class="sup"><a href="n.xhtml#id222" class="a">'
            '[002]</a></span>. Поэтому</p>')
    notes = ('<p class="p"><a href="text.xhtml#id206" class="a"/></p>'
             '<p class="p" id="id222"><a href="text.xhtml#id204" class="a">[002]</a> если бы даже…</p>')
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body, 'n.xhtml': notes}))
    t = book.text['OPS/text.xhtml']
    assert 'judicent (ep. 79)' + NBSP + '[2]. Поэтому' in kel.plain(t)
    assert 'class="sup"' not in t
    n = book.text['OPS/n.xhtml']
    assert '<a href="text.xhtml#id206" class="a"/>' in n               # самозакрывающийся якорь цел
    assert re.search(r'<p class="p" id="id222"><a href="text\.xhtml#fnref1" [^>]*>\[2\]</a> если бы даже', n)
    assert kel.check(book)[1:] == []


def test_shakespeare_style_notes(tmp_path):
    body = '<p class="p1">Место действия — Эльсинор <a href="ch2.xhtml#id66" class="a">[25]</a>.</p>'
    notes = '<div id="id66"><p class="p1">[25] <em>Эльсинор </em>— город в Дании.</p></div>'
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body, 'ch2.xhtml': notes}))
    assert 'Эльсинор' + NBSP + '[25].' in body_of(book)
    assert re.search(r'<div id="id66"><p class="p1"><a href="text\.xhtml#fnref1" [^>]*>\[25\]</a> <em>Эльсинор',
                     book.text['OPS/ch2.xhtml'])


def test_self_closing_anchor_not_swallowed(tmp_path):
    body = ('<p><a href="n.xhtml#x" class="a"/></p><p>Текст, который нельзя потерять.'
            '<a href="n.xhtml#n1" class="a">[1]</a></p>')
    notes = '<p id="n1">[1] Примечание.</p>'
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body, 'n.xhtml': notes}))
    t = book.text['OPS/text.xhtml']
    assert '<p><a href="n.xhtml#x" class="a"/></p><p>Текст, который нельзя потерять.' + NBSP in t


def test_section_links_are_not_notes(tmp_path):
    body = '<p>См. <a href="s.xhtml#s5">§ 5</a> и <a href="s.xhtml#s6">[6]</a>.</p>'
    sect = '<h2 id="s5">§ 5</h2><p id="s6">Обычный абзац без метки.</p>'
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body, 's.xhtml': sect}))
    assert book.text['OPS/text.xhtml'] == kel.Book(str(tmp_path / 'b.epub')).text['OPS/text.xhtml']


# ---------------------------------------------------------------- сноски-звёздочки

def test_asterisk_notes(tmp_path):
    body = ('<p class="p">существует лишь номинально*; они обречены. Слово** и ещё.</p>'
            '<p class="p">*Пусть тот, кто сочтёт это гиперболой.</p>'
            '<p class="p"><em>**Платоновские идеи </em>можно описать.</p>'
            '<p class="p">что* прежде и что* после — без сноски</p>'
            '<p class="p">a*b*c = x*y</p>')
    book, report = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body}))
    t = book.text['OPS/text.xhtml']
    p = kel.plain(t)
    assert 'номинально' + NBSP + '[*]; они обречены. Слово' + NBSP + '[**] и ещё.' in p
    assert re.search(r'<p class="p" id="krinik-ast\d+"><a href="#fnref\d+" [^>]*>\[\*\]</a> Пусть тот', t)
    assert re.search(r'<a href="#fnref\d+" [^>]*>\[\*\*\]</a> <em>Платоновские идеи </em>', t)
    assert 'что* прежде и что* после' in p and 'a*b*c = x*y' in p
    assert any('без текста сноски' in r for r in report)
    assert kel.check(book)[1:] == []


@pytest.mark.parametrize('frame', [
    '<p class="subtitle">* * *</p>', '<p>***</p>', '<p>*****</p>', '<p>*   *</p>',
    '<p class="title">* Глава первая *</p>', '<p><em>*Глава вторая*</em></p>', '<p>** Часть II **</p>',
])
def test_asterisk_frames_are_not_notes(tmp_path, frame):
    body = '<p>Текст до.</p>%s<p>Слово в тексте.</p>' % frame
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': body})
    book, _ = fixed(path)
    assert book.text['OPS/text.xhtml'] == kel.Book(str(path)).text['OPS/text.xhtml']


def test_frame_does_not_steal_reference(tmp_path):
    body = ('<p>Слово*, дальше.</p><p class="title">* Глава *</p><p>*Текст сноски.</p>')
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body}))
    t = book.text['OPS/text.xhtml']
    assert '<p class="title">* Глава *</p>' in t
    assert re.search(r'Слово <a href="#krinik-ast1"[^>]*>\[\*\]</a>, дальше', t)


def test_separators_opt_in(tmp_path):
    body = ('<p class="subtitle">* * *</p><p>***</p><p class="c" style="x">*****</p><p>⁂</p>'
            '<p>*   *</p><p>* Глава *</p><p>a*b*c</p>')
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': body})
    book, _ = fixed(path)
    assert book.text['OPS/text.xhtml'] == kel.Book(str(path)).text['OPS/text.xhtml']   # по умолчанию не трогаем
    book, report = fixed(path, separators=True)
    t = book.text['OPS/text.xhtml']
    assert t.count('>* * *</p>') == 4
    assert '<p style="text-align:center;text-indent:0">* * *</p>' in t
    assert '<p class="c" style="x">* * *</p>' in t
    assert '<p>*   *</p>' in t and '<p>* Глава *</p>' in t and '<p>a*b*c</p>' in t
    assert any('разделители' in r for r in report)
    assert any('разделители' in x for x in kel.survey(kel.Book(str(path))))


def test_asterisk_after_inline_tag(tmp_path):
    body = ('<p>условиям <em>внутреннего чувства</em>*,— то он способен.</p>'
            '<p>материализм.</p><p>* Ср. «Критику чистого разума».</p>')
    book, _ = fixed(make_epub(tmp_path / 'b.epub', {'text.xhtml': body}))
    assert 'внутреннего чувства' + NBSP + '[*],— то он' in body_of(book)
    assert '[*] Ср. «Критику' in body_of(book)
