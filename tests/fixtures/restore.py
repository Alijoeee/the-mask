"""The case of the restore tests: the brief's person, company and amount.

``CASE`` is the brief's key: [PERSON_1] John Smith, [COMPANY_1] Acme Supplies Ltd and [AMOUNT_1]
EUR 1,250,000, made at ``NOW``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from themask.model import Case, KeyEntry, PlaceholderType

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)

CASE = Case(
    "K4F7",
    NOW,
    ["c.docx"],
    [],
    [
        KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"]),
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme"]),
        KeyEntry("[AMOUNT_1]", PlaceholderType.AMOUNT, "EUR 1,250,000", []),
    ],
)
