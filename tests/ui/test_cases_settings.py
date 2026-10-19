"""The Cases and Settings screens.

The brief's tests are a case deleted from the list, the lists and the retention saved, and the
About box that names the owner. The rest cover what the brief leaves to the builder: what the
table shows, that every deletion asks first, the case files that cannot be opened, the buttons
that hand a case to the restore and the analysis, a store that cannot be read, and what saving
does to the lists and the settings the rest of the app is using.
"""

from __future__ import annotations

import errno
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from themask.about import APP_NAME, OWNER_NAME, VERSION
from themask.detect.lists import UserLists
from themask.errors import KeyStoreError
from themask.keystore.crypto import CORRUPT_MESSAGE
from themask.model import Case, KeyEntry, MaskedFile, PlaceholderType
from themask.paths import lists_path
from themask.ui import cases_screen
from themask.ui.app import RETENTION_DAYS, Settings, settings_path
from themask.ui.cases_screen import CasesScreen, format_expiry, format_moment
from themask.ui.settings_screen import SettingsScreen

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext

CLICK = Qt.MouseButton.LeftButton
OCT_10 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
OCT_17 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def a_case(
    case_id: str,
    created: datetime = OCT_17,
    files: list[str] | None = None,
    entries: int = 2,
    days: int = 30,
) -> Case:
    """A case of ``entries`` people, made at ``created``, kept for ``days``."""
    return Case(
        case_id,
        created,
        files if files is not None else [f"{case_id}.docx"],
        [MaskedFile(f"MASKED-{case_id}.docx", "ab" * 32)],
        [
            KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n} of {case_id}", [])
            for n in range(1, entries + 1)
        ],
        days,
    )


def cell(screen: CasesScreen, row: int, column: int) -> str:
    item = screen.table.item(row, column)
    assert item is not None
    return item.text()


def ids(screen: CasesScreen) -> list[str]:
    """The ids in the first column, top to bottom."""
    return [cell(screen, row, 0) for row in range(screen.table.rowCount())]


def damaged_file(ctx: AppContext, case_id: str = "B2C3") -> Path:
    """A file of the case folder that holds no case."""
    ctx.case_store.dir.mkdir(parents=True, exist_ok=True)
    path = ctx.case_store.dir / f"{case_id}.mask"
    path.write_bytes(b"this is not a case")
    return path


@pytest.fixture
def agree(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The questions the screen asked; it is answered yes."""
    asked: list[str] = []

    def yes(parent: object, message: str) -> bool:
        asked.append(message)
        return True

    monkeypatch.setattr(cases_screen, "confirm", yes)
    return asked


@pytest.fixture
def refuse(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The questions the screen asked; it is answered no."""
    asked: list[str] = []

    def no(parent: object, message: str) -> bool:
        asked.append(message)
        return False

    monkeypatch.setattr(cases_screen, "confirm", no)
    return asked


# ---- the Cases screen: the brief's ----------------------------------------------------------------


def test_cases_screen_delete(
    qtbot: QtBot,
    app_ctx: AppContext,
    exported: tuple[Path, Case],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cases_screen, "confirm", lambda *a: True)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.table.rowCount() == 1
    c.table.selectRow(0)
    qtbot.mouseClick(c.delete_button, CLICK)
    assert c.table.rowCount() == 0 and app_ctx.case_store.list() == []


# ---- what the table shows ---------------------------------------------------------------------


def test_the_table_shows_every_case_newest_first(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("B2C3", OCT_10, ["old.docx"], entries=1, days=7))
    app_ctx.case_store.save(a_case("K4F7", OCT_17, ["Supply.docx", "Annex.pdf"], entries=3))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    headers = [c.table.horizontalHeaderItem(n).text() for n in range(c.table.columnCount())]
    assert headers == ["Case", "Created", "Expires", "Files", "Entries"]
    assert ids(c) == ["K4F7", "B2C3"]
    assert cell(c, 0, 1) == format_moment(OCT_17)
    assert cell(c, 0, 2) == format_expiry(a_case("K4F7").expires_at)
    assert cell(c, 0, 3) == "Supply.docx, Annex.pdf" and cell(c, 0, 4) == "3"
    assert cell(c, 1, 3) == "old.docx" and cell(c, 1, 4) == "1"
    assert cell(c, 1, 2) == format_expiry(a_case("B2C3", OCT_10, days=7).expires_at)


def test_the_dates_are_written_the_same_way_in_every_language() -> None:
    local = OCT_17.astimezone()
    assert format_moment(OCT_17) == local.strftime("%Y-%m-%d %H:%M")
    assert format_expiry(OCT_17) == local.strftime("%Y-%m-%d")


def test_an_empty_store_says_so_and_offers_nothing(qtbot: QtBot, app_ctx: AppContext) -> None:
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.table.rowCount() == 0
    assert c.empty_label.isVisibleTo(c) and "No cases" in c.empty_label.text()
    assert not any(
        b.isEnabled()
        for b in (c.delete_button, c.delete_all_button, c.restore_button, c.add_button)
    )


def test_the_table_is_read_only_and_selects_whole_cases(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.table.editTriggers() == c.table.EditTrigger.NoEditTriggers
    item = c.table.item(0, 3)
    assert item is not None and not item.flags() & Qt.ItemFlag.ItemIsEditable
    c.table.selectRow(0)
    assert c.table.selectionBehavior() == c.table.SelectionBehavior.SelectRows
    assert len(c.table.selectionModel().selectedRows()) == 1


def test_refresh_shows_the_cases_the_store_holds_now(qtbot: QtBot, app_ctx: AppContext) -> None:
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.table.rowCount() == 0
    app_ctx.case_store.save(a_case("K4F7"))  # made by an export, say
    c.refresh()
    assert ids(c) == ["K4F7"] and not c.empty_label.isVisibleTo(c)
    app_ctx.case_store.delete("K4F7")
    c.refresh()
    assert ids(c) == [] and c.empty_label.isVisibleTo(c)


# ---- the buttons wait for a case --------------------------------------------------------------


def test_the_buttons_that_act_on_a_case_wait_for_one_to_be_selected(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    for button in (c.delete_button, c.restore_button, c.add_button):
        assert not button.isEnabled()
    assert c.delete_all_button.isEnabled()  # it needs no selection
    c.table.selectRow(0)
    for button in (c.delete_button, c.restore_button, c.add_button):
        assert button.isEnabled()
    c.table.clearSelection()
    assert not c.delete_button.isEnabled()


# ---- deleting asks first ----------------------------------------------------------------------


def test_deleting_a_case_asks_first_and_names_it(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.table.selectRow(0)
    qtbot.mouseClick(c.delete_button, CLICK)
    assert len(agree) == 1 and "K4F7" in agree[0] and "restore" in agree[0].lower()
    assert [s.id for s in app_ctx.case_store.list()] == ["B2C3"] and ids(c) == ["B2C3"]


def test_a_no_keeps_the_case(qtbot: QtBot, app_ctx: AppContext, refuse: list[str]) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.table.selectRow(0)
    qtbot.mouseClick(c.delete_button, CLICK)
    assert len(refuse) == 1
    assert [s.id for s in app_ctx.case_store.list()] == ["K4F7"] and ids(c) == ["K4F7"]


def test_delete_all_asks_first_and_takes_every_file_of_the_folder(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    damaged_file(app_ctx, "Z9Z9")
    leftover = app_ctx.case_store.dir / ".saving-x1y2z3.tmp"
    leftover.write_bytes(b"half a case")
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.unreadable_list.count() == 1
    qtbot.mouseClick(c.delete_all_button, CLICK)
    assert len(agree) == 1 and "2" in agree[0]  # how many cases it is about to delete
    assert list(app_ctx.case_store.dir.iterdir()) == []  # the damaged file and the leftover too
    assert c.table.rowCount() == 0 and c.unreadable_list.count() == 0
    assert not c.unreadable_label.isVisibleTo(c)


def test_delete_all_with_a_no_deletes_nothing(
    qtbot: QtBot, app_ctx: AppContext, refuse: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    qtbot.mouseClick(c.delete_all_button, CLICK)
    assert len(refuse) == 1 and [s.id for s in app_ctx.case_store.list()] == ["K4F7"]


def test_confirm_asks_with_a_question_box(monkeypatch: pytest.MonkeyPatch, qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QMessageBox, QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    answers = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
    asked: list[tuple[object, ...]] = []

    def question(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
        asked.append(args)
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    assert cases_screen.confirm(parent, "Delete it?") is True
    assert cases_screen.confirm(parent, "Delete it?") is False
    assert asked[0][0] is parent and asked[0][1] == APP_NAME and asked[0][2] == "Delete it?"


def test_a_case_that_cannot_be_deleted_is_said_and_stays(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)

    def refused(case_id: str) -> None:
        raise PermissionError(errno.EACCES, "Permission denied", "/Users/someone/cases/K4F7.mask")

    monkeypatch.setattr(app_ctx.case_store, "delete", refused)
    c.table.selectRow(0)
    qtbot.mouseClick(c.delete_button, CLICK)
    assert "Permission denied" in c.status_label.text() and "/Users" not in c.status_label.text()
    assert ids(c) == ["K4F7"]


# ---- case files that cannot be opened ---------------------------------------------------------


def test_a_case_file_that_cannot_be_opened_is_listed_and_can_be_deleted(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    bad = damaged_file(app_ctx)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert ids(c) == ["K4F7"]  # the table lists the cases that open
    assert c.unreadable_list.count() == 1 and c.unreadable_list.item(0).text() == "B2C3.mask"
    assert c.unreadable_label.isVisibleTo(c) and CORRUPT_MESSAGE in c.unreadable_label.text()
    assert not c.delete_unreadable_button.isEnabled()
    c.unreadable_list.setCurrentRow(0)
    assert c.delete_unreadable_button.isEnabled()
    qtbot.mouseClick(c.delete_unreadable_button, CLICK)
    assert len(agree) == 1 and "B2C3.mask" in agree[0]
    assert not bad.exists() and c.unreadable_list.count() == 0
    assert not c.unreadable_label.isVisibleTo(c)
    assert ids(c) == ["K4F7"]  # the case that opens is still there


def test_a_copy_of_a_case_file_under_another_name_is_listed_and_can_be_deleted(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    original = app_ctx.case_store.save(a_case("K4F7"))
    copy = original.with_name("K4F7 (copy).mask")  # made in Finder: no purge ever finds it
    copy.write_bytes(original.read_bytes())
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert ids(c) == ["K4F7"]  # the case is listed once
    assert [c.unreadable_list.item(n).text() for n in range(c.unreadable_list.count())] == [
        "K4F7 (copy).mask"
    ]
    c.unreadable_list.setCurrentRow(0)
    qtbot.mouseClick(c.delete_unreadable_button, CLICK)
    assert not copy.exists() and original.exists()  # only the copy went
    assert ids(c) == ["K4F7"] and c.unreadable_list.count() == 0


def test_a_no_keeps_the_damaged_file(qtbot: QtBot, app_ctx: AppContext, refuse: list[str]) -> None:
    bad = damaged_file(app_ctx)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.unreadable_list.setCurrentRow(0)
    qtbot.mouseClick(c.delete_unreadable_button, CLICK)
    assert bad.exists() and c.unreadable_list.count() == 1


def test_nothing_is_said_about_damaged_files_when_there_are_none(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert not c.unreadable_label.isVisibleTo(c) and not c.unreadable_list.isVisibleTo(c)
    assert not c.delete_unreadable_button.isVisibleTo(c)


def test_a_case_that_cannot_be_opened_does_not_count_as_a_case(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    damaged_file(app_ctx)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.table.rowCount() == 0 and c.empty_label.isVisibleTo(c)
    assert c.delete_all_button.isEnabled()  # there is still something in the folder to clear


# ---- what a case is used for ------------------------------------------------------------------


def test_restore_from_this_case_names_the_case(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.table.selectRow(1)
    with qtbot.waitSignal(c.restoreRequested, timeout=1000) as asked:
        qtbot.mouseClick(c.restore_button, CLICK)
    assert asked.args == ["B2C3"] and c.restore_button.text() == "Restore from this case"


def test_add_file_to_this_case_asks_for_files_and_hands_them_over_with_the_case(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    seen: list[tuple[object, ...]] = []

    def choose(*args: object, **kwargs: object) -> tuple[list[str], str]:
        seen.append(args)
        return ["/somewhere/a.docx", "/somewhere/notes.txt", "/somewhere/b.pdf"], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(choose))
    c.table.selectRow(0)
    with qtbot.waitSignal(c.addFilesRequested, timeout=1000) as chosen:
        qtbot.mouseClick(c.add_button, CLICK)
    assert c.add_button.text() == "Add file to this case"
    assert chosen.args == [[Path("/somewhere/a.docx"), Path("/somewhere/b.pdf")], "K4F7"]
    assert "Contracts (*.docx *.pdf)" in seen[0]  # the dialog offers what the app reads


def test_a_cancelled_file_dialog_adds_nothing(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    c.table.selectRow(0)
    with qtbot.assertNotEmitted(c.addFilesRequested):
        qtbot.mouseClick(c.add_button, CLICK)


# ---- a store that cannot be read ----------------------------------------------------------------


def test_a_store_that_cannot_be_read_is_said_in_the_screen(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    keychain = "The MASK could not reach the macOS Keychain. Unlock it."

    def refuse_list() -> list[object]:
        raise KeyStoreError(keychain)

    monkeypatch.setattr(app_ctx.case_store, "list", refuse_list)
    c = CasesScreen(app_ctx)  # no dialog: the window opens on this screen's neighbours
    qtbot.addWidget(c)
    assert c.status_label.text() == keychain and c.table.rowCount() == 0
    assert not c.empty_label.isVisibleTo(c)  # "No cases yet" would not be true: they cannot be read
    monkeypatch.undo()  # the Keychain is unlocked
    app_ctx.case_store.save(a_case("K4F7"))
    c.refresh()
    assert ids(c) == ["K4F7"] and c.status_label.text() == ""


def test_a_folder_that_cannot_be_read_is_said_in_words(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_list() -> list[object]:
        raise PermissionError(errno.EACCES, "Permission denied", "/Users/someone/cases")

    monkeypatch.setattr(app_ctx.case_store, "list", refuse_list)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert "Permission denied" in c.status_label.text() and "/Users" not in c.status_label.text()
    assert not c.empty_label.isVisibleTo(c)


# ---- the Settings screen: the brief's ---------------------------------------------------------


def test_settings_lists_and_retention(qtbot: QtBot, app_ctx: AppContext) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText("Project Falcon\nSite 7")
    s.retention_spin.setValue(14)
    qtbot.mouseClick(s.save_button, CLICK)
    assert UserLists.load(lists_path()).always_hide == ["Project Falcon", "Site 7"]
    assert app_ctx.settings.retention_days == 14


def test_about_shows_owner(qtbot: QtBot, app_ctx: AppContext) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    assert OWNER_NAME in s.about_label.text() and VERSION in s.about_label.text()


# ---- the Settings screen: the rest --------------------------------------------------------------


def test_the_about_box_says_what_the_app_is_and_how_it_works(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    text = s.about_label.text()
    assert APP_NAME in text
    assert "Runs fully offline. Restored text you copy is on the clipboard in clear." in text
    assert s.about_label.textFormat() == Qt.TextFormat.PlainText  # the owner's name may hold < >


def test_the_fields_show_what_is_kept_and_reload_picks_up_changes_made_elsewhere(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path
) -> None:
    app_ctx.user_lists.add_always("Project Falcon")
    app_ctx.user_lists.add_never("Site 7")
    app_ctx.settings.retention_days = 21
    app_ctx.settings.out_dir = tmp_path / "out"
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    assert s.always_edit.toPlainText() == "Project Falcon"
    assert s.never_edit.toPlainText() == "Site 7"
    assert s.retention_spin.value() == 21 and s.folder_edit.text() == str(tmp_path / "out")
    app_ctx.user_lists.add_always("Site 9")  # the review's "Always hide" button, say
    s.always_edit.setPlainText("typed but never saved")
    s.reload()
    assert s.always_edit.toPlainText() == "Project Falcon\nSite 9"  # what is kept, not the draft


def test_nothing_is_kept_until_save_is_clicked(qtbot: QtBot, app_ctx: AppContext) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText("Project Falcon")
    s.retention_spin.setValue(3)
    assert app_ctx.user_lists.always_hide == [] and app_ctx.settings.retention_days == 30
    assert UserLists.load(lists_path()).always_hide == [] and not settings_path().exists()


def test_saving_updates_the_lists_the_app_is_using_in_place(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    lists = app_ctx.user_lists  # the review and the analysis hold this very object
    settings = app_ctx.settings
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText("Project Falcon")
    s.never_edit.setPlainText("Falcon Freight")
    s.retention_spin.setValue(14)
    qtbot.mouseClick(s.save_button, CLICK)
    assert app_ctx.user_lists is lists and app_ctx.settings is settings
    assert lists.always_hide == ["Project Falcon"] and lists.never_hide == ["Falcon Freight"]
    assert settings.retention_days == 14
    assert UserLists.load(lists_path()) == UserLists(["Project Falcon"], ["Falcon Freight"])
    assert s.status_label.text() == "Saved."


def test_blank_lines_spaces_and_repeats_are_cleaned_up(qtbot: QtBot, app_ctx: AppContext) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText(
        "  Project Falcon  \n\nproject falcon\nSite 7\n COMPANY:Falcon Freight\nID:\n"
    )
    s.never_edit.setPlainText("\nthe Buyer's\nBUYER\n   \n")
    qtbot.mouseClick(s.save_button, CLICK)
    assert app_ctx.user_lists.always_hide == ["Project Falcon", "Site 7", "COMPANY:Falcon Freight"]
    assert app_ctx.user_lists.never_hide == ["the Buyer's"]
    # What was saved is what the owner now sees.
    assert s.always_edit.toPlainText() == "Project Falcon\nSite 7\nCOMPANY:Falcon Freight"
    assert s.never_edit.toPlainText() == "the Buyer's"


def test_a_value_on_both_lists_is_refused_and_nothing_is_saved(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText("Project Falcon\nFalcon Freight")
    s.never_edit.setPlainText("the falcon freight")  # the same value, as the lists compare them
    s.retention_spin.setValue(14)
    qtbot.mouseClick(s.save_button, CLICK)
    assert "Falcon Freight" in s.status_label.text() and "both" in s.status_label.text()
    assert app_ctx.user_lists == UserLists([], []) and app_ctx.settings.retention_days == 30
    assert UserLists.load(lists_path()) == UserLists([], []) and not settings_path().exists()


def test_the_retention_runs_from_a_day_to_a_year_and_starts_where_it_is_kept(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    assert (s.retention_spin.minimum(), s.retention_spin.maximum()) == (1, 365)
    assert (s.retention_spin.minimum(), s.retention_spin.maximum()) == (
        RETENTION_DAYS[0],
        RETENTION_DAYS[-1],
    )
    assert s.retention_spin.value() == 30  # the default
    s.retention_spin.setValue(1000)
    assert s.retention_spin.value() == 365


def test_the_folder_is_chosen_with_the_system_dialog_and_kept_on_save(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    picked = tmp_path / "Masked files"
    asked: list[tuple[object, ...]] = []

    def choose(*args: object, **kwargs: object) -> str:
        asked.append(args)
        return str(picked)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(choose))
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    before = app_ctx.settings.out_dir
    qtbot.mouseClick(s.folder_button, CLICK)
    assert len(asked) == 1 and s.folder_edit.text() == str(picked)
    assert app_ctx.settings.out_dir == before  # only the form changed
    s.retention_spin.setValue(14)
    qtbot.mouseClick(s.save_button, CLICK)
    assert app_ctx.settings.out_dir == picked
    assert Settings.load(settings_path()) == Settings(14, picked)
    assert json.loads(settings_path().read_text(encoding="utf-8"))["out_dir"] == str(picked)


def test_a_cancelled_folder_dialog_keeps_the_folder(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    shown = s.folder_edit.text()
    qtbot.mouseClick(s.folder_button, CLICK)
    assert s.folder_edit.text() == shown == str(app_ctx.settings.out_dir)


def test_lists_that_cannot_be_saved_are_said_and_change_nothing(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full_disk(self: UserLists, path: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device", str(path))

    monkeypatch.setattr(UserLists, "save", full_disk)
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText("Project Falcon")
    s.retention_spin.setValue(14)
    qtbot.mouseClick(s.save_button, CLICK)
    assert "No space left on device" in s.status_label.text()
    assert str(lists_path()) not in s.status_label.text()
    assert app_ctx.user_lists.always_hide == [] and app_ctx.settings.retention_days == 30
    assert not settings_path().exists()  # nothing was half done


def test_settings_that_cannot_be_saved_are_said_after_the_lists_were_kept(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full_disk(self: Settings, path: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device", str(path))

    monkeypatch.setattr(Settings, "save", full_disk)
    s = SettingsScreen(app_ctx)
    qtbot.addWidget(s)
    s.always_edit.setPlainText("Project Falcon")
    s.retention_spin.setValue(14)
    qtbot.mouseClick(s.save_button, CLICK)
    text = s.status_label.text()
    assert "No space left on device" in text and "lists were saved" in text
    assert app_ctx.user_lists.always_hide == ["Project Falcon"]  # kept, on disk and in use
    assert UserLists.load(lists_path()).always_hide == ["Project Falcon"]
    assert app_ctx.settings.retention_days == 30  # the settings were not
