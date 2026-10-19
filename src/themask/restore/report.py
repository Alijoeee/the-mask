"""What a restore found and did: one item per placeholder, and the report shown at the end."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from themask.model import KeyEntry
from themask.placeholders import PlaceholderMatch

# What a restore may do with a placeholder: put an exact one back, put one the AI changed back
# only once the owner confirms it, and leave one the key does not hold as it is.
RestoreStatus = Literal["exact", "altered", "unknown"]

# The reason given for a placeholder that a tracked change of the AI runs through (ruling R90).
TRACKED_CHANGE = "changed inside a tracked change"


@dataclass
class RestoreItem:
    """A placeholder in the AI's text, the key entry it stands for, and what a restore may do.

    ``entry`` is the key's entry for the placeholder, None when the key does not hold it,
    whether the AI kept it exact or changed it; ``status`` is ``"unknown"`` then. ``part`` is the
    part of the Word file it is in ("" in a text) and ``ordinal`` its number in the plan of the
    whole text or file, the number by which the owner confirms a changed placeholder
    (``confirm_altered``); the match's offsets count in its paragraph's text. ``reason`` says why
    the restore needs the owner beyond a changed form: ``TRACKED_CHANGE`` for a placeholder that
    a tracked change of the AI runs through. Its match and entry are then those of its form with
    the changes accepted (or rejected, when only that reading has one), and its status is the
    weakest of its forms with and without the changes: one unknown form makes it unknown.
    """

    match: PlaceholderMatch
    entry: KeyEntry | None
    status: RestoreStatus
    part: str = ""
    ordinal: int = -1
    reason: str = ""


@dataclass
class RestoreReport:
    """What a restore did, for the report shown to the owner at the end.

    ``restored`` counts every placeholder replaced by its value, exact or changed;
    ``altered_restored`` counts those of them the AI had changed. ``needs_check`` holds the
    changed placeholders left as written because the owner did not confirm them, and ``unknown``
    the placeholders the key does not hold, each as written, once, in order of first appearance.
    ``banner_removed`` is set when The MASK's banner or its instruction for the AI was taken out.
    """

    restored: int
    altered_restored: int
    needs_check: list[RestoreItem]
    unknown: list[str]
    banner_removed: bool

    def summary(self) -> str:
        """The report's one line, worded as the spec words it."""
        return f"{self.restored} placeholders restored, {len(self.needs_check)} need your check."
