# The made-up contract corpus

Every test that needs a contract uses this corpus: 25 made-up English contracts as Word files
(supply, logistics services, NDA and data processing agreements), three annexes that belong to
three of them, and for each Word file a **truth file** listing every secret in it. Nothing in it
is real: the companies are invented, web and e-mail domains end in `.example`, UK telephone
numbers come from Ofcom's ranges for drama, and IBANs, BICs and VAT numbers only have valid check
digits. The files are not stored in git; they are generated, the same bytes every time.

## Getting the files

- In tests: the session fixture `corpus` (in `tests/fixtures/corpus.py`) generates everything
  once per test run into a temporary folder and returns its path.
- By hand: `uv run python -m tools.make_corpus [out_dir]` (default `tests/corpus/generated/`,
  which git ignores). It takes about two seconds.

The generator is `tools/make_corpus.py` (the list of documents and `generate`) with its parts in
`tools/corpus/` (contract wording, people and numbers, truth, the Word writer).

## What is in the folder

- `<name>.docx` and `<name>.truth.json` for each document, for example `supply-01.docx`.
- `manifest.json`: a list of `{"file", "format", "features", "truth"}`, one per Word file. An
  annex has `"annex_of"` naming its contract (`supply-07-annex.docx` belongs to `supply-07.docx`).

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
