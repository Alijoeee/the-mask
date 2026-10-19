"""The review state: the logic behind the review screen (spec 8.3).

A ``ReviewState`` holds the analysed text with its groups and applies what the owner decides
before anything is masked: a whole group or a single occurrence switched off, text the analysis
missed hidden by hand, groups merged and split, values added to the always-hide and never-hide
lists. ``mask_plan`` and ``key_entries`` then give the replacements to make and the key to store.

* A group is never renumbered: the owner is looking at its placeholder. A group made in the
  review (hidden by hand, or split off) takes the next free number of its type, after the exact
  ``[TYPE_N]`` the text holds already (ruling R44), after the groups' own and after those an
  existing case's key holds (``reserved``, ruling R61).
* The owner's choice beats the analysis. ``hide_text`` hides a value whatever the never-hide
  lists say, finds every occurrence of it whether or not the sweep would have taken it (a bare
  surname inside a phrase, ruling R54), and re-types a group the analysis typed otherwise. What
  it hides is the owner's own ("user" findings): no later sweep takes it over.
* A sweep run here can take over another group's last finding (ruling R35); a group left with
  no finding is dropped, as the analysis does. The groups the case's key holds are never taken
  over, as in the analysis (ruling R61). Groups stay in order of first appearance and a group's
  findings in text order.
* A group the case's key holds keeps its value (ruling R107): merged with other groups it
  survives, whatever its number, with its canonical form, the stored value the key will keep;
  split, it keeps its canonical form too; and two such groups are never merged, as two stored
  values can never be one placeholder without a silent wrong value in the restore.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace

from themask.detect.grouping import PersonName
from themask.detect.identity import value_key
from themask.detect.lists import (
    CaseLists,
    UserLists,
    always_hide_entry,
    never_hide_check,
    on_never_hide_list,
)
from themask.detect.sweep import Spans, existing_placeholders, is_searchable, occurrences, sweep
from themask.model import (
    Analysis,
    Finding,
    Group,
    KeyEntry,
    MaskPlan,
    PlaceholderType,
    Replacement,
)
from themask.paths import lists_path
from themask.placeholders import PLACEHOLDER_RE, format_placeholder
from themask.textnorm import normalize

# The key lists the placeholder types in the order they are declared: PERSON, COMPANY, AMOUNT, ...
_TYPE_ORDER = {kind: rank for rank, kind in enumerate(PlaceholderType)}

# A leading "the" of a company's name: "the Northwind Group" is Northwind Group.
_LEADING_THE = re.compile(r"^(?i:the)\s+(?=\S)")


@dataclass(frozen=True)
class ReviewCounts:
    """The review screen's summary: groups, groups switched on, of those the ones to check, and
    the replacements that will be made.
    """

    groups: int
    enabled: int
    needs_check: int
    replacements: int


def _number(placeholder: str) -> int:
    """The number in a placeholder such as ``[COMPANY_3]``."""
    parsed = PLACEHOLDER_RE.fullmatch(placeholder)
    if parsed is None:
        raise ValueError(f"{placeholder!r} is not a placeholder.")
    return int(parsed["number"])


def _canonical(kind: PlaceholderType, forms: Iterable[str]) -> str:
    """The canonical form among ``forms``, as the analysis picks it: the longest, a run of spaces
    counting as one; of equal length the one not in capitals, then the first in alphabetical
    order. A company's has no leading "the": "the Northwind Group" is Northwind Group.
    """
    if kind is PlaceholderType.COMPANY:
        forms = [_LEADING_THE.sub("", form, count=1) for form in forms]
    return max(sorted(forms), key=lambda form: (len(" ".join(form.split())), not form.isupper()))


def _two_stored(groups: list[Group]) -> str:
    """Why two groups of the case's key cannot be merged, naming them."""
    names = [g.placeholder for g in groups]
    listed = f"{', '.join(names[:-1])} and {names[-1]}"
    if len(names) == 2:
        return (
            f"{listed} are both in the case's key and cannot be merged; leave them as two values."
        )
    return (
        f"{listed} are all in the case's key and cannot be merged; leave them as separate values."
    )


def _in_text_order(group: Group) -> None:
    """Put ``group``'s findings in the order they stand in; each keeps its switch."""
    order = sorted(
        range(len(group.findings)), key=lambda i: (group.findings[i].start, group.findings[i].end)
    )
    group.findings = [group.findings[i] for i in order]
    group.disabled = {new for new, old in enumerate(order) if old in group.disabled}


def _key_variants(group: Group) -> list[str]:
    """The variants a group's key entry lists: those worth searching for, but for a person's bare
    surname (ruling R52). The sweep hides it only where it stands as a name, which the leak
    check's plain scan cannot tell from "the Smith report"; the leak check looks for it with the
    sweep's own test instead.
    """
    bare = set()
    if group.type is PlaceholderType.PERSON:
        bare = {normalize(form) for form in PersonName.of(group.canonical).surnames()}
    return sorted(v for v in group.variants if is_searchable(v) and normalize(v) not in bare)


class ReviewState:
    """What the owner has decided about an analysis so far.

    ``text`` and ``groups`` are the analysed text and its groups (changed in place by the methods
    below), ``warnings`` the analysis's warnings for the screen. ``user_lists`` and ``case_lists``
    are the owner's lists and the case's; ``add_always_hide`` and ``add_never_hide`` change and
    save the owner's. ``reserved`` are the placeholders an existing case's key holds (ruling
    R61): a group made here never takes such a number, and a group that has one is never taken
    over by a sweep. Methods raise ValueError for an unknown group or occurrence, and for a
    change that cannot be made.
    """

    def __init__(
        self,
        text: str,
        groups: list[Group],
        warnings: list[str],
        user_lists: UserLists,
        case_lists: CaseLists,
        reserved: Collection[str] = (),
    ) -> None:
        self.text = text
        self.groups = groups
        self.warnings = warnings
        self.user_lists = user_lists
        self.case_lists = case_lists
        self.reserved = frozenset(reserved)

    @classmethod
    def from_analysis(
        cls,
        analysis: Analysis,
        user_lists: UserLists,
        case_lists: CaseLists,
        reserved: Collection[str] = (),
    ) -> ReviewState:
        """A review of ``analysis``, on copies of its groups: the analysis stays as it was.
        Adding a file to an existing case, pass the placeholders of its key as ``reserved``.
        """
        groups = [
            replace(
                g, variants=set(g.variants), findings=list(g.findings), disabled=set(g.disabled)
            )
            for g in analysis.groups
        ]
        return cls(analysis.text, groups, list(analysis.warnings), user_lists, case_lists, reserved)

    # --- Switches --------------------------------------------------------------------------------

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        """Switch a whole group on or off; its single switches stay as they are."""
        self._group(group_id).enabled = enabled

    def set_occurrence_enabled(self, group_id: str, finding_index: int, enabled: bool) -> None:
        """Switch one occurrence (an index into the group's findings) on or off."""
        group = self._group(group_id)
        if not 0 <= finding_index < len(group.findings):
            raise ValueError("The group has no such occurrence.")
        if enabled:
            group.disabled.discard(finding_index)
        else:
            group.disabled.add(finding_index)

    # --- Hiding text by hand ---------------------------------------------------------------------

    def hide_text(self, value: str, type: PlaceholderType) -> Group:
        """Hide every occurrence of ``value`` as ``type`` and return the group that holds them.

        If a group of ``type`` has ``value`` among its forms, the occurrences join it. If only a
        group of another type has, that whole group is re-typed: the owner's choice beats the
        analysis's guess, so it takes the next free number of ``type``, and is no longer marked
        to check. Otherwise the occurrences make a new group. Either way the group is switched
        on, its occurrences of the value switched back on if any was off (F-12), ``value`` is one
        of its variants, and an occurrence inside a longer finding stays inside it. Raises ValueError for text
        too short to look for, and for text with no occurrence to hide: one that is not in the
        document, runs over a line break (a replacement lies within one paragraph) or is hidden
        already.
        """
        value = value.strip()
        if not is_searchable(value):
            raise ValueError("Select at least two letters or digits to hide.")
        group = self._hide(value, type)
        if group is None:
            raise ValueError(
                "The selected text is not in the document, runs over a line break, or is hidden"
                " already."
            )
        return group

    def add_always_hide(self, value: str) -> None:
        """Add ``value`` to the owner's always-hide list, saved for every document, and hide it
        here: as ``TYPE:value`` writes it, else as CUSTOM. A plain value that a group has among
        its forms joins that group and keeps its type; only a ``TYPE:value`` entry re-types it
        (ruling R62). A value this document lacks is only added. Raises ValueError for a blank
        value.
        """
        self.user_lists.add_always(value)
        self.user_lists.save(lists_path())
        kind, text = always_hide_entry(value)
        if is_searchable(text):
            self._hide(text, kind, retype=text != value.strip())

    def add_never_hide(self, value: str) -> None:
        """Add ``value`` to the owner's never-hide list, saved for every document, and stop
        hiding it, the way the lists match: whatever the case, in the singular or the plural,
        with or without a leading "the". A group is switched off when its canonical form is
        the term, or every occurrence is. Of any other group only the occurrences that are the
        term are switched off, and the variants that are the term go: a longer text that holds
        a term is no term, so "Mark Price" stays hidden when "Price" is never hidden. Raises
        ValueError for a blank value.
        """
        self.user_lists.add_never(value)
        self.user_lists.save(lists_path())
        only_this, no_case = UserLists([], [value]), CaseLists([], [], set())

        def is_term(form: str) -> bool:
            return on_never_hide_list(form, only_this, no_case)

        for group in self.groups:
            terms = {i for i, f in enumerate(group.findings) if is_term(f.text)}
            if is_term(group.canonical) or len(terms) == len(group.findings):
                group.enabled = False
            else:
                group.disabled |= terms
                group.variants = {v for v in group.variants if not is_term(v)}

    # --- Merging and splitting -------------------------------------------------------------------

    def merge(self, group_ids: list[str]) -> Group:
        """Make the groups one, and return it. Only groups of one type can be merged.

        The group with the lowest number survives, with its id and placeholder. It takes the
        variants of all, the fullest of their canonical forms and all their findings in text
        order; it is marked to check if any was. Each occurrence keeps its switch: where the
        merged group is on, an occurrence of a group that was off stays off. The sweep then looks
        for each group's variants across the text. A group the case's key holds survives
        instead, whatever its number, and keeps its canonical form (ruling R107); raises
        ValueError when two of the groups are the key's, which can never be one value.
        """
        groups = list({g.id: g for g in map(self._group, group_ids)}.values())
        if len(groups) < 2:
            raise ValueError("Choose at least two groups to merge.")
        if len({g.type for g in groups}) > 1:
            raise ValueError("Only groups of the same type can be merged.")
        stored = [g for g in groups if g.placeholder in self.reserved]
        if len(stored) > 1:
            raise ValueError(_two_stored(stored))
        keep = stored[0] if stored else min(groups, key=lambda g: _number(g.placeholder))
        enabled = any(g.enabled for g in groups)
        occurrences_off = sorted(
            (
                (f, i in g.disabled or (enabled and not g.enabled))
                for g in groups
                for i, f in enumerate(g.findings)
            ),
            key=lambda pair: (pair[0].start, pair[0].end),
        )
        keep.variants = {form for g in groups for form in (g.canonical, *g.variants)}
        if not stored:
            keep.canonical = _canonical(keep.type, (g.canonical for g in groups))
        keep.needs_check = any(g.needs_check for g in groups)
        keep.enabled = enabled
        keep.findings = [f for f, _ in occurrences_off]
        keep.disabled = {i for i, (_, off) in enumerate(occurrences_off) if off}
        merged = {g.id for g in groups} - {keep.id}
        self.groups[:] = [g for g in self.groups if g.id not in merged]
        self._sweep()
        self._tidy()
        return keep

    def split(self, group_id: str, finding_indexes: list[int]) -> Group:
        """Move the occurrences at ``finding_indexes`` into a new group, and return it.

        The new group takes the next free number of the type, the longest of the moved texts as
        its canonical form and the moved texts as its variants; it is as switched as the group it
        came from, and so are its occurrences. The original keeps the rest, and loses a form only
        the moved occurrences showed (its canonical form too, which becomes the fullest it still
        shows; a group the case's key holds keeps its canonical form, the stored value: ruling
        R107). Raises ValueError for an index the group lacks, and for a split that would leave
        the original with nothing.
        """
        group = self._group(group_id)
        moved = sorted(set(finding_indexes))
        if not moved or moved[0] < 0 or moved[-1] >= len(group.findings):
            raise ValueError("Choose occurrences of the group to split off.")
        if len(moved) == len(group.findings):
            raise ValueError("A split must leave at least one occurrence in the group.")
        stay = [i for i in range(len(group.findings)) if i not in moved]
        leaving = [group.findings[i] for i in moved]
        staying = [group.findings[i] for i in stay]
        new = Group(
            uuid.uuid4().hex,
            group.type,
            _canonical(group.type, (f.text for f in leaving)),
            {f.text for f in leaving},
            leaving,
            self._next_placeholder(group.type),
            group.enabled,
            group.needs_check,
            {n for n, i in enumerate(moved) if i in group.disabled},
        )
        gone = {normalize(f.text) for f in leaving} - {normalize(f.text) for f in staying}
        group.variants = {v for v in group.variants if normalize(v) not in gone}
        if normalize(group.canonical) in gone:
            if group.placeholder not in self.reserved:
                group.canonical = _canonical(group.type, (f.text for f in staying))
            group.variants.add(group.canonical)
        group.disabled = {n for n, i in enumerate(stay) if i in group.disabled}
        group.findings = staying
        self.groups.append(new)
        self._tidy()
        return new

    # --- What the owner decided ------------------------------------------------------------------

    def mask_plan(self) -> MaskPlan:
        """The replacements to make: every finding of a group that is on, but the single
        occurrences switched off.
        """
        return MaskPlan(
            [
                Replacement(f.start, f.end, g.placeholder)
                for g in self.groups
                for f in g.active_findings()
            ]
        )

    def key_entries(self) -> list[KeyEntry]:
        """One key entry for each placeholder the plan uses, by type (in the order the types are
        declared) and number: the group's canonical form as the value, and its variants.
        """
        masked = [g for g in self.groups if g.active_findings()]
        masked.sort(key=lambda g: (_TYPE_ORDER[g.type], _number(g.placeholder)))
        return [KeyEntry(g.placeholder, g.type, g.canonical, _key_variants(g)) for g in masked]

    def counts(self) -> ReviewCounts:
        """The numbers for the screen's summary."""
        return ReviewCounts(
            groups=len(self.groups),
            enabled=sum(g.enabled for g in self.groups),
            needs_check=sum(g.enabled and g.needs_check for g in self.groups),
            replacements=sum(len(g.active_findings()) for g in self.groups),
        )

    # --- Helpers ---------------------------------------------------------------------------------

    def _group(self, group_id: str) -> Group:
        for group in self.groups:
            if group.id == group_id:
                return group
        raise ValueError("There is no such group.")

    def _hide(self, value: str, kind: PlaceholderType, retype: bool = True) -> Group | None:
        """Hide ``value`` as ``kind`` (see ``hide_text``); None when nothing could be hidden.
        Without ``retype`` a group of another type that has the value keeps its type.
        """
        group = self._holding(value, kind)
        if group is None:
            group = Group(uuid.uuid4().hex, kind, value, {value}, [], self._next_placeholder(kind))
            self.groups.append(group)
        elif retype and group.type is not kind:
            group.placeholder = self._next_placeholder(kind)
            group.type, group.needs_check = kind, False
            group.findings = [
                replace(f, type=kind, score=1.0, source="user") for f in group.findings
            ]
        kind = group.type
        group.enabled = True
        group.variants.add(value)
        # The places of the value the owner switched off come back on: they chose it (F-12).
        key = value_key(kind, value)
        group.disabled = {
            i for i in group.disabled if value_key(kind, group.findings[i].text) != key
        }
        known = {id(f) for f in group.findings}
        taken = Spans(
            [(f.start, f.end) for g in self.groups for f in g.findings]
            + [(p.start, p.end) for p in existing_placeholders(self.text)]
        )
        # Every place the value stands, without the sweep's test of a bare name: the owner chose it.
        for start, end in occurrences(self.text, value, taken):
            group.findings.append(Finding(kind, start, end, self.text[start:end], 1.0, "user"))
        # The sweep takes over the shorter findings a longer occurrence holds (ruling R35).
        self._sweep(fixed=[group])
        group.findings = [
            f if id(f) in known else replace(f, source="user") for f in group.findings
        ]
        self._tidy()
        return group if group.findings else None

    def _holding(self, value: str, kind: PlaceholderType) -> Group | None:
        """The group that has ``value`` among its forms however it is spelt, as a value of
        ``kind`` is spelt (``value_key``, ruling R100): its canonical form, its variants or a
        form it was seen in; of ``kind`` first."""
        key = value_key(kind, value)
        holding = [
            g
            for g in self.groups
            if key
            in {
                value_key(kind, form)
                for form in (g.canonical, *g.variants, *(f.text for f in g.findings))
            }
        ]
        return next((g for g in holding if g.type is kind), holding[0] if holding else None)

    def _next_placeholder(self, kind: PlaceholderType) -> str:
        """The placeholder a new group of ``kind`` takes: after the exact ``[TYPE_N]`` the text
        holds already (altered forms are no placeholders, ruling R44), after the groups' own and
        after the reserved ones (ruling R61).
        """
        found = list(PLACEHOLDER_RE.finditer(self.text))
        held = [*self.reserved, *(g.placeholder for g in self.groups)]
        found += [m for placeholder in held if (m := PLACEHOLDER_RE.fullmatch(placeholder))]
        highest = max((int(m["number"]) for m in found if m["type"] == kind.value), default=0)
        return format_placeholder(kind, highest + 1)

    def _sweep(self, fixed: Collection[Group] = ()) -> None:
        """Sweep the text for every group's variants, as the analysis did. The groups the case's
        key holds (``reserved``) are fixed besides ``fixed``: no sweep takes them over (ruling R61).
        """
        is_term = never_hide_check(self.user_lists, self.case_lists)
        keyed = [g for g in self.groups if g.placeholder in self.reserved]
        sweep(self.text, self.groups, fixed=[*fixed, *keyed], is_term=is_term)

    def _tidy(self) -> None:
        """Drop the groups a sweep left with no finding, and put each group's findings and the
        groups themselves in the order they stand in the text.
        """
        self.groups[:] = [g for g in self.groups if g.findings]
        for group in self.groups:
            _in_text_order(group)
        self.groups.sort(key=lambda g: g.findings[0].start)
