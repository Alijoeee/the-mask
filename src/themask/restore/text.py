"""Restoring pasted text: the key's values put back into the text an AI tool gave in its chat.

``restore_text`` restores one text. ``TextRestorer`` does the work for it, and for the Word
restore, which restores a file paragraph by paragraph, numbers every placeholder of the file in
one plan and keeps one report for all of them.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import replace

from themask.model import Case
from themask.restore.matcher import banner_spans, plan_restore, restore_span
from themask.restore.report import RestoreItem, RestoreReport

# Which of the placeholders the AI changed the owner confirmed: all (True), none (False), or
# those whose ordinals are given (ruling R91).
Confirmation = bool | Collection[int]


def restore_text(text: str, case: Case, confirm_altered: Confirmation) -> tuple[str, RestoreReport]:
    """``text`` with the real values of ``case`` put back, and the report of what was done.

    An exact placeholder the key holds is always replaced by its value. One the AI changed is
    replaced only when ``confirm_altered`` confirms it: True confirms every one, False none, and
    a collection of ordinals (those of ``plan_restore``) exactly those; otherwise it stays as
    written and is listed in ``needs_check``. One the key does not hold stays as written and is
    listed in ``unknown``. A replacement covers the whole placeholder as written, brackets and
    markdown markers included, except a bracket on one side only, which is the surrounding
    text's (``restore_span``). The MASK's own lines (``banner_spans``) are taken out. Nothing
    else in the text changes.
    """
    restorer = TextRestorer(case, confirm_altered)
    # From the end of the text to its start, so that each edit's offsets still hold.
    for start, end, new in reversed(restorer.edits(text)):
        text = text[:start] + new + text[end:]
    return text, restorer.report


class TextRestorer:
    """Restores texts for ``case``, one after another, numbering every placeholder it plans.

    ``plan`` holds the items in the order they were planned, each ``ordinal`` its place there;
    ``report`` counts what was done with them.
    """

    def __init__(self, case: Case, confirm_altered: Confirmation) -> None:
        self.case = case
        self.confirm_altered = confirm_altered
        self.plan: list[RestoreItem] = []
        self.report = RestoreReport(0, 0, [], [], banner_removed=False)

    def edits(
        self, text: str, keep: Sequence[tuple[int, int]] = (), part: str = ""
    ) -> list[tuple[int, int, str]]:
        """The changes that restore ``text``, as ``(start, end, new text)``, in text order.

        Each of The MASK's own lines is cut out, and each placeholder is numbered as in ``part``
        and dealt with as ``restore_text`` says, the report counting it; no two changes overlap.
        A placeholder or one of The MASK's own lines that overlaps a stretch of ``keep`` is left
        as it is, not numbered and not reported.
        """
        edits = self.banner_cuts(text, keep)
        for planned in plan_restore(text, self.case):
            if _overlaps(planned.match.start, planned.match.end, keep):
                continue
            item = self.number(planned, part)
            if self.restores(item) and item.entry is not None:
                start, end = restore_span(item.match)
                edits.append((start, end, item.entry.value))
        return sorted(edits)

    def banner_cuts(
        self, text: str, keep: Sequence[tuple[int, int]] = (), note: bool = True
    ) -> list[tuple[int, int, str]]:
        """Cuts that take The MASK's own lines out of ``text``, but none that overlaps ``keep``.

        With ``note`` the report records that a line was taken out; without it the caller does,
        once it knows the cuts are made.
        """
        banners = [span for span in banner_spans(text) if not _overlaps(*span, keep)]
        if banners and note:
            self.report.banner_removed = True
        return [(start, end, "") for start, end in banners]

    def number(self, item: RestoreItem, part: str) -> RestoreItem:
        """``item`` as the next one of the plan: in ``part``, with the plan's next ordinal."""
        numbered = replace(item, part=part, ordinal=len(self.plan))
        self.plan.append(numbered)
        return numbered

    def restores(self, item: RestoreItem) -> bool:
        """Whether ``item`` is put back; the report counts it either way.

        An item the key holds, exact or with its change confirmed, is put back and counted as
        restored. A changed one not confirmed is listed in ``needs_check``, as is any item with
        a reason that cannot be put back; one the key does not hold otherwise goes to
        ``unknown``, as written, once.
        """
        if item.status == "unknown" or item.entry is None:
            if item.reason:
                self.report.needs_check.append(item)
            elif item.match.raw not in self.report.unknown:
                self.report.unknown.append(item.match.raw)
            return False
        if item.status == "altered" and not self.confirmed(item):
            self.report.needs_check.append(item)
            return False
        self.report.restored += 1
        if item.status == "altered":
            self.report.altered_restored += 1
        return True

    def hold(self, item: RestoreItem) -> None:
        """Lists ``item`` in ``needs_check``: it is not put back, whatever its status."""
        self.report.needs_check.append(item)

    def confirmed(self, item: RestoreItem) -> bool:
        """Whether the owner confirmed ``item``'s change, by ``confirm_altered``."""
        if isinstance(self.confirm_altered, bool):
            return self.confirm_altered
        return item.ordinal in self.confirm_altered


def _overlaps(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)
