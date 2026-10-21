"""Restoring a masked file gives back the original text: no word of a place is lost.

A restore writes the key's value (the group's canonical form) in every place of a placeholder, so
a place may differ from the original only where it was a short form of the value (fewer words, all
of them in the value: "Acme" for "Acme Supplies Ltd") or another listed spelling of it. This
module defines that normalisation once (``same_but_for_short_forms``) and checks real Word
export-and-restore round trips with it, on the sentences the training round found.
"""

import difflib
import re
from pathlib import Path

import pytest

from themask.detect.lists import CaseLists
from themask.detect.pipeline import analyze
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.export import ExportOptions, combined_text, export_case, load_sources
from themask.restore.docx_restore import plan_docx, restore_docx
from themask.review import ReviewState

_WORD = re.compile(r"[^\W_]+")


def words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text)]


def _is_allowed(before: list[str], after: list[str]) -> bool:
    """One difference between the original's words and the restored words that is cosmetic:

    * the original words are all in the restored ones (a short form restored as the fuller value);
    * an initial restored as the first name that starts with it ("F." for "Frederick");
    * a telephone number written nationally restored as the value in its international form
      ("030 360 7352" for "+31 30 360 7352");
    * a note the owner hid in the original ("Internal note: ..."), which the masked file does not
      carry.
    """
    if set(before) <= set(after):
        return True
    if len(before) == 1 and len(before[0]) == 1 and any(w.startswith(before[0]) for w in after):
        return True
    digits = "".join(before).lstrip("0")
    if before and all(w.isdigit() for w in before + after) and digits in "".join(after):
        return True
    return before[:2] == ["internal", "note"] and not after


def same_but_for_short_forms(original: str, restored: str) -> list[str]:
    """The differences between ``original`` and ``restored`` that are not cosmetic (see
    ``_is_allowed``); [] when the two are the same words but for those."""
    a, b = words(original), words(restored)
    bad = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal" and not _is_allowed(a[i1:i2], b[j1:j2]):
            bad.append(f"{tag}: {a[i1:i2]} -> {b[j1:j2]}")
    return bad


def paragraphs(*texts: str) -> str:
    return "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{t.replace("&", "&amp;")}</w:t></w:r></w:p>'
        for t in texts
    )


def round_trip(path: Path, engine, lists, tmp_path: Path) -> tuple[str, str]:
    sources = load_sources([path], False)
    case_lists = CaseLists([], [], set())
    review = ReviewState.from_analysis(
        analyze(combined_text(sources), engine, lists, case_lists), lists, case_lists
    )
    res = export_case(
        sources, review, ExportOptions(tmp_path / "masked"), engine, lists, lambda case: None
    )
    assert not res.blocked and res.case is not None, res.leak_hits
    masked = res.outputs[0]
    plan = plan_docx(masked, res.case)
    out, _ = restore_docx(masked, res.case, True, expected_sha256=plan.sha256)
    return (
        extract_text(DocxPackage.open(path)).text,
        extract_text(DocxPackage.open(out)).text,
    )


SENTENCES = [
    "Northwind's Genel Müdürü Gülşen Öztürk'ın imzası ile Yıldız Enerji A.Ş. bağlanır.",
    "ZETA's Genel Müdürü Klaus von Heidenstein'da imzası ile Müller Anlagenbau GmbH bağlanır.",
    "Yıldız Enerji A.Ş. Yönetim Kurulu Üyesi Ayşe Demir tarafından temsil edilir.",
    "Kestrel's Hukuk Müşaviri Omar ibn Rashid'da imzası ile Demirtaş İnşaat Ltd.Şti. bağlanır.",
    "Hukuk Müşaviri Liam O'Brien'ın imzası ile Anatolia Bilişim Limited Şirketi bağlanır.",
    "Genel Müdürü Jan van der Berg'in imzası ile Zeta Global B.V. bağlanır.",
]
LATER = {
    0: "Gülşen Öztürk onaylar.",
    1: "Klaus von Heidenstein onaylar.",
    2: "Ayşe Demir onaylar.",
    3: "Omar ibn Rashid onaylar.",
    4: "Liam O'Brien onaylar.",
    5: "Jan van der Berg onaylar.",
}


@pytest.mark.parametrize("number", range(len(SENTENCES)))
def test_restoring_gives_back_the_original_text(engine, lists, make_docx, tmp_path, number):
    path = make_docx(paragraphs(SENTENCES[number], LATER[number]))
    original, restored = round_trip(path, engine, lists, tmp_path)
    assert same_but_for_short_forms(original, restored) == []


def test_the_normalisation_refuses_a_lost_word():
    assert (
        same_but_for_short_forms("Genel Müdürü Gülşen Öztürk'ın imzası", "Genel Müdürü Gülşen")
        != []
    )
    assert same_but_for_short_forms("Acme pays", "Acme Supplies Ltd pays") == []
