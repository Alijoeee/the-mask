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
from collections.abc import Collection, Iterable, Mapping
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
from themask.labels import (
    ClashProbe,
    FormSet,
    LabelError,
    check_label,
    clash_message,
    clashes_with_values,
    find_labels,
    label_key,
)
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


def key_variants(kind: PlaceholderType, canonical: str, forms: Iterable[str]) -> list[str]:
    """The variants a key entry of ``kind`` with the value ``canonical`` lists out of ``forms``:
    those worth searching for, but for a person's bare surname (ruling R52). The sweep hides it
    only where it stands as a name, which the leak check's plain scan cannot tell from "the
    Smith report"; the leak check looks for it with the sweep's own test instead. The export
    merges an added review's forms into a stored entry the same way (F-14).
    """
    bare = set()
    if kind is PlaceholderType.PERSON:
        bare = {normalize(form) for form in PersonName.of(canonical).surnames()}
    return sorted(v for v in set(forms) if is_searchable(v) and normalize(v) not in bare)


def asks_about(group: Group, answered: Collection[str] = ()) -> bool:
    """Whether the owner is asked about ``group``: the analysis was not sure of it and it is
    switched off, so it stays visible unless the owner says hide. A group the owner has answered
    "Show" to (``answered``) is not asked about again.
    """
    return group.needs_check and not group.enabled and group.id not in answered


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
        reserved_labels: Mapping[str, str] | None = None,
    ) -> None:
        self.text = text
        self.groups = groups
        self.warnings = warnings
        self.user_lists = user_lists
        self.case_lists = case_lists
        self.reserved = frozenset(reserved)
        # The ids of the groups the owner answered "Show" to under "Not sure — hide?": kept
        # here, not in the screen, so that a merge, a split and the export know them.
        self.answered: set[str] = set()
        # The names an existing case's key gives its placeholders (ruling R127). A group the
        # case holds keeps its name: the case's other masked files are written with it.
        self.reserved_labels = dict(reserved_labels or {})
        self._problems: tuple[object, list[tuple[str, str]]] | None = None
        # A name the case's key holds that this text already writes in square brackets: a restore
        # could not tell the two apart, and the export refuses it. Said here, in the review.
        self._bracketed = self._stored_names_in_text()
        for g in groups:
            if g.label is None and g.placeholder in self.reserved_labels:
                g.label = self.reserved_labels[g.placeholder]

    @classmethod
    def from_analysis(
        cls,
        analysis: Analysis,
        user_lists: UserLists,
        case_lists: CaseLists,
        reserved: Collection[str] = (),
        reserved_labels: Mapping[str, str] | None = None,
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
        return cls(
            analysis.text,
            groups,
            list(analysis.warnings),
            user_lists,
            case_lists,
            reserved,
            reserved_labels,
        )

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

    def hide_text(self, value: str, type: PlaceholderType, label: str | None = None) -> Group:
        """Hide every occurrence of ``value`` as ``type`` and return the group that holds them.

        If a group of ``type`` has ``value`` among its forms, the occurrences join it. If only a
        group of another type has, that whole group is re-typed: the owner's choice beats the
        analysis's guess, so it takes the next free number of ``type``, and is no longer marked
        to check. Otherwise the occurrences make a new group. Either way the group is switched
        on, its occurrences of the value switched back on if any was off (F-12), ``value`` is one
        of its variants, and an occurrence inside a longer finding stays inside it. Raises
        ValueError for text too short to look for, and for text with no occurrence to hide: one
        that is not in the document, runs over a line break (a replacement lies within one
        paragraph) or is hidden already.

        With ``label`` the group is named at once (``set_label``, ruling R127); a label that
        cannot be used raises LabelError before anything is hidden.
        """
        value = value.strip()
        if not is_searchable(value):
            raise ValueError("Select at least two letters or digits to hide.")
        group = self._hiding(value, type, label, retype=True)
        if group is None:
            raise ValueError(
                "The selected text is not in the document, runs over a line break, or is hidden"
                " already."
            )
        return group

    def add_always_hide(self, value: str, label: str | None = None) -> None:
        """Add ``value`` to the owner's always-hide list, saved for every document, and hide it
        here: as ``TYPE:value`` writes it, else as CUSTOM. A plain value that a group has among
        its forms joins that group and keeps its type; only a ``TYPE:value`` entry re-types it
        (ruling R62). A value this document lacks is only added. Raises ValueError for a blank
        value. With ``label`` the group it hides is named (ruling R127). Raises LabelError, and
        changes nothing (the list neither), when the name cannot be used, when the value is too
        short or not in this document so there is no group to name, or when the value would
        clash with a name already given.
        """
        kind, text = always_hide_entry(value)
        retype = text != value.strip()
        named = label is not None and bool(label.strip())
        if named and not is_searchable(text):
            raise LabelError("Select at least two letters or digits to hide and name.")
        if named or is_searchable(text):
            group = self._hiding(text, kind, label, retype=retype)
            if named and group is None:
                raise LabelError(
                    "That text is not in this document (or is hidden already), so there is no"
                    " group to give the name to. It was not added."
                )
        self.user_lists.add_always(value)
        self.user_lists.save(lists_path())

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
        named = [g for g in groups if g.label is not None]
        if len(named) > 1:
            raise ValueError(
                "These groups have different names; remove all but one name before merging."
            )
        if named and keep is not named[0] and keep.placeholder in self.reserved:
            raise ValueError(
                f"{keep.placeholder} is in the case's key without that name, so the name"
                " cannot be given to it; remove the name before merging."
            )
        label = named[0].label if named else None
        if label is not None and clashes_with_values(
            label,
            [f for g in groups for f in (g.canonical, *g.variants, *(x.text for x in g.findings))],
        ):
            raise ValueError(
                f"The name {label} contains, or is part of, a value in the groups you are"
                " merging, so the merged group would show part of it. Remove the name first, or"
                " do not merge these groups."
            )
        enabled = any(g.enabled for g in groups)
        # The merged group is answered when it was asked about and every one of those was.
        asked = [g for g in groups if g.needs_check and not g.enabled]
        was_answered = any(g.id in self.answered for g in groups) and all(
            g.id in self.answered for g in asked
        )
        # A guess the owner was asked about and did not answer is hidden along with the group it
        # joins (they merged it to hide it): the safe direction, not left visible unasked.
        unanswered = {g.id for g in asked if g.id not in self.answered}
        occurrences_off = sorted(
            (
                (f, i in g.disabled or (enabled and not g.enabled and g.id not in unanswered))
                for g in groups
                for i, f in enumerate(g.findings)
            ),
            key=lambda pair: (pair[0].start, pair[0].end),
        )
        keep.variants = {form for g in groups for form in (g.canonical, *g.variants)}
        if not stored:
            keep.canonical = _canonical(keep.type, (g.canonical for g in groups))
        keep.needs_check = any(g.needs_check for g in groups)
        keep.label = label
        keep.enabled = enabled
        keep.findings = [f for f, _ in occurrences_off]
        keep.disabled = {i for i, (_, off) in enumerate(occurrences_off) if off}
        merged = {g.id for g in groups} - {keep.id}
        self.answered -= merged
        self.answered.discard(keep.id)
        if was_answered:
            self.answered.add(keep.id)
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
        if group.id in self.answered:
            self.answered.add(new.id)
        self.groups.append(new)
        self._tidy()
        return new

    # --- What the owner decided ------------------------------------------------------------------

    def fingerprint(self) -> tuple[object, ...]:
        """What the owner has decided, as a value to compare: it differs after any switch, name,
        merge, split, hide or answer. Used to tell whether a review is as it was when exported.
        """
        return (
            tuple(
                (
                    g.id,
                    g.placeholder,
                    g.enabled,
                    g.label,
                    g.canonical,
                    tuple(sorted(g.disabled)),
                    tuple((f.start, f.end) for f in g.findings),
                )
                for g in self.groups
            ),
            frozenset(self.answered),
        )

    def mask_plan(self) -> MaskPlan:
        """The replacements to make: every finding of a group that is on, but the single
        occurrences switched off.
        """
        return MaskPlan(
            [Replacement(f.start, f.end, g.token) for g in self.groups for f in g.active_findings()]
        )

    def key_entries(self) -> list[KeyEntry]:
        """One key entry for each placeholder the plan uses, by type (in the order the types are
        declared) and number: the group's canonical form as the value, and its variants.
        """
        masked = [g for g in self.groups if g.active_findings()]
        masked.sort(key=lambda g: (_TYPE_ORDER[g.type], _number(g.placeholder)))
        return [
            KeyEntry(
                g.placeholder,
                g.type,
                g.canonical,
                key_variants(g.type, g.canonical, g.variants),
                g.label,
            )
            for g in masked
        ]

    def counts(self) -> ReviewCounts:
        """The numbers for the screen's summary."""
        return ReviewCounts(
            groups=len(self.groups),
            enabled=sum(g.enabled for g in self.groups),
            needs_check=sum(g.enabled and g.needs_check for g in self.groups),
            replacements=sum(len(g.active_findings()) for g in self.groups),
        )

    # --- Names the owner gives ---------------------------------------------------------------------

    def set_label(self, group_id: str, label: str | None) -> str | None:
        """Name a group (ruling R127): the masked file then writes ``[label]`` for it instead of
        its placeholder, which stays its identity in the key. Returns the name the group now has.

        An empty ``label`` or None removes the name, and so does the group's own placeholder
        ("COMPANY_1" for the group that is [COMPANY_1]). A name can be changed any time before
        the export. Raises LabelError, with the reason in plain words, for a name that is not
        1 to 32 letters, digits, spaces, hyphens or underscores with a letter in it; that
        another group has, or the placeholder of another group, or that spells any placeholder;
        that is one of the confidential values or part of one (the leak check would find it in
        the masked file); that the document already holds in square brackets (a restore could
        not tell it from the name); and for the group of an existing case's key, which keeps
        the name its other masked files were written with.
        """
        group = self._group(group_id)
        self._check_stored(group.placeholder, label)
        if group.placeholder in self.reserved and group.label is not None:
            return group.label  # the case's own name, spelt again: no change
        if label is None or not label.strip():
            group.label = None
            return None
        group.label = self._checked_label(
            label, group.placeholder, [group.canonical, *group.variants, *self._found_texts()]
        )
        return group.label

    # --- Helpers ---------------------------------------------------------------------------------

    def _found_texts(self) -> list[str]:
        return [f.text for g in self.groups for f in g.findings]

    def _check_stored(self, placeholder: str, label: str | None) -> None:
        """Raises LabelError for a change to the name of a group the case's key holds."""
        if placeholder not in self.reserved:
            return
        stored = self.reserved_labels.get(placeholder)
        wanted = None if label is None or not label.strip() else label
        same = (stored is None and wanted is None) or (
            stored is not None and wanted is not None and label_key(wanted) == label_key(stored)
        )
        if not same:
            raise LabelError(
                f"{placeholder} is in the case already, with its earlier files written as they"
                " are; its name cannot be changed."
            )

    def _checked_label(self, label: str, own: str, own_forms: Iterable[str]) -> str | None:
        """The label as ``check_label`` cleans it for the group ``own``, with the checks that
        need the review: the document's own brackets and the confidential values."""
        placeholders = {g.placeholder for g in self.groups} | self.reserved
        labels = {
            label_key(g.label): g.placeholder
            for g in self.groups
            if g.label is not None and g.placeholder != own
        }
        labels.update({label_key(v): p for p, v in self.reserved_labels.items() if p != own})
        text = check_label(
            label,
            own=own,
            other_placeholders=placeholders - {own},
            other_labels=labels,
        )
        if text is None:
            return None
        key = label_key(text)
        if find_labels(self.text, {key: text}):
            raise LabelError(
                f"The document already contains [{text}] in square brackets. A restore could not"
                " tell it from the name you chose; choose another name."
            )
        forms = [*own_forms, *(f for g in self.groups for f in (g.canonical, *g.variants))]
        forms += self._found_texts()
        if clashes_with_values(text, forms):
            raise LabelError(
                f"{text} is, or contains a word of, a value that is being hidden, so the masked"
                " file would still show part of it. Choose another name."
            )
        return text

    def _hiding(
        self, value: str, kind: PlaceholderType, label: str | None, retype: bool
    ) -> Group | None:
        """Hide ``value`` as ``kind`` and name the group ``label`` (if given), all or nothing:
        every check runs before the hide, and a failure after it puts the review back as it was.
        """
        named = label is not None and bool(label.strip())
        self._check_value_against_names(value)
        if named:
            self._check_label_before_hiding(value, kind, label or "", retype)
        before = self._snapshot()
        group = self._hide(value, kind, retype=retype)
        if group is not None and named:
            try:
                self.set_label(group.id, label)
            except LabelError:
                self._restore(before)
                raise
        return group

    def _snapshot(self) -> list[tuple[Group, Group]]:
        """Every group with a copy of its state, to put the review back (``_restore``)."""
        return [
            (
                g,
                replace(
                    g, variants=set(g.variants), findings=list(g.findings), disabled=set(g.disabled)
                ),
            )
            for g in self.groups
        ]

    def _restore(self, snapshot: list[tuple[Group, Group]]) -> None:
        for group, state in snapshot:
            group.__dict__.update(state.__dict__)
        self.groups[:] = [group for group, _ in snapshot]

    def _check_value_against_names(self, value: str) -> None:
        """Raises LabelError if hiding ``value`` would put part of it inside a name already given
        to a group: the masked file would show that part. Nothing is changed."""
        for g in self.groups:
            if g.label is not None and clashes_with_values(g.label, [value]):
                kept = (
                    " That name is in the case already and cannot change."
                    if g.placeholder in self.reserved
                    else " Remove or change the name first."
                )
                raise LabelError(
                    f"That text contains, or is part of, the name {g.label} given to"
                    f" {g.placeholder}, so the masked file would still show part of it.{kept}"
                )

    def label_problems(self) -> list[str]:
        """Plain messages for every name that clashes with a value that will be masked (a group
        that is on): what an export would refuse. Switching the other group off, or choosing
        another name, clears the message; a name from the case's key cannot change, so for
        it the other group must go. Empty when all is well.
        """
        return [message for _, message in self.label_problem_pairs()]

    def label_problem_pairs(self) -> list[tuple[str, str]]:
        """``label_problems`` as (id of the group whose name clashes, message) pairs.

        The answer is kept until a name, a switch, a place, a value or a key name changes, so the
        screen can ask after every redraw without paying for the test each time.
        """
        if not any(g.label is not None for g in self.groups):
            return list(self._bracketed)
        key = (
            tuple(
                (
                    g.id,
                    g.label,
                    g.enabled,
                    g.canonical,
                    tuple(sorted(g.variants)),
                    tuple((f.start, f.end) for f in g.findings),
                    tuple(sorted(g.disabled)),
                )
                for g in self.groups
            ),
            tuple(sorted(self.reserved_labels.items())),
        )
        if self._problems is not None and self._problems[0] == key:
            return list(self._problems[1])
        pairs = [*self._bracketed, *self._find_label_problems()]
        self._problems = (key, pairs)
        return list(pairs)

    def _stored_names_in_text(self) -> list[tuple[str, str]]:
        """(id of the group that has the name, or "" if the text has none; message) for each name
        of the case's key that the text already holds in square brackets.
        """
        pairs = []
        for placeholder, label in self.reserved_labels.items():
            if find_labels(self.text, {label_key(label): label}):
                owner = next((g.id for g in self.groups if g.placeholder == placeholder), "")
                pairs.append(
                    (
                        owner,
                        (
                            f"The file already contains [{label}] in square brackets, the name"
                            f" {placeholder} has in the case. A restore could not tell them"
                            " apart; take it out of the file in Word and open the file again."
                        ),
                    )
                )
        return pairs

    def _find_label_problems(self) -> list[tuple[str, str]]:
        masked = [g for g in self.groups if g.active_findings()]
        named = [g for g in masked if g.label is not None]
        if not named:
            return []
        sets = {
            g.id: FormSet([g.canonical, *g.variants, *(f.text for f in g.findings)]) for g in masked
        }
        pairs = []
        for g in named:
            assert g.label is not None
            probe = ClashProbe(g.label)
            stored = g.placeholder in self.reserved_labels
            for other in masked:
                forms = sets[other.id]
                if probe.may_clash(forms) and probe.clashes(forms.forms):
                    pairs.append(
                        (g.id, clash_message(g.label, g.placeholder, other.placeholder, stored))
                    )
        return pairs

    def _check_label_before_hiding(
        self, value: str, kind: PlaceholderType, label: str, retype: bool = True
    ) -> None:
        """Raises LabelError if ``label`` could not name the group ``hide_text`` is about to
        make or change for ``value``; nothing is changed."""
        holder = self._holding(value, kind)
        if holder is not None and (holder.type is kind or not retype):
            self._check_stored(holder.placeholder, label)
            own = holder.placeholder
        else:
            own = self._next_placeholder(kind)
        self._checked_label(label, own, [value])

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
        if (
            group is not None
            and retype
            and group.type is not kind
            and group.placeholder in self.reserved_labels
        ):
            raise LabelError(
                f"{group.placeholder} is in the case with the name {group.label}, so its type"
                " cannot be changed."
            )
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
        self.answered &= {g.id for g in self.groups}
        for group in self.groups:
            _in_text_order(group)
        self.groups.sort(key=lambda g: g.findings[0].start)
