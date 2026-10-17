import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from themask.instruction import AI_INSTRUCTION, BANNER_TEXT, IMAGE_NOTE, OBJECT_NOTE
from themask.model import (
    Analysis,
    Case,
    Finding,
    Group,
    KeyEntry,
    MaskedFile,
    MaskPlan,
    PlaceholderType,
    Replacement,
)

OCT_17 = datetime(2026, 10, 17, tzinfo=UTC)


def make_case(created_at: datetime = OCT_17, retention_days: int = 30) -> Case:
    return Case(
        "K4F7",
        created_at,
        ["a.docx"],
        [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
        [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"])],
        retention_days,
    )


def make_findings(count: int = 3) -> list[Finding]:
    return [
        Finding(PlaceholderType.PERSON, 10 * i, 10 * i + 4, "John", 0.9, "model")
        for i in range(count)
    ]


def make_group(enabled: bool = True, disabled: set[int] | None = None) -> Group:
    return Group(
        "g1",
        PlaceholderType.PERSON,
        "John Smith",
        {"John Smith", "John"},
        make_findings(),
        "[PERSON_1]",
        enabled=enabled,
        disabled=disabled or set(),
    )


def test_twelve_placeholder_types() -> None:
    assert [t.value for t in PlaceholderType] == [
        "PERSON",
        "COMPANY",
        "AMOUNT",
        "PERCENT",
        "QUANTITY",
        "EMAIL",
        "PHONE",
        "ADDRESS",
        "IBAN",
        "ID",
        "URL",
        "CUSTOM",
    ]
    assert all(str(t) == t.name == t.value for t in PlaceholderType)


def test_dataclass_fields_keep_the_order_other_tasks_rely_on() -> None:
    finding = Finding(PlaceholderType.EMAIL, 3, 9, "a@b.co", 0.8, "pattern")
    assert (finding.type, finding.start, finding.end, finding.text) == (
        PlaceholderType.EMAIL,
        3,
        9,
        "a@b.co",
    )
    assert (finding.score, finding.source) == (0.8, "pattern")
    assert Replacement(3, 9, "[EMAIL_1]") == Replacement(start=3, end=9, placeholder="[EMAIL_1]")
    analysis = Analysis("text", [], ["a warning"])
    assert (analysis.text, analysis.groups, analysis.warnings) == ("text", [], ["a warning"])
    entry = KeyEntry("[IBAN_1]", PlaceholderType.IBAN, "NL91 ABNA 0417 1643 00", [])
    assert (entry.placeholder, entry.type, entry.value, entry.variants) == (
        "[IBAN_1]",
        PlaceholderType.IBAN,
        "NL91 ABNA 0417 1643 00",
        [],
    )
    assert MaskedFile("MASKED-K4F7.docx", "00") == MaskedFile(name="MASKED-K4F7.docx", sha256="00")


def test_findings_and_replacements_are_frozen() -> None:
    finding, replacement = make_findings(1)[0], Replacement(0, 1, "[A_1]")
    with pytest.raises(FrozenInstanceError):
        finding.start = 1
    with pytest.raises(FrozenInstanceError):
        replacement.end = 2


def test_group_defaults() -> None:
    group = make_group()
    assert (group.enabled, group.needs_check, group.disabled) == (True, False, set())


def test_groups_do_not_share_their_switched_off_occurrences() -> None:
    first, second = make_group(), make_group()
    first.disabled.add(0)
    assert second.disabled == set()


def test_active_findings_are_all_findings_by_default() -> None:
    group = make_group()
    assert group.active_findings() == group.findings


def test_active_findings_skip_switched_off_occurrences() -> None:
    group = make_group(disabled={0, 2})
    assert group.active_findings() == [group.findings[1]]


def test_a_disabled_group_has_no_active_findings() -> None:
    group = make_group(enabled=False)
    assert group.active_findings() == []
    group.enabled = True
    assert group.active_findings() == group.findings


def test_maskplan_rejects_overlap() -> None:
    with pytest.raises(ValueError):
        MaskPlan([Replacement(0, 5, "[A_1]"), Replacement(3, 8, "[B_1]")])


@pytest.mark.parametrize(
    "replacements",
    [
        [Replacement(0, 10, "[A_1]"), Replacement(2, 4, "[B_1]")],  # one inside the other
        [Replacement(10, 12, "[A_1]"), Replacement(0, 5, "[B_1]"), Replacement(3, 8, "[C_1]")],
        [Replacement(0, 5, "[A_1]"), Replacement(0, 5, "[B_1]")],  # the same span twice
        [Replacement(4, 9, "[A_1]"), Replacement(0, 5, "[B_1]")],  # given out of order
    ],
)
def test_maskplan_rejects_every_kind_of_overlap(replacements: list[Replacement]) -> None:
    with pytest.raises(ValueError, match="overlap"):
        MaskPlan(replacements)


def test_maskplan_sorts_by_start() -> None:
    late = Replacement(20, 25, "[C_1]")
    middle = Replacement(10, 12, "[B_1]")
    early = Replacement(0, 5, "[A_1]")
    given = [late, middle, early]
    plan = MaskPlan(given)
    assert plan.replacements == [early, middle, late]
    assert given == [late, middle, early]  # the caller's list is left as it was


def test_maskplan_accepts_replacements_that_touch() -> None:
    plan = MaskPlan([Replacement(5, 8, "[B_1]"), Replacement(0, 5, "[A_1]")])
    assert [(r.start, r.end) for r in plan.replacements] == [(0, 5), (5, 8)]


def test_maskplan_may_be_empty() -> None:
    assert MaskPlan([]).replacements == []


def test_case_json_roundtrip() -> None:
    c = Case(
        "K4F7",
        datetime(2026, 10, 17, tzinfo=UTC),
        ["a.docx"],
        [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
        [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"])],
    )
    assert Case.from_json(c.to_json()) == c and c.expires_at == c.created_at + timedelta(days=30)


def test_case_retention_defaults_to_thirty_days() -> None:
    assert Case("K4F7", OCT_17, [], [], []).retention_days == 30


def test_case_expires_after_its_retention_days() -> None:
    case = make_case(retention_days=7)
    assert case.expires_at == datetime(2026, 10, 24, tzinfo=UTC)
    assert Case.from_json(case.to_json()).retention_days == 7


def test_case_json_has_the_agreed_shape() -> None:
    assert json.loads(make_case().to_json()) == {
        "id": "K4F7",
        "created_at": "2026-10-17T00:00:00+00:00",
        "source_files": ["a.docx"],
        "masked_files": [{"name": "MASKED-K4F7.docx", "sha256": "ab" * 32}],
        "entries": [
            {
                "placeholder": "[PERSON_1]",
                "type": "PERSON",
                "value": "John Smith",
                "variants": ["Mr Smith"],
            }
        ],
        "retention_days": 30,
    }


def test_case_json_stores_utc_whatever_the_timezone_given() -> None:
    case = make_case(created_at=datetime(2026, 10, 17, 9, 30, tzinfo=timezone(timedelta(hours=2))))
    assert json.loads(case.to_json())["created_at"] == "2026-10-17T07:30:00+00:00"
    restored = Case.from_json(case.to_json())
    assert restored == case  # the same moment in time
    assert restored.created_at.utcoffset() == timedelta(0)


def test_case_json_roundtrip_keeps_text_order_and_empty_lists() -> None:
    case = Case(
        "ZZ99",
        datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
        ["Überträge – Å.docx", "株式会社.docx"],
        [],
        [
            KeyEntry("[COMPANY_2]", PlaceholderType.COMPANY, "Zoë Müller-Ålesund B.V.", []),
            KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, 'Acme "The Best" Ltd', ["Acme"]),
            KeyEntry(
                "[CUSTOM_1]",
                PlaceholderType.CUSTOM,
                "one\ntwo\ttabbed",
                ["\N{LEFT SINGLE QUOTATION MARK}s"],
            ),
        ],
        retention_days=365,
    )
    assert Case.from_json(case.to_json()) == case


@pytest.mark.parametrize(
    "garbage", ["", "not json", "[]", "null", "5", '"text"', "{}", '{"id": "K4F7"}']
)
def test_case_from_json_refuses_what_is_not_a_case(garbage: str) -> None:
    with pytest.raises(ValueError):
        Case.from_json(garbage)


DAMAGE: dict[str, Callable[[dict[str, Any]], object]] = {
    "unknown placeholder type": lambda d: d["entries"][0].update(type="BOGUS"),
    "timestamp that is not a date": lambda d: d.update(created_at="yesterday"),
    "timestamp that is not text": lambda d: d.update(created_at=5),
    "masked file that is not an object": lambda d: d.update(masked_files=[5]),
    "entry without a type": lambda d: d.update(entries=[{"placeholder": "[PERSON_1]"}]),
    "missing retention": lambda d: d.pop("retention_days"),
}


@pytest.mark.parametrize("damage", DAMAGE.values(), ids=DAMAGE.keys())
def test_case_from_json_refuses_a_damaged_case(damage: Callable[[dict[str, Any]], object]) -> None:
    data = json.loads(make_case().to_json())
    damage(data)
    with pytest.raises(ValueError):
        Case.from_json(json.dumps(data))


def test_instruction_text_exact() -> None:
    assert AI_INSTRUCTION.startswith(
        "This document uses placeholders such as [PERSON_1] and [AMOUNT_2]"
    ) and AI_INSTRUCTION.endswith("Word (.docx) file.")


def test_fixed_copy_is_verbatim() -> None:
    assert AI_INSTRUCTION == (
        "This document uses placeholders such as [PERSON_1] and [AMOUNT_2] instead of "
        "confidential values. Keep every placeholder exactly as written, including the square "
        "brackets, in your answer and in any file you create. Do not guess the real values. "
        "Please give your result as a Word (.docx) file."
    )
    assert BANNER_TEXT == (
        "Confidential values in this document are replaced by placeholders such as [COMPANY_1]. "
        "Keep them unchanged."
    )
    assert IMAGE_NOTE == "[image removed]"
    assert OBJECT_NOTE == "[embedded object removed]"
