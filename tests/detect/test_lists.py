"""The owner's lists: what is hidden in every document, what never is, and how a term is matched."""

import json
import os

import pytest

from themask.detect.lists import (
    DEFAULT_NEVER_HIDE,
    CaseLists,
    UserLists,
    always_hide_entry,
    is_never_hide,
    never_hide_check,
)
from themask.errors import MaskError
from themask.model import PlaceholderType
from themask.paths import lists_path

CUSTOM = PlaceholderType.CUSTOM
COMPANY = PlaceholderType.COMPANY
NO_LISTS = UserLists([], [])
NO_CASE = CaseLists([], [], set())


# --- The terms that are never hidden ---------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        # roles, the document's own words and legal vocabulary
        "Supplier",
        "Buyer",
        "Party",
        "Agreement",
        "Goods",
        "Force Majeure",
        "Confidential Information",
        # months, weekdays, currencies, countries
        "March",
        "Monday",
        "Euro",
        "Pound Sterling",
        "EUR",
        "Netherlands",
        "Germany",
        "England and Wales",
        "European Union",
        # the single words the language model takes for a company or a person in a contract
        *("VAT", "IBAN", "BIC", "SWIFT", "GBP", "USD", "Schedule", "Appendix", "Annex"),
        *("Exhibit", "Clause", "Section", "Article", "Recital", "City", "Country", "Date"),
        *("Signature", "Title", "Name", "Attention", "Confidential", "Draft", "Page", "Total"),
        *("Subtotal", "Amount", "Price", "Site"),
    ],
)
def test_default_never_hide_holds(term):
    assert term in DEFAULT_NEVER_HIDE
    assert is_never_hide(term, NO_LISTS, NO_CASE)


@pytest.mark.parametrize(
    "text",
    [
        "the Supplier",
        "THE SUPPLIER",
        "supplier",
        "Suppliers",
        "the Parties",
        "Parties",
        "the Buyer's",
        "the Suppliers'",
        "Business Days",
        "the Netherlands",
        "Sub-processors",
        "\N{LEFT DOUBLE QUOTATION MARK}Buyer\N{RIGHT DOUBLE QUOTATION MARK}",
        # a document word with its reference, as headings and cross-references write them
        "SCHEDULE 1",
        "Clause 4.2",
        "APPENDIX 1A",
        "Annex II",
        "Exhibit A",
        "Article 28(3)",
        "1.2 Clause",
        # dates in words stay visible, however the model took them
        "June 2026",
        "25 June 2026",
        "June 25, 2026",
        "Monday, 1 June 2026",
        # public bodies a contract cites, and words the model takes for a company
        "the European Commission",
        "the Bank of England",
        "Time",
        "SUB",
        "Operations",
    ],
)
def test_never_hide_in_every_spelling(text):
    assert is_never_hide(text, NO_LISTS, NO_CASE)


@pytest.mark.parametrize(
    "text",
    [
        "Supplier Logistics Ltd",  # longer than the term: a name that holds it
        "Total Logistics Ltd",
        "Price Waterhouse",
        "Schedule 1 Ltd",
        "Northwind",
        "John Smith",
        "Project Falcon",
        "EUR 1,250,000",
        "April Jones",  # a month that is a first name
        "June Smith 2026",
        "Bank of Northwind",
        "",
        "  ",
    ],
)
def test_names_and_values_are_not_terms(text):
    assert not is_never_hide(text, NO_LISTS, NO_CASE)


def test_owners_and_cases_never_hide_lists():
    user = UserLists([], ["Falcon"])
    case = CaseLists([], ["the Depot"], set())
    assert is_never_hide("FALCON", user, case)
    assert is_never_hide("Depots", user, case)
    assert not is_never_hide("Falcon", NO_LISTS, NO_CASE)


def test_defined_terms_are_never_hidden():
    case = CaseLists([], [], {"Delivery Point"})
    assert is_never_hide("the Delivery Point", NO_LISTS, case)
    assert is_never_hide("Delivery Points", NO_LISTS, case)


def test_names_beat_defined_terms():
    # '"Acme" means Acme Supplies Ltd' makes "Acme" a defined term, but it is a name.
    case = CaseLists([], [], {"Acme", "Delivery Point"})
    check = never_hide_check(NO_LISTS, case, names=["Acme Supplies Ltd", "Acme"])
    assert not check("Acme") and not check("ACME")
    assert check("Delivery Point")
    assert is_never_hide("Acme", NO_LISTS, case)  # without the names, the term holds


def test_names_never_beat_the_owners_list_or_the_defaults():
    owner_says = never_hide_check(UserLists([], ["Acme"]), NO_CASE, names=["Acme"])
    case_says = never_hide_check(NO_LISTS, CaseLists([], ["Acme"], set()), names=["Acme"])
    defaults = never_hide_check(NO_LISTS, NO_CASE, names=["Total Logistics Ltd", "Total"])
    assert owner_says("Acme") and case_says("Acme") and defaults("Total")


# --- Always-hide entries -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("Project Falcon", (CUSTOM, "Project Falcon")),
        ("  Falcon  ", (CUSTOM, "Falcon")),
        ("COMPANY:Falcon Freight", (COMPANY, "Falcon Freight")),
        ("company : Falcon Freight ", (COMPANY, "Falcon Freight")),
        ("PERSON:Jane Doe", (PlaceholderType.PERSON, "Jane Doe")),
        ("Note: keep this", (CUSTOM, "Note: keep this")),  # "Note" is no placeholder type
        ("ID: ", (PlaceholderType.ID, "")),  # a type with nothing to hide
    ],
)
def test_always_hide_entry(entry, expected):
    assert always_hide_entry(entry) == expected


# --- The owner's lists on disk -------------------------------------------------------------------


def test_load_without_a_file_gives_empty_lists(tmp_path):
    assert UserLists.load(tmp_path / "lists.json") == UserLists([], [])


def test_save_and_load(tmp_path):
    path = tmp_path / "new folder" / "lists.json"
    lists = UserLists(["Project Falcon", "COMPANY:Gıda Sanayi A.Ş."], ["Bunzl"])
    lists.save(path)
    assert UserLists.load(path) == lists
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "always_hide": ["Project Falcon", "COMPANY:Gıda Sanayi A.Ş."],
        "never_hide": ["Bunzl"],
    }


def test_save_writes_a_temporary_file_and_replaces(tmp_path, monkeypatch):
    folder = tmp_path / "lists"
    path = folder / "lists.json"
    UserLists(["old"], []).save(path)
    replaced = []
    real_replace = os.replace

    def spy(source, target):
        replaced.append((os.path.dirname(source), os.fspath(target)))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", spy)
    UserLists(["new"], []).save(path)
    assert replaced == [(str(folder), str(path))]
    assert UserLists.load(path).always_hide == ["new"]
    assert sorted(p.name for p in folder.iterdir()) == ["lists.json"]  # no temporary file left


def test_a_failed_save_keeps_the_old_file(tmp_path, monkeypatch):
    folder = tmp_path / "lists"
    path = folder / "lists.json"
    UserLists(["old"], []).save(path)

    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        UserLists(["new"], []).save(path)
    assert UserLists.load(path).always_hide == ["old"]
    assert sorted(p.name for p in folder.iterdir()) == ["lists.json"]


def test_saved_lists_are_private(tmp_path):
    path = tmp_path / "lists.json"
    UserLists(["Project Falcon"], []).save(path)
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"always_hide": "Project Falcon", "never_hide": []}',
        '{"always_hide": [1, 2], "never_hide": []}',
    ],
)
def test_load_refuses_a_damaged_file(tmp_path, content):
    path = tmp_path / "lists.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(MaskError) as raised:
        UserLists.load(path)
    assert "lists" in raised.value.user_message


def test_load_refuses_a_file_that_is_not_utf8(tmp_path):
    # Raised minor M4
    path = tmp_path / "lists.json"
    path.write_bytes(b'{"always_hide": ["Caf\xe9"], "never_hide": []}')
    with pytest.raises(MaskError):
        UserLists.load(path)


def test_load_reads_a_file_with_one_list_missing(tmp_path):
    path = tmp_path / "lists.json"
    path.write_text('{"never_hide": ["Bunzl"]}', encoding="utf-8")
    assert UserLists.load(path) == UserLists([], ["Bunzl"])


def test_lists_fixture_is_saved_in_the_data_dir(lists, data_dir):
    assert lists == UserLists([], [])
    assert lists_path() == data_dir / "lists.json"
    assert UserLists.load(lists_path()) == lists


# --- Adding and removing -------------------------------------------------------------------------


def test_add_and_remove():
    lists = UserLists([], [])
    lists.add_always(" Project Falcon ")
    lists.add_never("Bunzl")
    assert lists == UserLists(["Project Falcon"], ["Bunzl"])
    lists.remove_always("project falcon")
    lists.remove_never("BUNZL")
    assert lists == UserLists([], [])
    lists.remove_never("not there")  # removing what is not there is no error


def test_add_keeps_one_entry_per_value():
    lists = UserLists([], [])
    lists.add_always("Project Falcon")
    lists.add_always("PROJECT FALCON")
    lists.add_always("COMPANY:Project Falcon")  # another type is another entry
    lists.add_never("the Depot")
    lists.add_never("Depot")
    assert lists == UserLists(["Project Falcon", "COMPANY:Project Falcon"], ["the Depot"])


def test_a_value_is_on_one_list_at_a_time():
    lists = UserLists([], ["Falcon"])
    lists.add_always("Falcon")
    assert lists == UserLists(["Falcon"], [])
    lists.add_never("falcon")
    assert lists == UserLists([], ["falcon"])
    lists.add_always("COMPANY:Falcon")
    assert lists == UserLists(["COMPANY:Falcon"], [])


@pytest.mark.parametrize("value", ["", "   ", "COMPANY: "])
def test_a_blank_value_cannot_be_added(value):
    lists = UserLists([], [])
    with pytest.raises(ValueError):
        lists.add_always(value)
    with pytest.raises(ValueError):
        lists.add_never(value.replace("COMPANY:", ""))
