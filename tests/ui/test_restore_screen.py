"""The Restore screen: a Word file or pasted text, put back together with the key of a case.

The first two tests are the brief's: the AI's Word file restored once its changed placeholder is
confirmed, and pasted text restored. The rest cover what the brief leaves to the builder: that
the cases come best fit first and the owner's choice is respected, that each place the AI changed
is confirmed or left as the AI wrote it (by the ordinals of the plan, ruling R91, and True when
every one is confirmed), what the result panel shows, a file that changes under the plan (the
restore is given its fingerprint, ruling R96), and that whatever goes wrong is said in words and
never ends in a trace.
"""

from __future__ import annotations

import errno
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget

from tests.helpers import simulate_ai
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.errors import KeyStoreError, MaskError
from themask.instruction import BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.restore.docx_restore import FILE_CHANGED_MESSAGE
from themask.restore.report import TRACKED_CHANGE
from themask.ui import restore_screen
from themask.ui.restore_screen import RestoreScreen, file_text

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from tests.fixtures.docx import MakeDocx
    from themask.ui.app import AppContext

CLICK = Qt.MouseButton.LeftButton
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
THREE_PLACEHOLDERS = "Dear [PERSON_1], [COMPANY_1] pays [AMOUNT_1]."


def the_key() -> list[KeyEntry]:
    return [
        KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"]),
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme"]),
        KeyEntry("[AMOUNT_1]", PlaceholderType.AMOUNT, "EUR 1,250,000", []),
    ]


def a_case(case_id: str = "K4F7", created: datetime = NOW, entries: int = 3) -> Case:
    """A case holding the first ``entries`` lines of the key."""
    return Case(case_id, created, [f"{case_id}.docx"], [], the_key()[:entries])


def para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def body(*lines: str) -> str:
    return "".join(para(line) for line in lines)


def text_of(path: Path) -> str:
    return extract_text(DocxPackage.open(path)).text


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def inserted(text: str) -> str:
    """A tracked insertion of the AI's."""
    return f'<w:ins w:id="9" w:author="AI tool" w:date="2026-10-17T09:00:00Z">{run(text)}</w:ins>'


def deleted(text: str) -> str:
    """A tracked deletion of the AI's."""
    return (
        '<w:del w:id="9" w:author="AI tool" w:date="2026-10-17T09:00:00Z">'
        f'<w:r><w:delText xml:space="preserve">{escape(text)}</w:delText></w:r></w:del>'
    )


def restored_beside(ai: Path) -> Path:
    """Where the restored copy of ``ai`` is written."""
    return ai.with_name(f"{ai.stem} – restored.docx")


def row_with(choices: QListWidget, text: str) -> int:
    """The number of the line of a list of changes that holds ``text``."""
    (found,) = [n for n in range(choices.count()) if text in choices.item(n).text()]
    return found


@pytest.fixture
def screen(qtbot: QtBot, app_ctx: AppContext) -> RestoreScreen:
    """The screen, with the case K4F7 in the store."""
    app_ctx.case_store.save(a_case())
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    return s


def ticks(choices: QListWidget) -> list[bool]:
    """Whether each line of a list of changes is ticked."""
    return [choices.item(n).checkState() == Qt.CheckState.Checked for n in range(choices.count())]


# ---- the brief's two ----------------------------------------------------------------------------


def test_restore_docx_flow(qtbot: QtBot, app_ctx: AppContext, exported: tuple[Path, Case]) -> None:
    masked, case = exported
    ai = simulate_ai(masked, masked.parent / "ai.docx")
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(ai)
    assert s.case_combo.currentData() == case.id and s.altered_list.count() == 1
    s.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(s.restoreFinished, timeout=30000):
        qtbot.mouseClick(s.restore_button, CLICK)
    assert s.report_label.text().endswith("need your check.")
    assert (masked.parent / "ai – restored.docx").exists()


def test_restore_text_flow(qtbot: QtBot, app_ctx: AppContext, exported: tuple[Path, Case]) -> None:
    _, case = exported
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.paste_box.setPlainText(f"Dear {case.entries[0].placeholder},")
    s.case_combo.setCurrentIndex(s.case_combo.findData(case.id))
    qtbot.mouseClick(s.restore_text_button, CLICK)
    assert case.entries[0].value in s.result_box.toPlainText()


# ---- a Word file ----------------------------------------------------------------------------------


def test_the_restored_file_is_a_new_one_beside_the_ai_s(
    qtbot: QtBot,
    app_ctx: AppContext,
    exported: tuple[Path, Case],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    masked, case = exported
    ai = simulate_ai(masked, masked.parent / "ai.docx")
    before = ai.read_bytes()
    revealed: list[Path] = []
    monkeypatch.setattr(restore_screen, "reveal", revealed.append)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(ai)
    in_masked = text_of(masked).removeprefix(BANNER_TEXT)
    exact = sum(in_masked.count(entry.placeholder) for entry in case.entries)
    # The AI's file has every placeholder of the masked file, one of them changed, and one more
    # in a comment. Not confirmed, the changed one is left as the AI wrote it ...
    with qtbot.waitSignal(s.restoreFinished, timeout=30000):
        qtbot.mouseClick(s.restore_button, CLICK)
    assert s.report_label.text() == f"{exact} placeholders restored, 1 need your check."
    assert "[PERSON 1]" in s.check_label.text()
    # ... and confirmed, it is put back like the rest, in a new file: never over the first.
    s.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(s.restoreFinished, timeout=30000):
        qtbot.mouseClick(s.restore_button, CLICK)
    restored = masked.parent / "ai – restored (2).docx"
    assert (masked.parent / "ai – restored.docx").exists() and restored.exists()
    assert ai.read_bytes() == before  # the AI's file is never written to
    text = text_of(restored)
    assert all(entry.value in text for entry in case.entries)
    assert "[PERSON_9]" in text  # a placeholder the case does not hold stays
    # The result panel: the report's own sentence, the file, what the case does not hold, the
    # folder.
    assert s.report_label.text() == f"{exact + 1} placeholders restored, 0 need your check."
    assert "ai – restored (2).docx" in s.saved_label.text()
    assert "[PERSON_9]" in s.unknown_label.text() and s.check_label.isHidden()
    assert s.finder_button.isVisibleTo(s) and not s.copy_button.isVisibleTo(s)
    assert not s.result_box.isVisibleTo(s)
    qtbot.mouseClick(s.finder_button, CLICK)
    assert revealed == [masked.parent]


def test_a_changed_placeholder_the_owner_did_not_confirm_is_left_as_written(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("Dear [PERSON_1],", "The fee is AMOUNT_1.", "Note [PERSON_9]."))
    screen.load_file(ai)
    assert screen.altered_list.count() == 1 and ticks(screen.altered_list) == [False]
    assert screen.altered_label.text() == restore_screen.CHANGED
    assert "AMOUNT_1" in screen.altered_list.item(0).text()
    assert "[AMOUNT_1]" in screen.altered_list.item(0).text()  # and what it stands for
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    lines = text_of(ai.with_name(f"{ai.stem} – restored.docx")).split("\n")
    assert lines == ["Dear John Smith,", "The fee is AMOUNT_1.", "Note [PERSON_9]."]
    assert screen.report_label.text() == "1 placeholders restored, 1 need your check."
    assert "AMOUNT_1" in screen.check_label.text()  # it needs a check ...
    assert "AMOUNT_1" not in screen.unknown_label.text()  # ... and is not one the case lacks
    assert "[PERSON_9]" in screen.unknown_label.text()


def test_a_changed_placeholder_the_owner_confirmed_is_restored(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("Dear [PERSON_1],", "The fee is AMOUNT_1."))
    screen.load_file(ai)
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    lines = text_of(ai.with_name(f"{ai.stem} – restored.docx")).split("\n")
    assert lines == ["Dear John Smith,", "The fee is EUR 1,250,000."]
    assert screen.report_label.text() == "2 placeholders restored, 0 need your check."
    assert screen.check_label.isHidden() and screen.unknown_label.isHidden()


def test_each_form_the_ai_changed_is_confirmed_on_its_own(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("COMPANY_1 pays AMOUNT_1 to [PERSON_1]."))
    screen.load_file(ai)
    assert screen.altered_list.count() == 2
    screen.altered_list.item(row_with(screen.altered_list, "[AMOUNT_1]")).setCheckState(
        Qt.CheckState.Checked
    )  # only this one
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert text_of(restored_beside(ai)) == "COMPANY_1 pays EUR 1,250,000 to John Smith."
    assert screen.report_label.text() == "2 placeholders restored, 1 need your check."


def test_each_place_the_ai_changed_is_a_line_of_its_own_and_confirmed_on_its_own(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("AMOUNT_1 and [ AMOUNT 1 ] and amount_1", "AMOUNT_1 again"))
    screen.load_file(ai)
    assert screen.altered_list.count() == 4
    texts = [screen.altered_list.item(n).text() for n in range(4)]
    assert texts == [
        "AMOUNT_1  →  [AMOUNT_1]",
        "[ AMOUNT 1 ]  →  [AMOUNT_1]",
        "amount_1  →  [AMOUNT_1]",
        "AMOUNT_1  →  [AMOUNT_1]",
    ]  # how each was written, and what it stands for
    screen.altered_list.item(3).setCheckState(Qt.CheckState.Checked)  # the last place only
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    lines = text_of(restored_beside(ai)).split("\n")
    assert lines == ["AMOUNT_1 and [ AMOUNT 1 ] and amount_1", "EUR 1,250,000 again"]
    assert screen.report_label.text() == "1 placeholders restored, 3 need your check."


def test_a_form_the_ai_changed_is_left_though_the_placeholder_is_written_exactly_elsewhere(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("[PERSON_1] signs. Then PERSON_1 pays."))
    screen.load_file(ai)
    assert screen.altered_list.count() == 1 and ticks(screen.altered_list) == [False]
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    # The exact place is restored; the changed one waits for the owner, who has not confirmed it.
    assert text_of(restored_beside(ai)) == "John Smith signs. Then PERSON_1 pays."
    assert screen.report_label.text() == "1 placeholders restored, 1 need your check."
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    second = ai.with_name(f"{ai.stem} – restored (2).docx")  # never over the first copy
    assert text_of(second) == "John Smith signs. Then John Smith pays."
    assert screen.report_label.text() == "2 placeholders restored, 0 need your check."


def test_a_comment_of_the_ai_is_looked_at_too(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(
        body("Nothing here."),
        parts={
            "word/comments.xml": f'<w:comment w:id="0">{para("Is AMOUNT_1 right?")}</w:comment>'
        },
    )
    screen.load_file(ai)
    assert screen.altered_list.count() == 1  # the plan of the file reaches into the comments
    assert screen.altered_list.item(0).text().endswith("in a comment")
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    comments = DocxPackage.open(restored_beside(ai)).raw("word/comments.xml")
    assert b"EUR 1,250,000" in comments and b"AMOUNT_1" not in comments


@pytest.mark.parametrize(
    ("part", "words"),
    [("word/header1.xml", "in a header"), ("word/footer1.xml", "in a footer")],
    ids=["header", "footer"],
)
def test_a_line_says_where_in_the_file_the_place_stands(
    screen: RestoreScreen, make_docx: MakeDocx, part: str, words: str
) -> None:
    screen.load_file(make_docx(body("Nothing here."), parts={part: para("Signed PERSON_1")}))
    assert screen.altered_list.count() == 1
    assert screen.altered_list.item(0).text() == f"PERSON_1  →  [PERSON_1], {words}"


def test_a_place_where_several_placeholders_meet_in_a_change_is_held_and_says_so(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    # The AI's deletion runs through two changed placeholders, "PERSON_1" and "COMPANY_1": this
    # place stands for both, and no restore puts it back, confirmed or not (ruling R96). It stays
    # on the list to check, as the AI wrote it.
    ai = make_docx(f"<w:p>{run('X PERSON_')}{deleted('1 and COMPANY_')}{run('1 Y')}</w:p>")
    screen.load_file(ai)
    assert screen.altered_list.count() == 1
    assert "stands for every placeholder in that change" in screen.altered_list.item(0).text()
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert screen.report_label.text() == "0 placeholders restored, 1 need your check."
    assert "stands for every placeholder in that change" in screen.check_label.text()
    assert text_of(restored_beside(ai)) == "X PERSON_1 Y"


def test_a_placeholder_a_tracked_change_runs_through_says_so_and_waits_for_the_owner(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    # Accepted, the AI's change makes "[PERSON_1]"; rejected it leaves "PERSON_1]", a changed form.
    ai = make_docx(f"<w:p>{run('Signed by ')}{inserted('[')}{run('PERSON_1].')}</w:p>")
    screen.load_file(ai)
    assert screen.altered_list.count() == 1
    row = screen.altered_list.item(0).text()
    assert TRACKED_CHANGE in row and "stands for every placeholder in that change" in row
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert "[PERSON_1]" in screen.check_label.text() and TRACKED_CHANGE in screen.check_label.text()
    assert screen.report_label.text() == "0 placeholders restored, 1 need your check."
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert screen.report_label.text() == "1 placeholders restored, 0 need your check."


def test_a_file_that_changed_under_the_list_is_not_restored_by_that_list(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx, tmp_path: Path
) -> None:
    ai = make_docx(body("The fee is AMOUNT_1."))
    screen.load_file(ai)
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    # Another program saves a different file under that name: its numbers are not the list's.
    other = make_docx(body("COMPANY_1 pays [AMOUNT_1] and AMOUNT_1."))
    ai.write_bytes(other.read_bytes())
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert screen.status_label.text() == FILE_CHANGED_MESSAGE
    assert not restored_beside(ai).exists() and not screen.result_panel.isVisibleTo(screen)
    assert screen.altered_list.count() == 2 and ticks(screen.altered_list) == [False, False]
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):  # looked at again: it goes
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert text_of(restored_beside(ai)) == "COMPANY_1 pays EUR 1,250,000 and AMOUNT_1."
    assert screen.status_label.isHidden()


def test_a_file_that_was_not_planned_is_never_restored_without_the_fingerprint(
    qtbot: QtBot,
    screen: RestoreScreen,
    make_docx: MakeDocx,
    file_restores: list[tuple[object, object]],
) -> None:
    ai = make_docx(body("The fee is AMOUNT_1."))
    screen.load_file(ai)
    good = ai.read_bytes()
    ai.write_bytes(b"not a Word file")  # the plan of the next case change cannot be made
    screen.case_combo.setCurrentIndex(-1)
    screen.case_combo.setCurrentIndex(0)
    assert not screen.status_label.isHidden() and screen.altered_list.count() == 0
    ai.write_bytes(good)  # and now the file reads again: but nobody has seen what is in it
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert file_restores == []  # a restore is always given the fingerprint of a plan (ruling R96)
    assert screen.status_label.text() == FILE_CHANGED_MESSAGE
    assert not restored_beside(ai).exists() and not screen.result_panel.isVisibleTo(screen)
    assert screen.altered_list.count() == 1  # the file as it is now, for the owner to look at
    click_restore(qtbot, screen)
    assert [sha for _, sha in file_restores] == [hashlib.sha256(good).hexdigest()]
    assert text_of(restored_beside(ai)) == "The fee is AMOUNT_1."  # nothing was confirmed


def test_typing_in_the_paste_box_leaves_the_ticks_of_the_file_alone(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("The fee is AMOUNT_1.")))
    screen.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    screen.paste_box.setPlainText("Dear [PERSON_1]")
    screen.paste_box.appendPlainText("and PERSON_1 again")
    assert ticks(screen.altered_list) == [True]  # the file's plan did not change
    assert screen.text_altered_list.count() == 1 and ticks(screen.text_altered_list) == [False]


def test_a_text_that_makes_another_case_the_best_fit_reads_the_file_again_for_it(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    app_ctx.case_store.save(a_case("A1A1", NOW - timedelta(days=3), entries=2))
    app_ctx.case_store.save(a_case("B2B2", NOW, entries=1))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("PERSON_1 signs for COMPANY_1.")))
    assert s.case_combo.currentData() == "A1A1" and s.altered_list.count() == 2
    s.case_combo.setCurrentIndex(s.case_combo.findData("B2B2"))
    s.case_combo.activated.emit(s.case_combo.currentIndex())  # the owner chose B2B2 ...
    assert s.altered_list.count() == 1
    s.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    s.paste_box.setPlainText("[COMPANY_1] only A1A1 holds")  # ... but only A1A1 holds this
    assert s.case_combo.currentData() == "A1A1"
    assert s.altered_list.count() == 2 and ticks(s.altered_list) == [False, False]


def test_a_file_that_makes_another_case_the_best_fit_reads_the_pasted_text_again_for_it(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    app_ctx.case_store.save(a_case("A1A1", NOW - timedelta(days=3), entries=2))  # person, company
    app_ctx.case_store.save(Case("B2B2", NOW, ["B2B2.docx"], [], the_key()[2:]))  # the amount only
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.paste_box.setPlainText("PERSON_1 signs for COMPANY_1")
    assert s.case_combo.currentData() == "A1A1" and s.text_altered_list.count() == 2
    s.load_file(make_docx(body("The fee is AMOUNT_1.")))  # only B2B2 holds the amount
    assert s.case_combo.currentData() == "B2B2"
    assert s.text_altered_list.count() == 0  # the text, read for B2B2, holds nothing of it
    assert s.text_fit_label.text() == "0 of 2 placeholders found in this case."


def test_the_file_is_read_again_when_the_case_changes(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    app_ctx.case_store.save(a_case("A1A1", NOW - timedelta(days=3), entries=2))
    app_ctx.case_store.save(a_case("B2B2", NOW, entries=1))  # holds the person only
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("PERSON_1 and COMPANY_1")))
    assert s.case_combo.currentData() == "A1A1" and s.altered_list.count() == 2
    s.case_combo.setCurrentIndex(s.case_combo.findData("B2B2"))  # [COMPANY_1] is unknown there
    assert s.altered_list.count() == 1 and "PERSON_1" in s.altered_list.item(0).text()
    assert s.file_fit_label.text() == "1 of 2 placeholders found in this case."


def test_a_new_file_clears_the_result_of_the_last(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("Dear [PERSON_1],")))
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert screen.result_panel.isVisibleTo(screen)
    screen.load_file(make_docx(body("Another one.")))
    assert not screen.result_panel.isVisibleTo(screen)


def test_the_fit_of_the_case_is_said_under_the_file(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    assert screen.file_fit_label.text() == ""
    screen.load_file(make_docx(body("[PERSON_1] [PERSON_8] [PERSON_9] [PERSON_9]")))
    assert screen.file_fit_label.text() == "1 of 3 placeholders found in this case."
    screen.load_file(make_docx(body("Nothing masked here.")))
    assert screen.file_fit_label.text() == "No placeholders found."


# ---- what a restore is given -------------------------------------------------------------------------------


@pytest.fixture
def file_restores(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, object]]:
    """The confirmation and the fingerprint each restore of a file was given; it still runs."""
    calls: list[tuple[object, object]] = []
    real = restore_screen.restore_docx

    def record(
        src: Path,
        case: Case,
        confirm_altered: object,
        out_dir: Path | None = None,
        expected_sha256: str | None = None,
    ) -> object:
        calls.append((confirm_altered, expected_sha256))
        return real(src, case, confirm_altered, out_dir, expected_sha256)  # type: ignore[arg-type]

    monkeypatch.setattr(restore_screen, "restore_docx", record)
    return calls


@pytest.fixture
def text_restores(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The confirmation each restore of text was given; it still runs."""
    calls: list[object] = []
    real = restore_screen.restore_text

    def record(text: str, case: Case, confirm_altered: object) -> object:
        calls.append(confirm_altered)
        return real(text, case, confirm_altered)  # type: ignore[arg-type]

    monkeypatch.setattr(restore_screen, "restore_text", record)
    return calls


def click_restore(qtbot: QtBot, screen: RestoreScreen) -> None:
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(screen.restore_button, CLICK)


def test_a_file_is_restored_with_the_ordinals_of_the_ticked_lines_and_the_plan_s_fingerprint(
    qtbot: QtBot,
    screen: RestoreScreen,
    make_docx: MakeDocx,
    file_restores: list[tuple[object, object]],
) -> None:
    ai = make_docx(body("COMPANY_1 pays AMOUNT_1 to [PERSON_1]."))
    fingerprint = hashlib.sha256(ai.read_bytes()).hexdigest()
    screen.load_file(ai)  # the plan: COMPANY_1 is item 0, AMOUNT_1 item 1, [PERSON_1] item 2
    click_restore(qtbot, screen)  # nothing ticked
    screen.altered_list.item(1).setCheckState(Qt.CheckState.Checked)
    click_restore(qtbot, screen)  # one ticked: AMOUNT_1, the second line
    assert file_restores == [(set(), fingerprint), ({1}, fingerprint)]


def test_a_file_is_restored_with_true_when_every_line_is_ticked(
    qtbot: QtBot,
    screen: RestoreScreen,
    make_docx: MakeDocx,
    file_restores: list[tuple[object, object]],
) -> None:
    screen.load_file(make_docx(body("COMPANY_1 pays AMOUNT_1.")))
    for number in range(screen.altered_list.count()):
        screen.altered_list.item(number).setCheckState(Qt.CheckState.Checked)
    click_restore(qtbot, screen)  # so that the changed placeholders of a text box's copy follow
    assert [confirmed for confirmed, _ in file_restores] == [True]


def test_with_nothing_changed_nothing_is_confirmed_not_everything(
    qtbot: QtBot,
    screen: RestoreScreen,
    make_docx: MakeDocx,
    file_restores: list[tuple[object, object]],
) -> None:
    screen.load_file(make_docx(body("Dear [PERSON_1].")))
    assert screen.altered_list.count() == 0
    click_restore(qtbot, screen)
    assert [confirmed for confirmed, _ in file_restores] == [set()]


def test_text_is_restored_with_the_ordinals_of_the_ticked_lines_or_true_for_all(
    qtbot: QtBot, screen: RestoreScreen, text_restores: list[object]
) -> None:
    screen.paste_box.setPlainText("COMPANY_1 pays AMOUNT_1 to [PERSON_1].")
    qtbot.mouseClick(screen.restore_text_button, CLICK)  # nothing ticked
    screen.text_altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    qtbot.mouseClick(screen.restore_text_button, CLICK)  # the first line: COMPANY_1, item 0
    screen.text_altered_list.item(1).setCheckState(Qt.CheckState.Checked)
    qtbot.mouseClick(screen.restore_text_button, CLICK)  # both lines: all of them
    assert text_restores == [set(), {0}, True]


def test_the_plan_of_the_text_is_made_again_whenever_the_text_changes(
    qtbot: QtBot, screen: RestoreScreen, text_restores: list[object]
) -> None:
    screen.paste_box.setPlainText("COMPANY_1 pays AMOUNT_1.")
    assert screen.text_altered_list.count() == 2
    screen.paste_box.setPlainText("Pays AMOUNT_1 only.")  # the list is the new text's
    assert screen.text_altered_list.count() == 1
    screen.text_altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.result_box.toPlainText() == "Pays EUR 1,250,000 only."
    assert text_restores == [True]  # its one changed placeholder is confirmed


# ---- pasted text -----------------------------------------------------------------------------------


def test_pasted_text_is_restored_and_can_be_copied(
    qtbot: QtBot, screen: RestoreScreen, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen.paste_box.setPlainText(THREE_PLACEHOLDERS)
    with qtbot.assertNotEmitted(screen.restoreFinished):  # that is the Word file's signal
        qtbot.mouseClick(screen.restore_text_button, CLICK)
    restored = "Dear John Smith, Acme Supplies Ltd pays EUR 1,250,000."
    assert screen.result_box.toPlainText() == restored and screen.result_box.isReadOnly()
    assert screen.report_label.text() == "3 placeholders restored, 0 need your check."
    assert screen.copy_button.isVisibleTo(screen) and screen.result_box.isVisibleTo(screen)
    assert not screen.finder_button.isVisibleTo(screen)
    qtbot.mouseClick(screen.copy_button, CLICK)
    assert QApplication.clipboard().text() == restored
    assert screen.paste_box.toPlainText() == THREE_PLACEHOLDERS  # what was pasted is left alone


def test_a_changed_placeholder_in_pasted_text_waits_for_the_owner(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    screen.paste_box.setPlainText("Dear PERSON_1, [COMPANY_1] pays [AMOUNT 1].")
    assert screen.text_altered_list.count() == 2 and ticks(screen.text_altered_list) == [False] * 2
    assert screen.altered_list.count() == 0  # the file's list is the file's
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.result_box.toPlainText() == "Dear PERSON_1, Acme Supplies Ltd pays [AMOUNT 1]."
    assert screen.report_label.text() == "1 placeholders restored, 2 need your check."
    assert "PERSON_1" in screen.check_label.text() and "[AMOUNT 1]" in screen.check_label.text()
    screen.text_altered_list.item(0).setCheckState(Qt.CheckState.Checked)  # PERSON_1
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.result_box.toPlainText() == "Dear John Smith, Acme Supplies Ltd pays [AMOUNT 1]."
    assert screen.report_label.text() == "2 placeholders restored, 1 need your check."


def test_the_banner_is_taken_out_of_pasted_text(qtbot: QtBot, screen: RestoreScreen) -> None:
    screen.paste_box.setPlainText(f"{BANNER_TEXT}\n\nHello [PERSON_1]")
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.result_box.toPlainText() == "Hello John Smith"


def test_the_buttons_wait_for_what_they_restore(screen: RestoreScreen, make_docx: MakeDocx) -> None:
    assert not screen.restore_button.isEnabled() and not screen.restore_text_button.isEnabled()
    screen.paste_box.setPlainText("   \n ")
    assert not screen.restore_text_button.isEnabled()  # blank is nothing
    screen.paste_box.setPlainText("[PERSON_1]")
    assert screen.restore_text_button.isEnabled() and not screen.restore_button.isEnabled()
    screen.load_file(make_docx(body("[PERSON_1]")))
    assert screen.restore_button.isEnabled()


# ---- the cases ---------------------------------------------------------------------------------------


def two_cases(ctx: AppContext) -> None:
    """A holds the person and the company (older); B only the person (newer)."""
    ctx.case_store.save(a_case("A1A1", NOW - timedelta(days=3), entries=2))
    ctx.case_store.save(a_case("B2B2", NOW, entries=1))


def combo_ids(s: RestoreScreen) -> list[str]:
    return [s.case_combo.itemData(n) for n in range(s.case_combo.count())]


def test_the_most_recent_case_comes_first_while_there_is_nothing_to_fit(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    two_cases(app_ctx)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    assert combo_ids(s) == ["B2B2", "A1A1"] and s.case_combo.currentData() == "B2B2"
    s.paste_box.setPlainText("Nothing masked in this answer.")  # no placeholder fits any case
    assert combo_ids(s) == ["B2B2", "A1A1"] and s.case_combo.currentData() == "B2B2"


def test_the_case_that_holds_most_of_the_placeholders_comes_first_and_is_preselected(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    two_cases(app_ctx)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.paste_box.setPlainText("[PERSON_1] and [COMPANY_1]")
    assert combo_ids(s) == ["A1A1", "B2B2"] and s.case_combo.currentData() == "A1A1"
    assert s.text_fit_label.text() == "2 of 2 placeholders found in this case."
    s.case_combo.setCurrentIndex(1)  # looking at the other one tells how it fits
    assert s.text_fit_label.text() == "1 of 2 placeholders found in this case."


def test_a_file_puts_the_cases_in_order_too(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    two_cases(app_ctx)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("[COMPANY_1] is Acme.")))
    assert combo_ids(s) == ["A1A1", "B2B2"] and s.case_combo.currentData() == "A1A1"


def test_the_owner_s_case_is_kept_while_it_fits_as_well_as_the_best(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    two_cases(app_ctx)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.paste_box.setPlainText("[PERSON_1]")  # both cases hold the person
    assert s.case_combo.currentData() == "B2B2"  # the newer
    s.case_combo.setCurrentIndex(s.case_combo.findData("A1A1"))
    s.case_combo.activated.emit(s.case_combo.currentIndex())  # the owner chose it
    s.paste_box.setPlainText("[PERSON_1] again")
    assert s.case_combo.currentData() == "A1A1"  # still the owner's: it fits as well
    s.paste_box.setPlainText("[PERSON_1] and [COMPANY_1]")  # ... but B2B2 never holds the company
    assert s.case_combo.currentData() == "A1A1"
    s.case_combo.setCurrentIndex(s.case_combo.findData("B2B2"))
    s.case_combo.activated.emit(s.case_combo.currentIndex())
    s.paste_box.setPlainText("[PERSON_1] and [COMPANY_1] too")  # now the chosen case fits worse
    assert s.case_combo.currentData() == "A1A1"  # the better fit is offered again


def test_the_case_asked_for_in_the_cases_screen_is_selected(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    two_cases(app_ctx)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.refresh_cases("A1A1")
    assert s.case_combo.currentData() == "A1A1"
    s.paste_box.setPlainText("[PERSON_1]")  # fits both as well: the owner's case stays
    assert s.case_combo.currentData() == "A1A1"
    s.refresh_cases("NOPE")  # a case that is not there changes nothing the owner chose
    assert s.case_combo.currentData() == "A1A1"


def test_the_case_asked_for_in_the_cases_screen_wins_over_a_better_fit(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    two_cases(app_ctx)  # A1A1 holds the person and the company, B2B2 the person only
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("PERSON_1 signs for COMPANY_1.")))
    assert s.case_combo.currentData() == "A1A1" and s.altered_list.count() == 2
    s.refresh_cases("B2B2")  # "Restore from this case": the owner asked for this one
    assert s.case_combo.currentData() == "B2B2"
    assert s.altered_list.count() == 1  # the file is read again for it
    assert s.file_fit_label.text() == "1 of 2 placeholders found in this case."
    s.refresh_cases()  # a visit to the screen later keeps the owner's choice
    assert s.case_combo.currentData() == "B2B2"


def test_refresh_shows_the_cases_the_store_holds_now(qtbot: QtBot, app_ctx: AppContext) -> None:
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    assert s.case_combo.count() == 0 and s.no_cases_label.isVisibleTo(s)
    app_ctx.case_store.save(a_case("K4F7"))  # an export made it
    s.refresh_cases()
    assert combo_ids(s) == ["K4F7"] and not s.no_cases_label.isVisibleTo(s)
    app_ctx.case_store.delete("K4F7")
    s.refresh_cases()
    assert s.case_combo.count() == 0 and s.no_cases_label.isVisibleTo(s)


def test_with_no_case_nothing_can_be_restored(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.paste_box.setPlainText("[PERSON_1]")
    s.load_file(make_docx(body("[PERSON_1]")))
    assert s.case_combo.currentData() is None
    assert not s.restore_button.isEnabled() and not s.restore_text_button.isEnabled()
    assert s.file_fit_label.text() == "" and s.altered_list.count() == 0


def test_a_case_line_names_the_case_and_its_files(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    assert "K4F7" in s.case_combo.itemText(0) and "K4F7.docx" in s.case_combo.itemText(0)


def test_a_store_that_cannot_be_read_is_said_in_the_screen(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    keychain = "The MASK could not reach the macOS Keychain. Unlock it."

    def refuse() -> list[Case]:
        raise KeyStoreError(keychain)

    monkeypatch.setattr(app_ctx.case_store, "load_all", refuse)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    assert s.status_label.text() == keychain and s.case_combo.count() == 0
    monkeypatch.undo()
    app_ctx.case_store.save(a_case("K4F7"))
    s.refresh_cases()
    assert combo_ids(s) == ["K4F7"] and s.status_label.text() == ""


# ---- the files that are dropped ----------------------------------------------------------------------


def test_a_dropped_file_is_taken(screen: RestoreScreen, make_docx: MakeDocx) -> None:
    ai = make_docx(body("[PERSON_1]"))
    screen.drop_zone.filesDropped.emit([ai])
    assert screen.file_label.text() == ai.name and screen.restore_button.isEnabled()
    assert screen.status_label.isHidden()


def test_only_the_first_of_several_files_is_taken_and_the_owner_is_told(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    first, second = make_docx(body("[PERSON_1]")), make_docx(body("[COMPANY_1]"))
    screen.drop_zone.filesDropped.emit([first, second])
    assert screen.file_label.text() == first.name
    assert screen.status_label.text() == restore_screen.ONE_AT_A_TIME


def test_a_file_that_is_not_word_is_refused_in_words(screen: RestoreScreen) -> None:
    screen.drop_zone.filesRefused.emit([Path("/somewhere/answer.pdf"), Path("/somewhere/a.txt")])
    text = screen.status_label.text()
    assert restore_screen.ONLY_WORD in text and "answer.pdf" in text and "a.txt" in text
    assert screen.file_label.text() == "No file chosen yet."


def test_the_zone_offers_only_word_files(screen: RestoreScreen) -> None:
    assert ".docx" in screen.drop_zone.hint_label.text()
    assert "Word" in screen.drop_zone.title_label.text()


@pytest.mark.parametrize("name", ["corrupt.docx", "not-a-docx.doc", "encrypted.docx"])
def test_a_file_that_cannot_be_read_is_said_in_words(
    screen: RestoreScreen, fixtures: Path, name: str
) -> None:
    screen.load_file(fixtures / name)
    assert screen.status_label.text() and "Traceback" not in screen.status_label.text()
    assert (
        not screen.restore_button.isEnabled() and screen.file_label.text() == "No file chosen yet."
    )


def test_a_file_that_is_not_there_is_said_in_words(screen: RestoreScreen, tmp_path: Path) -> None:
    screen.load_file(tmp_path / "gone.docx")
    assert "No such file" in screen.status_label.text()
    assert str(tmp_path) not in screen.status_label.text()  # what the system says, not the path


# ---- a restore that fails ------------------------------------------------------------------------------


def broken(error: Exception) -> object:
    def fail(*args: object, **kwargs: object) -> None:
        raise error

    return fail


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (MaskError("This is not a Word .docx file."), "not a Word .docx file"),
        (
            OSError(errno.ENOSPC, "No space left on device", "/Users/someone/ai – restored.docx"),
            "No space left on device",
        ),
    ],
    ids=["mask error", "disk"],
)
def test_a_restore_that_fails_says_why_and_still_finishes(
    qtbot: QtBot,
    screen: RestoreScreen,
    make_docx: MakeDocx,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    shown: str,
) -> None:
    screen.load_file(make_docx(body("[PERSON_1]")))
    monkeypatch.setattr(restore_screen, "restore_docx", broken(error))
    with qtbot.waitSignal(screen.restoreFinished, timeout=5000):  # it did not hang
        qtbot.mouseClick(screen.restore_button, CLICK)
    text = screen.status_label.text()
    assert shown in text and "/Users" not in text and not screen.status_label.isHidden()
    assert not screen.result_panel.isVisibleTo(screen)  # no result: nothing was restored


def test_a_file_that_is_gone_when_restore_is_clicked_is_not_called_unwritable(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("[PERSON_1]"))
    screen.load_file(ai)
    ai.unlink()  # the AI's file was moved away after it was chosen
    with qtbot.waitSignal(screen.restoreFinished, timeout=5000):
        qtbot.mouseClick(screen.restore_button, CLICK)
    text = screen.status_label.text()
    assert "No such file" in text and "written" not in text  # it was not read, not written
    assert str(ai.parent) not in text and not screen.result_panel.isVisibleTo(screen)


def test_an_unexpected_error_is_a_plain_sentence_and_only_its_type_is_logged(
    qtbot: QtBot,
    screen: RestoreScreen,
    make_docx: MakeDocx,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    screen.load_file(make_docx(body("[PERSON_1]")))
    monkeypatch.setattr(restore_screen, "restore_docx", broken(RuntimeError("Secret Client Ltd")))
    with (
        caplog.at_level(logging.INFO, logger="themask"),
        qtbot.waitSignal(screen.restoreFinished, timeout=5000),
    ):
        qtbot.mouseClick(screen.restore_button, CLICK)
    assert screen.status_label.text() == restore_screen.UNEXPECTED
    assert "RuntimeError" in caplog.text and "Secret" not in caplog.text


def test_a_failing_text_restore_is_a_plain_sentence_too(
    qtbot: QtBot, screen: RestoreScreen, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen.paste_box.setPlainText("[PERSON_1]")
    monkeypatch.setattr(restore_screen, "restore_text", broken(RuntimeError("Secret Client Ltd")))
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.status_label.text() == restore_screen.UNEXPECTED
    assert not screen.result_panel.isVisibleTo(screen)


def test_a_restore_that_works_clears_the_message_of_one_that_did_not(
    qtbot: QtBot, screen: RestoreScreen, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen.paste_box.setPlainText("[PERSON_1]")
    with monkeypatch.context() as patch:
        patch.setattr(restore_screen, "restore_text", broken(RuntimeError("x")))
        qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert not screen.status_label.isHidden()
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.status_label.isHidden() and screen.result_box.toPlainText() == "John Smith"


# ---- the text the cases are put in order for ---------------------------------------------------------------


def test_the_cases_are_put_in_order_for_the_text_of_the_file(make_docx: MakeDocx) -> None:
    ai = make_docx(body("Dear [PERSON_1],", "[COMPANY_1] pays."))
    assert file_text(ai) == "Dear [PERSON_1],\n[COMPANY_1] pays."
