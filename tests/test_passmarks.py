"""The spec's pass marks (section 9), measured on the made-up corpus with ``tools/evaluate.py``.

The two slow tests run the whole detection over every corpus file, the way the app does before the
owner's review. The others check how the evaluation counts, on texts made up here.
"""

import time

import pytest

from themask.detect.lists import CaseLists, UserLists, never_hide_check
from themask.detect.pipeline import analyze
from themask.export import combined_text, load_sources
from themask.model import Finding, Group, MaskPlan, PlaceholderType, Replacement
from tools.evaluate import DocumentResult, Evaluation, Secret, places, score

PERSON = PlaceholderType.PERSON
COMPANY = PlaceholderType.COMPANY
AMOUNT = PlaceholderType.AMOUNT
EMAIL = PlaceholderType.EMAIL


@pytest.mark.slow
def test_pass_marks(corpus, engine, lists):
    from tools.evaluate import evaluate

    ev = evaluate(corpus, engine, lists)
    print(ev.misses)
    print(ev.never_hide_false_positives)
    for name in ("docx", "pdf"):
        part = ev.of_format(name)
        print(name, part.recall_pattern, part.recall_names, part.seconds_thirty_pages)
    assert ev.recall_pattern >= 0.99 and ev.recall_names >= 0.95
    assert ev.never_hide_false_positives == []


@pytest.mark.slow
@pytest.mark.parametrize("name", ["supply-10.docx", "supply-10.pdf"])
def test_thirty_pages_under_sixty_seconds(corpus, engine, lists, name):
    t0 = time.perf_counter()
    srcs = load_sources([corpus / name], False)
    analyze(combined_text(srcs), engine, lists)
    assert time.perf_counter() - t0 < 60


# --- How the evaluation counts -------------------------------------------------------------------


def _group(kind, placeholder, text, *spans):
    findings = [Finding(kind, s, e, text[s:e], 0.9, "pattern") for s, e in spans]
    return Group(placeholder, kind, text[spans[0][0] : spans[0][1]], set(), findings, placeholder)


def _scored(text, groups, truth, user_lists=None, defined=()):
    plan = MaskPlan(
        [Replacement(f.start, f.end, g.placeholder) for g in groups for f in g.active_findings()]
    )
    case = CaseLists([], [], set(defined))
    names = [form for secret in truth for form in secret.forms]
    is_term = never_hide_check(user_lists or UserLists([], []), case, names=names)
    document = DocumentResult("x.docx", "docx", ())
    score(document, text, groups, plan, truth, is_term)
    return document


def _span(text, part, nth=0):
    start = -1
    for _ in range(nth + 1):
        start = text.index(part, start + 1)
    return start, start + len(part)


def test_a_place_is_found_as_written_whatever_its_spaces():
    text = "Acme  Supplies\nLtd and acme supplies ltd and Acme SuppliesLtd"
    assert places(text, "Acme Supplies Ltd") == [(0, 18)]


def test_a_secret_is_found_when_every_place_of_it_is_hidden():
    text = "Acme Supplies Ltd (Acme) pays. Acme signs."
    whole, short, again = (
        _span(text, "Acme Supplies Ltd"),
        _span(text, "Acme", 1),
        _span(text, "Acme", 2),
    )
    truth = [Secret(COMPANY, "Acme Supplies Ltd", ("Acme",))]
    hidden = _scored(text, [_group(COMPANY, "[COMPANY_1]", text, whole, short, again)], truth)
    missed_one = _scored(text, [_group(COMPANY, "[COMPANY_1]", text, whole, short)], truth)
    assert [(i.found, i.places) for i in hidden.items] == [(True, 3)]
    assert [(i.found, i.places) for i in missed_one.items] == [(False, 3)]


def test_a_place_hidden_in_two_pieces_is_not_found():
    text = "Pay EUR 1,250,000.00 now."
    truth = [Secret(AMOUNT, "EUR 1,250,000.00")]
    groups = [
        _group(AMOUNT, "[AMOUNT_1]", text, _span(text, "EUR 1,250")),
        _group(AMOUNT, "[AMOUNT_2]", text, _span(text, "000.00")),
    ]
    (item,) = _scored(text, groups, truth).items
    assert not item.found


def test_a_secret_hidden_as_another_type_is_found_and_typed_wrong():
    text = "Acme signs."
    truth = [Secret(COMPANY, "Acme")]
    (item,) = _scored(text, [_group(PERSON, "[PERSON_1]", text, _span(text, "Acme"))], truth).items
    assert (item.found, item.typed_right, item.placeholders) == (True, False, ("[PERSON_1]",))


def test_a_secret_not_in_the_text_is_not_counted():
    text = "Nothing here."
    truth = [Secret(EMAIL, "a@b.example"), Secret(PERSON, "Jane Doe", only_in_deletion=True)]
    document = _scored(text, [], truth)
    assert document.items == [] and [s.value for s in document.not_in_text] == [
        "a@b.example",
        "Jane Doe",
    ]


def test_a_group_that_hides_no_secret_is_listed():
    text = "Acme Ltd signs the Supply Agreement in Kraft paper."
    truth = [Secret(COMPANY, "Acme Ltd")]
    groups = [
        _group(COMPANY, "[COMPANY_1]", text, _span(text, "Acme Ltd signs")),
        _group(COMPANY, "[COMPANY_2]", text, _span(text, "Kraft")),
    ]
    document = _scored(text, groups, truth)
    assert [i.found for i in document.items] == [True]  # inside a longer group: found
    assert [(g.canonical, g.overlaps_secret) for g in document.false_positives] == [
        ("Acme Ltd signs", True),
        ("Kraft", False),
    ]


def test_a_hidden_never_hide_term_is_listed_but_a_name_that_is_a_defined_term_is_not():
    text = 'Northwind ("Northwind") is the Supplier. Northwind delivers.'
    truth = [Secret(COMPANY, "Northwind")]
    groups = [
        _group(COMPANY, "[COMPANY_1]", text, _span(text, "Northwind"), _span(text, "Northwind", 2)),
        _group(COMPANY, "[COMPANY_2]", text, _span(text, "Supplier")),
    ]
    document = _scored(text, groups, truth, defined=["Northwind", "Supplier"])
    assert document.never_hide == ["COMPANY 'Supplier'"]


def test_the_pass_marks_are_shares_of_the_secrets_of_each_class():
    text = "Acme Ltd, EUR 5,000.00 and EUR 7,000.00."
    truth = [
        Secret(COMPANY, "Acme Ltd"),
        Secret(AMOUNT, "EUR 5,000.00"),
        Secret(AMOUNT, "EUR 7,000.00"),
    ]
    groups = [
        _group(COMPANY, "[COMPANY_1]", text, _span(text, "Acme Ltd")),
        _group(AMOUNT, "[AMOUNT_1]", text, _span(text, "EUR 5,000.00")),
    ]
    ev = Evaluation.of([_scored(text, groups, truth)])
    assert (ev.recall_pattern, ev.recall_names, ev.type_accuracy) == (0.5, 1.0, 1.0)
    assert ev.misses == [("x.docx", "AMOUNT", "EUR 7,000.00")]
