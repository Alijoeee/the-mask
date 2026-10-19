"""The review state: what the owner decides on the review screen before anything is masked.

The brief's tests and the pinned order use the ``review`` fixture, which analyses the brief's
example contract with the real engine. The other tests build a review by hand from the groups
they need (``hand_made``), so they do not depend on what the engine finds.
"""

import uuid

import pytest

from themask.detect.lists import CaseLists, UserLists
from themask.model import Analysis, Finding, Group, PlaceholderType
from themask.paths import lists_path
from themask.review import ReviewCounts, ReviewState

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY
AMOUNT, CUSTOM = PlaceholderType.AMOUNT, PlaceholderType.CUSTOM


def spot(kind, text, needle, nth=0, source="model"):
    """The ``nth`` occurrence of ``needle`` in ``text``, as a finding."""
    start = -1
    for _ in range(nth + 1):
        start = text.index(needle, start + 1)
    return Finding(kind, start, start + len(needle), needle, 0.9, source)


def group(kind, placeholder, canonical, findings, variants=(), **flags):
    return Group(
        uuid.uuid4().hex,
        kind,
        canonical,
        {canonical, *variants},
        list(findings),
        placeholder,
        **flags,
    )


def hand_made(text, groups, lists, reserved=()):
    """A review of ``text`` over ``groups`` exactly as given: no engine, nothing swept."""
    analysis = Analysis(text, groups, [])
    return ReviewState.from_analysis(analysis, lists, CaseLists([], [], set()), reserved)


def placeholders(review):
    return [g.placeholder for g in review.groups]


# --- The brief's tests -----------------------------------------------------------------------


def test_disable_group_removes_replacements(review):
    n = len(review.mask_plan().replacements)
    gid = review.groups[0].id
    review.set_group_enabled(gid, False)
    assert len(review.mask_plan().replacements) == n - len(review.groups[0].findings)


def test_disable_single_occurrence(review):
    gid = review.groups[0].id
    review.set_occurrence_enabled(gid, 0, False)
    first = review.groups[0].findings[0].start
    assert first not in {r.start for r in review.mask_plan().replacements}


def test_hide_text_sweeps(review):
    g = review.hide_text("Project Falcon", PlaceholderType.CUSTOM)
    assert len(g.findings) == review.text.count("Project Falcon") and g.placeholder == "[CUSTOM_1]"


def test_merge_keeps_lowest_number(review):
    n = len(review.groups)
    a, b = review.groups[0], review.groups[1]
    m = review.merge([a.id, b.id])
    lowest = min(a.placeholder, b.placeholder, key=lambda p: int(p.split("_")[1].rstrip("]")))
    assert m.placeholder == lowest and len(review.groups) == n - 1


def test_split(review):
    g = review.groups[0]
    new = review.split(g.id, [0])
    assert len(new.findings) == 1 and new.placeholder != g.placeholder


def test_never_hide_disables(review, lists):
    v = review.groups[0].canonical
    review.add_never_hide(v)
    assert not review.groups[0].enabled and v in lists.never_hide


def test_key_entries_match_plan(review):
    plan = {r.placeholder for r in review.mask_plan().replacements}
    assert plan == {e.placeholder for e in review.key_entries()}


# --- The fixture, and the plan, the counts and the switches ---------------------------------


def test_the_fixture_groups_come_in_the_order_the_brief_expects(review):
    # The brief's absolute numbers rest on this: pin it, so a change in the engine shows here.
    assert [
        (g.placeholder, g.canonical, g.needs_check, len(g.findings)) for g in review.groups
    ] == [
        ("[COMPANY_1]", "Acme Supplies Ltd", False, 2),
        ("[COMPANY_2]", "Northwind Trading B.V.", False, 1),
        ("[PERSON_1]", "John Smith", False, 1),
        ("[COMPANY_3]", "Project Falcon", True, 2),
    ]


def test_mask_plan_replaces_every_active_finding_in_text_order(review):
    replacements = review.mask_plan().replacements
    assert [(review.text[r.start : r.end], r.placeholder) for r in replacements] == [
        ("Acme Supplies Ltd", "[COMPANY_1]"),
        ("Northwind Trading B.V.", "[COMPANY_2]"),
        ("John Smith", "[PERSON_1]"),
        ("Project Falcon", "[COMPANY_3]"),
        ("Project Falcon", "[COMPANY_3]"),
        ("Acme", "[COMPANY_1]"),
    ]


def test_an_occurrence_switched_off_can_be_switched_back_on(review):
    n = len(review.mask_plan().replacements)
    gid = review.groups[0].id
    review.set_occurrence_enabled(gid, 1, False)
    assert len(review.mask_plan().replacements) == n - 1
    review.set_occurrence_enabled(gid, 1, True)
    assert len(review.mask_plan().replacements) == n


def test_counts(review):
    assert review.counts() == ReviewCounts(groups=4, enabled=4, needs_check=1, replacements=6)
    review.set_group_enabled(review.groups[3].id, False)  # the group to check
    review.set_occurrence_enabled(review.groups[0].id, 1, False)
    assert review.counts() == ReviewCounts(groups=4, enabled=3, needs_check=0, replacements=3)


def test_an_unknown_group_or_occurrence_is_refused(review):
    gid = review.groups[0].id
    with pytest.raises(ValueError):
        review.set_group_enabled("no such group", False)
    for index in (-1, 2):
        with pytest.raises(ValueError):
            review.set_occurrence_enabled(gid, index, False)


def test_the_review_leaves_the_analysis_alone(lists):
    text = "Orion signs."
    orion = group(CUSTOM, "[CUSTOM_1]", "Orion", [spot(CUSTOM, text, "Orion")])
    analysis = Analysis(text, [orion], ["a warning"])
    review = ReviewState.from_analysis(analysis, lists, CaseLists([], [], set()))
    review.set_group_enabled(orion.id, False)
    review.set_occurrence_enabled(orion.id, 0, False)
    review.hide_text("signs", CUSTOM)
    assert orion.enabled and not orion.disabled and analysis.groups == [orion]
    assert review.warnings == ["a warning"] and review.text == text


# --- hide_text --------------------------------------------------------------------------------


def test_hide_text_of_another_type_retypes_the_group(review):
    n = len(review.groups)
    flagged = review.groups[3]
    g = review.hide_text("Project Falcon", CUSTOM)
    assert g.id == flagged.id and g.type is CUSTOM and g.placeholder == "[CUSTOM_1]"
    assert not g.needs_check and len(review.groups) == n
    assert "[COMPANY_3]" not in placeholders(review)
    assert {(f.type, f.source, f.score) for f in g.findings} == {(CUSTOM, "user", 1.0)}
    assert [r.placeholder for r in review.mask_plan().replacements].count("[CUSTOM_1]") == 2


def test_hide_text_of_a_value_that_differs_only_in_a_point_makes_a_new_group(lists):
    # Ruling R100: "EUR 125" is not "EUR 1.25", however alike their digits; another spelling of
    # the group's own value joins it.
    text = "The fee is EUR 1.25 per item; the cap is EUR 125, or 1,25 EUR with the discount."
    fee = group(AMOUNT, "[AMOUNT_1]", "EUR 1.25", [spot(AMOUNT, text, "EUR 1.25")])
    review = hand_made(text, [fee], lists)
    cap = review.hide_text("EUR 125", AMOUNT)
    assert cap.placeholder == "[AMOUNT_2]" and [f.text for f in cap.findings] == ["EUR 125"]
    assert review.hide_text("1,25 EUR", AMOUNT).placeholder == "[AMOUNT_1]"
    assert placeholders(review) == ["[AMOUNT_1]", "[AMOUNT_2]"]
    assert [f.text for f in review.groups[0].findings] == ["EUR 1.25", "1,25 EUR"]


def test_hide_text_makes_a_new_group_numbered_next_for_its_type(review):
    g = review.hide_text("starts now", C)
    assert g is review.groups[-1] and g.placeholder == "[COMPANY_4]"
    assert (g.type, g.canonical, g.variants, g.enabled, g.needs_check) == (
        C,
        "starts now",
        {"starts now"},
        True,
        False,
    )
    assert [(f.text, f.source, f.score) for f in g.findings] == [("starts now", "user", 1.0)]
    assert len(g.id) == 32 and len({x.id for x in review.groups}) == 5


def test_a_group_a_sweep_leaves_empty_is_dropped(review):
    # The owner selects a phrase that holds two values found already: their groups are left with
    # nothing, and go. Nothing is renumbered.
    g = review.hide_text("Northwind Trading B.V. appoint John Smith", CUSTOM)
    assert placeholders(review) == ["[COMPANY_1]", "[CUSTOM_1]", "[COMPANY_3]"]
    assert all(x.findings for x in review.groups) and len(g.findings) == 1
    assert g.findings[0].source == "user"  # the sweep found it, but the owner chose it
    assert [f.text for f in review.groups[0].findings] == ["Acme Supplies Ltd", "Acme"]
    assert len(review.mask_plan().replacements) == 6 - 1


def test_hide_text_beats_the_never_hide_lists(lists):
    lists.add_never("Supplier")
    review = hand_made("The Supplier pays. The Supplier signs.", [], lists)
    g = review.hide_text("Supplier", CUSTOM)
    assert [f.text for f in g.findings] == ["Supplier", "Supplier"]


def test_the_owner_can_hide_a_bare_name_the_sweep_left_visible(lists):
    # Ruling R54: "the Smith report" stays visible in the analysis; the owner hides it by hand.
    text = "John Smith signed. The Smith report is attached."
    smith = group(P, "[PERSON_1]", "John Smith", [spot(P, text, "John Smith")], variants=["Smith"])
    review = hand_made(text, [smith], lists)
    g = review.hide_text("Smith", P)
    assert g.id == smith.id and g.placeholder == "[PERSON_1]" and len(review.groups) == 1
    assert [(f.text, f.source) for f in g.findings] == [("John Smith", "model"), ("Smith", "user")]
    assert g.findings[1].start == text.index("The Smith") + 4


def test_hide_text_switches_a_group_back_on(review):
    flagged = review.groups[3]
    review.set_group_enabled(flagged.id, False)
    g = review.hide_text("Project Falcon", C)
    assert g.id == flagged.id and g.enabled and g.placeholder == "[COMPANY_3]"
    assert len(review.mask_plan().replacements) == 6


def test_hide_text_refuses_what_cannot_be_hidden(review):
    n = len(review.groups)
    for value in ("", "   ", "X", "not in the contract"):
        with pytest.raises(ValueError):
            review.hide_text(value, CUSTOM)
    with pytest.raises(ValueError):  # all of it is hidden inside a longer finding already
        review.hide_text("Supplies", CUSTOM)
    assert len(review.groups) == n and placeholders(review)[0] == "[COMPANY_1]"


def test_hide_text_cannot_cross_a_line_break(lists):
    review = hand_made("Project\nFalcon starts.", [], lists)
    with pytest.raises(ValueError):  # a replacement lies within one paragraph
        review.hide_text("Project Falcon", CUSTOM)
    assert review.groups == []


def test_hide_text_never_touches_a_placeholder_the_text_holds(lists):
    review = hand_made("[CUSTOM_4] and Orion.", [], lists)
    for value in ("[CUSTOM_4]", "CUSTOM_4"):  # a placeholder inside a placeholder breaks both
        with pytest.raises(ValueError):
            review.hide_text(value, CUSTOM)
    assert review.groups == [] and review.mask_plan().replacements == []


def test_new_numbers_follow_the_exact_placeholders_the_text_holds(lists):
    # Only [TYPE_N] counts (ruling R44): "custom_9" is text, "[CUSTOM_4]" is taken.
    review = hand_made("[CUSTOM_4] and custom_9: Orion signs.", [], lists)
    assert review.hide_text("Orion", CUSTOM).placeholder == "[CUSTOM_5]"
    assert review.hide_text("signs", CUSTOM).placeholder == "[CUSTOM_6]"


# --- merge and split --------------------------------------------------------------------------


def test_merge_refuses_groups_of_different_types(review):
    company, person = review.groups[0], review.groups[2]
    n = len(review.groups)
    with pytest.raises(ValueError):
        review.merge([company.id, person.id])
    with pytest.raises(ValueError):  # one group, or the same one twice, is nothing to merge
        review.merge([company.id, company.id])
    assert len(review.groups) == n


def test_merge_unites_variants_findings_and_marks(lists):
    text = "John Smith signs. J. Smith pays. John Smith leaves."
    john = group(
        P, "[PERSON_2]", "John Smith", [spot(P, text, "John Smith"), spot(P, text, "John Smith", 1)]
    )
    john.disabled = {1}
    short = group(P, "[PERSON_1]", "J. Smith", [spot(P, text, "J. Smith")], needs_check=True)
    review = hand_made(text, [john, short], lists)
    m = review.merge([john.id, short.id])
    assert review.groups == [m] and m.id == short.id and m.placeholder == "[PERSON_1]"
    assert m.canonical == "John Smith" and m.variants == {"John Smith", "J. Smith"}
    assert [f.text for f in m.findings] == ["John Smith", "J. Smith", "John Smith"]
    assert m.disabled == {2} and m.needs_check and m.enabled


def test_merge_sweeps_for_the_united_variants(lists):
    text = "John Smith signs. Mr Smith pays. Later John Smith leaves; Mr Smith returns."
    john = group(P, "[PERSON_1]", "John Smith", [spot(P, text, "John Smith")])
    mister = group(P, "[PERSON_2]", "Mr Smith", [spot(P, text, "Mr Smith")])
    review = hand_made(text, [john, mister], lists)
    m = review.merge([john.id, mister.id])
    assert [f.text for f in m.findings] == ["John Smith", "Mr Smith", "John Smith", "Mr Smith"]
    assert [r.placeholder for r in review.mask_plan().replacements] == ["[PERSON_1]"] * 4


def test_merging_a_switched_off_group_keeps_its_occurrences_off(lists):
    text = "Acme signs. Orion pays."
    acme = group(C, "[COMPANY_1]", "Acme", [spot(C, text, "Acme")])
    orion = group(C, "[COMPANY_2]", "Orion", [spot(C, text, "Orion")], enabled=False)
    review = hand_made(text, [acme, orion], lists)
    m = review.merge([acme.id, orion.id])
    assert m.enabled and m.disabled == {1}
    assert [review.text[r.start : r.end] for r in review.mask_plan().replacements] == ["Acme"]
    assert review.counts().replacements == 1


def test_split_gives_the_new_group_the_next_free_number(review):
    acme = review.groups[0]
    new = review.split(acme.id, [1])  # the second Acme
    assert (new.type, new.placeholder, new.canonical, new.variants) == (
        C,
        "[COMPANY_4]",
        "Acme",
        {"Acme"},
    )
    assert [f.text for f in new.findings] == ["Acme"] and new.enabled
    assert placeholders(review) == [
        "[COMPANY_1]",
        "[COMPANY_2]",
        "[PERSON_1]",
        "[COMPANY_3]",
        "[COMPANY_4]",
    ]
    # The original keeps the rest, and the form only the moved occurrence showed goes with it.
    assert [f.text for f in acme.findings] == ["Acme Supplies Ltd"]
    assert acme.canonical == "Acme Supplies Ltd" and "Acme" not in acme.variants


def test_split_carries_the_switches_and_repairs_the_canonical(lists):
    text = "John Smith signs. Smith pays. J. Smith leaves. Smith returns."
    findings = [
        spot(P, text, "John Smith"),
        spot(P, text, "Smith", 1),
        spot(P, text, "J. Smith"),
        spot(P, text, "Smith", 3),
    ]
    john = group(
        P,
        "[PERSON_1]",
        "John Smith",
        findings,
        variants=["Smith", "J. Smith"],
        needs_check=True,
        enabled=False,
    )
    john.disabled = {2, 3}  # "J. Smith" and the last "Smith"
    review = hand_made(text, [john], lists)
    original = review.groups[0]
    new = review.split(original.id, [0, 2])
    assert [f.text for f in new.findings] == ["John Smith", "J. Smith"]
    assert (new.canonical, new.variants, new.placeholder) == (
        "John Smith",
        {"John Smith", "J. Smith"},
        "[PERSON_2]",
    )
    assert new.disabled == {1} and new.needs_check and not new.enabled and not original.enabled
    # The canonical moved with its finding: the original is now the fullest form it still shows.
    assert [f.text for f in original.findings] == ["Smith", "Smith"] and original.disabled == {1}
    assert (original.canonical, original.variants) == ("Smith", {"Smith"})


def test_a_merged_company_takes_the_fullest_canonical_without_a_leading_the(lists):
    # The engine reports "the Northwind Group" as seen: a variant, but never the canonical form.
    text = "the Northwind Group pays. the Kestrel Foods Company signs."
    northwind = group(C, "[COMPANY_1]", "Northwind Group", [spot(C, text, "the Northwind Group")])
    kestrel = group(
        C, "[COMPANY_2]", "Kestrel Foods Company", [spot(C, text, "the Kestrel Foods Company")]
    )
    northwind.variants.add("the Northwind Group")
    kestrel.variants.add("the Kestrel Foods Company")
    review = hand_made(text, [northwind, kestrel], lists)
    m = review.merge([northwind.id, kestrel.id])
    assert m.canonical == "Kestrel Foods Company"
    assert m.variants >= {"the Northwind Group", "the Kestrel Foods Company"}


def test_a_split_company_canonical_has_no_leading_the_but_keeps_one_inside(lists):
    text = "the Northwind Group pays. Kestrel and the Sons Ltd signs. Northwind Group leaves."
    findings = [
        spot(C, text, "the Northwind Group"),
        spot(C, text, "Kestrel and the Sons Ltd"),
        spot(C, text, "Northwind Group", 1),
    ]
    review = hand_made(text, [group(C, "[COMPANY_1]", "Northwind Group", findings)], lists)
    first = review.groups[0]
    sons = review.split(first.id, [1])
    northwind = review.split(first.id, [0])
    assert sons.canonical == "Kestrel and the Sons Ltd"
    assert northwind.canonical == "Northwind Group"
    assert northwind.variants == {"the Northwind Group"}


def test_split_cannot_empty_a_group_or_use_a_missing_occurrence(review):
    g = review.groups[0]
    for indexes in ([0, 1], [], [2], [-1]):
        with pytest.raises(ValueError):
            review.split(g.id, indexes)
    with pytest.raises(ValueError):
        review.split("no such group", [0])
    assert len(g.findings) == 2 and len(review.groups) == 4


# --- The lists --------------------------------------------------------------------------------


def test_add_never_hide_persists_and_switches_off_the_group_whose_value_it_matches(review):
    review.add_never_hide("THE ACME SUPPLIES LTD")  # the value, the way the lists match
    assert [g.enabled for g in review.groups] == [False, True, True, True]
    assert UserLists.load(lists_path()).never_hide == ["THE ACME SUPPLIES LTD"]
    assert len(review.mask_plan().replacements) == 6 - 2


def test_add_never_hide_of_a_shorter_form_switches_off_only_those_occurrences(review):
    # "Acme" is a form of Acme Supplies Ltd, not its value: the full name is no term, so it stays.
    review.add_never_hide("THE ACME")
    acme = review.groups[0]
    assert acme.enabled and acme.disabled == {1} and "Acme" not in acme.variants
    assert [review.text[r.start : r.end] for r in review.mask_plan().replacements] == [
        "Acme Supplies Ltd",
        "Northwind Trading B.V.",
        "John Smith",
        "Project Falcon",
        "Project Falcon",
    ]


def test_add_never_hide_of_a_surname_keeps_the_full_name_hidden(lists):
    text = "Mark Price signs. Price pays."
    findings = [spot(P, text, "Mark Price"), spot(P, text, "Price", 1)]
    mark = group(P, "[PERSON_1]", "Mark Price", findings, variants=["Price"])
    review = hand_made(text, [mark], lists)
    review.add_never_hide("Price")
    g = review.groups[0]
    assert g.enabled and g.disabled == {1} and g.variants == {"Mark Price"}
    assert [review.text[r.start : r.end] for r in review.mask_plan().replacements] == ["Mark Price"]
    assert [e.variants for e in review.key_entries()] == [["Mark Price"]]


def test_add_never_hide_switches_off_a_group_whose_every_occurrence_is_the_term(lists):
    # The value "Acme Supplies Ltd" is the case key's; this file only says "Acme".
    text = "Acme signs. Acme pays."
    findings = [spot(C, text, "Acme"), spot(C, text, "Acme", 1)]
    acme = group(C, "[COMPANY_1]", "Acme Supplies Ltd", findings, variants=["Acme"])
    review = hand_made(text, [acme], lists)
    review.add_never_hide("Acme")
    assert not review.groups[0].enabled and review.mask_plan().replacements == []


def test_add_never_hide_of_a_value_nothing_has_still_persists(review):
    review.add_never_hide("Zeppelin")
    assert all(g.enabled for g in review.groups)
    assert UserLists.load(lists_path()).never_hide == ["Zeppelin"]


def test_add_always_hide_persists_and_hides_the_value_here(lists):
    review = hand_made("Orion is a code name. ORION again.", [], lists)
    review.add_always_hide("Orion")
    [g] = review.groups
    assert (g.type, g.placeholder, len(g.findings)) == (CUSTOM, "[CUSTOM_1]", 2)
    assert UserLists.load(lists_path()).always_hide == ["Orion"]


def test_a_plain_always_hide_entry_joins_the_group_that_has_it_and_keeps_its_type(lists):
    # Ruling R62: a plain entry names no type, so the group keeps the one the analysis gave it.
    text = "Acme Supplies Ltd signs. Acme pays."
    found = [spot(C, text, "Acme Supplies Ltd")]
    acme = group(C, "[COMPANY_1]", "Acme Supplies Ltd", found, variants=["Acme"])
    review = hand_made(text, [acme], lists)
    review.add_always_hide("Acme")
    [g] = review.groups
    assert (g.id, g.type, g.placeholder) == (acme.id, C, "[COMPANY_1]")
    assert [(f.text, f.type, f.source) for f in g.findings] == [
        ("Acme Supplies Ltd", C, "model"),
        ("Acme", C, "user"),
    ]
    assert UserLists.load(lists_path()).always_hide == ["Acme"]


def test_a_typed_always_hide_entry_re_types_the_group_that_has_it(lists):
    text = "Acme Supplies Ltd signs. Acme pays."
    found = [spot(C, text, "Acme Supplies Ltd")]
    acme = group(C, "[COMPANY_1]", "Acme Supplies Ltd", found, variants=["Acme"])
    review = hand_made(text, [acme], lists)
    review.add_always_hide("CUSTOM:Acme")  # an explicit type, even CUSTOM, is the owner's choice
    [g] = review.groups
    assert (g.id, g.type, g.placeholder, len(g.findings)) == (acme.id, CUSTOM, "[CUSTOM_1]", 2)


def test_add_always_hide_hides_a_typed_entry_as_its_type(lists):
    review = hand_made("Falcon Freight signs.", [], lists)
    review.add_always_hide("company:Falcon Freight")
    [g] = review.groups
    assert (g.type, g.placeholder, g.canonical) == (C, "[COMPANY_1]", "Falcon Freight")
    assert UserLists.load(lists_path()).always_hide == ["company:Falcon Freight"]


def test_add_always_hide_of_a_value_this_document_lacks_only_persists(lists):
    review = hand_made("Nothing to see here.", [], lists)
    review.add_always_hide("Orion")
    review.add_always_hide("x")  # too short to look for, but the owner's list may hold it
    assert review.groups == []
    assert UserLists.load(lists_path()).always_hide == ["Orion", "x"]
    with pytest.raises(ValueError):
        review.add_always_hide("   ")


# --- The key ---------------------------------------------------------------------------------


def test_key_entries_come_in_type_and_number_order(review):
    assert [e.placeholder for e in review.key_entries()] == [
        "[PERSON_1]",
        "[COMPANY_1]",
        "[COMPANY_2]",
        "[COMPANY_3]",
    ]
    entry = review.key_entries()[1]
    assert (entry.type, entry.value) == (C, "Acme Supplies Ltd")
    assert sorted(entry.variants) == ["Acme", "Acme Supplies", "Acme Supplies Ltd"]


def test_key_entries_are_only_for_what_is_masked(review):
    review.set_group_enabled(review.groups[0].id, False)
    review.set_occurrence_enabled(review.groups[1].id, 0, False)  # its only occurrence
    assert [e.placeholder for e in review.key_entries()] == ["[PERSON_1]", "[COMPANY_3]"]


def test_key_entries_leave_out_a_bare_surname(review):
    # Ruling R52: the sweep hides "Smith" where it stands as a name, which the leak check's plain
    # scan cannot tell from "the Smith report", so the key does not list it.
    person = next(e for e in review.key_entries() if e.type is P)
    assert person.value == "John Smith" and person.variants == ["J. Smith", "John Smith"]


def test_key_entries_leave_out_particle_surnames_and_tiny_variants(lists):
    text = "Jane van der Berg signs for Acme Ltd."
    forms = ["J. van der Berg", "van der Berg", "Berg", "J", "-"]
    jane = group(P, "[PERSON_1]", "Jane van der Berg", [spot(P, text, "Jane van der Berg")], forms)
    acme = group(C, "[COMPANY_1]", "Acme Ltd", [spot(C, text, "Acme Ltd")], variants=["Acme", "A"])
    review = hand_made(text, [jane, acme], lists)
    person, company = review.key_entries()
    assert person.variants == ["J. van der Berg", "Jane van der Berg"]
    assert company.variants == ["Acme", "Acme Ltd"]  # a company's short name stays


# --- An existing case's key (ruling R61) ------------------------------------------------------


def test_a_number_the_case_key_holds_is_never_taken_by_a_new_group(lists):
    # [COMPANY_2] belongs to an earlier file of the case: this file has no group for it.
    review = hand_made("Baltic Fasteners GmbH signs.", [], lists, reserved=["[COMPANY_2]"])
    assert review.hide_text("Baltic Fasteners GmbH", C).placeholder == "[COMPANY_3]"


def test_a_split_and_a_re_typed_group_skip_the_numbers_the_case_key_holds(lists):
    text = "Acme Ltd signs. Acme Ltd pays. Orion leaves."
    acme = group(
        C, "[COMPANY_1]", "Acme Ltd", [spot(C, text, "Acme Ltd"), spot(C, text, "Acme Ltd", 1)]
    )
    orion = group(C, "[COMPANY_2]", "Orion", [spot(C, text, "Orion")])
    review = hand_made(text, [acme, orion], lists, reserved=["[COMPANY_5]", "[CUSTOM_2]"])
    assert review.split(acme.id, [1]).placeholder == "[COMPANY_6]"
    assert review.hide_text("Orion", CUSTOM).placeholder == "[CUSTOM_3]"


def test_a_group_the_case_key_holds_is_not_taken_over_by_a_longer_hidden_text(lists):
    text = "Project Falcon starts. Later Project Falcon ends."

    def review_with(reserved):
        found = [spot(CUSTOM, text, "Falcon", source="sweep")]  # as the key's seed finds it
        return hand_made(text, [group(CUSTOM, "[CUSTOM_1]", "Falcon", found)], lists, reserved)

    # Without the key, the longer occurrence takes the shorter finding over (ruling R35) ...
    loose = review_with([])
    loose.hide_text("Project Falcon", CUSTOM)
    assert placeholders(loose) == ["[CUSTOM_2]"] and len(loose.groups[0].findings) == 2
    # ... but not a group whose placeholder the key holds: it keeps its finding.
    kept = review_with(["[CUSTOM_1]"])
    new = kept.hide_text("Project Falcon", CUSTOM)
    assert placeholders(kept) == ["[CUSTOM_1]", "[CUSTOM_2]"]
    assert [f.text for f in kept.groups[0].findings] == ["Falcon"]
    assert [f.start for f in new.findings] == [text.rindex("Project Falcon")]


def test_a_merge_does_not_take_over_a_group_the_case_key_holds(lists):
    text = "Project Falcon starts. Later Project Falcon ends. Orion leaves."
    seeded = group(CUSTOM, "[CUSTOM_1]", "Falcon", [spot(CUSTOM, text, "Falcon", source="sweep")])
    falcon = group(
        CUSTOM, "[CUSTOM_2]", "Project Falcon", [spot(CUSTOM, text, "Project Falcon", 1)]
    )
    orion = group(CUSTOM, "[CUSTOM_3]", "Orion", [spot(CUSTOM, text, "Orion")])
    review = hand_made(text, [seeded, falcon, orion], lists, reserved=["[CUSTOM_1]"])
    merged = review.merge([falcon.id, orion.id])
    assert merged.placeholder == "[CUSTOM_2]" and len(merged.findings) == 2
    assert [f.text for f in review.groups[0].findings] == ["Falcon"]
