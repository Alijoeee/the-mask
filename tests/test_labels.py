"""Owner-chosen names for placeholders (ruling R127): [Provider] in place of [COMPANY_1].

Made-up text only. Covers what a name may be, how it is stored, how a restore finds it (only in
square brackets, never as a bare word), the review's rules (unique, no clash with a value or with
the document's own brackets, kept for a file added to a case) and the export with names.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import pytest

from tests.fixtures.restore import NOW
from tests.helpers import reviewed, simulate_ai
from themask.detect.lists import CaseLists
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.export import ExportOptions, SourceDoc, combined_text, export_case, load_sources
from themask.instruction import AI_INSTRUCTION, AI_INSTRUCTION_NAMED, BANNER_TEXT, BANNER_TEXT_NAMED
from themask.keystore.cases import CaseStore
from themask.keystore.crypto import encrypt
from themask.labels import LabelError, check_label, clean_label
from themask.model import Case, Group, KeyEntry, PlaceholderType
from themask.restore.docx_restore import plan_docx, restore_docx
from themask.restore.matcher import plan_restore, suggest_cases
from themask.restore.text import restore_text
from themask.review import ReviewState

if TYPE_CHECKING:
    from tests.fixtures.docx import MakeDocx
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.keystore.secrets import KeyStore

COMPANY = PlaceholderType.COMPANY
PERSON = PlaceholderType.PERSON

SUPPLY = (
    "Northwind Trading B.V. supplies goods to Thamesgate Catering plc. "
    "The Provider shall deliver; the Customer shall pay. Northwind Trading B.V. signs."
)


def named_case(*labels: str | None) -> Case:
    """A case of three entries; ``labels`` name them in order."""
    entries = [
        KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", ["Northwind"]),
        KeyEntry("[COMPANY_2]", COMPANY, "Thamesgate Catering plc", []),
        KeyEntry("[PERSON_1]", PERSON, "Jane Doe", []),
    ]
    for entry, label in zip(entries, labels, strict=False):
        entry.label = label
    return Case("T1", NOW, ["a.docx"], [], entries)


PROVIDER_CUSTOMER = named_case("Provider", "Customer")


# ---- what a name may be -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label", ["Provider", "Data Provider", "a", "Müller-Gruppe", "Сторона_1", "供应商"]
)
def test_valid_names(label: str) -> None:
    assert clean_label(label) == label


def test_a_name_is_trimmed_and_its_spaces_made_one() -> None:
    assert clean_label("  Data   Provider ") == "Data Provider"


@pytest.mark.parametrize(
    "label",
    ["", "   ", "[Provider]", "Pro[vider", "Pro]vider", "Pro\nvider", "Pro\tvider", "x" * 33,
     "12345", "1 2", "-", "_", "Pro*vider", "Pro.vider", "Pro vider", "［X］", "a\x00b"],
)  # fmt: skip
def test_invalid_names(label: str) -> None:
    with pytest.raises(LabelError):
        clean_label(label)


def test_the_longest_name_is_32_characters() -> None:
    assert clean_label("x" * 32) == "x" * 32


@pytest.mark.parametrize("label", ["COMPANY_1", "company 1", "Person-3", "ID 12", "x COMPANY_1 y"])
def test_a_name_that_spells_a_placeholder_is_refused(label: str) -> None:
    with pytest.raises(LabelError, match="placeholder"):
        check_label(label, own="[PERSON_9]", other_placeholders=[], other_labels={})


def test_a_name_that_is_the_groups_own_placeholder_means_no_name() -> None:
    for label in ("COMPANY_1", "company 1", "Company-1"):
        assert check_label(label, own="[COMPANY_1]", other_placeholders=[], other_labels={}) is None


def test_another_groups_placeholder_is_refused_with_the_reason() -> None:
    with pytest.raises(LabelError, match=r"\[COMPANY_2\].*tell them apart"):
        check_label(
            "COMPANY_2", own="[COMPANY_1]", other_placeholders=["[COMPANY_2]"], other_labels={}
        )


def test_names_are_unique_whatever_the_case_and_separator() -> None:
    taken = {"data provider": "[COMPANY_2]"}
    for label in ("Data Provider", "DATA-PROVIDER", "data_provider"):
        with pytest.raises(LabelError, match="already used"):
            check_label(label, own="[COMPANY_1]", other_placeholders=[], other_labels=taken)


# ---- the stored case ----------------------------------------------------------------------------


def test_names_round_trip_through_json_and_old_cases_load_unchanged() -> None:
    case = named_case("Provider", None, "Signer")
    again = Case.from_json(case.to_json())
    assert [e.label for e in again.entries] == ["Provider", None, "Signer"] and again == case
    stored = json.loads(case.to_json())["entries"]
    assert "label" not in stored[1]  # an unnamed entry is stored exactly as before
    old = json.loads(named_case().to_json())
    assert Case.from_json(json.dumps(old)).entries == named_case().entries


@pytest.mark.parametrize(
    "bad",
    [None, 5, ["x"], "", "[x]", "COMPANY_2", "a\nb", "x" * 40, "Same", "123"],
)
def test_a_damaged_name_makes_the_case_unreadable(bad: object) -> None:
    data = json.loads(named_case("Same", None).to_json())
    data["entries"][1]["label"] = bad
    if bad == "Same":
        data["entries"][0]["label"] = "same"  # two entries, one name
    with pytest.raises(ValueError, match="Not a stored case"):
        Case.from_json(json.dumps(data))


def test_the_store_lists_a_case_with_a_damaged_name_as_unreadable(
    case_store: CaseStore, keystore: KeyStore
) -> None:
    good = named_case("Provider")
    case_store.save(good)
    data = json.loads(named_case("Provider").to_json())
    data["id"] = "BAD1"
    data["entries"][1]["label"] = "[oops]"
    case_store.dir.joinpath("BAD1.mask").write_bytes(
        encrypt(keystore.get_or_create_master_key(), json.dumps(data).encode())
    )
    assert [c.id for c in case_store.load_all()] == ["T1"]
    assert [p.name for p in case_store.unreadable] == ["BAD1.mask"]


# ---- how a restore finds a name -----------------------------------------------------------------


def test_an_exact_bracketed_name_is_restored_and_a_bare_word_never() -> None:
    text = "The Provider shall pay. [Provider] signs; provider, Provider and the PROVIDER stay."
    out, report = restore_text(text, PROVIDER_CUSTOMER, False)
    assert out == (
        "The Provider shall pay. Northwind Trading B.V. signs; provider, Provider and the "
        "PROVIDER stay."
    )
    assert report.restored == 1 and report.needs_check == [] and report.unknown == []


@pytest.mark.parametrize(
    "form",
    ["[provider]", "[ Provider ]", "[PROVIDER]", "**[Provider]**", r"\[Provider\]",
     "［Provider］", "[Provider ]", "`[Provider]`", "__[Provider]__"],
)  # fmt: skip
def test_a_changed_form_waits_for_the_owner(form: str) -> None:
    text = f"See {form} here."
    (item,) = plan_restore(text, PROVIDER_CUSTOMER)
    assert item.status == "altered" and item.entry is not None and item.entry.label == "Provider"
    kept, report = restore_text(text, PROVIDER_CUSTOMER, False)
    assert kept == text and len(report.needs_check) == 1  # never silently
    done, report = restore_text(text, PROVIDER_CUSTOMER, True)
    assert done == "See Northwind Trading B.V. here." and report.altered_restored == 1


@pytest.mark.parametrize(
    "text",
    ["[Provider", "Provider]", "Provider", "(Provider)", "{Provider}", "[Customers"],
)
def test_bare_and_one_sided_forms_are_left(text: str) -> None:
    assert plan_restore(text, PROVIDER_CUSTOMER) == []
    assert restore_text(text, PROVIDER_CUSTOMER, True)[0] == text


@pytest.mark.parametrize(
    "text",
    ["[Providers]", "[Provider\u2019s]", "[Provider.]", "[The Provider]", "[Provider\tGroup]",
     "[Provider, Customer]", "[the Provider]", "\u3010Provider's\u3011", "[Provider group]",
     "[Prov ider]"],
)  # fmt: skip
def test_a_changed_name_that_is_not_recognised_is_reported_never_replaced(text: str) -> None:
    # I3: it used to be silent (these were pinned as "left"); now the report names it.
    (item,) = plan_restore(text, PROVIDER_CUSTOMER)
    assert item.status == "unknown" and item.entry is None
    out, report = restore_text(text, PROVIDER_CUSTOMER, True)
    assert out == text and report.restored == 0 and report.unknown == [text]


@pytest.mark.parametrize("text", ["[Pro\u00advider]", "\u3010Provider\u3011", "[Provide\u0155]"])
def test_invisible_and_accent_changes_are_recognised_as_changed(text: str) -> None:
    (item,) = plan_restore(text, PROVIDER_CUSTOMER)
    assert item.status == "altered"
    assert restore_text(text, PROVIDER_CUSTOMER, False)[0] == text
    assert restore_text(text, PROVIDER_CUSTOMER, True)[0] == "Northwind Trading B.V."


def test_a_markdown_link_is_a_changed_form() -> None:
    # M3: it used to be restored as exact, leaving "Northwind Trading B.V.(https://x.y)".
    (item,) = plan_restore("[Provider](https://x.y)", PROVIDER_CUSTOMER)
    assert item.status == "altered"
    out, report = restore_text("[Provider](https://x.y)", PROVIDER_CUSTOMER, False)
    assert out == "[Provider](https://x.y)" and len(report.needs_check) == 1


def test_two_names_and_a_canonical_form_in_one_text() -> None:
    text = "[Provider] pays [Customer]; [COMPANY_1] and [PERSON_1] and [Nobody]."
    items = [(i.match.raw, i.status) for i in plan_restore(text, PROVIDER_CUSTOMER)]
    assert items == [
        ("[Provider]", "exact"),
        ("[Customer]", "exact"),
        ("[COMPANY_1]", "altered"),  # the files never wrote it for a named entry
        ("[PERSON_1]", "exact"),
    ]
    out, _ = restore_text(text, PROVIDER_CUSTOMER, True)
    assert out == (
        "Northwind Trading B.V. pays Thamesgate Catering plc; Northwind Trading B.V. and Jane Doe"
        " and [Nobody]."
    )


def test_a_name_of_another_case_is_ordinary_text() -> None:
    assert restore_text("[Provider]", named_case(), True)[0] == "[Provider]"
    assert restore_text("[Provider]", named_case("Seller"), True)[0] == "[Provider]"


def test_the_named_banner_and_instruction_are_taken_out() -> None:
    text = f"{BANNER_TEXT_NAMED}\n\n{AI_INSTRUCTION_NAMED}\n\nHello [Provider]"
    assert restore_text(text, PROVIDER_CUSTOMER, True)[0] == "Hello Northwind Trading B.V."
    assert "[Provider]" in AI_INSTRUCTION_NAMED  # the example is not a value of any case
    assert "square brackets" in AI_INSTRUCTION_NAMED and "square brackets" in BANNER_TEXT_NAMED
    assert "Keep every placeholder exactly as written" in AI_INSTRUCTION_NAMED


def test_suggest_cases_counts_names() -> None:
    other = named_case()
    other.id = "T2"
    best = suggest_cases("[Provider] and [Customer]", [other, PROVIDER_CUSTOMER])
    assert best[0].id == "T1"


def test_docx_restore_with_a_name_split_across_runs(make_docx: MakeDocx, tmp_path: Path) -> None:
    run = lambda t: f'<w:r><w:t xml:space="preserve">{escape(t)}</w:t></w:r>'
    body = (
        f"<w:p>{run('The Provider pays. [Pro')}{run('vider] and [Cust')}{run('omer]. [ customer ]')}</w:p>"
        f"<w:p>{run('Bare Provider and Customer stay.')}</w:p>"
    )
    path = make_docx(body)
    plan = plan_docx(path, PROVIDER_CUSTOMER)
    assert [(i.match.raw, i.status) for i in plan.items] == [
        ("[Provider]", "exact"),
        ("[Customer]", "exact"),
        ("[ customer ]", "altered"),
    ]
    out, report = restore_docx(path, PROVIDER_CUSTOMER, False, tmp_path / "o")
    text = extract_text(DocxPackage.open(out)).text
    assert text.splitlines()[0] == (
        "The Provider pays. Northwind Trading B.V. and Thamesgate Catering plc. [ customer ]"
    )
    assert "Bare Provider and Customer stay." in text and len(report.needs_check) == 1
    out, report = restore_docx(path, PROVIDER_CUSTOMER, True, tmp_path / "o2")
    assert report.restored == 3 and report.altered_restored == 1


# ---- the review ---------------------------------------------------------------------------------


def group(kind: PlaceholderType, placeholder: str, value: str, text: str) -> Group:
    from tests.test_export import group_of

    return group_of(text, placeholder, kind, value)


def review_of(text: str, lists: UserLists, *groups: Group, **kw: object) -> ReviewState:
    """A review over exactly these group objects (not copies), so a test can look at them."""
    return ReviewState(text, list(groups), [], lists, CaseLists([], [], set()), **kw)  # type: ignore[arg-type]


def two_companies(lists: UserLists, **kw: object) -> tuple[ReviewState, Group, Group]:
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", SUPPLY)
    b = group(COMPANY, "[COMPANY_2]", "Thamesgate Catering plc", SUPPLY)
    return review_of(SUPPLY, lists, a, b, **kw), a, b


def test_naming_changes_what_the_plan_writes_and_not_the_key_identity(lists: UserLists) -> None:
    review, a, _ = two_companies(lists)
    assert review.set_label(a.id, "  Provider ") == "Provider"
    assert {r.placeholder for r in review.mask_plan().replacements} == {"[Provider]", "[COMPANY_2]"}
    first, second = review.key_entries()
    assert (first.placeholder, first.label) == ("[COMPANY_1]", "Provider") and second.label is None


def test_a_name_can_be_changed_or_removed_any_time(lists: UserLists) -> None:
    review, a, b = two_companies(lists)
    review.set_label(a.id, "Provider")
    review.set_label(b.id, "Customer")
    review.set_label(a.id, "Seller")  # renamed: only alias metadata
    review.set_label(b.id, "Provider")  # the freed name can be used again
    assert [g.label for g in review.groups] == ["Seller", "Provider"]
    review.set_label(a.id, None)
    review.set_label(b.id, "")
    assert [g.label for g in review.groups] == [None, None]
    assert {r.placeholder for r in review.mask_plan().replacements} == {
        "[COMPANY_1]",
        "[COMPANY_2]",
    }


def test_a_name_is_refused_when_another_group_has_it_or_it_is_ambiguous(lists: UserLists) -> None:
    review, a, b = two_companies(lists)
    review.set_label(a.id, "Provider")
    for bad in ("provider", "PROVIDER ", "COMPANY_1", "[x]", "42"):
        with pytest.raises(LabelError):
            review.set_label(b.id, bad)
    assert b.label is None
    assert review.set_label(a.id, "company 1") is None  # its own placeholder: no name
    with pytest.raises(LabelError, match=r"\[COMPANY_1\]"):
        review.set_label(b.id, "Company_1")


def test_a_name_that_is_a_value_or_holds_one_is_refused(lists: UserLists) -> None:
    review, a, b = two_companies(lists)
    a.variants.add("Provider")
    with pytest.raises(LabelError, match="value"):
        review.set_label(b.id, "Provider")  # another group's variant: the leak check would hit it
    with pytest.raises(LabelError, match="value"):
        review.set_label(b.id, "Thamesgate Catering plc")
    with pytest.raises(LabelError, match="value"):
        review.set_label(b.id, "Northwind Trading B.V.".replace(".", ""))
    assert review.set_label(b.id, "Customer") == "Customer"


def test_a_name_the_document_already_holds_in_brackets_is_refused(lists: UserLists) -> None:
    text = SUPPLY + " See [Provider] and [ customer ]."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(text, lists, a)
    for bad in ("Provider", "provider", "Customer"):
        with pytest.raises(LabelError, match="already contains"):
            review.set_label(a.id, bad)
    assert review.set_label(a.id, "Seller") == "Seller"  # bare words do not count


def test_hiding_text_can_name_the_group_at_once(lists: UserLists) -> None:
    text = SUPPLY + " Project Falcon starts."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    b = group(COMPANY, "[COMPANY_2]", "Thamesgate Catering plc", text)
    review = review_of(text, lists, a, b)
    review.set_label(a.id, "Provider")
    g = review.hide_text("Project Falcon", PlaceholderType.CUSTOM, label="Codename")
    assert g.label == "Codename"
    with pytest.raises(LabelError):  # refused before anything is hidden
        review.hide_text("starts", PlaceholderType.CUSTOM, label="Provider")
    assert all(x.canonical != "starts" for x in review.groups)
    assert b.label is None


def test_hide_text_with_a_bad_label_changes_nothing(lists: UserLists) -> None:
    text = SUPPLY + " Project Falcon."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(text, lists, a)
    before = len(review.groups)
    with pytest.raises(LabelError):
        review.hide_text("Project Falcon", PlaceholderType.CUSTOM, label="CUSTOM_1x2[")
    assert len(review.groups) == before


def test_always_hide_can_name_the_group(lists: UserLists) -> None:
    text = SUPPLY + " Project Falcon."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(text, lists, a)
    review.add_always_hide("Project Falcon", label="Codename")
    assert [g.label for g in review.groups] == [None, "Codename"]
    with pytest.raises(LabelError):
        review.add_always_hide("Thamesgate", label="Codename")
    assert "Thamesgate" not in lists.always_hide


def test_merge_and_split_keep_names_safe(lists: UserLists) -> None:
    text = "Northwind Trading B.V. and Northwind Ltd and Thamesgate Catering plc."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    b = group(COMPANY, "[COMPANY_2]", "Northwind Ltd", text)
    c = group(COMPANY, "[COMPANY_3]", "Thamesgate Catering plc", text)
    review = review_of(text, lists, a, b, c)
    review.set_label(b.id, "Provider")
    review.set_label(c.id, "Customer")
    with pytest.raises(ValueError, match="different names"):
        review.merge([b.id, c.id])
    merged = review.merge([a.id, b.id])  # the one name goes to the survivor
    assert merged.placeholder == "[COMPANY_1]" and merged.label == "Provider"


def test_a_stored_group_keeps_its_name_and_new_files_cannot_reuse_it(lists: UserLists) -> None:
    stored = named_case("Provider", None)
    text = "Northwind Trading B.V. and Thamesgate Catering plc and Acme Corp."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    b = group(COMPANY, "[COMPANY_2]", "Thamesgate Catering plc", text)
    c = group(COMPANY, "[COMPANY_3]", "Acme Corp", text)
    review = review_of(
        text, lists, a, b, c,
        reserved=[e.placeholder for e in stored.entries],
        reserved_labels={"[COMPANY_1]": "Provider"},
    )  # fmt: skip
    assert a.label == "Provider"  # kept from the case
    with pytest.raises(LabelError, match="cannot be changed"):
        review.set_label(a.id, "Seller")
    with pytest.raises(LabelError, match="cannot be changed"):
        review.set_label(a.id, None)
    with pytest.raises(LabelError, match="cannot be changed"):
        review.set_label(b.id, "Customer")  # stored without a name: earlier files wrote it plain
    with pytest.raises(LabelError, match="already used"):
        review.set_label(c.id, "provider")  # a name of the case, for another group
    assert review.set_label(a.id, "PROVIDER") == "Provider"  # the same name is no change
    assert review.set_label(c.id, "Third Party") == "Third Party"


def test_a_stored_name_not_in_this_file_is_still_taken(lists: UserLists) -> None:
    text = "Acme Corp signs."
    c = group(COMPANY, "[COMPANY_3]", "Acme Corp", text)
    review = review_of(
        text, lists, c, reserved=["[COMPANY_1]"], reserved_labels={"[COMPANY_1]": "Provider"}
    )
    with pytest.raises(LabelError, match="already used"):
        review.set_label(c.id, "Provider")


def test_a_stored_name_already_in_brackets_in_the_added_file_is_said_in_the_review(
    lists: UserLists,
) -> None:
    text = "Northwind Trading B.V. met the [Provider] and Acme Corp."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(
        text, lists, a, reserved=["[COMPANY_1]"], reserved_labels={"[COMPANY_1]": "Provider"}
    )
    problems = review.label_problems()  # not first at the export
    assert len(problems) == 1 and "[Provider]" in problems[0]
    assert review.label_problem_pairs()[0][0] == a.id
    clean = review_of(
        "Northwind Trading B.V. signs.", lists,
        group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", "Northwind Trading B.V. signs."),
        reserved=["[COMPANY_1]"], reserved_labels={"[COMPANY_1]": "Provider"},
    )  # fmt: skip
    assert clean.label_problems() == []


# ---- the export ---------------------------------------------------------------------------------


def one_file(make_docx: MakeDocx, text: str = SUPPLY) -> list[SourceDoc]:
    body = f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
    return load_sources([make_docx(body)], False)


def masked_text(path: Path) -> str:
    return extract_text(DocxPackage.open(path)).text


def export(
    sources: list[SourceDoc],
    review: ReviewState,
    tmp_path: Path,
    engine: Engine,
    lists: UserLists,
    **options: object,
):
    return export_case(
        sources, review, ExportOptions(tmp_path, **options), engine, lists, lambda case: None  # type: ignore[arg-type]
    )  # fmt: skip


def named_review(sources: list[SourceDoc], lists: UserLists, **kw: object) -> ReviewState:
    text = combined_text(sources).text
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    b = group(COMPANY, "[COMPANY_2]", "Thamesgate Catering plc", text)
    return review_of(text, lists, a, b, **kw)


def test_export_with_names_round_trips(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx)
    review = named_review(sources, lists)
    review.set_label(review.groups[0].id, "Provider")
    review.set_label(review.groups[1].id, "Customer")
    res = export(sources, review, tmp_path / "out", engine, lists)
    assert not res.blocked and res.case is not None and res.leak_hits == []
    text = masked_text(res.outputs[0])
    assert text.startswith(BANNER_TEXT_NAMED) and res.instruction == AI_INSTRUCTION_NAMED
    assert (
        "[Provider]" in text
        and "[Customer]" in text
        and "[COMPANY_1]" not in text.replace(BANNER_TEXT_NAMED, "")
    )
    assert "Northwind" not in text and "Thamesgate" not in text
    # the bare words of the contract stay, the bracketed names come back as the values
    assert "The Provider shall deliver; the Customer shall pay." in text
    assert [e.label for e in res.case.entries] == ["Provider", "Customer"]
    again = Case.from_json(res.case.to_json())
    out, report = restore_docx(res.outputs[0], again, False, tmp_path / "back")
    back = masked_text(out)
    assert back == (
        "Northwind Trading B.V. supplies goods to Thamesgate Catering plc. "
        "The Provider shall deliver; the Customer shall pay. Northwind Trading B.V. signs."
    )
    assert report.restored == 3 and report.needs_check == []


def test_an_export_without_names_is_unchanged(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx)
    review = named_review(sources, lists)
    res = export(sources, review, tmp_path / "out", engine, lists)
    assert masked_text(res.outputs[0]).startswith(BANNER_TEXT)
    assert res.instruction == AI_INSTRUCTION
    assert "label" not in res.case.to_json()  # type: ignore[union-attr]


def test_the_leak_gate_still_treats_every_value_as_a_secret(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx)
    review = named_review(sources, lists)
    review.set_label(review.groups[0].id, "Provider")
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    font = f'<w:fonts xmlns:w="{ns}"><w:font w:name="Thamesgate Catering plc"/></w:fonts>'
    body = f'<w:p><w:r><w:t xml:space="preserve">{escape(SUPPLY)}</w:t></w:r></w:p>'
    sources = load_sources([make_docx(body, raw={"word/fontTable.xml": font.encode()})], False)
    review = named_review(sources, lists)
    review.set_label(review.groups[0].id, "Provider")
    res = export(sources, review, tmp_path / "out2", engine, lists)
    # the value in a place the masker cannot reach is still found, whatever the names are
    assert res.blocked and res.case is None and res.outputs == []


def test_a_group_switched_off_still_counts_for_the_twin(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx)
    review = named_review(sources, lists)
    review.set_label(review.groups[0].id, "Provider")
    review.set_occurrence_enabled(review.groups[0].id, 1, False)  # one place left visible
    res = export(sources, review, tmp_path / "out", engine, lists)
    assert not res.blocked and res.allowed_hits  # listed, as for an unnamed group


def test_an_invalid_or_clashing_name_in_the_key_stops_the_export(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx)
    for bad in ("COMPANY_2", "Northwind Trading BV", "[x]"):
        review = named_review(sources, lists)
        review.groups[0].label = bad  # set by hand, past the review's checks
        with pytest.raises(ValueError):
            export(sources, review, tmp_path / "bad", engine, lists)
    review = named_review(sources, lists)
    review.groups[0].label = review.groups[1].label = "Same"
    with pytest.raises(ValueError, match="same name"):
        export(sources, review, tmp_path / "bad", engine, lists)
    assert not (tmp_path / "bad").exists()


def test_a_document_that_holds_the_name_in_brackets_stops_the_export(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx, SUPPLY + " Also [Provider].")
    review = named_review(sources, lists)
    review.groups[0].label = "Provider"  # past the review's own check
    with pytest.raises(ValueError, match="already hold"):
        export(sources, review, tmp_path / "o", engine, lists)


def test_the_refusals_of_the_label_check_are_errors_with_a_message_for_the_owner(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    from themask.errors import MaskError

    sources = one_file(make_docx, SUPPLY + " Also [Provider].")
    review = named_review(sources, lists)
    review.groups[0].label = "Provider"
    with pytest.raises(MaskError) as caught:
        export(sources, review, tmp_path / "o", engine, lists)
    assert "square brackets" in caught.value.user_message
    sources = one_file(make_docx)
    review = named_review(sources, lists)
    review.groups[0].label = review.groups[1].label = "Same"
    with pytest.raises(MaskError):
        export(sources, review, tmp_path / "o2", engine, lists)


def test_a_file_added_to_a_case_keeps_the_names(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    first = one_file(make_docx)
    review = named_review(first, lists)
    review.set_label(review.groups[0].id, "Provider")
    case = export(first, review, tmp_path / "o1", engine, lists).case
    assert case is not None
    text2 = "Northwind Trading B.V. also deals with Acme Corp. The Provider is late."
    second = one_file(make_docx, text2)
    t = combined_text(second).text
    stored = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", t)
    new = group(COMPANY, "[COMPANY_3]", "Acme Corp", t)
    review2 = review_of(
        t, lists, stored, new,
        reserved=[e.placeholder for e in case.entries],
        reserved_labels={e.placeholder: e.label for e in case.entries if e.label},
    )  # fmt: skip
    assert stored.label == "Provider"
    with pytest.raises(LabelError):
        review2.set_label(new.id, "Provider")
    review2.set_label(new.id, "Third Party")
    res = export(second, review2, tmp_path / "o2", engine, lists, existing_case=case)
    assert not res.blocked and res.case is not None
    assert {e.placeholder: e.label for e in res.case.entries} == {
        "[COMPANY_1]": "Provider",
        "[COMPANY_2]": None,
        "[COMPANY_3]": "Third Party",
    }
    masked = masked_text(res.outputs[0])
    assert "[Provider] also deals with [Third Party]. The Provider is late." in masked
    out, report = restore_docx(res.outputs[0], res.case, False, tmp_path / "b")
    assert "Northwind Trading B.V. also deals with Acme Corp. The Provider is late." in masked_text(
        out
    )
    # the first file of the case restores with the same case
    out1, _ = restore_docx(res.outputs[0], res.case, True, tmp_path / "b2")
    assert report.needs_check == [] and out1.exists()


# ---- the corpus, with and without names ---------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize(
    "name", ["supply-01.docx", "supply-02.docx", "services-01.docx", "nda-01.docx"]
)
def test_corpus_round_trip_with_names(
    name: str, corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    truth = json.loads((corpus / name.replace(".docx", ".truth.json")).read_text("utf-8"))
    sources, review = reviewed([corpus / name], engine, lists)
    taken = []
    for kind, label in ((COMPANY, "Seller Party"), (PERSON, "Signatory")):
        target = next((g for g in review.groups if g.type is kind and g.enabled), None)
        if target is not None:
            review.set_label(target.id, label)
            taken.append(label)
    assert taken
    res = export(sources, review, tmp_path / "out", engine, lists)
    assert not res.blocked and res.case is not None, res.leak_hits
    masked = masked_text(res.outputs[0])
    for label in taken:
        assert f"[{label}]" in masked
    ai = simulate_ai(res.outputs[0], tmp_path / "ai.docx")
    plan = plan_docx(ai, res.case)
    out, report = restore_docx(ai, res.case, True, expected_sha256=plan.sha256)
    text = masked_text(out)
    for entry in res.case.entries:
        assert entry.value in text, entry.placeholder
    for secret in truth:
        if not (secret.get("only_in_deletion") or secret.get("hidden")):
            assert secret["value"] in text, secret["value"]
    assert report.needs_check == []
    assert not re.search(r"\[(Seller Party|Signatory)\]", text)


# ---- fix round: the review's findings ------------------------------------------------------------

PARTS = (
    "IBM Corp supplies goods to M\u00fcller GmbH and Northwind Trading B.V. Ahmet Y\u0131lmaz"
    " signs; Jane Smith witnesses."
)


def parts_review(lists: UserLists) -> tuple[ReviewState, dict[str, Group]]:
    groups = {
        "ibm": group(COMPANY, "[COMPANY_1]", "IBM Corp", PARTS),
        "mul": group(COMPANY, "[COMPANY_2]", "M\u00fcller GmbH", PARTS),
        "nw": group(COMPANY, "[COMPANY_3]", "Northwind Trading B.V.", PARTS),
        "ahmet": group(PERSON, "[PERSON_1]", "Ahmet Y\u0131lmaz", PARTS),
        "jane": group(PERSON, "[PERSON_2]", "Jane Smith", PARTS),
    }
    return review_of(PARTS, lists, *groups.values()), groups


@pytest.mark.parametrize(
    "name",
    ["IBM Side", "IBM", "Muller Side", "Mueller Side", "M\u00fcller", "Ahmet", "Ahmet Taraf",
     "AHMET", "Y\u0131lmaz", "Yilmaz Co", "Jane", "Trading", "Northwind", "Smith", "GmbH", "Corp"],
)  # fmt: skip
def test_c1_a_name_cannot_carry_part_of_a_hidden_value(lists: UserLists, name: str) -> None:
    review, groups = parts_review(lists)
    for key in ("ibm", "ahmet", "nw"):  # also on a group of another value
        with pytest.raises(LabelError, match="value"):
            review.set_label(groups[key].id, name)
    assert all(g.label is None for g in groups.values())


def test_c1_the_export_refuses_the_same_names_when_set_by_hand(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    sources = one_file(make_docx, PARTS)
    for name in ("IBM Side", "Mueller Side", "Ahmet Taraf", "Trading"):
        text = combined_text(sources).text
        review = review_of(
            text, lists,
            group(COMPANY, "[COMPANY_1]", "IBM Corp", text),
            group(COMPANY, "[COMPANY_2]", "M\u00fcller GmbH", text),
            group(PERSON, "[PERSON_1]", "Ahmet Y\u0131lmaz", text),
            group(COMPANY, "[COMPANY_3]", "Northwind Trading B.V.", text),
        )  # fmt: skip
        review.groups[0].label = name
        with pytest.raises(ValueError, match="value"):
            export(sources, review, tmp_path / "x", engine, lists)
    assert not (tmp_path / "x").exists()


TURKISH = named_case("Kirac\u0131", "\u0130\u015fveren")


@pytest.mark.parametrize(
    "form",
    ["[KIRACI]", "[K\u0130RACI]", "[kirac\u0131]", "[Kiraci]", "[KIRAC\u0130]", "**[Kiraci]**"],
)
def test_i1_turkish_case_forms_are_changed_forms_never_silent(form: str) -> None:
    (item,) = plan_restore(form, TURKISH)
    assert item.status == "altered" and item.entry is TURKISH.entries[0]
    out, report = restore_text(form, TURKISH, False)
    assert out == form and len(report.needs_check) == 1  # asked, not silent
    assert restore_text(form, TURKISH, True)[0] == "Northwind Trading B.V."


@pytest.mark.parametrize(
    "form", ["[i\u015fveren]", "[ISVEREN]", "[\u0130\u015eVEREN]", "[Isveren]"]
)
def test_i1_the_second_turkish_name(form: str) -> None:
    (item,) = plan_restore(form, TURKISH)
    assert item.status == "altered" and item.entry is TURKISH.entries[1]


def test_i1_the_stored_name_itself_is_exact() -> None:
    (item,) = plan_restore("[Kirac\u0131]", TURKISH)
    assert item.status == "exact"


def test_i1_and_i4_look_alike_names_are_one_name(lists: UserLists) -> None:
    review, groups = parts_review(lists)
    review.set_label(groups["ibm"].id, "Provider")
    for twin in ("Provid\u00e9r", "PROVIDER", "Provider\u00ad"):
        with pytest.raises(LabelError):
            review.set_label(groups["mul"].id, twin)
    review.set_label(groups["mul"].id, "Kiracı")
    for twin in ("Kiraci", "KIRACI", "K\u0130RACI"):
        with pytest.raises(LabelError, match="already used"):
            review.set_label(groups["nw"].id, twin)
    review.set_label(groups["nw"].id, "Isveren")
    with pytest.raises(LabelError, match="already used"):
        review.set_label(groups["ahmet"].id, "\u0130sveren")


@pytest.mark.parametrize("name", ["\u0420rovider", "Pr\u043evider", "\u0391lpha"])
def test_i4_mixed_script_names_are_refused(name: str) -> None:
    with pytest.raises(LabelError, match="alphabets"):
        clean_label(name)


def test_i4_a_whole_cyrillic_look_alike_is_the_same_name(lists: UserLists) -> None:
    review, groups = parts_review(lists)
    review.set_label(groups["ibm"].id, "Cope")
    with pytest.raises(LabelError, match="already used"):
        review.set_label(groups["mul"].id, "\u0421\u043e\u0440\u0435")  # Cyrillic C o p e


def test_stored_cases_with_look_alike_names_are_unreadable() -> None:
    data = json.loads(named_case("Kiracı", None).to_json())
    data["entries"][1]["label"] = "KIRACI"
    with pytest.raises(ValueError, match="Not a stored case"):
        Case.from_json(json.dumps(data))


def tracked_para(*parts: str) -> str:
    return "<w:p>" + "".join(parts) + "</w:p>"


def t_run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def ins(text: str) -> str:
    return f'<w:ins w:id="9" w:author="AI" w:date="2026-10-17T09:00:00Z">{t_run(text)}</w:ins>'


def dele(text: str) -> str:
    inner = f'<w:r><w:delText xml:space="preserve">{escape(text)}</w:delText></w:r>'
    return f'<w:del w:id="8" w:author="AI" w:date="2026-10-17T09:00:00Z">{inner}</w:del>'


@pytest.mark.parametrize(
    "paragraph",
    [
        tracked_para(t_run("Pay [Provider"), ins(" Group"), t_run("] now.")),
        tracked_para(t_run("Pay [Provider"), dele("s"), t_run("] now.")),
        tracked_para(t_run("Pay [Provider"), ins("s"), t_run("] now.")),
        tracked_para(t_run("Pay "), dele("[Supplier]"), ins("[Provider]"), t_run(" now.")),
        tracked_para(t_run("Pay "), dele("[Provider]"), ins("[Supplier]"), t_run(" now.")),
        tracked_para(t_run("Pay [Provider]"), ins("(x)"), t_run(" now.")),
    ],
)
def test_i2_a_tracked_change_inside_a_name_waits_for_the_owner(
    make_docx: MakeDocx, tmp_path: Path, paragraph: str
) -> None:
    path = make_docx(paragraph)
    out, report = restore_docx(path, PROVIDER_CUSTOMER, True, tmp_path / "o")
    # the owner confirming changed forms does not release a name a change runs through
    accepted = extract_text(DocxPackage.open(out)).text
    assert "Northwind" not in accepted or "(x)" in accepted
    if "(x)" not in accepted:
        assert report.restored == 0 and len(report.needs_check) == 1
        assert report.needs_check[0].reason == "changed inside a tracked change"


def test_i2_a_plain_name_in_a_tracked_insertion_is_still_restored(
    make_docx: MakeDocx, tmp_path: Path
) -> None:
    path = make_docx(tracked_para(t_run("Pay "), ins("[Provider]"), t_run(" now.")))
    out, report = restore_docx(path, PROVIDER_CUSTOMER, False, tmp_path / "o")
    assert report.restored == 1
    assert "Pay Northwind Trading B.V. now." in extract_text(DocxPackage.open(out)).text


def test_m1_retyping_a_stored_named_group_is_refused(lists: UserLists) -> None:
    text = "Northwind Trading B.V. signs."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(
        text, lists, a, reserved=["[COMPANY_1]"], reserved_labels={"[COMPANY_1]": "Provider"}
    )
    with pytest.raises(LabelError, match="cannot be changed"):
        review.hide_text("Northwind Trading B.V.", PlaceholderType.CUSTOM)
    assert a.type is COMPANY and a.placeholder == "[COMPANY_1]" and a.label == "Provider"


def test_m2_naming_a_value_that_is_not_there_is_refused(lists: UserLists) -> None:
    review, _ = parts_review(lists)
    n = len(review.groups)
    with pytest.raises(LabelError, match="not in this document"):
        review.add_always_hide("Absent Holdings", label="Seller")
    with pytest.raises(LabelError, match="at least two"):
        review.add_always_hide("x", label="Seller")
    assert len(review.groups) == n and "Absent Holdings" not in lists.always_hide
    review.add_always_hide("Absent Holdings")  # without a name it is only added, as before
    assert "Absent Holdings" in lists.always_hide


# ---- fix round 2 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["IBMSide", "AhmetTaraf", "Y\u0131lmazlar", "M\u00fcllerSeite", "MuellerSeite", "NorthwindCo",
     "Northwinds", "Smiths", "JaneS", "TradingCo", "Ibmco", "Ahmets", "XIBMX", "SideIBM"],
)  # fmt: skip
def test_a_a_value_word_inside_a_name_is_refused(lists: UserLists, name: str) -> None:
    review, groups = parts_review(lists)
    for key in ("ibm", "ahmet"):
        with pytest.raises(LabelError, match="value"):
            review.set_label(groups[key].id, name)


def test_a_the_export_refuses_the_same_names_with_a_plain_message(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    from themask.errors import MaskError
    from themask.labels import LabelClashError

    sources = one_file(make_docx, PARTS)
    for name in ("IBMSide", "AhmetTaraf", "MuellerSeite", "Northwinds"):
        text = combined_text(sources).text
        review = review_of(
            text, lists,
            group(COMPANY, "[COMPANY_1]", "IBM Corp", text),
            group(COMPANY, "[COMPANY_2]", "M\u00fcller GmbH", text),
            group(PERSON, "[PERSON_1]", "Ahmet Y\u0131lmaz", text),
            group(COMPANY, "[COMPANY_3]", "Northwind Trading B.V.", text),
        )  # fmt: skip
        review.groups[0].label = name
        with pytest.raises(LabelClashError) as caught:
            export(sources, review, tmp_path / "x", engine, lists)
        assert isinstance(caught.value, MaskError) and isinstance(caught.value, ValueError)
        assert name in caught.value.user_message and "Corp" not in caught.value.user_message


@pytest.mark.parametrize(
    ("name", "values"),
    [("Party 1", ["1 January 2024"]), ("Seller A", ["Demir A.\u015e."]),
     ("The Buyer", ["The Coca-Cola Company"]), ("Seller B", ["Demir A.\u015e.", "B2B GmbH"]),
     ("Party 12", ["12 pm"]), ("Provider", ["Thamesgate Catering plc"])],
)  # fmt: skip
def test_d_ordinary_names_stay_usable(name: str, values: list[str]) -> None:
    from themask.labels import clashes_with_values

    assert not clashes_with_values(name, values)


@pytest.mark.parametrize(
    ("name", "values"),
    [("Party 2024", ["1 January 2024"]), ("Coca", ["The Coca-Cola Company"]),
     ("Cola Side", ["The Coca-Cola Company"]), ("Party 123", ["Flat 123"])],
)  # fmt: skip
def test_d_identifying_words_still_clash(name: str, values: list[str]) -> None:
    from themask.labels import clashes_with_values

    assert clashes_with_values(name, values)


def test_c_umlaut_spellings_are_one_name(lists: UserLists) -> None:
    review, groups = parts_review(lists)
    review.set_label(groups["nw"].id, "Z\u00e4hler")
    for twin in ("Zaehler", "Zahler", "ZAEHLER"):
        with pytest.raises(LabelError, match="already used"):
            review.set_label(groups["jane"].id, twin)


def test_c_a_token_matching_a_name_only_by_umlaut_is_changed_not_exact() -> None:
    case = named_case("M\u00fcller", None)
    for token in ("[Mueller]", "[Muller]", "[M\u00dcLLER]"):
        (item,) = plan_restore(token, case)
        assert item.status == "altered" and item.entry is case.entries[0], token
        assert restore_text(token, case, False)[0] == token  # waits for the owner
    (item,) = plan_restore("[M\u00fcller]", case)
    assert item.status == "exact"


def test_c_stored_names_with_umlaut_twins_are_unreadable() -> None:
    data = json.loads(named_case("M\u00fcller", None).to_json())
    data["entries"][1]["label"] = "Mueller"
    with pytest.raises(ValueError, match="Not a stored case"):
        Case.from_json(json.dumps(data))


def test_e_a_name_inside_another_name_is_refused(lists: UserLists) -> None:
    review, groups = parts_review(lists)
    review.set_label(groups["ibm"].id, "Provider")
    with pytest.raises(LabelError, match="part of"):
        review.set_label(groups["mul"].id, "Provider Group")
    review.set_label(groups["mul"].id, "Data Customer")
    with pytest.raises(LabelError, match="part of"):
        review.set_label(groups["nw"].id, "Customer")


def test_f_a_failed_name_leaves_the_review_as_it_was(lists: UserLists) -> None:
    text = SUPPLY + " Project Falcon starts."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(text, lists, a)
    # a name that clashes with a value being hidden
    before = ([g.id for g in review.groups], [list(g.findings) for g in review.groups])
    for bad in ("Falcon", "ProjectFalcon", "Northwind Side"):
        with pytest.raises(LabelError):
            review.hide_text("Project Falcon", PlaceholderType.CUSTOM, label=bad)
        with pytest.raises(LabelError):
            review.add_always_hide("Project Falcon", label=bad)
    assert ([g.id for g in review.groups], [list(g.findings) for g in review.groups]) == before
    assert "Project Falcon" not in lists.always_hide


def test_f_a_failure_after_the_hide_is_rolled_back(
    lists: UserLists, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = SUPPLY + " Project Falcon starts."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    review = review_of(text, lists, a)

    def refuse(self: ReviewState, group_id: str, label: str | None) -> str | None:
        raise LabelError("late failure")

    monkeypatch.setattr(ReviewState, "set_label", refuse)
    with pytest.raises(LabelError, match="late"):
        review.hide_text("Project Falcon", PlaceholderType.CUSTOM, label="Codename")
    assert [g.canonical for g in review.groups] == ["Northwind Trading B.V."]


def test_b_ii_hiding_a_value_that_holds_an_existing_name_is_refused(lists: UserLists) -> None:
    text = "IBM Corp and Provider Side Ltd sign."
    a = group(COMPANY, "[COMPANY_1]", "IBM Corp", text)
    review = review_of(text, lists, a)
    review.set_label(a.id, "Side")
    with pytest.raises(LabelError, match="the name Side"):
        review.hide_text("Provider Side Ltd", COMPANY)
    with pytest.raises(LabelError, match="the name Side"):
        review.add_always_hide("Provider Side Ltd")
    assert len(review.groups) == 1 and "Provider Side Ltd" not in lists.always_hide
    a.label = None
    review.hide_text("Provider Side Ltd", COMPANY)  # fine once the name is gone


def test_b_i_a_stored_name_clashing_with_a_new_value_has_a_way_out(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    from themask.errors import MaskError

    stored = named_case("Provider", None)
    text2 = "Northwind Trading B.V. buys from Provider Holdings Ltd."
    sources = one_file(make_docx, text2)
    t = combined_text(sources).text
    old = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", t)
    new = group(COMPANY, "[COMPANY_3]", "Provider Holdings Ltd", t)
    review = review_of(
        t, lists, old, new,
        reserved=[e.placeholder for e in stored.entries],
        reserved_labels={"[COMPANY_1]": "Provider"},
    )  # fmt: skip
    (problem,) = review.label_problems()
    assert "[COMPANY_3]" in problem and "cannot change" in problem and "Switch off" in problem
    assert "Holdings" not in problem  # names and placeholders only, never a value
    with pytest.raises(MaskError, match="Switch off"):
        export(sources, review, tmp_path / "o", engine, lists, existing_case=stored)
    review.set_group_enabled(new.id, False)  # the way out
    assert review.label_problems() == []
    res = export(sources, review, tmp_path / "o2", engine, lists, existing_case=stored)
    assert not res.blocked and res.case is not None


def test_b_the_export_worker_shows_the_plain_message(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    from themask.ui.export_dialog import UNEXPECTED_MESSAGE, ExportWorker

    sources = one_file(make_docx, PARTS)
    text = combined_text(sources).text
    review = review_of(text, lists, group(COMPANY, "[COMPANY_1]", "IBM Corp", text))
    review.groups[0].label = "IBMSide"
    worker = ExportWorker(
        sources, review, ExportOptions(tmp_path / "w"), engine, lists, lambda c: None
    )
    failures: list[str] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert len(failures) == 1 and failures[0] != UNEXPECTED_MESSAGE and "IBMSide" in failures[0]


def test_g_lookalike_letters_fold_to_latin() -> None:
    from themask.labels import label_key

    assert label_key("\u0432") == label_key("b") and label_key("\u03b2") == "b"
    assert label_key("\u03b7\u03bc") == "nu"


# ---- fix round 3 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [("BPSide", "BP plc"), ("HPTeam", "HP Inc"), ("3MCo", "3M Company"), ("SideBP", "BP plc"),
     ("SideBPTeam", "BP plc"), ("Tel12345678", "+49 30 12345678"),
     ("Acct 37040044", "DE89 3704 0044 0532 0130 00"), ("VAT123456789", "NL123456789B01"),
     ("Fee1250000", "EUR 1250000"), ("Side 1250000", "EUR 1,250,000")],
)  # fmt: skip
def test_n1_short_values_and_digit_runs_cannot_ride_in_a_name(name: str, value: str) -> None:
    from themask.labels import clashes_with_values

    assert clashes_with_values(name, [value])


@pytest.mark.parametrize(
    ("name", "value"),
    [("Party 12", "12 pm"), ("Party 1", "1 January 2024"), ("Seller B", "B2B GmbH"),
     ("Provider", "Thamesgate Catering plc"), ("Fee 125", "EUR 1250000")],
)  # fmt: skip
def test_n1_ordinary_names_stay_usable(name: str, value: str) -> None:
    from themask.labels import clashes_with_values

    assert not clashes_with_values(name, [value])


def test_n1_the_review_and_the_export_refuse_them(
    make_docx: MakeDocx, tmp_path: Path, engine: Engine, lists: UserLists
) -> None:
    from themask.labels import LabelClashError

    text = "BP plc owes EUR 1,250,000 to HP Inc."
    a = group(COMPANY, "[COMPANY_1]", "BP plc", text)
    b = group(PlaceholderType.AMOUNT, "[AMOUNT_1]", "EUR 1,250,000", text)
    review = review_of(text, lists, a, b)
    for name in ("BPSide", "Side 1250000"):
        with pytest.raises(LabelError):
            review.set_label(a.id, name)
    sources = one_file(make_docx, text)
    for name in ("BPSide", "Fee1250000"):
        review = review_of(
            combined_text(sources).text, lists,
            group(COMPANY, "[COMPANY_1]", "BP plc", text),
            group(PlaceholderType.AMOUNT, "[AMOUNT_1]", "EUR 1,250,000", text),
        )  # fmt: skip
        review.groups[0].label = name
        with pytest.raises(LabelClashError):
            export(sources, review, tmp_path / "x", engine, lists)


def test_m1_merging_into_a_name_that_clashes_is_refused(lists: UserLists) -> None:
    text = "Northwind Trading B.V. and Provider Holdings Ltd and Provider."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    b = group(COMPANY, "[COMPANY_2]", "Provider Holdings Ltd", text)
    review = review_of(
        text, lists, a, b, reserved=["[COMPANY_1]"], reserved_labels={"[COMPANY_1]": "Provider"}
    )
    with pytest.raises(ValueError, match="merging"):
        review.merge([a.id, b.id])
    assert [g.placeholder for g in review.groups] == ["[COMPANY_1]", "[COMPANY_2]"]
    assert a.label == "Provider" and b.canonical == "Provider Holdings Ltd"


def test_m2_a_failure_after_a_retype_puts_the_group_back(
    lists: UserLists, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "Northwind Trading B.V. signs; Northwind again."
    a = group(COMPANY, "[COMPANY_1]", "Northwind Trading B.V.", text)
    a.variants.add("Northwind")
    review = review_of(text, lists, a)
    state = (a.type, a.placeholder, a.canonical, set(a.variants), list(a.findings), a.enabled)

    def refuse(self: ReviewState, group_id: str, label: str | None) -> str | None:
        raise LabelError("late failure")

    monkeypatch.setattr(ReviewState, "set_label", refuse)
    with pytest.raises(LabelError, match="late"):
        review.hide_text("Northwind Trading B.V.", PlaceholderType.CUSTOM, label="Codename")
    assert review.groups == [a]
    assert (
        a.type,
        a.placeholder,
        a.canonical,
        set(a.variants),
        list(a.findings),
        a.enabled,
    ) == state
    assert {f.type for f in a.findings} == {COMPANY}
