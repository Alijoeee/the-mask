### Task 7: Names, companies, addresses: model + contract rules

**Files:**
- Create: `src/themask/detect/contract_rules.py`
- Modify: `src/themask/detect/engine.py` (call rules; address confirmation for LOCATION), `src/themask/textnorm.py` (`LEGAL_FORMS` constant shared)
- Test: `tests/detect/test_contract_rules.py`

**Interfaces:**
- Produces: `LEGAL_FORMS: tuple[str, ...]` (`B.V., N.V., GmbH, AG, S.A., S.A.S., S.r.l., S.p.A., Ltd, Limited, LLP, LLC, Inc., Incorporated, plc, Corp., Corporation, Co., KG, OHG, A.Ş., Ltd. Şti., Oy, AB, ApS, A/S, SE` with optional dots); `find_parties(text) -> list[Finding]` (BETWEEN clause within the first 4,000 chars); `find_legal_form_companies(text) -> list[Finding]` (1–6 capitalised tokens + legal form, score 0.95); `find_signature_blocks(text) -> list[Finding]` (`Name:`/`By:`/`Signed by:` → PERSON unless legal form → COMPANY; `Attention:`/`Attn:`/`For the attention of` → PERSON); `find_addresses(text) -> list[Finding]` (`Address:`/`Registered office:` lines; `registered office is at …`/`principal place of business at …` up to `(`, `;`, ` and `, newline; street-pattern with number + street word incl. `straat weg laan plein Straße Platz Caddesi Sokak`; postcodes UK/NL/DE/FR/TR extend the span); `find_defined_terms(text) -> set[str]` (`(the "Supplier")`, `("Buyer")`, `hereinafter "X"`); `apply_rules(text) -> tuple[list[Finding], set[str]]`.
- Changes `Engine.analyze`: merges rule findings (`source="rule"`); model LOCATION kept only if overlapping/adjacent to an address finding (else dropped); COMPANY from the model without a legal form and without rule confirmation gets `score = min(score, 0.6)` (becomes "check" in Task 8).

- [ ] **Step 1: Write the failing tests**

```python
PARTIES = 'THIS AGREEMENT is made on 1 March 2026\nBETWEEN:\n(1) Northwind Trading B.V., a company registered in the Netherlands under number 12345678, whose registered office is at Keizersgracht 123, 1015 CJ Amsterdam, the Netherlands (the "Supplier"); and\n(2) Acme Supplies Ltd, registered in England and Wales under number 01234567, whose registered office is at 10 Downing Street, London SW1A 2AA (the "Buyer").'
def texts(fs, t): return {t[f.start:f.end] for f in fs}
def test_parties_found():
    fs, terms = apply_rules(PARTIES)
    assert {"Northwind Trading B.V.", "Acme Supplies Ltd"} <= texts([f for f in fs if f.type == PlaceholderType.COMPANY], PARTIES)
    assert terms == {"Supplier", "Buyer"}
def test_addresses_found():
    fs, _ = apply_rules(PARTIES); addr = texts([f for f in fs if f.type == PlaceholderType.ADDRESS], PARTIES)
    assert any(a.startswith("Keizersgracht 123") and a.endswith("Netherlands") for a in addr) and any("SW1A 2AA" in a for a in addr)
def test_signature_block():
    t = "SIGNED for and on behalf of the Supplier\nBy: ____\nName: Dr Jane Smith\nTitle: Managing Director\nAttention: Mr Tom Brown"
    fs, _ = apply_rules(t); assert {"Dr Jane Smith", "Mr Tom Brown"} <= texts([f for f in fs if f.type == PlaceholderType.PERSON], t)
    assert "Managing Director" not in texts(fs, t)
def test_jurisdiction_stays_visible(engine):
    fs = engine.analyze("This Agreement is governed by the laws of the Netherlands and the courts of Amsterdam.")
    assert not [f for f in fs if f.type == PlaceholderType.ADDRESS]
def test_model_person_in_prose(engine):
    fs = engine.analyze("The notice was sent by Jane Smith to the Buyer on Monday."); assert "Jane Smith" in texts([f for f in fs if f.type == PlaceholderType.PERSON], "The notice was sent by Jane Smith to the Buyer on Monday.")
def test_legal_form_company_in_prose(engine):
    t = "Supplies are sourced from Baltic Fasteners GmbH and its affiliates."; assert "Baltic Fasteners GmbH" in texts([f for f in engine.analyze(t) if f.type == PlaceholderType.COMPANY], t)
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement.** **Step 4: Run to verify pass**, lint, types.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: contract-aware rules for parties, signatures, addresses"`

---

