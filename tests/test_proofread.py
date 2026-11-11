"""Встроенные проверки корректуры (без LanguageTool)."""
import pytest

import krinik_epub_linter as kel
import krinik_proofread as kp

from test_linter import make_epub


def kinds(text):
    return {h['kind'] for h in kp.builtin_checks([('f', 1, text)])}


@pytest.mark.parametrize('text, kind', [
    ('Cтивен Вайнберг — физик.', 'Смешение алфавитов'),        # латинская C
    ('Ha этом этапе всё ясно.', 'Смешение алфавитов'),          # латинская H
    ('Мы пошли в в магазин.', 'Повтор слова'),
    ('Мы пошли в магазин , и купили хлеб.', 'Пробел перед знаком'),
    ('Купили хлеб.Потом пошли домой.', 'Нет пробела после знака'),
    ('Сказано,сделано.', 'Нет пробела после знака'),
    ('Москва - столица России.', 'Дефис вместо тире'),
    ('Он сказал (и замолчал.', 'Непарные ()'),
])
def test_builtin_finds(text, kind):
    assert kind in kinds(text)


@pytest.mark.parametrize('text', [
    'Обычная правильная фраза — без ошибок, «в кавычках» (и скобках).',
    'Очень-очень долго, кто-то где-то.',          # дефисные повторы — не ошибка
    'Формула E = mc2 и слово Windows рядом с русским.',  # латиница отдельными словами
    '«Первый абзац многоабзацной цитаты без закрывающей кавычки',
    'Т. е. А. С. Пушкин, т.е. сокращения.',
    'Подождите... Что?',
])
def test_builtin_quiet_on_good_text(text):
    assert kinds(text) == set()


def test_paragraphs_strip_footnote_refs(tmp_path):
    body = '<p class="p1">Слово%s, дальше.</p>' % ' <a href="n.xhtml#a" id="fnref1" class="krinik-fn">[12]</a>'
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': body, 'n.xhtml': '<p>x</p>'})
    paras = kp.paragraphs(kel.Book(str(path)))
    assert paras == [('OPS/text.xhtml', 1, 'Слово, дальше.')]


def test_proofread_report_without_languagetool(tmp_path):
    body = '<p class="p1">Cтивен пошёл в в магазин.</p><p class="p1">Всё хорошо.</p>'
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': body})
    res = kp.proofread(kel.Book(str(path)), use_lt=False)
    assert res['paragraphs'] == 2
    assert {h['kind'] for h in res['hits']} == {'Смешение алфавитов', 'Повтор слова'}
    md = kp.to_markdown(res, 'Автор. Книга')
    assert '⟦Cтивен⟧' in md and '⟦в в⟧' in md
    assert kp.to_json(res).startswith('{')


def test_book_is_not_modified(tmp_path):
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': '<p>Cтивен в в доме.</p>'})
    before = path.read_bytes()
    assert kel.main(['proofread', str(path), '-o', str(tmp_path / 'r'), '--no-lt']) == 0
    assert path.read_bytes() == before
    assert (tmp_path / 'r' / 'b.proofread.md').exists()


def test_calibre_div_paragraphs(tmp_path):
    body = ('<div class="paragraph" id="a">Cтивен пошёл.</div>'
            '<div class="wrap"><p>Внутренний абзац.</p></div><ul><li><p>Пункт.</p></li></ul>')
    path = make_epub(tmp_path / 'b.epub', {'text.xhtml': body})
    assert [p[2] for p in kp.paragraphs(kel.Book(str(path)))] == ['Cтивен пошёл.', 'Внутренний абзац.', 'Пункт.']
