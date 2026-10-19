"""Restoring pasted text: the key's values put back into the text an AI tool gave in its chat.

``restore_text`` restores one text. ``TextRestorer`` does the work for it, and for the Word
restore, which restores a file paragraph by paragraph and keeps one report for all of them.
"""

from __future__ import annotations

from collections.abc import Sequence

from themask.model import Case
from themask.restore.matcher import banner_spans, plan_restore, restore_span
from themask.restore.report import RestoreReport


def restore_text(text: str, case: Case, confirm_altered: bool) -> tuple[str, RestoreReport]:
    """``text`` with the real values of ``case`` put back, and the report of what was done.

    An exact placeholder the key holds is always replaced by its value. One the AI changed is
    replaced only when ``confirm_altered`` is set; otherwise it stays as written and is listed in
    ``needs_check``. One the key does not hold stays as written and is listed in ``unknown``. A
    replacement covers the whole placeholder as written, brackets and markdown markers included,
    except a bracket on one side only, which is the surrounding text's (``restore_span``). The
    MASK's own lines (``banner_spans``) are taken out. Nothing else in the text changes.
    """
    restorer = TextRestorer(case, confirm_altered)
    # From the end of the text to its start, so that each edit's offsets still hold.
    for start, end, new in reversed(restorer.edits(text)):
        text = text[:start] + new + text[end:]
    return text, restorer.report


class TextRestorer:
    """Restores texts for ``case``, one after another, and keeps the report of them all."""

    def __init__(self, case: Case, confirm_altered: bool) -> None:
        self.case = case
        self.confirm_altered = confirm_altered
        self.report = RestoreReport(0, 0, [], [], banner_removed=False)

    def edits(self, text: str, keep: Sequence[tuple[int, int]] = ()) -> list[tuple[int, int, str]]:
        """The changes that restore ``text``, as ``(start, end, new text)``, in text order.

        Each of The MASK's own lines is cut out, and each placeholder dealt with as
        ``restore_text`` says, the report counting it; no two changes overlap. A placeholder
        that overlaps a stretch of ``keep`` is left as it is and not reported.
        """
        banners = banner_spans(text)
        self.report.banner_removed = self.report.banner_removed or bool(banners)
        edits = [(start, end, "") for start, end in banners]
        for item in plan_restore(text, self.case):
            match = item.match
            if any(match.start < end and start < match.end for start, end in keep):
                continue
            if item.entry is None:
                if match.raw not in self.report.unknown:  # each once, as it first appears
                    self.report.unknown.append(match.raw)
            elif item.status == "exact" or self.confirm_altered:
                start, end = restore_span(match)
                edits.append((start, end, item.entry.value))
                self.report.restored += 1
                if item.status == "altered":
                    self.report.altered_restored += 1
            else:
                self.report.needs_check.append(item)
        return sorted(edits)
