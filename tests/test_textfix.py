"""Правка текста с журналом."""
import json

import pytest

import krinik_epub_linter as kel
import krinik_textfix as kt
from test_linter import make_epub


@pytest.mark.parametrize('src, dst', [
    ('Cтивен Вайнберг', 'Стивен Вайнберг'),          # латинская C
    ('Cэмюэл Джонсон', 'Сэмюэл Джонсон'),
    ('книга Hаrdy и Wright', 'книга Hardy и Wright'),  # русская а в латинском слове
    ('слово. Ha этом этапе', 'слово. На этом этапе'),  # латинское слово-двойник
    ('купили хлеб.Потом домой', 'купили хлеб. Потом домой'),
    ('сказано,сделано', 'сказано, сделано'),
    ('INT(x). He знаю, верна ли', 'INT(x). Не знаю, верна ли'),
    ('и есть ответ Флупа. He-ответ Флупа', 'и есть ответ Флупа. Не-ответ Флупа'),
    ('состояния «He-разума»', 'состояния «Не-разума»'),
    ('Ойн: He поставишь ли ты', 'Ойн: Не поставишь ли ты'),
    ('Tы напористa, хладнокровнa', 'Ты напориста, хладнокровна'),
])
def test_autofix_text(src, dst):
    new, changes = kt.autofix_text(src)
    assert new == dst and changes


@pytest.mark.parametrize('src', [
    'SSSO/а и (а*а)',             # формулы Хофштадтера: S без кириллического двойника
    'Ea:Eb:(SS0*b)=c',
    'Windows и Linux рядом с русским',
    'т.е. и т.д.', 'А.С.Пушкин', 'E = mc2', 'OK',
    'Пример: a, b и c.',           # однобуквенные переменные
    'в XX веке и в XXX году, DCC меньше',   # римские цифры
    'спутник COBE показал', 'аппараты типа KH-8 или KH-9', 'пару AT и CG',   # аббревиатуры
    '~Eа:ПАРА-ДОКАЗАТЕЛЬСТВА', 'фX174', 'Ea:Eb',     # поровну латиницы и кириллицы, обозначения
    'He took his vorpal sword', '«He left it dead»',  # английский текст
])
def test_autofix_leaves_alone(src):
    assert kt.autofix_text(src) == (src, [])


def test_textfix_cli_auto_and_apply(tmp_path):
    body = ('<p class="p1">Cтивен пошёл.Потом всё.</p>'
            '<p class="p1">Они <em>эпадают</em> в реку, эпадают снова.</p>'
            '<p class="p1">Только одно: эпадение.</p>')
    src = make_epub(tmp_path / 'b.epub', {'text.xhtml': body})
    fixes = tmp_path / 'fixes.json'
    fixes.write_text(json.dumps([
        {'file': 'OPS/text.xhtml', 'para': 3, 'find': 'эпадение', 'replace': 'впадение', 'reason': 'опечатка'},
        {'file': 'OPS/text.xhtml', 'para': 2, 'find': 'эпадают', 'replace': 'впадают', 'reason': 'неоднозначно'},
        {'file': 'OPS/text.xhtml', 'para': 9, 'find': 'x', 'replace': 'y', 'reason': 'нет абзаца'},
    ], ensure_ascii=False), encoding='utf-8')
    out = tmp_path / 'out'
    assert kel.main(['textfix', str(src), '-o', str(out), '--auto', '--apply', str(fixes)]) == 0
    t = kel.Book(str(out / 'b.epub')).text['OPS/text.xhtml']
    assert 'Стивен пошёл. Потом всё.' in t
    assert 'впадение' in t and t.count('эпадают') == 2          # неоднозначная правка пропущена
    log = json.loads((out / 'b.textfix.json').read_text(encoding='utf-8'))
    assert len(log['auto']) == 2 and len(log['applied']) == 1 and len(log['skipped']) == 2
    md = (out / 'b.textfix.md').read_text(encoding='utf-8')
    assert 'Cтивен' in md and 'Стивен' in md and 'найден 2 раз' in md and 'нет такого абзаца' in md
    assert src.read_bytes() == src.read_bytes()


def test_textfix_skips_markup_and_head(tmp_path):
    src = make_epub(tmp_path / 'b.epub', {'text.xhtml': '<p class="Cтиль">Текст &amp;Cтивен</p>'})
    book = kel.Book(str(src))
    before = book.text['OPS/text.xhtml']
    kt.auto(book)
    assert book.text['OPS/text.xhtml'] == before   # атрибуты и узлы с сущностями не трогаем
