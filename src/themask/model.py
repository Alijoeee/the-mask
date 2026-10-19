"""Core data model for The MASK: placeholder types, findings, groups, plans, keys and cases."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Literal


class PlaceholderType(StrEnum):
    """The twelve placeholder types, spelled exactly as they appear inside ``[TYPE_N]``."""

    PERSON = "PERSON"
    COMPANY = "COMPANY"
    AMOUNT = "AMOUNT"
    PERCENT = "PERCENT"
    QUANTITY = "QUANTITY"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    IBAN = "IBAN"
    ID = "ID"
    URL = "URL"
    CUSTOM = "CUSTOM"


# What found a value: a pattern (e-mail, IBAN, ...), the language model, a contract rule, one of
# the owner's lists, the sweep for further copies of a value, or the owner's own selection.
FindingSource = Literal["pattern", "model", "rule", "list", "sweep", "user"]


@dataclass(frozen=True)
class Finding:
    """One confidential value found in the analysed text; ``text`` is the value itself."""

    type: PlaceholderType
    start: int
    end: int
    text: str
    score: float
    source: FindingSource


@dataclass
class Group:
    """The findings that stand for one real value, and the one placeholder they all get.

    ``canonical`` is the fullest form of the value and ``variants`` are all the forms seen.
    ``enabled`` switches the whole group on or off, ``disabled`` holds the indexes of single
    occurrences in ``findings`` that the owner switched off, and ``needs_check`` marks a group the
    owner should look at because the analysis was not sure of it.
    """

    id: str
    type: PlaceholderType
    canonical: str
    variants: set[str]
    findings: list[Finding]
    placeholder: str
    enabled: bool = True
    needs_check: bool = False
    disabled: set[int] = field(default_factory=set)

    def active_findings(self) -> list[Finding]:
        """The findings that will be replaced.

        None when the whole group is switched off, otherwise all but the occurrences switched off.
        """
        if not self.enabled:
            return []
        return [f for i, f in enumerate(self.findings) if i not in self.disabled]


@dataclass
class Analysis:
    """The result of analysing a text: the groups found, and warnings to show the owner."""

    text: str
    groups: list[Group]
    warnings: list[str]


@dataclass(frozen=True)
class Replacement:
    """Put ``placeholder`` in place of ``text[start:end]``."""

    start: int
    end: int
    placeholder: str


@dataclass
class MaskPlan:
    """The replacements to make, kept in text order; two of them may touch but never overlap.

    Each replacement must cover a real span of the text: it cannot start before the text or end
    before it starts. An empty span (``start == end``) is allowed.
    """

    replacements: list[Replacement]

    def __post_init__(self) -> None:
        for r in self.replacements:
            if r.start < 0 or r.end < r.start:
                raise ValueError(
                    f"Replacement {r.placeholder} has an invalid span {r.start}-{r.end}."
                )
        self.replacements = sorted(self.replacements, key=lambda r: (r.start, r.end))
        for before, after in pairwise(self.replacements):
            if before.end > after.start:
                raise ValueError(
                    f"Replacements overlap: {before.placeholder} at {before.start}-{before.end}"
                    f" and {after.placeholder} at {after.start}-{after.end}."
                )


@dataclass
class KeyEntry:
    """One line of a case's key: the real ``value`` behind a ``placeholder``, with its variants."""

    placeholder: str
    type: PlaceholderType
    value: str
    variants: list[str]


@dataclass
class MaskedFile:
    """A masked file written for a case, with the SHA-256 of its bytes."""

    name: str
    sha256: str


# The checks ``Case.from_json`` runs on each value read from JSON. Each raises TypeError for a value
# of the wrong kind, which ``from_json`` turns into its one "Not a stored case." error.


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected text.")
    return value


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("Expected a list.")
    return [_text(item) for item in value]


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError("Expected a list of objects.")
    return value


def _whole_number(value: object) -> int:
    # bool is a kind of int in Python, but a stored true or false is not a number of days.
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Expected a whole number.")
    return value


@dataclass
class Case:
    """One masking job: the files that went in, the masked files that came out, and the key.

    ``created_at`` must be timezone-aware; it is stored as UTC.
    """

    id: str
    created_at: datetime
    source_files: list[str]
    masked_files: list[MaskedFile]
    entries: list[KeyEntry]
    retention_days: int = 30

    @property
    def expires_at(self) -> datetime:
        """When the case is due to be deleted."""
        return self.created_at + timedelta(days=self.retention_days)

    def to_json(self) -> str:
        """The case as JSON text: UTC ISO-8601 timestamp, placeholder types by their name."""
        return json.dumps(
            {
                "id": self.id,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "source_files": self.source_files,
                "masked_files": [{"name": f.name, "sha256": f.sha256} for f in self.masked_files],
                "entries": [
                    {
                        "placeholder": e.placeholder,
                        "type": e.type.value,
                        "value": e.value,
                        "variants": e.variants,
                    }
                    for e in self.entries
                ],
                "retention_days": self.retention_days,
            }
        )

    @classmethod
    def from_json(cls, s: str) -> Case:
        """Read a case written by ``to_json``.

        Raises ValueError("Not a stored case.") for anything else: text that is not JSON, a field
        that is missing or of the wrong kind, an unknown placeholder type, a timestamp that is
        not a date or has no timezone (a case without one could not be compared with the clock),
        or a key that holds the same placeholder twice (ruling R108: the app never writes one,
        and a restore with it would take whichever entry came last).
        """
        try:
            data = json.loads(s)
            created_at = datetime.fromisoformat(_text(data["created_at"]))
            if created_at.utcoffset() is None:
                raise ValueError("The timestamp has no timezone.")
            placeholders = [_text(e["placeholder"]) for e in _objects(data["entries"])]
            if len(set(placeholders)) != len(placeholders):
                raise ValueError("A placeholder is in the key twice.")
            return cls(
                id=_text(data["id"]),
                created_at=created_at,
                source_files=_texts(data["source_files"]),
                masked_files=[
                    MaskedFile(_text(f["name"]), _text(f["sha256"]))
                    for f in _objects(data["masked_files"])
                ],
                entries=[
                    KeyEntry(
                        _text(e["placeholder"]),
                        PlaceholderType(_text(e["type"])),
                        _text(e["value"]),
                        _texts(e["variants"]),
                    )
                    for e in _objects(data["entries"])
                ],
                retention_days=_whole_number(data["retention_days"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Not a stored case.") from error
