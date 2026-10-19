### Task 4: Made-up contract corpus (Word) with ground truth

**Files:**
- Create: `tools/make_corpus.py`, `tests/corpus/__init__.py`, `tests/corpus/README.md`, `tests/test_corpus.py`
- Modify: `tests/conftest.py` (add `corpus` fixture), `.gitignore` (`tests/corpus/generated/`)

**Interfaces:**
- Produces (`tools/make_corpus.py`, importable as `tools.make_corpus`): `@dataclass TruthItem(type: PlaceholderType, value: str, variants: list[str])`; `@dataclass ContractSpec(kind: Literal["supply","services","nda","dpa"], seed: int, features: frozenset[str], truth: list[TruthItem], defined_terms: list[str], …)`; `build_spec(seed: int, kind: str, features: frozenset[str]) -> ContractSpec`; `write_docx(spec, path: Path) -> None`; `write_truth(spec, path: Path) -> None` (JSON list of TruthItem); `generate(out_dir: Path) -> list[dict]` writing 20 `.docx` + 20 `.truth.json` + `manifest.json`; CLI `python -m tools.make_corpus <out_dir>`.
- Features (each used by ≥ 3 documents, all 20 have `header_footer` and `table`): `comments`, `tracked_changes`, `secret_only_in_deletion`, `image`, `footnotes`, `hidden_text`, `textbox`, `properties`, `hyperlinks`, `shared_surname`, `existing_placeholders`, `nbsp_numbers`, `annex` (a second file in the same case), `thirty_pages`. In every document the party names in the parties clause are **bold and split across three runs** (as Word often saves them).
- Fixed assignments later tasks rely on: `supply-01` baseline; `supply-02` comments; `supply-03` tracked_changes + secret_only_in_deletion (truth item carries `"only_in_deletion": true`); `supply-04` properties (+ custom.xml); `supply-05` image (logo); `supply-06` footnotes + "Acme" in header and footer; `supply-07` + `supply-07-annex.docx` (annex); `supply-08` shared_surname + the phrase "Project Falcon" twice; `supply-09` existing_placeholders; `supply-10` thirty_pages; `services-01` hyperlinks (a `mailto:` link); `services-02` hidden_text (truth item carries `"hidden": true`); `services-03` textbox containing "Text box note"; `services-04` nbsp_numbers. The remaining documents (`services-05`, `nda-01…05`, `dpa-01…05`) mix the features freely.
- Produces fixture `corpus(tmp_path_factory) -> Path` (session scope, generated once per run).

- [ ] **Step 1: Write the failing tests**

```python
def test_corpus_counts(corpus):
    assert len(list(corpus.glob("*.docx"))) >= 20 and len(list(corpus.glob("*.truth.json"))) >= 20
def test_truth_covers_every_type(corpus):
    types = {t["type"] for p in corpus.glob("*.truth.json") for t in json.loads(p.read_text())}
    assert {"PERSON","COMPANY","AMOUNT","PERCENT","QUANTITY","EMAIL","PHONE","ADDRESS","IBAN","ID","URL"} <= types
def test_features_are_real(corpus):
    man = json.loads((corpus / "manifest.json").read_text())
    for doc in man:
        names = set(zipfile.ZipFile(corpus / doc["file"]).namelist()); xml = zipfile.ZipFile(corpus / doc["file"]).read("word/document.xml").decode()
        if "comments" in doc["features"]: assert "word/comments.xml" in names
        if "tracked_changes" in doc["features"]: assert "<w:ins " in xml and "<w:del " in xml
        if "image" in doc["features"]: assert any(n.startswith("word/media/") for n in names)
        if "properties" in doc["features"]: assert "<dc:creator>" in zipfile.ZipFile(corpus / doc["file"]).read("docProps/core.xml").decode()
def test_every_truth_value_is_in_the_file(corpus):
    for p in corpus.glob("*.truth.json"):
        blob = normalize("".join(zipfile.ZipFile(p.with_suffix("").with_suffix(".docx")).read(n).decode("utf-8","ignore") for n in zipfile.ZipFile(p.with_suffix("").with_suffix(".docx")).namelist() if n.endswith(".xml")))
        for t in json.loads(p.read_text()): assert normalize(t["value"]) in blob, (p.name, t["value"])
def test_deterministic(tmp_path):
    a = generate(tmp_path / "a"); b = generate(tmp_path / "b"); assert a == b and (tmp_path/"a"/"supply-01.truth.json").read_bytes() == (tmp_path/"b"/"supply-01.truth.json").read_bytes()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_corpus.py -q` → FAIL.

- [ ] **Step 3: Implement `tools/make_corpus.py`**

`Faker("en_GB")` and `random.Random(seed)`, seeded per document. Each contract: title, parties clause (`BETWEEN: (1) <Company A>, a company registered in <country> under number <reg>, whose registered office is at <address> (the "Supplier"); and (2) <Company B> … (the "Buyer")`), 8–12 numbered clauses using the defined terms, a pricing table (amounts, percentages, quantities with units), payment clause with IBAN/BIC (valid, from `schwifty` generation) and VAT numbers (valid via `stdnum`), notices clause (`Attention: <Mr X>`, address, e-mail, phone, URL), signature blocks (`By: … Name: … Title: …`), header with short party names and footer with page number. Variants used deliberately in the text (`Acme`, `Mr Smith`, `J. Smith`) and listed in `TruthItem.variants`. Dates, durations (`30 days`), governing law (`England and Wales`) appear and are **not** in truth. Tracked changes and comments are written as raw XML with lxml (python-docx 1.2 can add comments; `w:ins`/`w:del` by hand). `thirty_pages` repeats clause blocks until ≥ 30 pages of text (~12,000 words). `existing_placeholders` contains the literal `[PERSON_1]` and `[Name]`. `shared_surname` has two signatories with the same surname and a later `Mr <Surname>`.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_corpus.py -q` → PASS. Open one generated file in Word by hand once to confirm it looks like a contract (`open tests/corpus/generated/supply-01.docx`).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "test: deterministic made-up contract corpus with ground truth"`

---

