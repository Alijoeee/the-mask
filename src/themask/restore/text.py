"""Restoring pasted text: the key's values put back into the text an AI tool gave in its chat."""

from __future__ import annotations

from themask.model import Case
from themask.restore.matcher import banner_spans, plan_restore, restore_span
from themask.restore.report import RestoreItem, RestoreReport


def restore_text(text: str, case: Case, confirm_altered: bool) -> tuple[str, RestoreReport]:
    """``text`` with the real values of ``case`` put back, and the report of what was done.

    An exact placeholder the key holds is always replaced by its value. One the AI changed is
    replaced only when ``confirm_altered`` is set; otherwise it stays as written and is listed in
    ``needs_check``. One the key does not hold stays as written and is listed in ``unknown``. A
    replacement covers the whole placeholder as written, brackets and markdown markers included,
    except a bracket on one side only, which is the surrounding text's (``restore_span``). The
    MASK's own lines (``banner_spans``) are taken out. Nothing else in the text changes.
    """
    banners = banner_spans(text)
    # (start, end, new text) for each stretch of the text to change; no two of them overlap.
    edits = [(start, end, "") for start, end in banners]
    restored = altered_restored = 0
    needs_check: list[RestoreItem] = []
    unknown: list[str] = []
    for item in plan_restore(text, case):
        if item.entry is None:
            unknown.append(item.match.raw)
        elif item.status == "exact" or confirm_altered:
            start, end = restore_span(item.match)
            edits.append((start, end, item.entry.value))
            restored += 1
            if item.status == "altered":
                altered_restored += 1
        else:
            needs_check.append(item)
    # From the end of the text to its start, so that each edit's offsets still hold.
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text, RestoreReport(
        restored=restored,
        altered_restored=altered_restored,
        needs_check=needs_check,
        unknown=list(dict.fromkeys(unknown)),  # each once, in order of first appearance
        banner_removed=bool(banners),
    )
