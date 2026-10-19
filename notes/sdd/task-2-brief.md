### Task 2: Data model and placeholder grammar

**Files:**
- Create: `src/themask/model.py`, `src/themask/placeholders.py`, `src/themask/instruction.py`
- Test: `tests/test_model.py`, `tests/test_placeholders.py`

**Interfaces:**
- Produces (`model.py`): `class PlaceholderType(StrEnum)` with the 12 types; `@dataclass(frozen=True) Finding(type, start, end, text, score: float, source: Literal["pattern","model","rule","list","sweep","user"])`; `@dataclass Group(id: str, type, canonical: str, variants: set[str], findings: list[Finding], placeholder: str, enabled: bool = True, needs_check: bool = False, disabled: set[int] = field(default_factory=set))` with `active_findings() -> list[Finding]`; `@dataclass Analysis(text: str, groups: list[Group], warnings: list[str])`; `@dataclass(frozen=True) Replacement(start, end, placeholder)`; `@dataclass MaskPlan(replacements: list[Replacement])` sorted, non-overlapping (validated in `__post_init__`, raises `ValueError`); `@dataclass KeyEntry(placeholder, type, value, variants: list[str])`; `@dataclass MaskedFile(name, sha256)`; `@dataclass Case(id, created_at: datetime, source_files: list[str], masked_files: list[MaskedFile], entries: list[KeyEntry], retention_days: int = 30)` with `expires_at`, `to_json() -> str`, `Case.from_json(s)`.
- Produces (`placeholders.py`): `format_placeholder(t: PlaceholderType, n: int) -> str`; `PLACEHOLDER_RE: re.Pattern[str]` (exact form); `@dataclass(frozen=True) PlaceholderMatch(start, end, raw: str, placeholder: str, exact: bool)`; `find_placeholders(text: str) -> list[PlaceholderMatch]`; `next_free_number(text: str, t: PlaceholderType) -> int`.
- Produces (`instruction.py`): `AI_INSTRUCTION`, `BANNER_TEXT`, `IMAGE_NOTE`, `OBJECT_NOTE` — the exact strings from Global Constraints.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_placeholders.py
def test_format(): assert format_placeholder(PlaceholderType.PERSON, 1) == "[PERSON_1]"
@pytest.mark.parametrize("raw", ["[PERSON_1]"])
def test_exact(raw):
    m, = find_placeholders(f"Dear {raw},"); assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", True, raw)
@pytest.mark.parametrize("raw", ["PERSON_1", "[PERSON 1]", "[person_1]", r"\[PERSON_1\]", "**[PERSON_1]**", "__[PERSON_1]__", "`[PERSON_1]`", "[PERSON-1]", "[PERSON_01]", "[ PERSON_1 ]", "［PERSON_1］"])
def test_altered(raw):
    m, = find_placeholders(f"Dear {raw},"); assert (m.placeholder, m.exact, m.raw) == ("[PERSON_1]", False, raw)
def test_not_a_placeholder(): assert find_placeholders("[Name] and [Date] and PERSONAL_1 and [TOTAL_3]") == []
def test_next_free(): assert next_free_number("[PERSON_2] [PERSON_7] [COMPANY_1]", PlaceholderType.PERSON) == 8
def test_next_free_empty(): assert next_free_number("nothing", PlaceholderType.PERSON) == 1
```
```python
# tests/test_model.py
def test_maskplan_rejects_overlap():
    with pytest.raises(ValueError): MaskPlan([Replacement(0, 5, "[A_1]"), Replacement(3, 8, "[B_1]")])
def test_case_json_roundtrip():
    c = Case("K4F7", datetime(2026, 10, 17, tzinfo=UTC), ["a.docx"], [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
             [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"])])
    assert Case.from_json(c.to_json()) == c and c.expires_at == c.created_at + timedelta(days=30)
def test_instruction_text_exact():
    assert AI_INSTRUCTION.startswith("This document uses placeholders such as [PERSON_1] and [AMOUNT_2]") and AI_INSTRUCTION.endswith("Word (.docx) file.")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_placeholders.py tests/test_model.py -q` → FAIL (import errors).

- [ ] **Step 3: Implement `model.py`, `placeholders.py`, `instruction.py`**

`find_placeholders`: one compiled regex over an optional marker prefix (`\*\*|__|`|\\`), optional `[`/`［`, optional spaces, type name (case-insensitive, from the enum), separator `[_ -]`, digits, optional spaces, optional `]`/`］`/`\]`, matching marker suffix; `exact` is true only for `[TYPE_N]` with upper-case type, underscore, no leading zero, no markers. Whole-word check (`(?<![A-Za-z0-9])` … `(?![A-Za-z0-9])`) so `PERSONAL_1` is not matched.

- [ ] **Step 4: Run to verify pass** — same command → PASS; `uv run ruff check src tests && uv run mypy src` clean.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: data model, placeholder grammar and fixed copy"`

---

