<a name="english"></a>

<h2 align="center">Krinik EPUB Linter</h2>

<p align="center">
  <a href="#english"><img src="https://img.shields.io/badge/English-2C7BE5?style=for-the-badge" alt="English"></a>
  &nbsp;
  <a href="#russian"><img src="https://img.shields.io/badge/Русский-C0392B?style=for-the-badge" alt="Русский"></a>
</p>

<p align="center"><b>Check and repair Russian EPUB books</b><br>
Footnotes made uniform, readable and clickable both ways; Russian text proofread and repaired with a full change log</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.8+-3776AB.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/dependencies-0-3DDC84.svg" alt="Zero dependencies for the core">
  <img src="https://img.shields.io/badge/offline-your_books_stay_local-555D60.svg" alt="Works offline, books stay on your computer">
  <img src="https://img.shields.io/badge/tests-pytest-0A9EDC.svg" alt="Tests: pytest">
</p>

[Читать по-русски →](#russian)

> [!TIP]
> **Made for reading on the Xteink X4 Pro** with [KCCP · Krinik Custom CrossPoint](https://github.com/MikalaiKryvusha/Krinik-Custom-CrossPoint)
> firmware: footnote references come out as full-size `[N]` that are easy to tap, and every note links back to its place in the text.
> Any EPUB reader benefits the same way.

**Krinik EPUB Linter** is a command-line tool for EPUB books, mostly Russian ones converted from FB2 or built with Calibre.
It never changes the original file — results go to a separate folder, and every text change is written to a log.

| Command | What it does |
|---|---|
| `survey` | Shows how the book's footnotes, separators and asterisks are built and what is wrong with them |
| `fix` | Makes footnotes uniform: `[N]` in normal size, spaced, clickable both ways; renames the file to `Author. Title.epub` |
| `check` | Verifies a fixed book (exit code 1 on problems) |
| `proofread` | Spelling, grammar and punctuation report — built-in checks plus local LanguageTool. Report only |
| `textfix` | Repairs text with a log: `--auto` for unambiguous technical errors, `--apply` for a reviewed list of fixes |

### Install

```bash
git clone https://github.com/MikalaiKryvusha/Krinik-EPUB-Linter.git
cd Krinik-EPUB-Linter
python3 -m venv .venv
.venv/bin/pip install -e ".[proofread,dev]"   # proofread: LanguageTool; dev: pytest and ruff
```

`fix`, `check`, `survey` and `textfix` use only the Python standard library. `proofread` with LanguageTool needs Java 17+;
LanguageTool downloads itself on first run (~260 MB) and then works locally — the text never leaves your computer.

### Footnotes — `fix`

```bash
krinik-epub-linter survey Book.fb2.epub
krinik-epub-linter fix Book.fb2.epub -o Fixed --author "Max Tegmark" --title "Our Mathematical Universe"
krinik-epub-linter check Fixed/*.epub
```

| Before | After |
|---|---|
| `inflation.¹⁶ The` — small superscript (`.a { font-size: 0.7em; vertical-align: super }`) | `inflation. [16] The` — normal size |
| `accelerator[28] near` | `accelerator [28] near` |
| `Kingdoms[20], – he said` | `Kingdoms [20], – he said` — punctuation stays glued after the reference |
| `mountain»[177].Said` | `mountain» [177]. Said` |
| `<sup>{1}</sup>`, `<span class="sup">[002]</span>` | `[1]`, `[2]` |
| `nominally*;` + a paragraph `*Let him who…` | `nominally [*];` + `[*] Let him who…` |
| Note: label `88` as a separate heading, text below | `[88] Text of the note` — `[88]` leads back to the text |

- A non-breaking space before the reference keeps `[N]` from wrapping to a new line alone.
- References get the `krinik-fn` class and an explicit `font-size:1em; vertical-align:baseline`; `<sup>`, `<small>`,
  `<span class="sup">` wrappers are removed. Tooltips (`title="…"`) are kept.
- Note formats understood: label as a heading (FB2 → EPUB), `[N] text` (Calibre and others, with or without a back-link),
  zero-padded labels `[002]`, asterisk notes `word*` + `*Text` in the same file.
- **Two note series with the same numbers** (e.g. Notes and Comments): the smaller one gets a prefix from its heading —
  `[К1]`, `[К2]`. Manually: `--prefix OPS/ch2.xhtml=К`.
- **A reference pointing to the wrong note** (`[52]` leading to note 51): if note 52 exists and nothing links to it,
  the reference is retargeted and reported.
- Left alone: scene breaks `* * *`, formulas, exponents (`10<sup>26</sup>`), ordinary and cross-reference links, numbered
  section headings, asterisks used as frames (`* Chapter *`) or in formulas and bibliographies.
- `--separators` turns `***`, `*****`, `⁂` into a centred `* * *`. Off by default: in some books `*****` is part of
  mathematical derivations — check `survey` first.

### Russian text — `proofread` and `textfix`

```bash
krinik-epub-linter textfix --auto Fixed/*.epub -o Stage1          # technical errors, with a log
krinik-epub-linter proofread Stage1/*.epub -o Reports             # report: .md to read, .json for tools
krinik-epub-linter textfix Stage1/Book.epub -o Final --apply fixes.json   # reviewed fixes, with a log
```

`textfix --auto` fixes only what is unambiguous:

| Error | Example |
|---|---|
| Latin look-alike letters in a Russian word | `Cтивен` → `Стивен`, `Tы напористa` → `Ты напориста` |
| Cyrillic look-alike letters in a Latin word | `Jamеs` → `James`, `МIU` → `MIU` |
| A Latin look-alike word between Russian words | `Ha этом` → `На этом`, `He знаю` → `Не знаю` |
| No space after a punctuation mark | `хлеб.Потом` → `хлеб. Потом` |

Roman numerals (`XX век`), abbreviations (`COBE`, `KH-9`), formulas (`Ea:Eb`, `SSSO/a`), designations glued to digits
(`φX174`) and words with as many Latin as Cyrillic letters are never touched.

`proofread` reports what needs a human (or AI) eye: spelling, agreement of gender and case, punctuation, typography.
LanguageTool categories that judge the author's style («too many pronouns», «redundant modifiers») are off, so the
author's voice is not «corrected». Unknown capitalised words and frequent words (names, terms) go to a separate
collapsed list.

`textfix --apply` takes a reviewed list of fixes:

```json
[{"file": "OPS/ch1.xhtml", "para": 12, "find": "эпадают", "replace": "впадают", "reason": "OCR typo"}]
```

A fix is applied only if the fragment occurs exactly once in that paragraph; otherwise it is skipped and logged.

### Development

```bash
.venv/bin/pytest          # synthetic books with every case met in real books; real books are not in the repo
.venv/bin/ruff check .
```

- `krinik_epub_linter.py` — the CLI, footnotes, `survey`, `check`.
- `krinik_proofread.py` — built-in checks and LanguageTool.
- `krinik_textfix.py` — technical fixes and reviewed fixes with a log.

### Licence

MIT — see [LICENSE](LICENSE).

---

<a name="russian"></a>

<h2 align="center">Krinik EPUB Linter</h2>

<p align="center">
  <a href="#english"><img src="https://img.shields.io/badge/English-2C7BE5?style=for-the-badge" alt="English"></a>
  &nbsp;
  <a href="#russian"><img src="https://img.shields.io/badge/Русский-C0392B?style=for-the-badge" alt="Русский"></a>
</p>

<p align="center"><b>Проверка и починка русских EPUB-книг</b><br>
Сноски — в едином виде, крупно и кликабельно в обе стороны; русский текст — корректура и правка с полным журналом</p>

[Read in English →](#english)

> [!TIP]
> **Сделано для чтения на Xteink X4 Pro** с прошивкой [KCCP · Krinik Custom CrossPoint](https://github.com/MikalaiKryvusha/Krinik-Custom-CrossPoint):
> ссылки на сноски — крупные `[N]`, в которые легко попасть пальцем, а из каждого примечания можно вернуться к месту в тексте.
> На любой другой читалке это работает так же.

**Krinik EPUB Linter** — утилита командной строки для EPUB-книг, в первую очередь русских, сконвертированных из FB2
или собранных в Calibre. Оригинал никогда не меняется: результат — в отдельной папке, каждое изменение текста — в журнале.

| Команда | Что делает |
|---|---|
| `survey` | Показывает, как устроены сноски, разделители и звёздочки в книге и что с ними не так |
| `fix` | Приводит сноски к одному виду: `[N]` обычного размера, с пробелами, кликабельно в обе стороны; имя файла — `Автор. Название.epub` |
| `check` | Проверяет исправленную книгу (код возврата 1 при проблемах) |
| `proofread` | Отчёт об орфографии, грамматике и пунктуации — встроенные проверки и локальный LanguageTool. Только отчёт |
| `textfix` | Правит текст с журналом: `--auto` — однозначные технические ошибки, `--apply` — проверенный список правок |

### Установка

```bash
git clone https://github.com/MikalaiKryvusha/Krinik-EPUB-Linter.git
cd Krinik-EPUB-Linter
python3 -m venv .venv
.venv/bin/pip install -e ".[proofread,dev]"   # proofread — LanguageTool, dev — pytest и ruff
```

`fix`, `check`, `survey` и `textfix` используют только стандартную библиотеку Python. Для `proofread` с LanguageTool нужна
Java 17+; при первом запуске LanguageTool скачивается (~260 МБ) и дальше работает локально — текст никуда не отправляется.

### Сноски — `fix`

```bash
krinik-epub-linter survey Книга.fb2.epub
krinik-epub-linter fix Книга.fb2.epub -o Причёсанные --author "Макс Тегмарк" --title "Наша математическая вселенная"
krinik-epub-linter check Причёсанные/*.epub
```

| Было | Стало |
|---|---|
| `инфляцией.¹⁶ Экстраполяция` — мелкая надстрочная (`.a { font-size: 0.7em; vertical-align: super }`) | `инфляцией. [16] Экстраполяция` — обычного размера |
| `ускорителя[28] в окрестностях` | `ускорителя [28] в окрестностях` |
| `Царств[20], – заметил` | `Царств [20], – заметил` — знак препинания остаётся сразу после ссылки |
| `к горе»[177].Сказано` | `к горе» [177]. Сказано` |
| `<sup>{1}</sup>`, `<span class="sup">[002]</span>` | `[1]`, `[2]` |
| `номинально*;` + абзац `*Пусть тот…` | `номинально [*];` + `[*] Пусть тот…` |
| Примечание: номер `88` отдельным заголовком, ниже текст | `[88] Текст примечания` — `[88]` ведёт обратно к месту в тексте |

- Перед ссылкой — неразрывный пробел, чтобы `[N]` не переносилась на новую строку отдельно от слова.
- Ссылки получают класс `krinik-fn` и явный `font-size:1em; vertical-align:baseline`; обёртки `<sup>`, `<small>`,
  `<span class="sup">` снимаются. Всплывающие подсказки (`title="…"`) сохраняются.
- Понимает примечания: номер заголовком (FB2 → EPUB), `[N] текст` (Calibre и др., с обратной ссылкой и без),
  номера с нулями `[002]`, сноски-звёздочки `слово*` + `*Текст` в том же файле.
- **Две серии примечаний с одинаковыми номерами** («Примечания» и «Комментарии»): меньшая получает приставку по первой
  букве заголовка — `[К1]`, `[К2]`. Вручную: `--prefix OPS/ch2.xhtml=К`.
- **Ссылка ведёт не на то примечание** (`[52]` ведёт на 51): если примечание 52 есть и на него никто не ссылается,
  ссылка перенаправляется, это пишется в отчёт.
- Не трогается: разделители `* * *`, формулы, степени (`10<sup>26</sup>`), обычные и перекрёстные ссылки, нумерованные
  подзаголовки, звёздочки-обрамление (`* Глава *`), звёздочки в формулах и библиографиях.
- `--separators` приводит `***`, `*****`, `⁂` к `* * *` по центру. По умолчанию выключено: в некоторых книгах `*****` —
  часть математических выкладок, сначала посмотрите `survey`.

### Русский текст — `proofread` и `textfix`

```bash
krinik-epub-linter textfix --auto Причёсанные/*.epub -o Этап1      # технические ошибки, с журналом
krinik-epub-linter proofread Этап1/*.epub -o Отчёты                # отчёт: .md — читать, .json — для программ
krinik-epub-linter textfix Этап1/Книга.epub -o Готово --apply правки.json   # проверенные правки, с журналом
```

`textfix --auto` правит только однозначное:

| Ошибка | Пример |
|---|---|
| Латинские буквы-двойники в русском слове | `Cтивен` → `Стивен`, `Tы напористa` → `Ты напориста` |
| Русские буквы-двойники в латинском слове | `Jamеs` → `James`, `МIU` → `MIU` |
| Латинское слово-двойник среди русских слов | `Ha этом` → `На этом`, `He знаю` → `Не знаю` |
| Нет пробела после знака препинания | `хлеб.Потом` → `хлеб. Потом` |

Римские цифры (`XX век`), аббревиатуры (`COBE`, `KH-9`), формулы (`Ea:Eb`, `SSSO/a`), обозначения рядом с цифрами
(`φX174`) и слова, где латиницы и кириллицы поровну, не трогаются никогда.

`proofread` показывает то, что требует взгляда человека (или ИИ): орфографию, согласование рода и падежа, пунктуацию,
типографику. Категории LanguageTool, которые оценивают стиль автора («перегружено местоимениями», «избыточные
определения»), отключены — авторский голос не «исправляется». Незнакомые слова с заглавной буквы и частые слова (имена,
термины) вынесены в отдельный свёрнутый список.

`textfix --apply` принимает проверенный список правок:

```json
[{"file": "OPS/ch1.xhtml", "para": 12, "find": "эпадают", "replace": "впадают", "reason": "опечатка распознавания"}]
```

Правка применяется, только если фрагмент встречается в этом абзаце ровно один раз; иначе она пропускается и попадает
в журнал.

### Разработка

```bash
.venv/bin/pytest          # синтетические книги со всеми случаями из настоящих книг; самих книг в репозитории нет
.venv/bin/ruff check .
```

- `krinik_epub_linter.py` — командная строка, сноски, `survey`, `check`.
- `krinik_proofread.py` — встроенные проверки и LanguageTool.
- `krinik_textfix.py` — технические правки и проверенные правки с журналом.

### Лицензия

MIT — см. [LICENSE](LICENSE).
