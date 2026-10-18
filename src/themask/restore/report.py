"""What a restore found and did: one item per placeholder, and the report shown at the end."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from themask.model import KeyEntry
from themask.placeholders import PlaceholderMatch

# What a restore may do with a placeholder: put an exact one back, put one the AI changed back
# only once the owner confirms it, and leave one the key does not hold as it is.
RestoreStatus = Literal["exact", "altered", "unknown"]


@dataclass
class RestoreItem:
    """A placeholder in the AI's text, the key entry it stands for, and what a restore may do.

    ``entry`` is None exactly when ``status`` is ``"unknown"``: the key does not hold the
    placeholder, whether the AI kept it exact or changed it.
    """

    match: PlaceholderMatch
    entry: KeyEntry | None
    status: RestoreStatus


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
