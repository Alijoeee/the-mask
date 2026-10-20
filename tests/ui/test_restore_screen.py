"""The Restore screen: a Word file or pasted text, put back together with the key of a case.

The first two tests are the brief's: the AI's Word file restored once its changed placeholder is
confirmed, and pasted text restored. The rest cover what the brief leaves to the builder: that
the cases come best fit first and the owner's choice is respected, that each place the AI changed
is confirmed or left as the AI wrote it (by the ordinals of the plan, ruling R91, and True when
every one is confirmed), what the result panel shows, a file that changes under the plan (the
restore is given its fingerprint, ruling R96), and that whatever goes wrong is said in words and
never ends in a trace. Ruling R103: two cases that hold the same placeholder names are never
guessed between (the code in the name of the file decides, else the owner is asked), a case the
owner chose is never replaced by the screen (a case that fits better is only pointed out), and
the screen shows which values the selected case would put back.
"""

from __future__ import annotations

import errno
import hashlib
import logging
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QWidget

from tests.fixtures.d3_look import appears_in
from tests.helpers import simulate_ai
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.errors import KeyStoreError, MaskError
from themask.instruction import BANNER_TEXT
from themask.model import Case, KeyEntry, PlaceholderType
from themask.restore.docx_restore import FILE_CHANGED_MESSAGE
from themask.restore.report import TRACKED_CHANGE
from themask.ui import restore_screen, theme
from themask.ui.cases_screen import format_when
from themask.ui.restore_screen import RestoreScreen, file_text

if TYPE_CHECKING:
    from PySide6.QtGui import QImage
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


def test_a_text_that_another_case_fits_better_does_not_take_the_owner_s_case_away(
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
    s.paste_box.setPlainText("[COMPANY_1] only A1A1 holds")  # ... and only A1A1 holds this
    assert s.case_combo.currentData() == "B2B2"  # the screen does not choose for the owner
    assert ticks(s.altered_list) == [True]  # the file is read as before: nothing changed for B2B2
    assert s.better_fit_label.isVisibleTo(s) and s.restore_button.isEnabled()
    pick(s, "A1A1")  # the owner takes the hint
    assert not s.better_fit_label.isVisibleTo(s)
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


def test_the_owner_s_case_is_kept_whatever_the_text_says(qtbot: QtBot, app_ctx: AppContext) -> None:
    two_cases(app_ctx)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.paste_box.setPlainText("[PERSON_1]")  # both cases hold the person: not the newer, by guess
    assert s.case_combo.currentIndex() == -1 and s.choose_label.isVisibleTo(s)
    s.case_combo.setCurrentIndex(s.case_combo.findData("A1A1"))
    s.case_combo.activated.emit(s.case_combo.currentIndex())  # the owner chose it
    s.paste_box.setPlainText("[PERSON_1] again")
    assert s.case_combo.currentData() == "A1A1"  # still the owner's: it fits as well
    assert not s.better_fit_label.isVisibleTo(s)
    s.paste_box.setPlainText("[PERSON_1] and [COMPANY_1]")  # A1A1 holds both: the best fit
    assert s.case_combo.currentData() == "A1A1" and not s.better_fit_label.isVisibleTo(s)
    s.case_combo.setCurrentIndex(s.case_combo.findData("B2B2"))
    s.case_combo.activated.emit(s.case_combo.currentIndex())  # now the owner chose B2B2 ...
    s.paste_box.setPlainText("[PERSON_1] and [COMPANY_1] too")  # ... which never holds the company
    assert s.case_combo.currentData() == "B2B2"  # it is still the owner's: the screen only says so
    assert (
        s.better_fit_label.text()
        == "Another case fits this file better \N{EM DASH} check the case."
    )
    assert s.better_fit_label.isVisibleTo(s) and s.restore_text_button.isEnabled()
    s.paste_box.setPlainText("[PERSON_1] only")  # B2B2 fits as well as any case again
    assert s.case_combo.currentData() == "B2B2" and not s.better_fit_label.isVisibleTo(s)


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
    assert s.better_fit_label.isVisibleTo(s)  # A1A1 holds both placeholders: said, not forced
    assert s.preview_grid.text() == "[PERSON_1] \N{RIGHTWARDS ARROW} John Smith"  # B2B2's pair only
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
    assert not s.no_cases_label.isVisibleTo(s)  # "no saved case" would not be true: not readable
    monkeypatch.undo()
    app_ctx.case_store.save(a_case("K4F7"))
    s.refresh_cases()
    assert combo_ids(s) == ["K4F7"] and s.status_label.text() == ""


# ---- two cases that fit a file alike (ruling R103) ---------------------------------------------------


def alice_and_bob(ctx: AppContext, company: bool = False) -> None:
    """The cases of two contracts, both holding [PERSON_1]: K4F7, the older, where it is Alice
    Smith, and M5N6, the newer, where it is Bob Jones. With ``company`` K4F7 holds [COMPANY_1] as
    well, so that a file with the person and the company fits it better than M5N6.
    """
    person = PlaceholderType.PERSON
    older, newer = NOW - timedelta(days=5), NOW
    alice = [KeyEntry("[PERSON_1]", person, "Alice Smith", [])]
    if company:
        alice.append(KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Northwind Trading B.V.", []))
    ctx.case_store.save(Case("K4F7", older, ["Supply.docx"], [], alice))
    ctx.case_store.save(
        Case(
            "M5N6", newer, ["Services.docx"], [], [KeyEntry("[PERSON_1]", person, "Bob Jones", [])]
        )
    )


def named_file(make_docx: MakeDocx, tmp_path: Path, name: str, *lines: str) -> Path:
    """A Word file called ``name`` holding ``lines``: what an AI tool gives back under its name."""
    path = tmp_path / name
    shutil.copy(make_docx(body(*lines)), path)
    return path


def pick(s: RestoreScreen, case_id: str) -> None:
    """The owner chooses a case in the combo box."""
    s.case_combo.setCurrentIndex(s.case_combo.findData(case_id))
    s.case_combo.activated.emit(s.case_combo.currentIndex())


def screen_with_alice_and_bob(
    qtbot: QtBot, ctx: AppContext, company: bool = False
) -> RestoreScreen:
    alice_and_bob(ctx, company)
    s = RestoreScreen(ctx)
    qtbot.addWidget(s)
    return s


def test_two_cases_that_fit_a_file_alike_are_not_guessed_between(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))  # nothing in the name says which contract
    assert s.case_combo.currentIndex() == -1 and s.case_combo.currentData() is None
    assert combo_ids(s) == ["M5N6", "K4F7"]  # both are on offer, the newer one first
    assert s.choose_label.isVisibleTo(s)
    assert s.choose_label.text() == "Several cases fit this file \N{EM DASH} choose one."
    assert not s.restore_button.isEnabled()
    assert s.altered_list.count() == 0 and s.file_fit_label.text() == ""
    assert not s.preview_grid.isVisibleTo(s)  # no case, so no values to show


def test_the_owner_s_choice_is_the_case_the_file_is_restored_with(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    ai = make_docx(body("Dear [PERSON_1],"))
    s.load_file(ai)
    pick(s, "K4F7")  # the older contract's case
    assert s.restore_button.isEnabled() and not s.choose_label.isVisibleTo(s)
    assert s.file_fit_label.text() == "1 of 1 placeholder found in this case."
    click_restore(qtbot, s)
    assert text_of(restored_beside(ai)) == "Dear Alice Smith,"  # not the newer case's Bob Jones


@pytest.mark.parametrize(
    ("name", "case_id", "value"),
    [
        ("MASKED-K4F7.docx", "K4F7", "Alice Smith"),
        ("MASKED-K4F7-1.docx", "K4F7", "Alice Smith"),
        ("masked-m5n6-2.docx", "M5N6", "Bob Jones"),
    ],
)
def test_the_code_in_the_name_of_the_file_picks_the_case_without_asking(
    qtbot: QtBot,
    app_ctx: AppContext,
    make_docx: MakeDocx,
    tmp_path: Path,
    name: str,
    case_id: str,
    value: str,
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    ai = named_file(make_docx, tmp_path, name, "Dear [PERSON_1],")
    s.load_file(ai)
    assert s.case_combo.currentData() == case_id  # the older case, though the newer fits as well
    assert not s.choose_label.isVisibleTo(s) and s.restore_button.isEnabled()
    click_restore(qtbot, s)
    assert text_of(restored_beside(ai)) == f"Dear {value},"


@pytest.mark.parametrize(
    "name",
    ["MASKED-B2C3.docx", "MASKED-K4F7-M5N6.docx", "MASKED-K4F7X.docx", "answer.docx"],
    ids=["a case that is not here", "two codes", "not a whole word", "no code"],
)
def test_a_name_that_does_not_point_to_one_case_leaves_the_choice_to_the_owner(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path, name: str
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(named_file(make_docx, tmp_path, name, "Dear [PERSON_1],"))
    assert s.case_combo.currentIndex() == -1 and s.choose_label.isVisibleTo(s)
    assert not s.restore_button.isEnabled()


def test_pasted_text_is_not_guessed_either(qtbot: QtBot, app_ctx: AppContext) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.paste_box.setPlainText("Dear [PERSON_1],")
    assert s.case_combo.currentIndex() == -1 and s.choose_label.isVisibleTo(s)
    assert s.choose_label.text() == "Several cases fit this file \N{EM DASH} choose one."
    assert not s.restore_text_button.isEnabled()
    qtbot.mouseClick(s.restore_text_button, CLICK)  # a disabled button takes no click
    assert not s.result_panel.isVisibleTo(s)
    pick(s, "K4F7")
    assert s.restore_text_button.isEnabled() and not s.choose_label.isVisibleTo(s)
    qtbot.mouseClick(s.restore_text_button, CLICK)
    assert s.result_box.toPlainText() == "Dear Alice Smith,"


def test_the_ranking_is_given_the_name_of_the_file_and_none_for_pasted_text(
    qtbot: QtBot,
    app_ctx: AppContext,
    make_docx: MakeDocx,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, str | None]] = []
    real = restore_screen.suggest_cases

    def spy(text: str, cases: list[Case], file_name: str | None = None) -> list[Case]:
        asked.append((text, file_name))
        return real(text, cases, file_name)

    monkeypatch.setattr(restore_screen, "suggest_cases", spy)
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(named_file(make_docx, tmp_path, "MASKED-K4F7.docx", "Dear [PERSON_1],"))
    assert asked[-1] == ("Dear [PERSON_1],", "MASKED-K4F7.docx")
    s.paste_box.setPlainText("[PERSON_1] again")
    assert asked[-1] == ("[PERSON_1] again", None)


def test_a_case_the_owner_chose_stays_chosen_while_the_text_changes_and_on_a_visit(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))
    pick(s, "K4F7")
    s.paste_box.setPlainText("[PERSON_1] again")  # both cases still fit alike: the owner's stays
    s.paste_box.setPlainText("[PERSON_1] and once more")
    assert s.case_combo.currentData() == "K4F7" and not s.choose_label.isVisibleTo(s)
    s.refresh_cases()  # a visit to the screen
    assert s.case_combo.currentData() == "K4F7" and s.restore_button.isEnabled()


def test_clearing_the_paste_box_takes_back_the_question_its_text_raised(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.paste_box.setPlainText("Dear [PERSON_1],")
    assert s.choose_label.isVisibleTo(s) and s.case_combo.currentIndex() == -1
    s.paste_box.clear()
    assert not s.choose_label.isVisibleTo(s)  # nothing is left to fit
    assert s.case_combo.currentData() == "M5N6"  # the newest, as at the start


def test_clearing_the_paste_box_goes_back_to_the_file(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(named_file(make_docx, tmp_path, "MASKED-K4F7.docx", "Dear [PERSON_1],"))
    assert s.case_combo.currentData() == "K4F7"  # the name of the file says which
    s.paste_box.setPlainText("[PERSON_1] in the text")  # a text has no file name to go by
    assert s.case_combo.currentIndex() == -1 and s.choose_label.isVisibleTo(s)
    assert not s.restore_button.isEnabled()
    s.paste_box.clear()  # only the file is left, and its name says which case again
    assert s.case_combo.currentData() == "K4F7" and not s.choose_label.isVisibleTo(s)
    assert s.restore_button.isEnabled()


def test_a_visit_changes_nothing_while_the_cases_are_the_same(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))
    pick(s, "K4F7")
    click_restore(qtbot, s)  # the choice is used up by the restore ...
    assert s.result_panel.isVisibleTo(s)
    s.refresh_cases()  # ... and a visit to the screen does not take the case away again
    assert s.case_combo.currentData() == "K4F7" and s.restore_button.isEnabled()
    assert s.result_panel.isVisibleTo(s) and not s.choose_label.isVisibleTo(s)
    app_ctx.case_store.save(Case("B2C3", NOW, ["Other.docx"], [], the_key()[:1]))  # a new case
    s.refresh_cases()  # now the cases are put in order again, for the file
    assert combo_ids(s) == ["B2C3", "M5N6", "K4F7"] and s.case_combo.currentIndex() == -1
    assert s.choose_label.isVisibleTo(s)


def test_the_one_case_that_fits_best_is_selected_without_a_question(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    two_cases(app_ctx)  # A1A1 holds the person and the company (older), B2B2 the person only
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("[PERSON_1] signs for [COMPANY_1].")))
    assert s.case_combo.currentData() == "A1A1" and not s.choose_label.isVisibleTo(s)
    assert s.restore_button.isEnabled()


def test_when_no_case_fits_the_newest_is_selected_and_nothing_is_asked(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    assert s.case_combo.currentData() == "M5N6" and not s.choose_label.isVisibleTo(s)
    s.load_file(make_docx(body("[PERSON_9] and nothing else.")))  # no case holds it
    assert s.case_combo.currentData() == "M5N6" and not s.choose_label.isVisibleTo(s)
    assert s.file_fit_label.text() == "0 of 1 placeholder found in this case."  # nothing to write


def test_a_choice_made_for_one_file_is_not_carried_to_the_next(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))
    pick(s, "K4F7")
    assert s.case_combo.currentData() == "K4F7"
    s.load_file(make_docx(body("Another contract: [PERSON_1] signs.")))  # fits both alike again
    assert s.case_combo.currentIndex() == -1 and s.choose_label.isVisibleTo(s)
    assert not s.restore_button.isEnabled()


def test_a_choice_ends_with_the_restore_it_was_made_for(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.paste_box.setPlainText("Dear [PERSON_1],")
    pick(s, "K4F7")
    qtbot.mouseClick(s.restore_text_button, CLICK)
    assert s.result_box.toPlainText() == "Dear Alice Smith,"
    assert s.restore_text_button.isEnabled()  # the same text can be restored again
    s.paste_box.setPlainText("The next answer: [PERSON_1] signs.")
    assert s.case_combo.currentIndex() == -1 and not s.restore_text_button.isEnabled()
    pick(s, "M5N6")
    qtbot.mouseClick(s.restore_text_button, CLICK)
    assert s.result_box.toPlainText() == "The next answer: Bob Jones signs."
    s.load_file(make_docx(body("And a file: [PERSON_1].")))  # the pick was for the text
    assert s.case_combo.currentIndex() == -1


def test_the_same_file_can_be_restored_again_with_the_case_chosen_for_it(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    ai = make_docx(body("Dear [PERSON_1], and PERSON_1 too."))
    s.load_file(ai)
    pick(s, "K4F7")
    click_restore(qtbot, s)
    s.altered_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert s.case_combo.currentData() == "K4F7" and s.restore_button.isEnabled()
    click_restore(qtbot, s)
    second = ai.with_name(f"{ai.stem} \N{EN DASH} restored (2).docx")
    assert text_of(second) == "Dear Alice Smith, and Alice Smith too."


def test_the_case_asked_for_in_the_cases_screen_counts_as_chosen_for_the_first_file(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.refresh_cases("K4F7")  # "Restore from this case" in the Cases screen
    s.load_file(make_docx(body("Dear [PERSON_1],")))  # both fit alike: the owner has said which
    assert s.case_combo.currentData() == "K4F7" and not s.choose_label.isVisibleTo(s)


def test_the_case_asked_for_in_the_cases_screen_is_for_the_next_file_even_when_one_is_loaded(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("An earlier answer: [PERSON_1].")))
    pick(s, "M5N6")
    click_restore(qtbot, s)  # the owner is done with that file ...
    s.refresh_cases("K4F7")  # ... and goes to the Cases screen: "Restore from this case"
    assert s.case_combo.currentData() == "K4F7"
    next_answer = make_docx(body("The next answer: [PERSON_1]."))
    s.load_file(next_answer)  # both fit alike, and K4F7 was asked for
    assert s.case_combo.currentData() == "K4F7" and not s.choose_label.isVisibleTo(s)
    s.load_file(make_docx(body("And another: [PERSON_1].")))  # but the request was for one file
    assert s.case_combo.currentIndex() == -1 and s.choose_label.isVisibleTo(s)


def test_when_the_case_chosen_is_deleted_the_one_that_is_left_is_selected(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))
    pick(s, "K4F7")
    app_ctx.case_store.delete("K4F7")  # deleted in the Cases screen
    s.refresh_cases()
    assert combo_ids(s) == ["M5N6"] and s.case_combo.currentData() == "M5N6"  # now the only one
    assert not s.choose_label.isVisibleTo(s)


# ---- a case the owner chose is never replaced by the screen (R103 b, fix round 1) --------------------

BETTER_FIT = "Another case fits this file better \N{EM DASH} check the case."


def test_the_case_asked_for_in_the_cases_screen_stays_though_the_file_fits_another_better(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)  # K4F7: person and company
    s.refresh_cases("M5N6")  # "Restore from this case": the owner asked for Bob Jones's case
    s.load_file(make_docx(body("[PERSON_1] signs for [COMPANY_1].")))  # K4F7 fits this better
    assert s.case_combo.currentData() == "M5N6"  # the screen does not replace it
    assert s.better_fit_label.isVisibleTo(s) and s.better_fit_label.text() == BETTER_FIT
    assert not s.choose_label.isVisibleTo(s)
    assert s.restore_button.isEnabled()  # the owner chose: nothing is taken away
    arrow = "\N{RIGHTWARDS ARROW}"
    assert s.preview_grid.text() == f"[PERSON_1] {arrow} Bob Jones"  # what M5N6 would write
    assert s.file_fit_label.text() == "1 of 2 placeholders found in this case."


@pytest.mark.parametrize("asked_first", [True, False], ids=["asked for first", "file loaded first"])
def test_the_case_asked_for_stays_whichever_comes_first(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, asked_first: bool
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    ai = make_docx(body("[PERSON_1] signs for [COMPANY_1]."))
    if asked_first:
        s.refresh_cases("M5N6")
        s.load_file(ai)
    else:
        s.load_file(ai)
        assert s.case_combo.currentData() == "K4F7"  # the best fit, before anyone asked
        s.refresh_cases("M5N6")
    assert s.case_combo.currentData() == "M5N6" and s.better_fit_label.isVisibleTo(s)


def test_a_case_picked_by_hand_stays_when_the_text_is_edited_and_another_fits_better(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    s.paste_box.setPlainText("[PERSON_1] and [COMPANY_1]")
    assert s.case_combo.currentData() == "K4F7" and not s.better_fit_label.isVisibleTo(s)
    pick(s, "M5N6")  # the owner prefers Bob's
    assert s.better_fit_label.isVisibleTo(s)
    s.paste_box.appendPlainText("one more line")  # an edit re-ranks the cases ...
    assert s.case_combo.currentData() == "M5N6"  # ... and does not take the choice away
    assert s.better_fit_label.isVisibleTo(s) and s.restore_text_button.isEnabled()
    qtbot.mouseClick(s.restore_text_button, CLICK)  # and the restore uses the owner's case
    assert s.result_box.toPlainText() == "Bob Jones and [COMPANY_1]\none more line"


def test_a_chosen_case_is_used_for_the_restore_whatever_fits_better(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    ai = make_docx(body("[PERSON_1] signs for [COMPANY_1]."))
    s.refresh_cases("M5N6")
    s.load_file(ai)
    click_restore(qtbot, s)
    assert text_of(restored_beside(ai)) == "Bob Jones signs for [COMPANY_1]."  # M5N6 has no company
    assert s.report_label.text() == "1 placeholders restored, 0 need your check."
    assert "[COMPANY_1]" in s.unknown_label.text()


def test_the_hint_goes_when_the_owner_picks_the_better_case(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    s.load_file(make_docx(body("PERSON_1 signs for COMPANY_1.")))
    assert s.case_combo.currentData() == "K4F7"  # the best fit: nothing to point out
    assert not s.better_fit_label.isVisibleTo(s)
    pick(s, "M5N6")
    assert s.better_fit_label.isVisibleTo(s) and s.altered_list.count() == 1
    pick(s, "K4F7")  # the owner takes the hint
    assert not s.better_fit_label.isVisibleTo(s) and s.altered_list.count() == 2


def test_the_hint_follows_the_cases_the_store_holds(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)  # both hold the person only
    s.load_file(make_docx(body("[PERSON_1] signs for [COMPANY_1].")))
    pick(s, "M5N6")
    assert not s.better_fit_label.isVisibleTo(s)  # K4F7 does not fit better
    person_and_company = [
        KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "Carol White", []),
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Fabrikam Ltd", []),
    ]
    app_ctx.case_store.save(Case("B2C3", NOW, ["Third.docx"], [], person_and_company))
    s.refresh_cases()  # a case that does fit better was made meanwhile
    assert s.case_combo.currentData() == "M5N6" and s.better_fit_label.isVisibleTo(s)
    app_ctx.case_store.delete("B2C3")
    s.refresh_cases()  # and is gone again
    assert s.case_combo.currentData() == "M5N6" and not s.better_fit_label.isVisibleTo(s)


def test_the_hint_follows_the_selection_however_it_changed(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    s.load_file(make_docx(body("[PERSON_1] signs for [COMPANY_1].")))
    s.case_combo.setCurrentIndex(s.case_combo.findData("M5N6"))  # no click: the combo's own change
    assert s.better_fit_label.isVisibleTo(s)
    s.case_combo.setCurrentIndex(s.case_combo.findData("K4F7"))
    assert not s.better_fit_label.isVisibleTo(s)
    s.case_combo.setCurrentIndex(-1)  # nothing selected: nothing to say about the choice
    assert not s.better_fit_label.isVisibleTo(s)


def test_a_case_named_by_the_file_stays_and_a_better_fit_is_pointed_out(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    ai = named_file(make_docx, tmp_path, "MASKED-M5N6.docx", "[PERSON_1] signs for [COMPANY_1].")
    s.load_file(ai)
    assert s.case_combo.currentData() == "M5N6"  # the name decides ...
    assert s.better_fit_label.isVisibleTo(s)  # ... and the owner is told the placeholders fit K4F7


@pytest.mark.parametrize(
    "lines",
    [("[PERSON_1] signs.",), ("[PERSON_9] and nothing else.",), ("Nothing masked here.",)],
    ids=["fit alike", "nothing fits", "no placeholder"],
)
def test_there_is_no_hint_when_no_case_fits_better_than_the_one_selected(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, lines: tuple[str, ...]
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)  # both hold the person only
    assert not s.better_fit_label.isVisibleTo(s)  # nothing on the screen yet
    s.load_file(make_docx(body(*lines)))
    if s.case_combo.currentIndex() == -1:  # alike: the owner is asked, not told
        assert s.choose_label.isVisibleTo(s)
        pick(s, "K4F7")
    assert s.case_combo.currentIndex() != -1 and not s.better_fit_label.isVisibleTo(s)
    assert not s.choose_label.isVisibleTo(s)


# ---- which values the selected case would put back (ruling R103) ----------------------------------------


def test_the_preview_shows_the_values_the_selected_case_would_put_back(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))
    assert not s.preview_grid.isVisibleTo(s)
    pick(s, "K4F7")
    assert s.preview_grid.isVisibleTo(s)
    assert s.preview_grid.text() == "[PERSON_1] \N{RIGHTWARDS ARROW} Alice Smith"
    pick(s, "M5N6")
    assert (
        s.preview_grid.text() == "[PERSON_1] \N{RIGHTWARDS ARROW} Bob Jones"
    )  # the wrong one shows


def test_the_preview_follows_the_text_and_hides_when_there_is_nothing_to_show(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    assert not screen.preview_grid.isVisibleTo(screen)  # nothing loaded or pasted
    screen.paste_box.setPlainText("Dear [PERSON_1], [PERSON_9] too")
    assert (
        screen.preview_grid.text() == "[PERSON_1] \N{RIGHTWARDS ARROW} John Smith"
    )  # not [PERSON_9]
    screen.paste_box.setPlainText("Dear [PERSON_1], [COMPANY_1] pays")
    assert screen.preview_grid.text().split("\n") == [
        "[PERSON_1] \N{RIGHTWARDS ARROW} John Smith",
        "[COMPANY_1] \N{RIGHTWARDS ARROW} Acme Supplies Ltd",
    ]
    screen.paste_box.setPlainText("Nothing masked here, and [PERSON_9] is not in the case.")
    assert not screen.preview_grid.isVisibleTo(screen) and screen.preview_grid.text() == ""


def test_the_preview_names_at_most_five_placeholders_in_the_order_they_stand(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    people = [
        KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n} of K4F7", [])
        for n in range(1, 9)
    ]
    app_ctx.case_store.save(Case("K4F7", NOW, ["K4F7.docx"], [], people))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(
        make_docx(body("[PERSON_3] [PERSON_1] [PERSON_8] [PERSON_3] [PERSON_2] [PERSON_5]"))
    )
    s.paste_box.setPlainText("[PERSON_7] [PERSON_1] [PERSON_4]")  # the text's come after the file's
    arrow = "\N{RIGHTWARDS ARROW}"
    assert s.preview_grid.text().split("\n") == [
        f"[PERSON_{n}] {arrow} Person {n} of K4F7" for n in (3, 1, 8, 2, 5)
    ]  # each once, five of the seven
    s.load_file(make_docx(body("[PERSON_2]")))
    s.paste_box.clear()
    assert s.preview_grid.text() == f"[PERSON_2] {arrow} Person 2 of K4F7"


def test_the_preview_shows_a_placeholder_the_ai_changed_too(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("The fee is AMOUNT_1.")))  # changed: it waits for a tick
    assert screen.preview_grid.text() == "[AMOUNT_1] \N{RIGHTWARDS ARROW} EUR 1,250,000"


def test_the_preview_is_plain_text_and_keeps_a_long_value_short(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    markup = "<b>Bob</b> & <i>Co</i>"
    long_value = "Brightwater Logistics Holdings " * 10
    entries = [
        KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, markup, []),
        KeyEntry("[ADDRESS_1]", PlaceholderType.ADDRESS, f"Main Street 1,\n{long_value}", []),
    ]
    app_ctx.case_store.save(Case("K4F7", NOW, ["K4F7.docx"], [], entries))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("[COMPANY_1] at [ADDRESS_1]")))
    first, second = s.preview_grid.text().split("\n")
    # The grid is made of labels: none of them reads what it is given as markup.
    shown = [
        label
        for label in s.preview_grid.findChildren(QLabel)
        if label.text().startswith("\N{RIGHTWARDS ARROW}")
    ]
    assert len(shown) == 2 and all(l.textFormat() == Qt.TextFormat.PlainText for l in shown)
    assert first == f"[COMPANY_1] \N{RIGHTWARDS ARROW} {markup}"  # shown as written, not as markup
    assert second.startswith("[ADDRESS_1] \N{RIGHTWARDS ARROW} Main Street 1, Brightwater")
    assert len(second) < 100 and second.endswith("\N{HORIZONTAL ELLIPSIS}")  # and on one line


def test_the_values_of_the_preview_are_never_logged(
    qtbot: QtBot,
    app_ctx: AppContext,
    make_docx: MakeDocx,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        s = screen_with_alice_and_bob(qtbot, app_ctx)
        s.load_file(make_docx(body("Dear [PERSON_1],")))
        pick(s, "K4F7")
        s.paste_box.setPlainText("[PERSON_1] again")
        click_restore(qtbot, s)
    assert "Alice Smith" in s.preview_grid.text()
    assert "Alice" not in caplog.text and "Bob" not in caplog.text and "Smith" not in caplog.text


# ---- what a line of the case list says ---------------------------------------------------------------


def test_a_case_line_carries_the_code_the_files_the_day_and_the_number_of_values(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    case = Case("K4F7", NOW, ["Supply.docx", "Annex.pdf"], [], the_key())
    app_ctx.case_store.save(case)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    line = s.case_combo.itemText(0)
    # The line of the mockup: "K4F7 · supply-01.docx · today 14:02 · 14 values" (it said
    # "K4F7 – Supply.docx, Annex.pdf (2026-10-17 09:00)").
    assert (
        line
        == f"K4F7 \N{MIDDLE DOT} Supply.docx, Annex.pdf \N{MIDDLE DOT} {format_when(NOW)} \N{MIDDLE DOT} 3 values"
    )
    assert s.case_combo.itemData(0, Qt.ItemDataRole.ToolTipRole) == line  # long ones can be read


@pytest.mark.parametrize(("entries", "words"), [(3, "3 values"), (1, "1 value")])
def test_a_case_that_stores_no_file_names_is_told_by_its_code_day_and_values(
    qtbot: QtBot, app_ctx: AppContext, entries: int, words: str
) -> None:
    app_ctx.case_store.save(Case("K4F7", NOW, [], [], the_key()[:entries]))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    line = s.case_combo.itemText(0)
    assert line == f"K4F7 \N{MIDDLE DOT} {format_when(NOW)} \N{MIDDLE DOT} {words}"
    assert "()" not in line and "\N{MIDDLE DOT}  " not in line  # no empty list of files


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
    assert screen.file_label.text() == restore_screen.DROP_TITLE  # the card still asks for a file


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
        not screen.restore_button.isEnabled()
        and screen.file_label.text() == restore_screen.DROP_TITLE  # was "No file chosen yet."
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


# ---- the window's part: the title and the Restore button ------------------------------------------


def test_the_screen_gives_the_window_its_title_and_caption(screen: RestoreScreen) -> None:
    assert screen.title() == (
        "Restore",
        "Put the real values back into the file an AI tool returned",
    )
    heard: list[tuple[str, str]] = []
    screen.titleChanged.connect(lambda title, caption: heard.append((title, caption)))
    screen.titleChanged.emit(*screen.title())  # what the screen does if its words ever change
    assert heard == [screen.title()]


def test_the_windows_restore_button_does_what_the_screens_own_does(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("Dear [PERSON_1],"))
    screen.load_file(ai)
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        screen.primary()
    assert screen.report_label.text() == "1 placeholders restored, 0 need your check."
    assert restored_beside(ai).exists() and screen.result_panel.isVisibleTo(screen)


def test_the_windows_restore_button_does_nothing_while_there_is_no_file(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    screen.paste_box.setPlainText("Dear [PERSON_1],")  # a text is not what that button restores
    with qtbot.assertNotEmitted(screen.restoreFinished):
        screen.primary()
    assert not screen.result_panel.isVisibleTo(screen)


def test_the_screen_says_when_the_windows_restore_button_may_be_pressed(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = RestoreScreen(app_ctx)  # no case in the store yet
    qtbot.addWidget(s)
    heard: list[bool] = []
    s.primaryEnabledChanged.connect(heard.append)
    assert not s.primary_enabled()
    app_ctx.case_store.save(a_case())
    s.load_file(make_docx(body("Dear [PERSON_1],")))
    s.refresh_cases()
    assert s.primary_enabled() and heard == [True] and s.restore_button.isEnabled()
    s.case_combo.setCurrentIndex(-1)  # no case selected: nothing can be restored
    assert not s.primary_enabled() and heard == [True, False]
    s.case_combo.setCurrentIndex(0)
    assert heard == [True, False, True]


def test_the_screens_own_restore_button_goes_when_the_window_has_one(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.show()
    assert screen.restore_button.isVisibleTo(screen)  # alone, the screen can restore
    assert screen.restore_button.objectName() == "primary"
    screen.set_primary_in_toolbar(True)
    assert not screen.restore_button.isVisibleTo(screen)
    screen.load_file(make_docx(body("Dear [PERSON_1],")))
    assert not screen.restore_button.isVisibleTo(screen) and screen.primary_enabled()
    screen.set_primary_in_toolbar(False)
    assert screen.restore_button.isVisibleTo(screen)


# ---- the file card ---------------------------------------------------------------------------------


def test_the_file_card_asks_for_a_file_until_there_is_one(screen: RestoreScreen) -> None:
    zone = screen.drop_zone
    assert zone.objectName() == "fileCard"  # the card of this screen, not the home screen's
    assert screen.file_label is zone.title_label
    assert zone.title_label.text() == restore_screen.DROP_TITLE
    assert zone.hint_label.text() == restore_screen.DROP_HINT
    assert zone.choose_button.text() == "Choose file\N{HORIZONTAL ELLIPSIS}"
    assert zone.illustration is not None
    assert zone.illustration.width() == zone.illustration.height() == 64  # document with a check
    assert zone.shortcut_label.isHidden()  # no key opens this card's dialog


def test_the_file_card_shows_exactly_one_picture(screen: RestoreScreen) -> None:
    from themask.ui.art import Illustration

    screen.show()
    zone = screen.drop_zone
    assert len(zone.findChildren(Illustration)) == 1
    assert not hasattr(zone, "picture")


def test_a_very_long_file_name_does_not_stretch_the_screen(
    screen: RestoreScreen, make_docx: MakeDocx, tmp_path: Path
) -> None:
    name = "A" * 140 + ".docx"
    ai = named_file(make_docx, tmp_path, name, "[PERSON_1] [COMPANY_1] x")
    screen.resize(700, 760)
    screen.show()
    screen.load_file(ai)
    zone = screen.drop_zone
    assert zone.title_label.text() == name  # the whole name is kept and read
    assert zone.title_label.toolTip() == name
    shown = zone.title_label.displayed_text()  # type: ignore[attr-defined]
    assert "\N{HORIZONTAL ELLIPSIS}" in shown and shown.endswith(".docx")
    assert zone.title_label.width() <= zone.width()
    assert screen.scroll_area.horizontalScrollBar().maximum() == 0  # nothing to scroll sideways
    content = screen.scroll_area.widget()
    assert content.minimumSizeHint().width() <= screen.scroll_area.viewport().width()


def test_the_file_card_names_the_file_and_what_is_known_of_it(
    screen: RestoreScreen, make_docx: MakeDocx, tmp_path: Path
) -> None:
    ai = named_file(make_docx, tmp_path, "MASKED-K4F7.docx", "[PERSON_1] [COMPANY_1] [AMOUNT_1] x")
    screen.load_file(ai)
    zone = screen.drop_zone
    assert zone.title_label.text() == "MASKED-K4F7.docx"
    assert zone.title_label.toolTip() == "MASKED-K4F7.docx"
    assert zone.hint_label.text() == (
        "Dropped just now \N{MIDDLE DOT} 3 placeholders found \N{MIDDLE DOT} case K4F7 fits best"
    )
    assert zone.choose_button.text() == "Choose another file\N{HORIZONTAL ELLIPSIS}"
    assert zone.title_label.textFormat() == Qt.TextFormat.PlainText  # a name may hold < >
    assert not screen.file_fit_label.isVisibleTo(screen)  # the case holds all three: nothing to add


def test_one_placeholder_is_not_written_in_the_plural(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("Dear [PERSON_1],")))
    assert "1 placeholder found" in screen.drop_zone.hint_label.text()
    assert "1 placeholders" not in screen.drop_zone.hint_label.text()


def test_the_file_card_says_so_when_the_file_has_no_placeholders(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("Nothing masked here.")))
    assert screen.drop_zone.hint_label.text() == (
        "Dropped just now \N{MIDDLE DOT} No placeholders found"  # and no case fits best
    )
    assert not screen.file_fit_label.isVisibleTo(screen)


def test_the_fit_line_shows_only_when_the_case_lacks_placeholders_of_the_file(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("[PERSON_1] [PERSON_8] [PERSON_9]")))
    assert screen.file_fit_label.isVisibleTo(screen)
    assert screen.file_fit_label.text() == "1 of 3 placeholders found in this case."
    assert "3 placeholders found" in screen.drop_zone.hint_label.text()
    screen.load_file(make_docx(body("[PERSON_1]")))
    assert not screen.file_fit_label.isVisibleTo(screen)


def test_the_card_does_not_say_a_case_fits_best_when_the_owner_chose_it(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    s.load_file(make_docx(body("[PERSON_1] and [COMPANY_1]")))  # K4F7 fits better
    assert s.case_combo.currentData() == "K4F7"
    assert "case K4F7 fits best" in s.drop_zone.hint_label.text()
    pick(s, "M5N6")  # the owner's own choice, which does not
    assert "fits best" not in s.drop_zone.hint_label.text()
    assert s.better_fit_label.isVisibleTo(s)


def test_the_card_says_nothing_of_the_best_fit_while_the_owner_has_to_choose(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(make_docx(body("Dear [PERSON_1],")))  # both cases fit alike: none is selected
    assert s.case_combo.currentIndex() == -1
    assert s.drop_zone.hint_label.text() == ("Dropped just now \N{MIDDLE DOT} 1 placeholder found")


def test_a_file_dropped_on_the_card_is_taken_like_one_dropped_on_the_zone(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("[PERSON_1]"))
    with qtbot.waitSignal(screen.drop_zone.filesDropped, timeout=1000):
        screen.drop_zone._pass_on([ai, ai.with_name("answer.pdf")])  # what a drop does
    assert screen.file_label.text() == ai.name  # the Word file; the PDF is refused in words
    assert restore_screen.ONLY_WORD in screen.status_label.text()


def test_a_drag_over_the_card_marks_it_for_the_style_sheet(screen: RestoreScreen) -> None:
    screen.drop_zone._mark_drag_over(True)
    assert screen.drop_zone.property("dragOver") is True  # `QFrame#fileCard[dragOver="true"]`


# ---- the three state texts of the case card -------------------------------------------------------


def test_a_case_chosen_from_the_name_of_the_file_says_so_in_green(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    assert not s.chosen_label.isVisibleTo(s)
    s.load_file(named_file(make_docx, tmp_path, "MASKED-K4F7.docx", "Dear [PERSON_1],"))
    assert s.case_combo.currentData() == "K4F7"
    assert s.chosen_label.isVisibleTo(s) and s.chosen_label.text() == "Chosen from the file name"
    assert s.chosen_label.contentsMargins().left() > 0  # the room of its tick
    s.load_file(named_file(make_docx, tmp_path, "answer.docx", "Dear [PERSON_1],"))
    assert not s.chosen_label.isVisibleTo(s)  # the name says nothing: the owner is asked instead
    assert s.choose_label.isVisibleTo(s)


def test_a_case_the_owner_chose_is_not_said_to_come_from_the_file_name(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx)
    s.load_file(named_file(make_docx, tmp_path, "MASKED-K4F7.docx", "Dear [PERSON_1],"))
    assert s.chosen_label.isVisibleTo(s)
    pick(s, "K4F7")  # the same case, but now by hand
    assert not s.chosen_label.isVisibleTo(s)


def test_a_case_taken_for_the_pasted_text_is_not_said_to_come_from_the_file_name(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    s.load_file(named_file(make_docx, tmp_path, "MASKED-K4F7.docx", "Dear [PERSON_1],"))
    assert s.chosen_label.isVisibleTo(s)
    s.paste_box.setPlainText("[PERSON_1] [COMPANY_1]")  # now the text decides, not the name
    assert not s.chosen_label.isVisibleTo(s)


def test_the_three_state_texts_are_the_mockup_s(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = screen_with_alice_and_bob(qtbot, app_ctx, company=True)
    assert s.choose_label.text() == "Several cases fit this file \N{EM DASH} choose one."
    assert (
        s.better_fit_label.text()
        == "Another case fits this file better \N{EM DASH} check the case."
    )
    assert s.chosen_label.text() == "Chosen from the file name"
    assert (s.choose_label.objectName(), s.better_fit_label.objectName()) == ("notice", "notice")


# ---- the cards and how they wrap --------------------------------------------------------------------


def corner(screen: RestoreScreen, widget: QWidget) -> tuple[int, int]:
    point = widget.mapTo(screen, widget.rect().topLeft())
    return point.x(), point.y()


def test_the_file_card_and_the_paste_card_sit_side_by_side_on_a_wide_window(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    screen.resize(1180, 760)
    screen.show()
    qtbot.waitExposed(screen)
    paste_card = screen.paste_box.parentWidget()
    assert paste_card is not None
    (file_x, file_y), (paste_x, paste_y) = (
        corner(screen, screen.drop_zone),
        corner(screen, paste_card),
    )
    assert file_y == paste_y and paste_x > file_x + screen.drop_zone.width()  # one row
    assert abs(screen.drop_zone.width() - paste_card.width()) <= 1  # of two equal cards
    assert screen.drop_zone.height() == paste_card.height()


def test_the_cards_wrap_one_under_the_other_on_a_narrow_window(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    screen.resize(620, 760)
    screen.show()
    qtbot.waitExposed(screen)
    paste_card = screen.paste_box.parentWidget()
    assert paste_card is not None
    (file_x, file_y), (paste_x, paste_y) = (
        corner(screen, screen.drop_zone),
        corner(screen, paste_card),
    )
    assert paste_x == file_x and paste_y >= file_y + screen.drop_zone.height()  # one column


def test_the_paste_card_has_a_label_for_its_box_and_the_mockup_s_hint(
    screen: RestoreScreen,
) -> None:
    assert screen.paste_label.text() == "Or paste the AI\N{RIGHT SINGLE QUOTATION MARK}s answer"
    assert screen.paste_label.buddy() is screen.paste_box  # a label for every input
    assert screen.paste_box.placeholderText() == (
        "Paste text with placeholders such as [PERSON_1] here. It is restored on screen;"
        " nothing is written to disk."
    )
    assert screen.restore_text_button.text() == "Restore text"
    assert screen.restore_text_button.objectName() != "primary"  # one primary button per screen


def test_the_case_card_has_a_label_for_its_box(screen: RestoreScreen) -> None:
    labels = [label for label in screen.findChildren(QLabel) if label.buddy() is screen.case_combo]
    assert [label.text() for label in labels] == ["Case"]
    assert screen.case_combo.sizeHint().width() >= 360  # it asks for the mockup's width ...
    assert screen.case_combo.minimumSizeHint().width() <= 200  # ... and gives way when narrow


# ---- the values the case would put back --------------------------------------------------------------


def preview_cells(s: RestoreScreen) -> list[QWidget]:
    """The cells of the preview grid, in the order they stand (row by row)."""
    grid = s.preview_grid
    layout = grid.layout()
    assert layout is not None
    cells = [layout.itemAt(n).widget() for n in range(layout.count())]
    return sorted(cells, key=lambda cell: (cell.pos().y(), cell.pos().x()))


def test_the_preview_is_a_grid_of_three_columns(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    people = [
        KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n}", []) for n in range(1, 6)
    ]
    app_ctx.case_store.save(Case("K4F7", NOW, ["K4F7.docx"], [], people))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.resize(1180, 760)
    s.show()
    s.load_file(make_docx(body("[PERSON_1] [PERSON_2] [PERSON_3] [PERSON_4] [PERSON_5]")))
    qtbot.waitExposed(s)
    cells = preview_cells(s)
    assert len(cells) == 5  # all five, and nothing more to say
    columns = sorted({cell.mapTo(s, cell.rect().topLeft()).x() for cell in cells})
    rows = sorted({cell.mapTo(s, cell.rect().topLeft()).y() for cell in cells})
    assert len(columns) == 3 and len(rows) == 2  # three to a row: 3 + 2
    assert s.preview_grid.more_text() == ""


def test_the_preview_says_how_many_more_there_are(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    people = [
        KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n}", []) for n in range(1, 15)
    ]
    app_ctx.case_store.save(Case("K4F7", NOW, ["K4F7.docx"], [], people))
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body(" ".join(f"[PERSON_{n}]" for n in range(1, 15)))))
    assert len(s.preview_grid.lines()) == 5 and s.preview_grid.more_text() == "and 9 more"
    more = [label for label in s.preview_grid.findChildren(QLabel) if label.text() == "and 9 more"]
    assert len(more) == 1  # the sixth cell of the grid
    assert len(preview_cells(s)) == 6
    s.load_file(make_docx(body("[PERSON_1] [PERSON_2]")))
    assert s.preview_grid.more_text() == "" and len(preview_cells(s)) == 2


def test_the_preview_shows_each_placeholder_in_the_mono_font_and_each_value_beside_it(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("Dear [PERSON_1], [COMPANY_1] pays.")))
    tokens = [
        label
        for label in screen.preview_grid.findChildren(QLabel)
        if label.objectName() == "previewToken"
    ]
    values = [
        label
        for label in screen.preview_grid.findChildren(QLabel)
        if label.objectName() == "previewValue"
    ]
    assert [t.text() for t in tokens] == ["[PERSON_1]", "[COMPANY_1]"]
    assert [v.text() for v in values] == [
        "\N{RIGHTWARDS ARROW} John Smith",
        "\N{RIGHTWARDS ARROW} Acme Supplies Ltd",
    ]
    assert all(t.font().styleHint() == t.font().StyleHint.Monospace for t in tokens)


def test_a_preview_that_has_not_changed_is_not_built_again(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("Dear [PERSON_1],")))
    first = preview_cells(screen)[0]
    screen.paste_box.setPlainText("nothing")  # the same case, the same values
    assert preview_cells(screen)[0] is first


# ---- what the AI changed -----------------------------------------------------------------------------


def row_rect(choices: QListWidget, row: int) -> QRect:
    item = choices.item(row)
    assert item is not None
    return choices.visualItemRect(item)


def test_the_notice_card_shows_only_while_the_ai_changed_something(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.show()
    assert not screen.altered_card.isVisibleTo(screen)
    screen.load_file(make_docx(body("The fee is AMOUNT_1 and [PERSON_1].")))
    assert (
        screen.altered_card.isVisibleTo(screen) and screen.altered_card.objectName() == "noticeCard"
    )
    assert (
        screen.altered_label.text()
        == "These placeholders were changed by the AI \N{EM DASH} restore them?"
    )
    assert screen.altered_list.count() == 1
    screen.load_file(make_docx(body("Nothing changed: [PERSON_1].")))
    assert not screen.altered_card.isVisibleTo(screen) and screen.altered_list.count() == 0


def test_a_row_is_ticked_by_a_click_anywhere_on_it_and_by_the_space_key(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.resize(1180, 760)
    screen.show()
    screen.load_file(make_docx(body("AMOUNT_1 and PERSON_1 and COMPANY_1")))
    qtbot.waitExposed(screen)
    choices = screen.altered_list
    assert ticks(choices) == [False, False, False]
    qtbot.mouseClick(
        choices.viewport(), Qt.MouseButton.LeftButton, pos=row_rect(choices, 1).center()
    )
    assert ticks(choices) == [False, True, False]  # on the text, not only on the box
    qtbot.mouseClick(
        choices.viewport(), Qt.MouseButton.LeftButton, pos=row_rect(choices, 1).center()
    )
    assert ticks(choices) == [False, False, False]
    choices.setFocus()
    choices.setCurrentRow(2)
    qtbot.keyClick(choices, Qt.Key.Key_Space)
    assert ticks(choices) == [False, False, True]  # keyboard: the arrows move, Space ticks
    qtbot.keyClick(choices, Qt.Key.Key_Up)
    qtbot.keyClick(choices, Qt.Key.Key_Space)
    assert ticks(choices) == [False, True, True]
    qtbot.keyClick(choices, Qt.Key.Key_Space)
    assert ticks(choices) == [False, False, True]


def test_a_tick_is_what_the_restore_goes_by(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    ai = make_docx(body("The fee is AMOUNT_1."))
    screen.resize(1180, 760)
    screen.show()
    screen.load_file(ai)
    qtbot.waitExposed(screen)
    qtbot.mouseClick(
        screen.altered_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=row_rect(screen.altered_list, 0).center(),
    )
    with qtbot.waitSignal(screen.restoreFinished, timeout=30000):
        screen.primary()
    assert text_of(restored_beside(ai)) == "The fee is EUR 1,250,000."


def test_a_row_keeps_its_words_for_a_reader_of_the_list(
    screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.load_file(make_docx(body("The fee is AMOUNT_1.")))
    item = screen.altered_list.item(0)
    assert item is not None and item.text() == "AMOUNT_1  \N{RIGHTWARDS ARROW}  [AMOUNT_1]"
    assert item.toolTip() == item.text()
    assert screen.altered_list.accessibleName() == restore_screen.CHANGED


def test_the_list_of_changes_is_as_tall_as_its_rows_up_to_six(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.show()
    heights = []
    for count in (1, 3, 6, 9):
        screen.load_file(make_docx(body(*(f"AMOUNT_1 line {n}" for n in range(count)))))
        heights.append(screen.altered_list.height())
    row = restore_screen.CHANGE_ROW
    assert heights == [row + 2, 3 * row + 2, 6 * row + 2, 6 * row + 2]  # nine scroll in six
    bar = screen.altered_list.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)  # the rest is a scroll away


def test_the_changes_of_a_pasted_text_are_listed_in_the_paste_card(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    screen.show()
    paste_card = screen.paste_box.parentWidget()
    assert paste_card is not None and not screen.text_altered_card.isVisibleTo(screen)
    screen.paste_box.setPlainText("Dear PERSON_1,")
    assert screen.text_altered_card.isVisibleTo(screen)
    assert screen.text_altered_card.parentWidget() is paste_card  # beside the text it is about
    assert screen.text_altered_card.property("inner") is True
    assert screen.text_altered_label.text() == restore_screen.CHANGED
    assert not screen.altered_card.isVisibleTo(screen)  # the file has nothing to confirm
    screen.paste_box.setPlainText("Dear [PERSON_1],")
    assert not screen.text_altered_card.isVisibleTo(screen)


# ---- the result ----------------------------------------------------------------------------------------


def test_the_result_card_of_a_file_names_the_file_and_the_folder_button(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed: list[Path] = []
    monkeypatch.setattr(restore_screen, "reveal", revealed.append)
    ai = make_docx(body("Dear [PERSON_1]. Call [PERSON_9]."))
    screen.show()
    screen.load_file(ai)
    assert not screen.result_panel.isVisibleTo(screen)
    screen.primary()
    assert screen.result_panel.isVisibleTo(screen)
    assert screen.result_panel.property("card") is True
    assert screen.report_label.text() == "1 placeholders restored, 0 need your check."
    assert screen.saved_label.text() == (
        f"Saved as \N{LEFT DOUBLE QUOTATION MARK}{restored_beside(ai).name}"
        "\N{RIGHT DOUBLE QUOTATION MARK} next to the AI\N{RIGHT SINGLE QUOTATION MARK}s file."
    )
    assert screen.unknown_label.text() == "Unknown: [PERSON_9]."
    assert (
        screen.finder_button.isVisibleTo(screen) and screen.finder_button.text() == "Show in Finder"
    )
    assert not screen.copy_button.isVisibleTo(screen) and not screen.result_box.isVisibleTo(screen)
    qtbot.mouseClick(screen.finder_button, CLICK)
    assert revealed == [ai.parent]


def test_the_result_of_a_pasted_text_is_the_box_with_a_copy_button(
    qtbot: QtBot, screen: RestoreScreen
) -> None:
    screen.show()
    screen.paste_box.setPlainText("Dear [PERSON_1], see [PERSON_9].")
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.result_panel.isVisibleTo(screen)
    assert screen.result_box.isVisibleTo(screen) and screen.result_box.isReadOnly()
    assert screen.result_box.toPlainText() == "Dear John Smith, see [PERSON_9]."
    assert screen.copy_button.isVisibleTo(screen) and screen.copy_button.text() == "Copy"
    assert not screen.finder_button.isVisibleTo(screen) and screen.saved_label.isHidden()
    assert (
        screen.report_label.text() == "1 placeholders restored, 0 need your check."
    )  # the report too
    assert screen.unknown_label.text() == "Unknown: [PERSON_9]."
    QApplication.clipboard().setText("something else")
    qtbot.mouseClick(screen.copy_button, CLICK)
    assert QApplication.clipboard().text() == "Dear John Smith, see [PERSON_9]."


def test_the_result_of_a_text_does_not_stay_for_a_file(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx
) -> None:
    screen.show()
    screen.paste_box.setPlainText("Dear [PERSON_1],")
    qtbot.mouseClick(screen.restore_text_button, CLICK)
    assert screen.result_box.isVisibleTo(screen)
    screen.load_file(make_docx(body("[PERSON_1]")))  # a new file clears the result
    assert not screen.result_panel.isVisibleTo(screen) and screen.result_box.toPlainText() == ""
    screen.primary()
    assert screen.result_panel.isVisibleTo(screen) and not screen.result_box.isVisibleTo(screen)


def test_a_status_message_scrolls_the_screen_to_its_top(
    qtbot: QtBot, screen: RestoreScreen, make_docx: MakeDocx, tmp_path: Path
) -> None:
    screen.resize(900, 300)  # a window so short that the screen scrolls
    screen.show()
    screen.load_file(make_docx(body(*(f"AMOUNT_{n} x" for n in range(1, 4)), "[PERSON_1]")))
    qtbot.waitExposed(screen)
    bar = screen.scroll_area.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    screen.drop_zone.filesRefused.emit([tmp_path / "answer.pdf"])
    assert screen.status_label.isVisibleTo(screen) and bar.value() == 0


# ---- the look ----------------------------------------------------------------------------------------


def today_at(hour: int, minute: int) -> datetime:
    """Today at ``hour``:``minute`` on the owner's clock."""
    return datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)


def mockup_key() -> list[KeyEntry]:
    """The key of the case of the mockup: fourteen values."""
    kinds = PlaceholderType
    return [
        KeyEntry("[COMPANY_1]", kinds.COMPANY, "Northwind Trading B.V.", ["Northwind"]),
        KeyEntry("[COMPANY_2]", kinds.COMPANY, "Acme Supplies Ltd", []),
        KeyEntry("[PERSON_1]", kinds.PERSON, "John Carter", ["Mr Carter"]),
        KeyEntry("[AMOUNT_1]", kinds.AMOUNT, "EUR 1,250,000", []),
        KeyEntry("[EMAIL_1]", kinds.EMAIL, "j.carter@acme-supplies.example", []),
        KeyEntry("[IBAN_1]", kinds.IBAN, "NL91 ABNA 0417 1643 00", []),
        KeyEntry("[ADDRESS_1]", kinds.ADDRESS, "Keizersgracht 123, 1015 CJ Amsterdam", []),
        KeyEntry("[PERCENT_1]", kinds.PERCENT, "8 %", []),
        KeyEntry("[QUANTITY_1]", kinds.QUANTITY, "12,000 units", []),
        KeyEntry("[PHONE_1]", kinds.PHONE, "+31 20 555 0101", []),
        KeyEntry("[ID_1]", kinds.ID, "NL853456789B01", []),
        KeyEntry("[URL_1]", kinds.URL, "www.acme-supplies.example", []),
        KeyEntry("[PERSON_2]", kinds.PERSON, "Jane Doe", []),
        KeyEntry("[COMPANY_3]", kinds.COMPANY, "Falcon Freight", []),
    ]


def mockup_screen(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path, restored: bool = True
) -> RestoreScreen:
    """The screen as the Restore mockup shows it: the AI's file dropped (it keeps the code of the
    case in its name, so the case is chosen from it), a second case in the box, the values the
    case would put back, two placeholders the AI changed (one ticked) and, when ``restored``,
    the result. The window's own Restore button is taken to be there.
    """
    first = Case("K4F7", today_at(14, 2), ["supply-01.docx"], [], mockup_key())
    second = Case(
        "Z8Q2",
        today_at(9, 41) - timedelta(days=1),
        ["nda-02.docx", "nda-02-annex.docx"],
        [],
        [
            KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n}", [])
            for n in range(1, 22)
        ],
    )
    app_ctx.case_store.save(first)
    app_ctx.case_store.save(second)
    placeholders = " ".join(entry.placeholder for entry in mockup_key())
    ai = named_file(
        make_docx,
        tmp_path,
        "revised-supply-01-K4F7.docx",
        f"Dear [PERSON 1], the fee is AMOUNT_1. {placeholders}",
        "Please call [PERSON_9] about it.",
    )
    screen = RestoreScreen(app_ctx)
    qtbot.addWidget(screen)
    screen.set_primary_in_toolbar(True)
    screen.resize(1180, 760)
    screen.load_file(ai)
    screen.altered_list.item(row_with(screen.altered_list, "[PERSON 1]")).setCheckState(
        Qt.CheckState.Checked
    )
    if restored:
        screen.primary()
    return screen


def test_the_mockup_screen_says_what_the_mockup_says(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx, tmp_path: Path
) -> None:
    s = mockup_screen(qtbot, app_ctx, make_docx, tmp_path)
    s.show()
    assert s.file_label.text() == "revised-supply-01-K4F7.docx"
    assert s.drop_zone.hint_label.text() == (
        "Dropped just now \N{MIDDLE DOT} 15 placeholders found \N{MIDDLE DOT} case K4F7 fits best"
    )
    assert (
        s.case_combo.currentText()
        == "K4F7 \N{MIDDLE DOT} supply-01.docx \N{MIDDLE DOT} today 14:02 \N{MIDDLE DOT} 14 values"
    )
    assert s.case_combo.itemText(1).startswith(
        "Z8Q2 \N{MIDDLE DOT} nda-02.docx, nda-02-annex.docx \N{MIDDLE DOT} yesterday"
    )
    assert s.case_combo.itemText(1).endswith("\N{MIDDLE DOT} 21 values")
    assert s.chosen_label.isVisibleTo(s)
    assert s.preview_grid.lines()[:2] == [
        "[PERSON_1] \N{RIGHTWARDS ARROW} John Carter",
        "[AMOUNT_1] \N{RIGHTWARDS ARROW} EUR 1,250,000",
    ]
    assert s.preview_grid.more_text() == "and 9 more"
    assert s.report_label.text() == "15 placeholders restored, 1 need your check."


@pytest.mark.parametrize("restored", [False, True], ids=["before", "after"])
def test_the_restore_screen_is_drawn_in_the_colours_of_its_appearance(
    qtbot: QtBot,
    app_ctx: AppContext,
    make_docx: MakeDocx,
    tmp_path: Path,
    d3_appearance: str,
    d3_shot: Callable[[QWidget, str, str], QImage],
    restored: bool,
) -> None:
    t = theme.tokens(d3_appearance)
    s = mockup_screen(qtbot, app_ctx, make_docx, tmp_path, restored=restored)
    s.show()
    qtbot.waitExposed(s)
    qtbot.wait(50)  # the scroll area settles
    image = d3_shot(s, "restore" if restored else "restore-before", d3_appearance)
    assert (image.width(), image.height()) == (1180, 760)
    assert image.pixelColor(2, 2) == QColor(t.ground)  # the screen's ground
    assert not s.scroll_area.verticalScrollBar().isVisible()  # it all fits at 1180 by 760
    assert appears_in(image, t.panel, s.drop_zone, s) and appears_in(
        image, t.panel, s._case_card, s
    )
    assert appears_in(image, t.notice_card_bg, s.altered_card, s)  # the notice card
    assert appears_in(image, t.success_text, s.chosen_label, s)  # "Chosen from the file name"
    assert appears_in(image, t.accent, s.altered_list, s)  # the ticked box is in the accent colour
    if restored:
        assert appears_in(image, t.success, s.result_panel, s) and appears_in(
            image, t.success_bg, s.result_panel, s
        )


def test_the_restore_screen_fits_the_narrowest_window_of_the_app(
    qtbot: QtBot,
    app_ctx: AppContext,
    make_docx: MakeDocx,
    tmp_path: Path,
    d3_appearance: str,
    d3_shot: Callable[[QWidget, str, str], QImage],
) -> None:
    s = mockup_screen(qtbot, app_ctx, make_docx, tmp_path, restored=True)
    s.set_primary_in_toolbar(False)
    s.resize(660, 760)  # a 880-point window less the 220 of its sidebar
    s.show()
    qtbot.waitExposed(s)
    qtbot.wait(50)
    d3_shot(s, "restore-narrow", d3_appearance)
    content = s.scroll_area.widget()
    assert content is not None and content.minimumSizeHint().width() <= 660
    assert not s.scroll_area.horizontalScrollBar().isVisible()  # nothing is cut off at the side
    for part in (s.case_combo, s.chosen_label, s.restore_button, s.drop_zone):
        assert part.mapTo(s, part.rect().bottomRight()).x() <= 660 - 32 + 1, part.objectName()


def test_the_restore_screen_is_drawn_for_a_text_and_for_a_narrow_window_too(
    qtbot: QtBot,
    app_ctx: AppContext,
    make_docx: MakeDocx,
    tmp_path: Path,
    d3_appearance: str,
    d3_shot: Callable[[QWidget, str, str], QImage],
) -> None:
    s = mockup_screen(qtbot, app_ctx, make_docx, tmp_path, restored=False)
    s.set_primary_in_toolbar(False)  # as the screen is without a window's Restore button
    s.paste_box.setPlainText(
        "Dear PERSON_1, the fee is [AMOUNT_1] to [COMPANY_2]. Call [COMPANY_9]."
    )
    s.show()
    qtbot.waitExposed(s)
    qtbot.mouseClick(s.restore_text_button, CLICK)
    s.resize(640, 900)  # the cards wrap
    qtbot.wait(50)
    image = d3_shot(s, "restore-text-narrow", d3_appearance)
    assert image.width() == 640 and s.result_box.isVisibleTo(s) and s.restore_button.isVisibleTo(s)


def test_a_file_whose_placeholders_are_all_owner_names_does_not_say_none_found(
    qtbot: QtBot, app_ctx: AppContext, make_docx: MakeDocx
) -> None:
    named = Case(
        "N4M3",
        NOW,
        ["Named.docx"],
        [],
        [
            KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "Alice Smith", [], "Provider"),
            KeyEntry(
                "[COMPANY_1]", PlaceholderType.COMPANY, "Northwind Trading B.V.", [], "Customer"
            ),
        ],
    )
    app_ctx.case_store.save(named)
    s = RestoreScreen(app_ctx)
    qtbot.addWidget(s)
    s.load_file(make_docx(body("The [Provider] shall deliver to the [Customer].")))
    assert s.file_fit_label.text() == "2 of 2 placeholders found in this case."
    caption = s.drop_zone.hint_label.text()
    assert "No placeholders found" not in caption and "2 placeholders found" in caption
