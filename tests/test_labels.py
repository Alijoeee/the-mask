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
    ["[Provider", "Provider]", "Provider", "[Providers]", "[the Provider]", "[Provider, Customer]",
     "[Prov ider]", "(Provider)", "{Provider}", "[Provider](#x)y"],
)  # fmt: skip
def test_forms_that_are_not_the_name_are_left(text: str) -> None:
    items = plan_restore(text, PROVIDER_CUSTOMER)
    if text == "[Provider](#x)y":  # a markdown link: the bracketed name is found, as changed or not
        assert [i.status for i in items] == ["exact"]
        return
    assert items == []
    assert restore_text(text, PROVIDER_CUSTOMER, True)[0] == text


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
