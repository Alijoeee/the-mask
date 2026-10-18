# The made-up contract corpus

Every test that needs a contract uses this corpus: 25 made-up English contracts as Word files
(supply, logistics services, NDA and data processing agreements), three annexes that belong to
three of them, and for each Word file a **truth file** listing every secret in it. Eight PDF files
are made from the same contracts (see [PDF files](#pdf-files)). Nothing in it is real: the companies
are invented, web and e-mail domains end in `.example`, UK telephone numbers come from Ofcom's
ranges for drama, and IBANs, BICs and VAT numbers only have valid check digits. The files are not
stored in git; they are generated, the same bytes every time.

## Getting the files

- In tests: the session fixture `corpus` (in `tests/fixtures/corpus.py`) generates everything
  once per test run into a temporary folder and returns its path.
- By hand: `uv run python -m tools.make_corpus [out_dir]` (default `tests/corpus/generated/`,
  which git ignores). It takes about two seconds.

The generator is `tools/make_corpus.py` (the list of documents and `generate`) with its parts in
`tools/corpus/` (contract wording, people and numbers, truth, the Word writer and the PDF writer).

## What is in the folder

- `<name>.docx` and `<name>.truth.json` for each document, for example `supply-01.docx`.
- `<name>.pdf` for the eight PDF files. They have no truth file of their own.
- `manifest.json`: a list of `{"file", "format", "features", "truth"}`, one per file: the Word
  files first (`"format": "docx"`), then the PDF files (`"format": "pdf"`, with two more keys, see
  below). An annex has `"annex_of"` naming its contract (`supply-07-annex.docx` belongs to
  `supply-07.docx`).

A truth file is a JSON list of `{"type", "value", "variants"}`, `type` being a placeholder type
(`PERSON`, `COMPANY`, `AMOUNT`, ...). `value` is the fullest form and `variants` the other forms
the document uses ("Northwind", "Mr Smith", "J. Smith", an IBAN without spaces), each written
exactly as in the document; the file is plain ASCII, so a no-break space in a number shows as
`\u00a0`. Two flags appear only when true: `"only_in_deletion"` (the value is only in tracked-deleted
text) and `"hidden"` (only in hidden text). Dates, durations ("30 days"), clause numbers,
governing law ("England and Wales"), defined terms and bare currency codes are never secrets.
"Project Falcon" in `supply-08` is not a truth item: it is plain text, the term later tests
add by hand as one the owner always hides.

## Features

Every contract has a header with the parties' short names and the title, a footer with a `PAGE`
field, a table, and both party names in bold and split across three runs in its parties clause.

| Feature | Files |
|---|---|
| `header_footer`, `table` | all 25 contracts |
| `comments` | supply-02, services-05, nda-05 |
| `tracked_changes` | supply-03, nda-05, dpa-03, dpa-05 |
| `secret_only_in_deletion` | supply-03, nda-05, dpa-03 |
| `image` (logo and signature) | supply-05, nda-03, dpa-01 |
| `footnotes` | supply-06, nda-01, dpa-02, dpa-05 |
| `hidden_text` | services-02, nda-02, dpa-03 |
| `textbox` ("Text box note") | services-03, nda-04, dpa-03 |
| `properties` (core, app and custom) | supply-04, nda-04, dpa-01 |
| `hyperlinks` (`mailto:` and web) | services-01, nda-01, dpa-01 |
| `shared_surname` | supply-08, nda-02, dpa-04 |
| `existing_placeholders` (`[PERSON_1]`, `[Name]`) | supply-09, nda-03, dpa-04 |
| `nbsp_numbers` | services-04, nda-04, dpa-02 |
| `annex` | supply-07, services-05, dpa-02 |
| `thirty_pages` (over 12,000 words) | supply-10, services-05, dpa-05 |

The first file named for a feature is the one later tasks test it on. `supply-01` is the plain
baseline (straight quotes, amounts like "EUR 1,250,000.00", percentages like "4 per cent") whose
first party is "Northwind Trading B.V." with IBAN NL91 ABNA 0417 1643 00; `supply-06` has "Acme"
in its header, footer and footnotes; `supply-08` names "Project Falcon" twice. The other
contracts vary the style: curly quotes, `€` or a code after the number, European separators,
amounts in words, names in capitals.

## PDF files

Eight PDF files come from the same contract data as Word files, and a PDF shares the truth file of
the contract it is made from. Its manifest entry says which: `"source"` is the contract
(`"supply-01"`) and `"truth"` its truth file (`"supply-01.truth.json"`). `"image_pages"` lists the
pages, counted from 1, that are only a picture and have no text layer.

| File | Made from | `features` | `image_pages` | What it is for |
|---|---|---|---|---|
| `supply-01.pdf` | supply-01 | `header_footer`, `table` | none | the plain baseline (straight quotes, "per cent"), 5 pages |
| `supply-04.pdf` | supply-04 | `header_footer`, `table` | none | a second supply contract (percentages as 1.5%); its document properties stay in Word |
| `supply-05.pdf` | supply-05 | `header_footer`, `image`, `table` | none | a logo and a signature as pictures among the text |
| `supply-06.pdf` | supply-06 | `footnotes`, `header_footer`, `table` | none | footnotes, in a "NOTES" block at the end; "Acme" in the header |
| `supply-10.pdf` | supply-10 | `header_footer`, `table`, `thirty_pages` | none | a long PDF: 24 pages, about 12,800 words |
| `nda-01.pdf` | nda-01 | `footnotes`, `header_footer`, `table` | none | a short NDA (4 pages) with curly quotes and footnotes; its links stay in Word |
| `scanned-01.pdf` | supply-01 | `scanned` | all (1 to 5) | no text at all: one picture to a page |
| `mixed-01.pdf` | dpa-01 | `mixed` | 2 | text on every page but page 2, which is a picture |

**The six text PDFs** have A4 pages set in Helvetica (the built-in font family: nothing embedded).
Every page has a running header `<Short A> / <Short B> — <Title>`, for example
`Northwind / Thamesgate — Supply Agreement`, and a footer `Page N of M · Confidential`. Titles are
set in 16 pt, headings in 12 pt bold capitals and body text in 10 pt, so a reader can tell headings
by size; table cells are 9 pt and the header and footer 8.5 pt. The pricing table is a ruled grid
with a shaded header row, and lettered lists are (a), (b), (c). A paragraph or table never splits
across pages, so a page break never cuts a value in two. The footnotes of the Word file are a
"NOTES" block after the signatures, with a raised number in the text.

A PDF keeps only the features of its Word file that a PDF can have (`header_footer`, `table`,
`image`, `footnotes` and `thirty_pages`); comments, tracked changes, hidden text, text boxes,
document properties and links are Word's own. These six contracts have no value only in deleted or
hidden text and no special space (the narrow no-break space of `services-04` is not in the font's
encoding), so every value and every variant of their truth file is in the text of the PDF:
`normalize(value)` is found in `pdfplumber`'s text of the pages, and every place the Word file
writes a value, the PDF writes it whole (a line break only adds a space).

**`scanned-01.pdf`** is `supply-01` typeset page by page by Pillow at 150 dpi (a picture of 1240 by
1754 pixels on every A4 page, grey on white, in Bitstream Vera Sans, which reportlab brings with it)
and placed by reportlab, so the file has no text layer: `extract_text()` is empty on all five
pages. A reader gets the values by OCR. In one check with macOS Vision every value and variant of
its truth file was read back except the BIC `ABNANL2A`, which came out as `ABNANLZA`.

**`mixed-01.pdf`** is `dpa-01` as a text PDF whose page 2 is a picture of the blocks that page
holds in the all-text layout (a little smaller, so that they fit), with the same header and footer
drawn into it. The other four pages are text. Some values are only on page 2, in the picture, for
example the processor's IBAN; the BIC is on page 3, as text.
