"""Restoring a Word file: the real values put back into the .docx an AI tool gives back.

``restore_docx`` reads the AI's file into memory and writes the restored copy as a new file,
"<name> – restored.docx", next to it or in the folder asked for, and never over a file that is
there; the AI's file itself is never written to. Every paragraph of the text parts (the document,
its headers, footers, footnotes and endnotes) and of the comments is restored the way
``restore_text`` restores a text: exact placeholders are always put back, changed ones only once
the owner confirms them, unknown ones are left as written. One plan numbers every placeholder of
the file, and ``plan_docx`` gives that plan without changing anything, so that the owner can
confirm changed placeholders one by one by their ordinals (ruling R91); one report counts them all.
The plan also holds the file's fingerprint, and a restore given it refuses a file that has changed
since (ruling R96). The value goes in through ``replace_in_paragraph``, so it takes the formatting
of the placeholder's first run, also where Word split the placeholder across runs, and a tab or
line break in a value becomes a ``w:tab`` or ``w:br`` as Word writes them. A text box's fallback
copy, which Word keeps for old readers, is restored the same way but not counted again; its changed
placeholders are put back only when the owner confirmed every changed placeholder of the file, by
True or by a set of all their ordinals.

The AI's tracked changes are restored too, so that neither accepting nor rejecting one brings a
placeholder back or a wrong value in (rulings R88, R90). A paragraph with tracked changes is read
with every change accepted and with every change rejected. A placeholder in text both readings
share, or wholly in one insertion or one deletion, is put back where it stands; one is planned
once however many readings show it. A placeholder that a change runs through, a digit, a word or
a bracket of it inserted or deleted, becomes one change of whole values: a new deletion holding
the value the paragraph reads with the changes rejected and a new insertion holding the one it
reads with them accepted, in the placeholder's first run's formatting and with the author and
date of the AI's change. Where a reading's form of it is unknown, or changed and not confirmed,
it is left as it is and listed to check, with ``TRACKED_CHANGE`` as the reason. So is a place
where several placeholders meet: one reading's placeholders joined in the other's, or any
placeholder with a character inside the stretch a changed placeholder spans, which its change
of values would take (ruling R96); and so is a changed placeholder in a paragraph whose line
of The MASK's would have to be cut, which then stays.

The MASK's banner and its instruction for the AI are taken out (``banner_spans``). A paragraph
of the body that holds nothing but one of them is deleted, with an empty paragraph right after
it; elsewhere (a table cell, a header, a note, a comment) the paragraph stays, emptied, since
the place must keep a paragraph, and so does a paragraph that holds anything besides the line.
A paragraph that ends a section is never deleted, as its section would go with it.

Not restored: placeholders in field instructions, link addresses and bookmark names. The AI
reads and writes the text, not those, and changing them could break the field or the link.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path

from lxml import etree

from themask.docx.cleaner import comment_parts
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import TextNode, View, paragraph_nodes
from themask.docx.restorer import replace_in_paragraph
from themask.errors import MaskError
from themask.labels import find_brackets
from themask.model import Case
from themask.placeholders import PlaceholderMatch
from themask.restore.matcher import banner_spans, plan_restore, restore_span
from themask.restore.report import (
    TRACKED_CHANGE,
    RestoreItem,
    RestorePlan,
    RestoreReport,
    RestoreStatus,
)
from themask.restore.text import Confirmation, TextRestorer

_W = f"{{{NS['w']}}}"
_BODY = f"{_W}body"
_P = f"{_W}p"
_PPR = f"{_W}pPr"
_R = f"{_W}r"
_RPR = f"{_W}rPr"
_T = f"{_W}t"
_DEL_TEXT = f"{_W}delText"
_SECT_PR = f"{_W}sectPr"
_INS = f"{_W}ins"
_DEL = f"{_W}del"
# The tracked changes of text: inserted, deleted, moved here and moved away.
_REVISIONS = (_INS, _DEL, f"{_W}moveTo", f"{_W}moveFrom")
_ID = f"{_W}id"
_FALLBACK = f"{{{NS['mc']}}}Fallback"
_XML_SPACE = f"{{{NS['xml']}}}space"
# How Word writes a tab and a line break in a run.
_MARKS = {"\t": f"{_W}tab", "\n": f"{_W}br"}
_MARK = re.compile("([\t\n])")

Edits = list[tuple[int, int, str]]

# What a restore says when the file is not the one its plan was made from (ruling R96).
FILE_CHANGED_MESSAGE = "The file changed since it was checked. Load it again."


def plan_docx(src: Path, case: Case) -> RestorePlan:
    """Every placeholder of the AI's Word file ``src`` that ``restore_docx`` deals with.

    The items come in the order the restore numbers them, each with its part and its
    ``ordinal``, the number by which ``restore_docx`` takes the owner's confirmation; nothing is
    restored or written. The plan also holds the fingerprint of the file, to give the restore
    (``expected_sha256``). Raises what ``DocxPackage.open`` raises.
    """
    sha256 = _fingerprint(src)
    restorer = TextRestorer(case, confirm_altered=False)
    _restore_package(DocxPackage.open(src), restorer, apply=False, every_change_confirmed=False)
    return RestorePlan(restorer.plan, sha256)


def restore_docx(
    src: Path,
    case: Case,
    confirm_altered: Confirmation,
    out_dir: Path | None = None,
    expected_sha256: str | None = None,
) -> tuple[Path, RestoreReport]:
    """Restores the AI's Word file ``src`` with the key of ``case``; returns the new file and
    the report of what was done.

    ``confirm_altered`` says which changed placeholders the owner confirmed: all (True), none
    (False), or those whose ordinals (``plan_docx``) it holds. The new file goes into
    ``out_dir``, made when it is missing, or else next to ``src``: "<stem> – restored.docx",
    or "<stem> – restored (2).docx", "(3)" ... when that name is taken. Given the fingerprint
    ``plan_docx`` returned (``expected_sha256``), a restore of a file that changed since raises
    MaskError (``FILE_CHANGED_MESSAGE``) before anything is written (ruling R96). Raises what
    ``DocxPackage.open`` raises for a file that is not a Word file or is protected.
    """
    if expected_sha256 is not None and _fingerprint(src) != expected_sha256:
        raise MaskError(FILE_CHANGED_MESSAGE)
    pkg = DocxPackage.open(src)
    restorer = TextRestorer(case, confirm_altered)
    every = _confirms_every_change(pkg, case, confirm_altered)
    _restore_package(pkg, restorer, apply=True, every_change_confirmed=every)
    target = _new_file(
        src.parent if out_dir is None else out_dir, f"{src.stem} \N{EN DASH} restored"
    )
    try:
        pkg.save(target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target, restorer.report


def _restore_package(
    pkg: DocxPackage, restorer: TextRestorer, apply: bool, every_change_confirmed: bool
) -> None:
    """Plans every paragraph the restore covers, in order, and with ``apply`` restores it.

    Each paragraph is planned as it was read, before it changes, and no paragraph changes
    another's text, so planning alone numbers the placeholders as the restore does.
    """
    # Fallback copies are counted apart, their report unused. Confirmations by number name the
    # visible copy's placeholders, so a copy's changed ones are put back only when every changed
    # placeholder of the file is confirmed (ruling R96).
    copies = TextRestorer(restorer.case, every_change_confirmed)
    texts = pkg.TEXT_PARTS
    # The comments' parts, found the way the cleaner finds them; only word/comments.xml holds
    # text, the others (extensions, ids, people) no paragraph.
    parts = texts + [name for name in comment_parts(pkg, texts[0]) if name not in texts]
    for part in parts:
        doomed: dict[etree._Element, None] = {}
        for p in list(pkg.xml(part).iter(_P)):
            in_copy = next(p.iterancestors(_FALLBACK), None) is not None
            found = _restore_paragraph(p, part, copies if in_copy else restorer, apply)
            doomed.update(dict.fromkeys(found))
        for p in doomed:
            p.getparent().remove(p)


def _restore_paragraph(
    p: etree._Element, part: str, restorer: TextRestorer, apply: bool
) -> list[etree._Element]:
    """Plans paragraph ``p``, and with ``apply`` restores it; returns the paragraphs to delete
    once the part is done.

    That is ``p`` when it stands in the body and held one of The MASK's own lines and nothing
    else, with the paragraph after it when that one is empty.
    """
    text, nodes = paragraph_nodes(p, "accepted")
    if next(p.iter(*_REVISIONS), None) is not None:
        _restore_tracked(p, part, restorer, apply)
    else:
        # A placeholder in a field instruction stays (see the module's docstring).
        instructions = [(node.start, node.end) for node in nodes if node.kind == "instr"]
        edits = restorer.edits(text, keep=instructions, part=part)
        if apply and edits:
            replace_in_paragraph(p, "accepted", edits, breaks=True)
    if not apply:
        return []
    own_line = bool(text) and banner_spans(text) == [(0, len(text))]
    if not (own_line and p.getparent().tag == _BODY and _is_empty(p)):
        return []
    after = p.getnext()
    return [p, after] if after is not None and _is_empty(after) else [p]


# ---- tracked changes ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    """A placeholder as one reading of a paragraph shows it.

    ``pieces`` are the stretches of the text nodes it covers, as ``(node, start, end)`` within
    each node's text, in document order; ``changes`` the tracked change each piece lies in (None
    for text both readings share).
    """

    view: View
    item: RestoreItem
    pieces: tuple[tuple[etree._Element, int, int], ...]
    changes: tuple[etree._Element | None, ...]
    # A bracketed text that is no placeholder (ruling R127): it matters only where a tracked change
    # puts it at the place of a name in the other reading, which then waits for the owner.
    generic: bool = False

    def touches(self, other: _Token) -> bool:
        """Whether the two tokens cover a character of the same node."""
        return any(
            node is other_node and start < other_end and other_start < end
            for node, start, end in self.pieces
            for other_node, other_start, other_end in other.pieces
        )


class _Reading:
    """Paragraph ``p`` as ``view`` reads it: its text, its nodes, and its placeholders."""

    def __init__(self, p: etree._Element, view: View) -> None:
        self.p = p
        self.view = view
        self.text, self.nodes = paragraph_nodes(p, view)

    def tokens(self, restorer: TextRestorer) -> list[_Token]:
        """The placeholders of this reading, but those in a field instruction."""
        instructions = _spans([node for node in self.nodes if node.kind == "instr"])
        items = plan_restore(self.text, restorer.case)
        if restorer.case.label_index():
            spans = banner_spans(self.text)
            taken = [(i.match.start, i.match.end) for i in items]
            items += [
                RestoreItem(PlaceholderMatch(start, end, raw, raw, False), None, "unknown")
                for start, end, raw in find_brackets(self.text)
                if not any(start < e and s < end for s, e in [*taken, *spans])
            ]
        tokens = []
        for item in items:
            match = item.match
            if any(match.start < end and start < match.end for start, end in instructions):
                continue
            # The nodes that hold a character of it (an empty node holds none).
            covered = [
                n
                for n in self.nodes
                if n.start < n.end and n.start < match.end and match.start < n.end
            ]
            pieces = tuple(
                (n.elem, max(match.start, n.start) - n.start, min(match.end, n.end) - n.start)
                for n in covered
            )
            changes = tuple(_change_of(n.elem, self.p) for n in covered)
            tokens.append(_Token(self.view, item, pieces, changes, item.ordinal == -1))
        return tokens


def _restore_tracked(p: etree._Element, part: str, restorer: TextRestorer, apply: bool) -> None:
    """Plans and restores a paragraph with tracked changes (see the module's docstring)."""
    accepted, rejected = _Reading(p, "accepted"), _Reading(p, "rejected")
    shared = {node.elem for node in accepted.nodes} & {node.elem for node in rejected.nodes}
    instructions = [n for n in accepted.nodes if n.kind == "instr"]
    edits: dict[View, Edits] = {
        "accepted": restorer.banner_cuts(accepted.text, keep=_spans(instructions), note=False),
        # In the rejected reading only what it alone holds may change.
        "rejected": _taken_out_cuts(rejected, shared, restorer),
    }
    places = _places(accepted.tokens(restorer) + rejected.tokens(restorer), p)
    # A bracketed text that no name stands against in the other reading is ordinary text.
    places = [place for place in places if not all(t.generic for t in place.tokens)]
    if restorer.case.label_index():
        for place in places:
            if place.plain is not None and _beside_other_bracket(place.plain):
                place.held = True
    if any(edits.values()) and any(place.plain is None for place in places):
        # Cutting The MASK's line could take the nodes of a placeholder a change runs through:
        # the line stays, and every such placeholder is left to the owner (ruling R96).
        edits = {"accepted": [], "rejected": []}
        for place in places:
            place.held = place.held or place.plain is None
    if any(edits.values()):
        restorer.report.banner_removed = True
    straddles: list[_Straddle] = []
    for place in places:
        if place.held:
            restorer.hold(restorer.number(place.item(), part))
        elif place.plain is not None:
            item = restorer.number(place.plain.item, part)
            if restorer.restores(item) and item.entry is not None:
                start, end = restore_span(item.match)
                edits[place.plain.view].append((start, end, item.entry.value))
        elif restorer.restores(restorer.number(place.item(), part)):
            straddles.append(_Straddle.of(place.token_a, place.token_r, accepted, rejected, p))
    if not apply:
        return
    _isolate(straddles)
    # The rejected reading's changes touch only what it alone holds, so the accepted reading's
    # positions still hold after them.
    for view in ("rejected", "accepted"):
        if edits[view]:
            replace_in_paragraph(p, view, sorted(edits[view]), breaks=True)
    for straddle in straddles:
        straddle.rewrite(p)


_BRACKETS = (
    "[]\N{FULLWIDTH LEFT SQUARE BRACKET}\N{FULLWIDTH RIGHT SQUARE BRACKET}\u3010\u3011\u3014\u3015"
)


def _beside_other_bracket(token: _Token) -> bool:
    """Whether ``token`` lies in an insertion whose neighbour is a deletion with a bracket in it,
    or the other way round: one name swapped for another text in brackets (ruling R127). The
    two readings then show different tokens at one place, which only the owner can settle.
    """
    changes = [change for change in token.changes if change is not None]
    if not changes:
        return False
    other = {"ins": "del", "del": "ins"}.get(etree.QName(changes[0]).localname)
    return other is not None and any(
        sibling is not None
        and etree.QName(sibling).localname == other
        and any(char in _BRACKETS for char in "".join(sibling.itertext()))
        for sibling in (changes[0].getprevious(), changes[0].getnext())
    )


def _taken_out_cuts(
    rejected: _Reading, shared: set[etree._Element], restorer: TextRestorer
) -> Edits:
    """Cuts for The MASK's own lines as the rejected reading alone holds them.

    A line that overlaps text both readings share stays whole; of the others only the text
    nodes are cut, so that no tab or break both readings share goes with them.
    """
    keep = _spans([n for n in rejected.nodes if n.elem in shared or n.kind == "instr"])
    cuts = []
    for start, end, _ in restorer.banner_cuts(rejected.text, keep=keep, note=False):
        for node in rejected.nodes:
            if node.elem not in shared and node.start < end and start < node.end:
                cuts.append((max(start, node.start), min(end, node.end), ""))
    return cuts


def _spans(nodes: list[TextNode]) -> list[tuple[int, int]]:
    return [(node.start, node.end) for node in nodes]


def _change_of(node: etree._Element, p: etree._Element) -> etree._Element | None:
    """The tracked change of paragraph ``p`` that ``node`` lies in, if any."""
    for ancestor in node.iterancestors():
        if ancestor is p:
            return None
        if ancestor.tag in _REVISIONS:
            return ancestor
    return None


# Where a character of a paragraph lies: the place of its node in the paragraph, and its offset.
_Point = tuple[int, int]


@dataclass
class _Place:
    """The placeholders of a paragraph's two readings that stand at one place.

    ``span`` is where the place lies, from its first character to past its last. ``plain`` is
    the token to put back where it stands, when the place needs no change of whole values;
    otherwise ``token_a`` and ``token_r`` are the forms of the placeholder that a change runs
    through, as each reading shows it. ``held`` places are left to the owner: several
    placeholders meet in them.
    """

    tokens: list[_Token]
    span: tuple[_Point, _Point]
    held: bool
    plain: _Token | None = None
    token_a: _Token | None = None
    token_r: _Token | None = None

    @classmethod
    def of(cls, tokens: list[_Token], order: dict[etree._Element, int]) -> _Place:
        tokens = sorted(tokens, key=lambda t: (t.view, order[t.pieces[0][0]], t.pieces[0][1]))
        points = [(order[n], o) for t in tokens for n, s, e in t.pieces for o in (s, e)]
        span = (min(points), max(points))
        in_accepted = [t for t in tokens if t.view == "accepted"]
        in_rejected = [t for t in tokens if t.view == "rejected"]
        if len(in_accepted) > 1 or len(in_rejected) > 1:
            return cls(tokens, span, held=True)
        token_a = in_accepted[0] if in_accepted else None
        token_r = in_rejected[0] if in_rejected else None
        return cls(tokens, span, False, _plain(token_a, token_r), token_a, token_r)

    @classmethod
    def held_at(cls, tokens: list[_Token], order: dict[etree._Element, int]) -> _Place:
        """The place of ``tokens`` held, however many of them each reading has."""
        place = cls.of(tokens, order)
        return cls(place.tokens, place.span, held=True)

    def covers(self, other: _Place, order: dict[etree._Element, int]) -> bool:
        """Whether a character of ``other`` lies within this place's span."""
        start, end = self.span
        return any(
            start < (order[node], piece_end) and (order[node], piece_start) < end
            for token in other.tokens
            for node, piece_start, piece_end in token.pieces
        )

    def item(self) -> RestoreItem:
        """The plan's one item for a place that is not plain.

        Its match is that of the place's first form with the changes accepted (or rejected,
        when only that reading has one); its status is the weakest of all the place's forms:
        unknown, then changed, then exact.
        """
        statuses = {t.item.status for t in self.tokens}
        status: RestoreStatus = next(s for s in ("unknown", "altered", "exact") if s in statuses)
        return replace(self.tokens[0].item, status=status, reason=TRACKED_CHANGE)


def _places(tokens: list[_Token], p: etree._Element) -> list[_Place]:
    """The tokens grouped by the place they stand at, in document order.

    A token of one reading and one of the other stand at one place when they cover a character
    of the same node; tokens of one reading never overlap one another. A place that is not
    plain is rewritten over every text node from its first character to its last, so any other
    place with a character there joins it, and the joined place is held (ruling R96).
    """
    order = {element: index for index, element in enumerate(p.iter())}
    groups: list[list[_Token]] = []
    for token in tokens:
        joined = [group for group in groups if any(token.touches(other) for other in group)]
        merged = [token] + [other for group in joined for other in group]
        groups = [group for group in groups if all(group is not j for j in joined)] + [merged]
    places = [_Place.of(group, order) for group in groups]
    while True:
        for place in places:
            if place.plain is None:
                inside = [o for o in places if o is not place and place.covers(o, order)]
                if inside:
                    break
        else:
            return sorted(places, key=lambda place: place.span[0])
        there = place.tokens + [token for other in inside for token in other.tokens]
        places = [q for q in places if q is not place and all(q is not o for o in inside)]
        places.append(_Place.held_at(there, order))


def _plain(token_a: _Token | None, token_r: _Token | None) -> _Token | None:
    """The token to put back where it stands, if the place needs no whole-token change.

    That is a token of shared text that both readings show alike, or a token wholly in one
    insertion (shown only when the changes are accepted) or one deletion (only when rejected).
    """
    if token_a is not None and token_r is not None:
        alike = token_a.pieces == token_r.pieces and set(token_a.changes) == {None}
        return token_a if alike else None
    token = token_a if token_a is not None else token_r
    if token is None or len(set(token.changes)) != 1 or token.changes[0] is None:
        return None
    return token


@dataclass
class _Straddle:
    """A placeholder a tracked change runs through, and the change of whole values it becomes.

    ``nodes`` are the text nodes of its place in document order, the first and the last split
    off (``_isolate``) at ``start`` and ``end``; ``rejected`` and ``accepted`` are the place's
    text as each reading shows it, the placeholder's value put in.
    """

    nodes: list[etree._Element]
    start: int
    end: int
    rejected: str
    accepted: str
    properties: etree._Element | None
    signature: dict[str, str]

    @classmethod
    def of(
        cls,
        token_a: _Token | None,
        token_r: _Token | None,
        accepted: _Reading,
        rejected: _Reading,
        p: etree._Element,
    ) -> _Straddle:
        order = {element: index for index, element in enumerate(p.iter())}
        pieces = [piece for t in (token_a, token_r) if t is not None for piece in t.pieces]
        first = min(pieces, key=lambda piece: (order[piece[0]], piece[1]))
        last = max(pieces, key=lambda piece: (order[piece[0]], piece[2]))
        lo, hi = order[first[0]], order[last[0]]
        between = [
            n.elem
            for n in accepted.nodes + rejected.nodes
            if n.kind == "t" and lo <= order[n.elem] <= hi
        ]
        nodes = sorted(dict.fromkeys(between), key=order.__getitem__)
        change = next(
            (c for node in nodes if (c := _change_of(node, p)) is not None),
            next(p.iter(*_REVISIONS)),
        )
        return cls(
            nodes=nodes,
            start=first[1],
            end=last[2],
            rejected=_shown(rejected, token_r, first, last, order),
            accepted=_shown(accepted, token_a, first, last, order),
            properties=first[0].getparent().find(_RPR),
            signature={k: v for k, v in change.attrib.items() if k != _ID},
        )

    def rewrite(self, p: etree._Element) -> None:
        """Puts the change of whole values in place of the place's nodes."""
        anchor = _anchor(self.nodes[0], p)
        if self.rejected == self.accepted:
            new = [self._run(self.accepted, _T)]
        else:
            last = _last_id(p)
            ids = iter((last + 1, last + 2))
            new = [
                self._change(tag, self._run(text, text_tag), next(ids))
                for tag, text, text_tag in (
                    (_DEL, self.rejected, _DEL_TEXT),
                    (_INS, self.accepted, _T),
                )
                if text
            ]
        for element in reversed(new):
            anchor.addnext(element)
        for node in self.nodes:
            _prune(node, p)

    def _run(self, text: str, text_tag: str) -> etree._Element:
        run = etree.Element(_R)
        if self.properties is not None:
            run.append(copy.deepcopy(self.properties))
        pieces = _MARK.split(text)
        for index, piece in enumerate(pieces):
            if index % 2:
                etree.SubElement(run, _MARKS[piece])
            elif piece:
                node = etree.SubElement(run, text_tag)
                node.text = piece
                node.set(_XML_SPACE, "preserve")
        return run

    def _change(self, tag: str, run: etree._Element, number: int) -> etree._Element:
        change = etree.Element(tag, {_ID: str(number), **self.signature})
        change.append(run)
        return change


def _shown(
    reading: _Reading,
    token: _Token | None,
    first: tuple[etree._Element, int, int],
    last: tuple[etree._Element, int, int],
    order: dict[etree._Element, int],
) -> str:
    """The text ``reading`` shows between ``first`` and ``last``, ``token`` given its value."""
    lo, hi = order[first[0]], order[last[0]]
    inside = [n for n in reading.nodes if lo <= order[n.elem] <= hi and n.kind == "t"]
    if not inside:
        return ""
    begin = inside[0].start + (first[1] if inside[0].elem is first[0] else 0)
    finish = inside[-1].start + (
        last[2] if inside[-1].elem is last[0] else inside[-1].end - inside[-1].start
    )
    text = reading.text[begin:finish]
    if token is None or token.item.entry is None:
        return text
    match = token.item.match
    return text[: match.start - begin] + token.item.entry.value + text[match.end - begin :]


def _isolate(straddles: list[_Straddle]) -> None:
    """Splits the first and the last node of each place so that its nodes hold it alone.

    A node splits into nodes of its kind, in its run, that read as it read: no reading's text
    and no position in it changes.
    """
    cuts: dict[etree._Element, set[int]] = {}
    for straddle in straddles:
        cuts.setdefault(straddle.nodes[0], set()).add(straddle.start)
        cuts.setdefault(straddle.nodes[-1], set()).add(straddle.end)
    pieces: dict[tuple[etree._Element, int], etree._Element] = {}
    ends: dict[tuple[etree._Element, int], etree._Element] = {}
    for node, offsets in cuts.items():
        text = node.text or ""
        bounds = [0, *sorted(o for o in offsets if 0 < o < len(text)), len(text)]
        made = node
        node.text = text[bounds[0] : bounds[1]]
        pieces[(node, 0)] = node
        ends[(node, bounds[1])] = node
        for begin, finish in pairwise(bounds[1:]):
            twin = etree.Element(node.tag)
            twin.text = text[begin:finish]
            twin.set(_XML_SPACE, "preserve")
            made.addnext(twin)
            made = twin
            pieces[(node, begin)] = twin
            ends[(node, finish)] = twin
        node.set(_XML_SPACE, "preserve")
    for straddle in straddles:
        first, last = straddle.nodes[0], straddle.nodes[-1]
        straddle.nodes[0] = pieces.get((first, straddle.start), first)
        straddle.nodes[-1] = ends.get((last, straddle.end), last)


def _anchor(node: etree._Element, p: etree._Element) -> etree._Element:
    """The element after which a change that starts at ``node`` goes.

    That is ``node``'s run, or the outermost tracked change of ``p`` the run lies in. Anything
    after ``node`` in its run first moves to a run of its own after it.
    """
    run = node.getparent()
    rest = list(node.itersiblings())
    if rest:
        twin = etree.Element(_R)
        properties = run.find(_RPR)
        if properties is not None:
            twin.append(copy.deepcopy(properties))
        twin.extend(rest)
        run.addnext(twin)
    anchor = run
    for ancestor in run.iterancestors():
        if ancestor is p:
            break
        if ancestor.tag in _REVISIONS:
            anchor = ancestor
    return anchor


def _prune(node: etree._Element, p: etree._Element) -> None:
    """Takes ``node`` out, with its run when nothing but formatting is left in it, and the
    tracked changes left empty by that."""
    holder = node.getparent()
    holder.remove(node)
    while holder is not p and (holder.tag == _R or holder.tag in _REVISIONS):
        if holder.tag == _R and any(child.tag != _RPR for child in holder):
            return
        if holder.tag != _R and len(holder):
            return
        parent = holder.getparent()
        parent.remove(holder)
        holder = parent


def _last_id(p: etree._Element) -> int:
    """The highest number any ``w:id`` of the part holds."""
    numbers = (v for e in p.getroottree().getroot().iter() if (v := e.get(_ID)) and v.isdigit())
    return max((int(v) for v in numbers), default=0)


# ---- helpers -------------------------------------------------------------------------------------


def _confirms_every_change(pkg: DocxPackage, case: Case, confirm_altered: Confirmation) -> bool:
    """Whether ``confirm_altered`` confirms every changed placeholder of the file.

    True does and False does not; a collection does when it holds the ordinal of each, which a
    plan of a copy of the package finds.
    """
    if isinstance(confirm_altered, bool):
        return confirm_altered
    planner = TextRestorer(case, confirm_altered=False)
    _restore_package(pkg.copy(), planner, apply=False, every_change_confirmed=False)
    changed = {item.ordinal for item in planner.plan if item.status == "altered"}
    return changed <= set(confirm_altered)


def _fingerprint(path: Path) -> str:
    """The SHA-256 of the bytes of the file at ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_empty(element: etree._Element) -> bool:
    """Whether ``element`` is a paragraph with nothing in it but properties and empty runs.

    A paragraph whose properties end a section (``w:sectPr``) is not: it holds the section's
    page setup.
    """
    return element.tag == _P and all(
        (child.tag == _PPR and child.find(_SECT_PR) is None)
        or (child.tag == _R and all(c.tag == _RPR for c in child))
        for child in element
    )


def _new_file(folder: Path, stem: str) -> Path:
    """A new empty file "<stem>.docx" in ``folder``, made when missing, or "<stem> (2).docx",
    "<stem> (3).docx" ... when the name is taken: a file that is there is never written over.
    """
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        target = folder / (f"{stem}.docx" if number == 1 else f"{stem} ({number}).docx")
        number += 1
        try:
            target.open("xb").close()  # only a file that is not there yet
        except FileExistsError:
            continue
        return target
