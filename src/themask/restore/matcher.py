"""Which placeholders in an AI tool's text a case's key can fill, and which case fits a text best.

``plan_restore`` gives each placeholder in a text its status: an exact ``[TYPE_N]`` the key holds
is put back, a form of it the AI changed waits for the owner's confirmation, and one the key does
not hold is left as written. The MASK's banner and its instruction for the AI hold placeholders as
examples; a line that is one of them is not planned, because a restore takes the line out.
"""

from __future__ import annotations

from themask.instruction import AI_INSTRUCTION, BANNER_TEXT
from themask.model import Case
from themask.placeholders import PlaceholderMatch, find_placeholders
from themask.restore.report import RestoreItem

# The MASK's own lines, with each run of whitespace written as one space (see banner_spans).
_OWN_LINES = frozenset(" ".join(line.split()) for line in (BANNER_TEXT, AI_INSTRUCTION))


def banner_spans(text: str) -> list[tuple[int, int]]:
    """Where The MASK's own lines stand in ``text``, as ``(start, end)`` spans in text order.

    A line counts when, with each run of whitespace written as one space and none at its ends, it
    reads exactly ``BANNER_TEXT`` or ``AI_INSTRUCTION``: an AI tool may copy the banner from the
    masked file, or the instruction the owner pasted with the question. A span covers the line
    with its line break, and one blank line after it if there is one.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    after_own_line = False
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        if " ".join(line.split()) in _OWN_LINES:
            spans.append((start, end))
            after_own_line = True
        else:
            if after_own_line and not line.strip():
                spans[-1] = (spans[-1][0], end)
            after_own_line = False
        start = end
    return spans


def _placeholders(text: str) -> list[PlaceholderMatch]:
    """The placeholders in ``text``, in text order, but none on The MASK's own lines."""
    spans = banner_spans(text)
    # A placeholder never runs over a line break, so one that overlaps a span lies inside it.
    return [
        match
        for match in find_placeholders(text)
        if not any(match.start < end and start < match.end for start, end in spans)
    ]


def plan_restore(text: str, case: Case) -> list[RestoreItem]:
    """One item for each placeholder in ``text``, in text order, with what a restore may do.

    A placeholder the case's key holds is ``"exact"`` when the AI kept it exactly as written and
    ``"altered"`` when the AI changed it (brackets dropped or escaped, spaces, lower case, markdown
    markers); one the key does not hold is ``"unknown"``, without an entry, whatever its form.
    Placeholders on The MASK's own lines (``banner_spans``) get no item.
    """
    key = {entry.placeholder: entry for entry in case.entries}
    plan: list[RestoreItem] = []
    for match in _placeholders(text):
        entry = key.get(match.placeholder)
        if entry is None:
            plan.append(RestoreItem(match, None, "unknown"))
        else:
            plan.append(RestoreItem(match, entry, "exact" if match.exact else "altered"))
    return plan


def suggest_cases(text: str, cases: list[Case]) -> list[Case]:
    """All of ``cases``, the one that fits ``text`` best first.

    A case fits better the more of the text's placeholders its key holds, exact or changed, each
    counted once however often it stands in the text; of two that hold as many, the newer comes
    first. Cases that hold none still come back, last and newest first, so that the most recent
    case can be preselected when no case fits. The MASK's own lines do not count.
    """
    found = {match.placeholder for match in _placeholders(text)}

    def held(case: Case) -> int:
        return len(found & {entry.placeholder for entry in case.entries})

    return sorted(cases, key=lambda case: (held(case), case.created_at), reverse=True)
