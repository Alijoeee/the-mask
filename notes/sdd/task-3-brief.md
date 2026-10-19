### Task 3: Text normalisation and variants

**Files:**
- Create: `src/themask/textnorm.py`
- Test: `tests/test_textnorm.py`

**Interfaces:**
- Produces: `normalize(s: str) -> str` (NFKC → casefold → drop every Unicode whitespace incl. `     ` → drop punctuation `.,;:'"’‘“”()[]{}/\-_–—` → keep letters and digits); `variants_of(value: str, t: PlaceholderType) -> set[str]` (always includes `value`); `flexible_pattern(value: str) -> re.Pattern[str]` (case-insensitive; any run of whitespace in `value` matches `\s+`; word boundaries at alphanumeric ends).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("a,b", [("1,250,000", "1.250.000"), ("EUR 1 250 000,00", "eur 1.250.000,00"), ("NL91 ABNA 0417 1643 00", "NL91ABNA0417164300"), ("John  Smith", "john smith"), ("Acme Supplies Ltd.", "ACME SUPPLIES LTD")])
def test_normalize_equal(a, b): assert normalize(a) == normalize(b)
def test_normalize_keeps_digits_and_letters(): assert normalize("K4-F7 x") == "k4f7x"
def test_person_variants():
    v = variants_of("Mr John Smith", PlaceholderType.PERSON); assert {"Mr John Smith", "John Smith", "J. Smith"} <= v and "Smith" not in v
def test_company_variants():
    v = variants_of("Northwind Trading B.V.", PlaceholderType.COMPANY); assert {"Northwind Trading", "Northwind"} <= v
def test_company_first_word_not_common():
    assert "General" not in variants_of("General Supplies Ltd", PlaceholderType.COMPANY)
def test_amount_variants(): assert "1,250,000" in variants_of("EUR 1,250,000.00", PlaceholderType.AMOUNT)
def test_phone_variants(): assert "020 123 4567" in variants_of("+31 20 123 4567", PlaceholderType.PHONE)
def test_url_variants(): assert {"northwind.example", "www.northwind.example"} <= variants_of("https://www.northwind.example", PlaceholderType.URL)
def test_flexible_pattern(): assert flexible_pattern("John Smith").search("JOHN\n  smith") and not flexible_pattern("Smith").search("Smithson")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_textnorm.py -q` → FAIL.

- [ ] **Step 3: Implement `textnorm.py`**

Variant rules: PERSON — strip honorifics (`Mr Mrs Ms Mx Dr Prof Sir Dame Mevr Dhr Herr Frau`), add `F. Last` initial form, never surname alone. COMPANY — strip one trailing legal-form token (list shared with Task 7 via a module constant `LEGAL_FORMS`), add first token alone only if ≥ 4 letters and not in a small `COMMON_WORDS` stoplist (General, International, Global, European, National, United, Services, Group, Holdings, Trading, Supplies…). AMOUNT — the bare number, number without decimals, with/without currency. PHONE — national format via `phonenumbers` when parseable. URL — without scheme, without `www.`. Others — the value only (normalise handles spacing/case).

- [ ] **Step 4: Run to verify pass**, lint, types. **Step 5: Commit** — `git commit -am "feat: text normalisation and value variants"` (after `git add`).

---

