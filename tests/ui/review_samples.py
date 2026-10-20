"""Reviews made by hand for the tests of the review screen: no detection engine, so they are fast.

``custom_review`` makes a review of a text with a group for each spec; the samples below are a
contract with one group of each family (two of them to check) and one with a group to check that
is switched off.
"""

from __future__ import annotations

from typing import Any

from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import CombinedText
from themask.model import Finding, Group, PlaceholderType
from themask.review import ReviewState

COMPANY = PlaceholderType.COMPANY
PERSON = PlaceholderType.PERSON
AMOUNT = PlaceholderType.AMOUNT
PERCENT = PlaceholderType.PERCENT
EMAIL = PlaceholderType.EMAIL
CUSTOM = PlaceholderType.CUSTOM


def custom_review(text: str, specs: list[dict[str, Any]]) -> tuple[CombinedText, ReviewState]:
    """A review of ``text`` with a group for each of ``specs``: its ``kind``, its ``canonical``
    form, the ``forms`` it has finds for (the canonical form if none), and whether it is to
    ``check``, ``enabled`` and from what ``source``. The finds are every place a form stands.
    """
    combined = CombinedText.join([("a.docx (after)", text)])
    groups: list[Group] = []
    numbers: dict[PlaceholderType, int] = {}
    for k, spec in enumerate(specs):
        kind: PlaceholderType = spec["kind"]
        forms: list[str] = spec.get("forms") or [spec["canonical"]]
        findings = []
        for form in forms:
            start = text.find(form)
            while start >= 0:
                findings.append(
                    Finding(kind, start, start + len(form), form, 1.0, spec.get("source", "model"))
                )
                start = text.find(form, start + len(form))
        findings.sort(key=lambda f: f.start)
        numbers[kind] = numbers.get(kind, 0) + 1
        groups.append(
            Group(
                f"g{k}",
                kind,
                spec["canonical"],
                set(forms),
                findings,
                f"[{kind.value}_{numbers[kind]}]",
                enabled=spec.get("enabled", True),
                needs_check=spec.get("check", False),
            )
        )
    groups.sort(key=lambda g: g.findings[0].start)
    state = ReviewState(combined.text, groups, [], UserLists([], []), CaseLists([], [], set()))
    return combined, state


CONTRACT = (
    "This Agreement is made between Northwind Trading B.V. and Acme Supplies Ltd, represented by"
    " Mr John Carter (Mr Carter) and Ms Fatma Yildiz. The price is EUR 1,250,000 and a late payment"
    " bears 8 % a year. Notices go to j.carter@acme.example. The project is called Project Falcon."
)
FAMILY_SPECS: list[dict[str, Any]] = [
    {"kind": COMPANY, "canonical": "Northwind Trading B.V."},
    {"kind": COMPANY, "canonical": "Acme Supplies Ltd"},
    {"kind": PERSON, "canonical": "Mr John Carter", "forms": ["Mr John Carter", "Mr Carter"]},
    {"kind": PERSON, "canonical": "Ms Fatma Yildiz", "check": True},
    {"kind": AMOUNT, "canonical": "EUR 1,250,000"},
    {"kind": PERCENT, "canonical": "8 %", "check": True, "source": "pattern"},
    {"kind": EMAIL, "canonical": "j.carter@acme.example"},
    {"kind": CUSTOM, "canonical": "Project Falcon"},
]

UNSURE_SPECS: list[dict[str, Any]] = [
    {"kind": COMPANY, "canonical": "Northwind Trading B.V."},
    {"kind": COMPANY, "canonical": "Acme Supplies Ltd", "check": True, "enabled": False},
    {"kind": CUSTOM, "canonical": "Project Falcon", "check": True},
]
