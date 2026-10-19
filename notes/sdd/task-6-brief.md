### Task 6: Detection engine and pattern recognizers

**Files:**
- Create: `src/themask/detect/__init__.py`, `src/themask/detect/engine.py`, `src/themask/detect/patterns.py`, `src/themask/detect/nlp_config.yaml`
- Modify: `tests/conftest.py` (session fixture `engine`)
- Test: `tests/detect/test_patterns.py`

**Interfaces:**
- Produces: `class Engine: def __init__(self, model_name: str = "en_core_web_md") ...; def analyze(self, text: str) -> list[Finding]` (Presidio `AnalyzerEngine` with `NlpEngineProvider(conf_file=nlp_config.yaml)`, our recognizers registered, Presidio entities mapped: `EMAIL_ADDRESS→EMAIL, PHONE_NUMBER→PHONE, IBAN_CODE→IBAN, CREDIT_CARD→ID, URL→URL, PERSON→PERSON, ORGANIZATION→COMPANY, LOCATION→ADDRESS (kept only when Task 7 confirms an address context), US_SSN/US_PASSPORT/UK_NHS/UK_NINO→ID`; `low_score_entity_names: []`; `labels_to_ignore` keeps Presidio's defaults so MONEY/PERCENT/QUANTITY come from our regexes). Phone regions `GB NL DE FR BE IE TR US ES IT CH AT DK SE NO PL`.
- Produces (`patterns.py`, all `presidio_analyzer.PatternRecognizer` subclasses, `supported_entity` = our type names): `AmountRecognizer`, `PercentRecognizer`, `QuantityRecognizer`, `VatRecognizer` (validates with `stdnum.eu.vat`; valid → 0.9, format-only → 0.6), `RegistrationNumberRecognizer` (context: registered/company/registration/KvK/Chamber of Commerce/Companies House/HRB + number), `BicRecognizer` (validated with `schwifty.BIC`), `AccountNumberRecognizer` (context account/sort code), `NationalIdRecognizer` (NL BSN via `stdnum.nl.bsn`, TR TCKN via `stdnum.tr.tckimlik`, passport-number context), `BareNumberRecognizer` (≥ 1,000 with separators or decimals, base 0.4, context price/fee/amount/total/value/charge → 0.75; excludes years 1900–2099, clause numbers `\d+\.\d+` at line start, numbers followed by day/days/month/months/year/years/hours).
- `Engine.analyze` returns `Finding(score=…, source="pattern" | "model")`; findings with score < 0.3 are dropped.

- [ ] **Step 1: Write the failing tests** (positive and negative per type; `engine` fixture is session-scoped)

```python
def types_at(engine, text, needle):
    return {f.type for f in engine.analyze(text) if text[f.start:f.end].strip() == needle}
@pytest.mark.parametrize("text,needle", [("The Price is EUR 1,250,000.00 per year.", "EUR 1,250,000.00"), ("a fee of €1.25m", "€1.25m"), ("pay 1.250.000,00 EUR", "1.250.000,00 EUR"), ("the sum of one million euros", "one million euros"), ("EUR 1 250 000,00", "EUR 1 250 000,00"), ("GBP 48,000", "GBP 48,000")])
def test_amounts(engine, text, needle): assert PlaceholderType.AMOUNT in types_at(engine, text, needle)
@pytest.mark.parametrize("text", ["within 30 days", "in 2026", "clause 10.2 applies", "a term of 5 years", "Schedule 3"])
def test_not_amount_or_quantity(engine, text): assert not {PlaceholderType.AMOUNT, PlaceholderType.QUANTITY} & {f.type for f in engine.analyze(text)}
@pytest.mark.parametrize("text,needle", [("a discount of 12.5%", "12.5%"), ("interest at 8 per cent", "8 per cent")])
def test_percent(engine, text, needle): assert PlaceholderType.PERCENT in types_at(engine, text, needle)
@pytest.mark.parametrize("text,needle", [("minimum order of 10,000 units", "10,000 units"), ("deliver 48 pallets", "48 pallets"), ("capacity of 2.5 tonnes", "2.5 tonnes")])
def test_quantity(engine, text, needle): assert PlaceholderType.QUANTITY in types_at(engine, text, needle)
def test_iban_valid_only(engine):
    assert PlaceholderType.IBAN in types_at(engine, "IBAN NL91 ABNA 0417 1643 00", "NL91 ABNA 0417 1643 00")
    assert PlaceholderType.IBAN not in {f.type for f in engine.analyze("IBAN NL91 ABNA 0417 1643 01")}
def test_bic(engine): assert PlaceholderType.ID in types_at(engine, "BIC: ABNANL2A", "ABNANL2A")
def test_vat(engine): assert PlaceholderType.ID in types_at(engine, "VAT number NL123456782B01", "NL123456782B01")
def test_registration(engine): assert PlaceholderType.ID in types_at(engine, "registered in England and Wales under number 01234567", "01234567")
def test_email_phone_url(engine):
    t = "Contact j.smith@northwind.example, +31 20 123 4567 or https://www.northwind.example/legal"
    found = {f.type for f in engine.analyze(t)}; assert {PlaceholderType.EMAIL, PlaceholderType.PHONE, PlaceholderType.URL} <= found
def test_bare_number_in_price_context_is_low_confidence_amount(engine):
    f, = [f for f in engine.analyze("Total price: 48,000") if f.type == PlaceholderType.AMOUNT]; assert 0.3 <= f.score < 0.85
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/detect/test_patterns.py -q` → FAIL.
- [ ] **Step 3: Implement `nlp_config.yaml`, `engine.py`, `patterns.py`** (regexes for amounts: currency symbol/code before or after; digits with `[.,\s   ]` separators; optional decimals; optional `k|m|bn|million|billion|thousand`; number words one…ninety-nine + hundred/thousand/million + currency word).
- [ ] **Step 4: Run to verify pass**, lint, types. **Step 5: Commit** — `git add -A && git commit -m "feat: Presidio engine with contract pattern recognizers"`

---

