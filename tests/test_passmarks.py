"""The spec's pass marks (section 9), measured on the made-up corpus with ``tools/evaluate.py``.

The two slow tests run the whole detection over every corpus file, the way the app does before the
owner's review. The others check how the evaluation counts, on texts made up here.
"""

import json
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


# The secrets of the corpus that no analysed text holds: six only in tracked-deleted or hidden
# text, and the IBAN on the picture page of mixed-01.pdf. Any other secret left out would shrink
# the pass marks' own count (ruling R95).
LEFT_OUT = {
    ("supply-03.docx", "AMOUNT", "EUR 224,000.00"),
    ("services-02.docx", "AMOUNT", "\N{EURO SIGN}769,000.00"),
    ("nda-02.docx", "PERSON", "Neil Cartwright"),
    ("nda-05.docx", "PERSON", "Damian Sullivan"),
    ("dpa-03.docx", "EMAIL", "privacy@havenlicht.example"),
    ("dpa-03.docx", "PHONE", "+353 1 471 4299"),
    ("mixed-01.pdf", "IBAN", "IE96 BOFI 9000 1735 4448 87"),
}


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
    # Every file but the scanned one is analysed, and only the secrets no text holds are left out.
    assert [d.file for d in ev.documents if d.skipped] == ["scanned-01.pdf"]
    assert len([d for d in ev.documents if not d.skipped]) == 35
    left_out = {(d.file, s.type.value, s.value) for d in ev.documents for s in d.not_in_text}
    assert left_out == LEFT_OUT


@pytest.mark.slow
@pytest.mark.parametrize("name", ["supply-10.docx", "supply-10.pdf"])
def test_thirty_pages_under_sixty_seconds(corpus, engine, lists, name):
    t0 = time.perf_counter()
    srcs = load_sources([corpus / name], False)
    analyze(combined_text(srcs), engine, lists)
    assert time.perf_counter() - t0 < 60


@pytest.mark.slow
def test_full_round_trip_every_docx(corpus, engine, lists, tmp_path):
    """Mask every Word file of the corpus, change it as an AI tool might, and restore it.

    Every value of the key comes back (the one placeholder the AI changed once the owner
    confirms it), the AI's invented [PERSON_9] stays as it is and nothing else is left; every
    secret of the truth is in the restored text, so no value came back in another's place. A
    file that held placeholders of its own keeps them as they are.
    """
    from tests.helpers import simulate_ai
    from themask.docx.package import DocxPackage
    from themask.docx.reader import extract_text
    from themask.export import ExportOptions, export_case
    from themask.placeholders import find_placeholders
    from themask.restore.docx_restore import plan_docx, restore_docx
    from themask.review import ReviewState

    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    for doc in (d for d in manifest if d["format"] == "docx"):
        name = doc["file"]
        sources = load_sources([corpus / name], False)
        case_lists = CaseLists([], [], set())
        review = ReviewState.from_analysis(
            analyze(combined_text(sources), engine, lists, case_lists), lists, case_lists
        )
        options = ExportOptions(tmp_path / name)
        res = export_case(sources, review, options, engine, lists, lambda case: None)
        assert not res.blocked and res.case is not None, (name, res.leak_hits)
        ai = simulate_ai(res.outputs[0], tmp_path / f"ai-{name}")
        plan = plan_docx(ai, res.case)
        out, rep = restore_docx(ai, res.case, True, expected_sha256=plan.sha256)
        text = extract_text(DocxPackage.open(out)).text
        altered = [item for item in plan.items if item.status == "altered"]
        print(
            f"{name}: key {len(res.case.entries)}, planned {len(plan.items)}, restored"
            f" {rep.restored} ({rep.altered_restored} changed), unknown {rep.unknown}"
        )
        for entry in res.case.entries:
            assert entry.value in text, (name, entry.placeholder)
        truth = json.loads((corpus / doc["truth"]).read_text(encoding="utf-8"))
        for secret in truth:
            if not (secret.get("only_in_deletion") or secret.get("hidden")):
                assert secret["value"] in text, (name, secret["value"])
        assert rep.needs_check == [] and rep.altered_restored == len(altered)
        if "existing_placeholders" not in doc["features"]:
            # The AI changed the first [PERSON_1], when the key has one (an annex may name no
            # person): caught, confirmed and restored.
            person_1 = any(entry.placeholder == "[PERSON_1]" for entry in res.case.entries)
            assert [item.match.raw for item in altered] == (["[PERSON 1]"] if person_1 else [])
            assert {m.placeholder for m in find_placeholders(text)} == {"[PERSON_9]"}
            assert rep.unknown == ["[PERSON_9]"]
        else:
            # The first [PERSON_1] is the file's own, which the key does not hold: left as written.
            assert "[PERSON_9]" in rep.unknown and "[PERSON 1]" in text


# --- How the evaluation counts -------------------------------------------------------------------


def _group(kind, placeholder, text, *spans):
    findings = [Finding(kind, s, e, text[s:e], 0.9, "pattern") for s, e in spans]
    return Group(placeholder, kind, text[spans[0][0] : spans[0][1]], set(), findings, placeholder)


def _scored(text, groups, truth, user_lists=None, defined=(), image_pages=()):
    plan = MaskPlan(
        [Replacement(f.start, f.end, g.placeholder) for g in groups for f in g.active_findings()]
    )
    case = CaseLists([], [], set(defined))
    names = [form for secret in truth for form in secret.forms]
    is_term = never_hide_check(user_lists or UserLists([], []), case, names=names)
    document = DocumentResult("x.docx", "docx", (), image_pages=tuple(image_pages))
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


def test_a_secret_only_in_deleted_or_hidden_text_is_not_counted():
    text = "Nothing here."
    truth = [
        Secret(EMAIL, "a@b.example", hidden=True),
        Secret(PERSON, "Jane Doe", only_in_deletion=True),
    ]
    document = _scored(text, [], truth)
    assert document.items == [] and [s.value for s in document.not_in_text] == [
        "a@b.example",
        "Jane Doe",
    ]


def test_a_secret_missing_from_the_text_is_a_miss_unless_a_page_is_a_picture():
    # Ruling R95 (I5): a secret the text lost is no reason to count it out.
    text = "Nothing here."
    truth = [Secret(EMAIL, "a@b.example")]
    (item,) = _scored(text, [], truth).items
    assert (item.found, item.places) == (False, 0)
    on_a_picture = _scored(text, [], truth, image_pages=[2])
    assert on_a_picture.items == [] and [s.value for s in on_a_picture.not_in_text] == [
        "a@b.example"
    ]


def test_no_secret_counted_is_no_pass():
    ev = Evaluation.of([DocumentResult("x.docx", "docx", ())])
    assert (ev.recall_pattern, ev.recall_names, ev.passed) == (0.0, 0.0, False)


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
