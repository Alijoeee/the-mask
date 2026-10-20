"""The Cases and Settings screens.

The brief's tests are a case deleted from the list, the lists and the retention saved, and the
About box that names the owner. The rest cover what the brief leaves to the builder: what the
table shows, that every deletion asks first, the case files that cannot be opened, the buttons
that hand a case to the restore and the analysis, a store that cannot be read, and what saving
does to the lists and the settings the rest of the app is using.

The design pass changed the Cases screen (the last section of its tests is new): the table has
the columns Code, Files, Exported, Expires and Values; "Delete…" is a button with a menu (Delete
this case, Delete all cases: ``delete_case_action`` and ``delete_all_action``, which are what
the old Delete and Delete all buttons were); a case file that cannot be opened is a grey row of
the table with a Delete button of its own (``unreadable_buttons``), not a list below it; and the
screen reads the cases themselves (``load_all``) for the card that says what the selected one
holds, so what the store cannot read is the store's ``load_all`` that fails, not ``list``.
"""

from __future__ import annotations

import errno
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from tests.fixtures.d3_look import appears_in
from themask.about import APP_NAME, OWNER_NAME, VERSION
from themask.detect.lists import UserLists
from themask.errors import KeyStoreError
from themask.keystore.crypto import CORRUPT_MESSAGE
from themask.model import Case, KeyEntry, MaskedFile, PlaceholderType
from themask.paths import lists_path
from themask.ui import cases_screen, theme
from themask.ui.app import RETENTION_DAYS, Settings, settings_path
from themask.ui.cases_screen import (
    CasesScreen,
    days_left,
    describe_expiry,
    describe_holds,
    format_date,
    format_expiry,
    format_exported,
    format_moment,
    format_when,
)
from themask.ui.settings_screen import SettingsScreen
from themask.ui.theme import mono_font

if TYPE_CHECKING:
    from PySide6.QtGui import QImage
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
    """The codes of the cases in the first column, top to bottom (a grey row for a file that
    cannot be opened is not a case).
    """
    rows = range(screen.table.rowCount())
    return [
        cell(screen, row, 0)
        for row in rows
        if screen.table.item(row, 0).data(cases_screen.CASE_ROLE) is not None  # type: ignore[union-attr]
    ]


def damaged_rows(screen: CasesScreen) -> list[str]:
    """The names of the case files that cannot be opened, as the grey rows say them."""
    return list(screen.unreadable_buttons)


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
    # "Delete…" opens a menu: its first item is what the Delete button was.
    menu = c.delete_button.menu()
    assert menu is not None and menu.actions()[0] is c.delete_case_action
    c.delete_case_action.trigger()
    assert c.table.rowCount() == 0 and app_ctx.case_store.list() == []


# ---- what the table shows ---------------------------------------------------------------------


def test_the_table_shows_every_case_newest_first(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("B2C3", OCT_10, ["old.docx"], entries=1, days=7))
    app_ctx.case_store.save(a_case("K4F7", OCT_17, ["Supply.docx", "Annex.pdf"], entries=3))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    headers = [c.table.horizontalHeaderItem(n).text() for n in range(c.table.columnCount())]
    # The columns of the mockup (they were "Case", "Created", "Expires", "Files", "Entries").
    assert headers == ["Code", "Files", "Exported", "Expires", "Values"]
    assert ids(c) == ["K4F7", "B2C3"]
    assert cell(c, 0, 1) == "Supply.docx, Annex.pdf" and cell(c, 0, 4) == "3"
    assert cell(c, 1, 1) == "old.docx" and cell(c, 1, 4) == "1"
    assert cell(c, 0, 2) == format_exported(OCT_17)
    assert cell(c, 1, 2) == format_exported(OCT_10)
    assert cell(c, 0, 3) == describe_expiry(a_case("K4F7").expires_at)[0]
    assert cell(c, 1, 3) == describe_expiry(a_case("B2C3", OCT_10, days=7).expires_at)[0]


def test_the_expiry_counts_the_days_the_case_is_kept_for_not_a_fixed_thirty(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    now = datetime.now().astimezone()
    app_ctx.settings.retention_days = 45
    app_ctx.case_store.save(a_case("K4F7", created=now, days=app_ctx.settings.retention_days))
    app_ctx.case_store.save(a_case("Z8Q2", created=now, days=14))
    screen = CasesScreen(app_ctx)
    qtbot.addWidget(screen)
    texts = {ids(screen)[r]: cell(screen, r, cases_screen.EXPIRES_COLUMN) for r in range(2)}
    assert texts["K4F7"].endswith("\N{MIDDLE DOT} 45 days")
    assert texts["Z8Q2"].endswith("\N{MIDDLE DOT} 14 days")


def test_the_dates_are_written_the_same_way_in_every_language() -> None:
    local = OCT_17.astimezone()
    assert format_moment(OCT_17) == local.strftime("%Y-%m-%d %H:%M")
    assert format_expiry(OCT_17) == local.strftime("%Y-%m-%d")


def test_a_moment_is_said_as_today_yesterday_or_the_day() -> None:
    now = datetime(2026, 10, 19, 15, 30).astimezone()  # the owner's clock
    earlier_today = now.replace(hour=14, minute=2)
    yesterday = (now - timedelta(days=1)).replace(hour=9, minute=41)
    last_week = (now - timedelta(days=7)).replace(hour=23, minute=59)
    assert format_when(earlier_today, now) == "today 14:02"
    assert format_when(yesterday, now) == "yesterday 09:41"
    assert format_when(last_week, now) == "12 Oct 2026"
    assert format_exported(earlier_today, now) == "Today, 14:02"
    assert format_exported(yesterday, now) == "Yesterday, 09:41"
    assert format_exported(last_week, now) == "12 Oct 2026"
    assert format_date(now) == "19 Oct 2026"


def test_a_day_is_the_calendar_day_not_a_span_of_24_hours() -> None:
    now = datetime(2026, 10, 19, 0, 10).astimezone()
    just_before_midnight = datetime(2026, 10, 18, 23, 50).astimezone()  # 20 minutes ago
    assert format_when(just_before_midnight, now) == "yesterday 23:50"
    assert format_when(datetime(2026, 10, 17, 23, 55).astimezone(), now) == "17 Oct 2026"


@pytest.mark.parametrize(
    ("month", "name"),
    [(1, "Jan"), (3, "Mar"), (5, "May"), (8, "Aug"), (11, "Nov"), (12, "Dec")],
)
def test_the_month_is_three_english_letters_in_every_language(month: int, name: str) -> None:
    assert format_date(datetime(2026, month, 5, 12, 0).astimezone()) == f"5 {name} 2026"


def test_an_empty_store_says_so_and_offers_nothing(qtbot: QtBot, app_ctx: AppContext) -> None:
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.table.rowCount() == 0
    assert c.empty_label.isVisibleTo(c) and "No cases" in c.empty_label.text()
    assert not any(b.isEnabled() for b in (c.delete_button, c.restore_button, c.add_button))
    assert not c.delete_case_action.isEnabled() and not c.delete_all_action.isEnabled()
    assert not c.table.isVisibleTo(c)  # nothing to list: the line says so


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
    for button in (c.restore_button, c.add_button):
        assert not button.isEnabled()
    assert not c.delete_case_action.isEnabled()  # no case selected: "Delete this case" waits
    assert c.delete_all_action.isEnabled()  # it needs no selection, so the menu is there
    assert c.delete_button.isEnabled()
    c.table.selectRow(0)
    for button in (c.restore_button, c.add_button):
        assert button.isEnabled()
    assert c.delete_case_action.isEnabled()
    c.table.clearSelection()
    assert not c.delete_case_action.isEnabled() and not c.restore_button.isEnabled()


# ---- deleting asks first ----------------------------------------------------------------------


def test_deleting_a_case_asks_first_and_names_it(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.table.selectRow(0)
    c.delete_case_action.trigger()
    assert len(agree) == 1 and "K4F7" in agree[0] and "restore" in agree[0].lower()
    assert [s.id for s in app_ctx.case_store.list()] == ["B2C3"] and ids(c) == ["B2C3"]


def test_a_no_keeps_the_case(qtbot: QtBot, app_ctx: AppContext, refuse: list[str]) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.table.selectRow(0)
    c.delete_case_action.trigger()
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
    assert damaged_rows(c) == ["Z9Z9.mask"]
    c.delete_all_action.trigger()
    assert len(agree) == 1 and "2" in agree[0]  # how many cases it is about to delete
    assert list(app_ctx.case_store.dir.iterdir()) == []  # the damaged file and the leftover too
    assert c.table.rowCount() == 0 and damaged_rows(c) == []
    assert not c.unreadable_label.isVisibleTo(c)


def test_delete_all_with_a_no_deletes_nothing(
    qtbot: QtBot, app_ctx: AppContext, refuse: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    c.delete_all_action.trigger()
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
    c.delete_case_action.trigger()
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
    assert ids(c) == ["K4F7"]  # the cases that open are the cases ...
    assert damaged_rows(c) == ["B2C3.mask"]  # ... and the file that does not is a grey row after
    assert cell(c, 1, 1) == "B2C3.mask \N{MIDDLE DOT} cannot be read"
    assert c.unreadable_label.isVisibleTo(c) and CORRUPT_MESSAGE in c.unreadable_label.text()
    button = c.unreadable_buttons["B2C3.mask"]  # its own Delete button, in the row
    assert button.text() == "Delete" and button.isEnabled()
    assert c.table.cellWidget(1, 4) is not None
    qtbot.mouseClick(button, CLICK)
    assert len(agree) == 1 and "B2C3.mask" in agree[0]
    assert not bad.exists() and damaged_rows(c) == []
    assert not c.unreadable_label.isVisibleTo(c)
    assert ids(c) == ["K4F7"] and c.table.rowCount() == 1  # the case that opens is still there


def test_a_copy_of_a_case_file_under_another_name_is_listed_and_can_be_deleted(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    original = app_ctx.case_store.save(a_case("K4F7"))
    copy = original.with_name("K4F7 (copy).mask")  # made in Finder: no purge ever finds it
    copy.write_bytes(original.read_bytes())
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert ids(c) == ["K4F7"]  # the case is listed once
    assert damaged_rows(c) == ["K4F7 (copy).mask"]
    qtbot.mouseClick(c.unreadable_buttons["K4F7 (copy).mask"], CLICK)
    assert not copy.exists() and original.exists()  # only the copy went
    assert ids(c) == ["K4F7"] and damaged_rows(c) == []


def test_a_no_keeps_the_damaged_file(qtbot: QtBot, app_ctx: AppContext, refuse: list[str]) -> None:
    bad = damaged_file(app_ctx)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    qtbot.mouseClick(c.unreadable_buttons["B2C3.mask"], CLICK)
    assert bad.exists() and damaged_rows(c) == ["B2C3.mask"]


def test_nothing_is_said_about_damaged_files_when_there_are_none(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert not c.unreadable_label.isVisibleTo(c) and damaged_rows(c) == []
    assert c.table.rowCount() == 1  # the case alone: no grey row


def test_a_case_that_cannot_be_opened_does_not_count_as_a_case(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    damaged_file(app_ctx)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert ids(c) == [] and c.empty_label.isVisibleTo(c)  # the grey row is no case
    assert damaged_rows(c) == ["B2C3.mask"] and c.table.rowCount() == 1
    assert c.delete_all_action.isEnabled()  # there is still something in the folder to clear


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
    assert c.add_button.text() == "Add a file to this case"  # (it said "Add file to this case")
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

    monkeypatch.setattr(app_ctx.case_store, "load_all", refuse_list)  # (it was ``list``)
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

    monkeypatch.setattr(app_ctx.case_store, "load_all", refuse_list)  # (it was ``list``)
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert "Permission denied" in c.status_label.text() and "/Users" not in c.status_label.text()
    assert not c.empty_label.isVisibleTo(c)


# ---- the Cases screen of the mockup --------------------------------------------------------------


def mockup_cases(ctx: AppContext) -> None:
    """The cases of the Cases mockup: K4F7 exported today (fourteen values of seven kinds), Z8Q2
    yesterday (two files), P3XM a week ago with three days left, and a case file that cannot be
    opened.
    """
    kinds = PlaceholderType
    values = (
        [(kinds.COMPANY, "Northwind Trading B.V."), (kinds.COMPANY, "Acme Supplies Ltd")]
        + [(kinds.PERSON, "John Carter"), (kinds.PERSON, "Jane Doe")]
        + [(kinds.AMOUNT, "EUR 1,250,000"), (kinds.AMOUNT, "EUR 80,000")]
        + [(kinds.ADDRESS, "Keizersgracht 123, 1015 CJ Amsterdam")]
        + [(kinds.EMAIL, "j.carter@acme-supplies.example")]
        + [(kinds.IBAN, "NL91 ABNA 0417 1643 00")]
        + [(kinds.PERCENT, "8 %"), (kinds.PHONE, "+31 20 555 0101"), (kinds.ID, "NL853456789B01")]
        + [(kinds.URL, "www.acme-supplies.example"), (kinds.QUANTITY, "12,000 units")]
    )
    key = [
        KeyEntry(f"[{kind.value}_{n}]", kind, value, [])
        for n, (kind, value) in enumerate(values, start=1)
    ]
    now = datetime.now().astimezone()  # the owner's clock: "today" is the day on it
    first = Case(
        "K4F7",
        now.replace(hour=14, minute=2, second=0, microsecond=0),
        ["supply-01.docx"],
        [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
        key,
    )
    second_key = [
        KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n}", []) for n in range(21)
    ]
    second = Case(
        "Z8Q2",
        now.replace(hour=9, minute=41, second=0, microsecond=0) - timedelta(days=1),
        ["nda-02.docx", "nda-02-annex.docx"],
        [MaskedFile("MASKED-Z8Q2-1.docx", "ab" * 32), MaskedFile("MASKED-Z8Q2-2.docx", "cd" * 32)],
        second_key,
    )
    third = Case(
        "P3XM",
        now - timedelta(days=7),
        ["services-03.pdf"],
        [MaskedFile("MASKED-P3XM.docx", "ef" * 32)],
        key[:9],
        retention_days=10,
    )
    for case in (first, second, third):
        ctx.case_store.save(case)
    damaged_file(ctx, "W7KD")


def cases_screen_of(qtbot: QtBot, ctx: AppContext) -> CasesScreen:
    """The screen at the size of the mockups, with the owner's folder where it is by default."""
    ctx.settings.out_dir = Path.home() / "Documents" / "The MASK"
    c = CasesScreen(ctx)
    qtbot.addWidget(c)
    c.resize(1180, 760)
    return c


def cell_rect(c: CasesScreen, row: int, column: int) -> QRect:
    """Where the cell is, in the coordinates of the screen."""
    item = c.table.item(row, column)
    assert item is not None
    rect = c.table.visualItemRect(item)
    return QRect(c.table.viewport().mapTo(c, rect.topLeft()), rect.size())


def shows(image: QImage, colour: str, rect: QRect) -> bool:
    """Whether a pixel of ``rect`` in the picture has the colour."""
    wanted = QColor(colour).rgb()
    return any(
        image.pixel(x, y) == wanted
        for x in range(rect.left(), rect.right() + 1)
        for y in range(rect.top(), rect.bottom() + 1)
    )


def test_the_screen_gives_the_window_its_title_and_the_new_case_button_its_work(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    assert c.title() == (
        "Cases",
        "The keys that put real values back \N{MIDDLE DOT} kept on this Mac, encrypted",
    )
    heard: list[tuple[str, str]] = []
    c.titleChanged.connect(lambda title, caption: heard.append((title, caption)))
    c.titleChanged.emit(*c.title())  # what the screen does if its words ever change
    assert heard == [c.title()]
    with qtbot.waitSignal(c.newCaseRequested, timeout=1000):
        c.primary()  # "New case" in the tool bar of the window
    with qtbot.assertNotEmitted(c.newCaseRequested):
        c.table.clearSelection()


def test_there_is_no_primary_button_on_the_screen_the_window_has_it(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = CasesScreen(app_ctx)
    qtbot.addWidget(c)
    primaries = [b for b in c.findChildren(QPushButton) if b.objectName() == "primary"]
    assert primaries == []  # "New case" is the tool bar's: one primary button per screen
    assert [b.text() for b in (c.restore_button, c.add_button)] == [
        "Restore from this case",
        "Add a file to this case",
    ]


# ---- the filter -----------------------------------------------------------------------------------


def filtered_screen(qtbot: QtBot, ctx: AppContext) -> CasesScreen:
    ctx.case_store.save(a_case("K4F7", OCT_17, ["supply-01.docx"]))
    ctx.case_store.save(a_case("Z8Q2", OCT_10, ["nda-02.docx", "nda-02-annex.docx"]))
    ctx.case_store.save(a_case("P3XM", OCT_10.replace(day=9), ["services-03.pdf"]))
    c = cases_screen_of(qtbot, ctx)
    c.show()
    return c


def visible_codes(c: CasesScreen) -> list[str]:
    return [
        cell(c, row, 0)
        for row in range(c.table.rowCount())
        if not c.table.isRowHidden(row) and c.table.item(row, 0).data(cases_screen.CASE_ROLE)  # type: ignore[union-attr]
    ]


def test_the_filter_is_a_field_of_260_points_with_a_label_and_a_magnifier(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = filtered_screen(qtbot, app_ctx)
    assert c.filter_edit.width() == 260
    assert c.filter_edit.placeholderText() == "Filter by file or code"
    assert c.filter_edit.accessibleName() == "Filter cases"  # a label for every input
    assert c.filter_edit.isClearButtonEnabled()
    assert not c.filter_edit.actions()[0].icon().isNull()  # the magnifier


def test_the_filter_keeps_the_rows_whose_file_names_or_code_hold_what_is_typed(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = filtered_screen(qtbot, app_ctx)
    assert visible_codes(c) == ["K4F7", "Z8Q2", "P3XM"]
    c.filter_edit.setText("nda")  # a file name (two of them, in one case)
    assert visible_codes(c) == ["Z8Q2"]
    c.filter_edit.setText("ANNEX")  # whatever the case of the letters
    assert visible_codes(c) == ["Z8Q2"]
    c.filter_edit.setText("k4f")  # the code
    assert visible_codes(c) == ["K4F7"]
    c.filter_edit.setText("  p3xm ")  # and the spaces round it
    assert visible_codes(c) == ["P3XM"]
    c.filter_edit.setText("pdf")
    assert visible_codes(c) == ["P3XM"]
    c.filter_edit.clear()
    assert visible_codes(c) == ["K4F7", "Z8Q2", "P3XM"] and c.table.isVisibleTo(c)


def test_a_filter_that_matches_nothing_says_so_and_gives_the_table_back_when_cleared(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = filtered_screen(qtbot, app_ctx)
    c.filter_edit.setText("nothing like this")
    assert not c.table.isVisibleTo(c) and c.empty_label.isVisibleTo(c)
    assert c.empty_label.text() == "No case matches that filter."
    c.filter_edit.clear()
    assert c.table.isVisibleTo(c) and not c.empty_label.isVisibleTo(c)


def test_the_filter_never_says_there_are_no_cases_when_there_are(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = CasesScreen(app_ctx)  # an empty store
    qtbot.addWidget(c)
    c.filter_edit.setText("something")
    assert c.empty_label.text() == cases_screen.NO_CASES  # there are none: not "no match"


def test_a_case_the_filter_takes_away_is_no_longer_selected(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = filtered_screen(qtbot, app_ctx)
    c.table.selectRow(0)  # K4F7
    assert c.detail_card.isVisibleTo(c) and c.restore_button.isEnabled()
    c.filter_edit.setText("nda")
    assert c.table.selectionModel().selectedRows() == []  # it would act on a row nobody sees
    assert not c.detail_card.isVisibleTo(c) and not c.restore_button.isEnabled()
    assert not c.delete_case_action.isEnabled() and c.delete_all_action.isEnabled()


def test_a_case_the_filter_keeps_stays_selected(qtbot: QtBot, app_ctx: AppContext) -> None:
    c = filtered_screen(qtbot, app_ctx)
    c.table.selectRow(1)  # Z8Q2
    c.filter_edit.setText("z8q")
    assert c._selected_case() == "Z8Q2" and c.detail_card.isVisibleTo(c)


def test_the_filter_looks_for_a_file_that_cannot_be_opened_by_its_name(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    damaged_file(app_ctx, "B2C3")
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    c.filter_edit.setText("b2c3")
    assert visible_codes(c) == [] and not c.table.isRowHidden(1) and c.table.isRowHidden(0)
    assert c.table.isVisibleTo(c)  # the grey row is left to see
    c.filter_edit.setText("k4f7")
    assert visible_codes(c) == ["K4F7"] and c.table.isRowHidden(1)


def test_the_filter_is_kept_when_the_screen_is_refreshed(qtbot: QtBot, app_ctx: AppContext) -> None:
    c = filtered_screen(qtbot, app_ctx)
    c.filter_edit.setText("nda")
    app_ctx.case_store.save(a_case("N7N7", OCT_17, ["nda-07.docx"]))  # an export made it
    c.refresh()
    assert visible_codes(c) == ["N7N7", "Z8Q2"]


# ---- the Delete menu ------------------------------------------------------------------------------


def test_delete_is_a_button_with_a_menu_of_two_items(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = cases_screen_of(qtbot, app_ctx)
    button = c.delete_button
    assert isinstance(button, QToolButton)
    assert button.text() == "Delete\N{HORIZONTAL ELLIPSIS}"
    assert button.accessibleName() == "Delete\N{HORIZONTAL ELLIPSIS}"
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    menu = button.menu()
    assert menu is not None
    assert [action.text() for action in menu.actions()] == ["Delete this case", "Delete all cases"]
    assert menu.actions() == [c.delete_case_action, c.delete_all_action]


def test_both_items_of_the_menu_ask_first(
    qtbot: QtBot, app_ctx: AppContext, refuse: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = cases_screen_of(qtbot, app_ctx)
    c.table.selectRow(0)
    c.delete_case_action.trigger()
    assert len(refuse) == 1 and "K4F7" in refuse[0]
    c.delete_all_action.trigger()
    assert len(refuse) == 2 and "2 saved cases" in refuse[1]
    assert len(app_ctx.case_store.list()) == 2  # a no deleted nothing


def test_the_menu_is_off_while_there_is_nothing_to_delete(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    c = cases_screen_of(qtbot, app_ctx)
    assert not c.delete_button.isEnabled()
    app_ctx.case_store.save(a_case("K4F7"))
    c.refresh()
    assert c.delete_button.isEnabled() and c.delete_all_action.isEnabled()
    assert not c.delete_case_action.isEnabled()  # until a case is selected


def test_delete_is_written_in_the_danger_colour(
    qtbot: QtBot, app_ctx: AppContext, d3_appearance: str
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    qtbot.waitExposed(c)
    image = c.grab().toImage()
    t = theme.tokens(d3_appearance)
    top_left = c.delete_button.mapTo(c, c.delete_button.rect().topLeft())
    assert shows(image, t.danger, QRect(top_left, c.delete_button.size()))
    heights = {w.height() for w in (c.filter_edit, c.restore_button, c.add_button, c.delete_button)}
    assert heights == {30}  # the field and the three buttons are one row


# ---- when a case runs out ---------------------------------------------------------------------------

NOW = datetime(2026, 10, 19, 15, 30).astimezone()


@pytest.mark.parametrize(
    ("days", "text", "near"),
    [
        (30, "18 Nov 2026 \N{MIDDLE DOT} 30 days", False),
        (29, "17 Nov 2026 \N{MIDDLE DOT} 29 days", False),
        (8, "27 Oct 2026 \N{MIDDLE DOT} 8 days", False),
        (7, "in 7 days", True),  # within a week: the danger colour
        (3, "in 3 days", True),
        (1, "in 1 day", True),
    ],
)
def test_an_expiry_is_a_date_and_the_days_left_or_in_so_many_days_when_near(
    days: int, text: str, near: bool
) -> None:
    assert describe_expiry(NOW + timedelta(days=days), NOW) == (text, near)


def test_a_part_of_a_day_counts_as_a_day_and_a_case_that_is_due_is_expired() -> None:
    assert days_left(NOW + timedelta(days=6, hours=1), NOW) == 7
    assert describe_expiry(NOW + timedelta(days=7, hours=1), NOW) == (
        "26 Oct 2026 \N{MIDDLE DOT} 8 days",
        False,
    )
    assert days_left(NOW + timedelta(minutes=5), NOW) == 1  # the last day
    assert describe_expiry(NOW - timedelta(hours=1), NOW) == ("expired", True)
    assert describe_expiry(NOW, NOW) == ("expired", True)


def test_a_case_that_runs_out_within_a_week_says_so_in_its_row(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    now = datetime.now(UTC)
    app_ctx.case_store.save(a_case("K4F7", now, days=30))
    app_ctx.case_store.save(a_case("B2C3", now - timedelta(days=7), days=10))  # 3 days left
    c = cases_screen_of(qtbot, app_ctx)
    assert cell(c, 1, 3) == "in 3 days"
    assert c.table.item(1, 3).data(cases_screen.TONE_ROLE) == "danger"  # type: ignore[union-attr]
    assert c.table.item(0, 3).data(cases_screen.TONE_ROLE) is None  # 30 days: as the rest


def test_the_expiry_near_is_red_in_both_appearances_and_stays_red_on_the_chosen_row(
    qtbot: QtBot, app_ctx: AppContext, d3_appearance: str
) -> None:
    now = datetime.now(UTC)
    app_ctx.case_store.save(a_case("K4F7", now, days=30))
    app_ctx.case_store.save(a_case("B2C3", now - timedelta(days=7), days=10))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    qtbot.waitExposed(c)
    t = theme.tokens(d3_appearance)
    near = cell_rect(c, 1, 3)
    assert shows(c.grab().toImage(), t.danger, near)  # on a plain row
    assert not shows(c.grab().toImage(), t.danger, cell_rect(c, 0, 3))  # the 30 days are not
    c.table.selectRow(1)
    qtbot.wait(30)
    chosen = c.grab().toImage()
    assert shows(chosen, t.accent_soft, near)  # the row is chosen: on accent-soft ...
    assert shows(chosen, t.danger, near)  # ... and the expiry is red still


# ---- the code, the grey rows and the head ----------------------------------------------------------


def test_a_code_is_in_the_accent_colour_and_in_the_text_on_soft_colour_when_chosen(
    qtbot: QtBot, app_ctx: AppContext, d3_appearance: str
) -> None:
    app_ctx.case_store.save(a_case("K4F7", OCT_17))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    qtbot.waitExposed(c)
    t = theme.tokens(d3_appearance)
    other, chosen = cell_rect(c, 1, 0), cell_rect(c, 0, 0)
    assert shows(c.grab().toImage(), t.accent, other) and shows(
        c.grab().toImage(), t.accent, chosen
    )
    c.table.selectRow(0)
    qtbot.wait(30)
    image = c.grab().toImage()
    assert shows(image, t.accent_text_on_soft, chosen)  # the accent is too pale on accent-soft
    assert not shows(image, t.accent, chosen) or t.accent == t.accent_text_on_soft
    assert shows(image, t.accent, other)  # the others are as they were
    assert c.table.item(0, 0).font().family() == mono_font().family()  # type: ignore[union-attr]


def test_a_grey_row_is_not_a_case_and_cannot_be_chosen(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    damaged_file(app_ctx, "B2C3")
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    first = c.table.item(1, 1)
    assert first is not None and not first.flags() & Qt.ItemFlag.ItemIsSelectable
    c.table.selectRow(1)
    assert c._selected_case() is None and not c.detail_card.isVisibleTo(c)
    assert c.table.item(1, 0).data(cases_screen.TONE_ROLE) == "muted"  # type: ignore[union-attr]
    assert cell(c, 1, 0) == "\N{EM DASH}" and cell(c, 1, 2) == "\N{EM DASH}"


def test_a_grey_row_has_a_delete_button_that_names_its_file(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    damaged_file(app_ctx, "B2C3")
    damaged_file(app_ctx, "Z9Z9")
    c = cases_screen_of(qtbot, app_ctx)
    assert sorted(c.unreadable_buttons) == ["B2C3.mask", "Z9Z9.mask"]
    assert c.unreadable_buttons["B2C3.mask"].accessibleName() == "Delete B2C3.mask"
    c.resize(1180, 760)
    c.show()
    for button in c.unreadable_buttons.values():  # the button is whole, not cut by its column
        assert button.width() >= button.sizeHint().width() and button.isVisibleTo(c)
    assert c.unreadable_label.text() == cases_screen.DAMAGED_MANY  # of two files: the plural


def test_the_column_head_is_in_capitals_over_the_table_head_colour(
    qtbot: QtBot, app_ctx: AppContext, d3_appearance: str
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    qtbot.waitExposed(c)
    t = theme.tokens(d3_appearance)
    header = c.table.horizontalHeader()
    top_left = header.mapTo(c, header.rect().topLeft())
    rect = QRect(top_left, header.size())
    image = c.grab().toImage()
    assert shows(image, t.table_head, rect) and shows(image, t.secondary, rect)
    assert header.height() == cases_screen.HEADER_HEIGHT
    # What they are called stays as it was written; the capitals are how the head is drawn.
    assert [c.table.horizontalHeaderItem(n).text() for n in range(5)] == list(cases_screen.COLUMNS)
    values = c.table.horizontalHeaderItem(4)
    assert values is not None and values.textAlignment() & Qt.AlignmentFlag.AlignRight


def test_the_table_is_as_tall_as_its_rows_and_gives_way_when_the_window_is_short(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    for n, code in enumerate(("K4F7", "B2C3", "M5N6", "P3XM")):
        app_ctx.case_store.save(a_case(code, OCT_17.replace(day=10 + n)))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    row, head = cases_screen.ROW_HEIGHT, cases_screen.HEADER_HEIGHT
    assert c.table.sizeHint().height() == head + 4 * row + 2
    assert c.table.height() == head + 4 * row + 2  # as tall as its cases, not as the window
    c.filter_edit.setText("k4f7")
    assert c.table.sizeHint().height() == head + row + 2  # a hidden row takes no room
    c.filter_edit.clear()
    c.resize(1180, 330)  # a short window: the table is as short as it may be and scrolls
    assert c.table.height() <= c.table.sizeHint().height()
    assert c.table.minimumSizeHint().height() == head + 3 * row + 2


# ---- the card of the selected case ----------------------------------------------------------------


def holds_of(**kinds: int) -> str:
    counts = {PlaceholderType[name.upper()]: number for name, number in kinds.items()}
    return describe_holds(counts)


def test_what_a_case_holds_is_counted_by_kind_in_the_words_of_the_mockup() -> None:
    text = holds_of(company=2, person=2, amount=2, address=1, email=1, iban=1, percent=3, id=2)
    assert text == (
        "14 values: 2 companies, 2 people, 2 amounts, 1 address, 1 e-mail, 1 bank account, 5 more"
    )


@pytest.mark.parametrize(
    ("kinds", "text"),
    [
        ({}, "0 values"),
        ({"person": 1}, "1 value: 1 person"),
        ({"company": 1, "person": 2}, "3 values: 1 company, 2 people"),
        ({"amount": 1, "percent": 2}, "3 values: 1 amount, 2 percentages"),
        ({"email": 2, "phone": 1}, "3 values: 2 e-mails, 1 phone number"),
        (
            {"quantity": 1, "url": 2, "custom": 3},
            "6 values: 1 quantity, 2 web addresses, 3 other values",
        ),
    ],
)
def test_what_a_case_holds_has_the_right_number_and_the_right_plural(
    kinds: dict[str, int], text: str
) -> None:
    assert holds_of(**kinds) == text


def test_the_first_six_kinds_are_named_and_the_values_of_the_rest_are_counted() -> None:
    every = {kind: 1 for kind in PlaceholderType}  # twelve kinds, one value each
    text = describe_holds(every)
    assert text.startswith("12 values: 1 company, 1 person, 1 amount, 1 address, 1 e-mail,")
    assert text.endswith("1 bank account, 6 more")  # six kinds named, six values left
    assert (
        describe_holds({PlaceholderType.COMPANY: 4, PlaceholderType.PERSON: 1}).count("more") == 0
    )


def test_the_card_is_not_there_until_a_case_is_selected(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    assert not c.detail_card.isVisibleTo(c)
    c.table.selectRow(0)
    assert c.detail_card.isVisibleTo(c)
    c.table.clearSelection()
    assert not c.detail_card.isVisibleTo(c)


def test_the_card_says_what_the_selected_case_is_and_holds(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    mockup_cases(app_ctx)
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    c.table.selectRow(0)
    assert c.case_kicker.text() == "Case K4F7"
    assert c.case_files_label.text() == "supply-01.docx"
    assert c.case_copy_label.text() == (
        "Masked copy: MASKED-K4F7.docx in Documents \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}"
        " The MASK"
    )
    assert c.holds_kicker.text() == "What it holds"
    assert c.holds_label.text() == (
        "14 values: 2 companies, 2 people, 2 amounts, 1 address, 1 e-mail, 1 bank account, 5 more"
    )
    assert c.keychain_label.text() == (
        "Encrypted with the key in your Keychain. Values are shown only on the Restore screen."
    )
    c.table.selectRow(1)  # another case: the card follows
    assert c.case_kicker.text() == "Case Z8Q2"
    assert c.case_files_label.text() == "nda-02.docx, nda-02-annex.docx"
    assert c.case_copy_label.text().startswith(
        "Masked copies: MASKED-Z8Q2-1.docx, MASKED-Z8Q2-2.docx in "
    )
    assert c.holds_label.text() == "21 values: 21 people"


def test_the_card_names_the_folder_when_the_masked_files_are_not_known(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(Case("K4F7", OCT_17, ["Supply.docx"], [], []))
    c = cases_screen_of(qtbot, app_ctx)
    c.table.selectRow(0)
    assert c.case_copy_label.text() == (
        "Masked copies are saved in Documents \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} The MASK"
    )
    assert c.holds_label.text() == "0 values"


def test_the_card_says_so_when_a_case_keeps_no_file_names(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(Case("K4F7", OCT_17, [], [], []))
    c = cases_screen_of(qtbot, app_ctx)
    c.table.selectRow(0)
    assert c.case_files_label.text() == cases_screen.NO_FILE_NAMES
    assert cell(c, 0, 1) == ""  # nothing in the Files column either


def test_the_card_and_the_screen_never_hold_a_value_of_a_key(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    case = a_case("K4F7", entries=3)
    app_ctx.case_store.save(case)
    c = cases_screen_of(qtbot, app_ctx)
    c.table.selectRow(0)
    texts = [label.text() for label in c.findChildren(QLabel)]
    texts += [cell(c, 0, column) for column in range(5)]
    assert not any(entry.value in text for entry in case.entries for text in texts)
    row = c._rows["K4F7"]
    assert row.counts == {PlaceholderType.PERSON: 3} and row.n_values == 3
    assert not any(entry.value in repr(row) for entry in case.entries)  # what the screen keeps


def test_file_names_in_the_card_are_text_not_markup(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(Case("K4F7", OCT_17, ["<b>Acme</b> & Co.docx"], [], []))
    c = cases_screen_of(qtbot, app_ctx)
    c.table.selectRow(0)
    assert c.case_files_label.textFormat() == Qt.TextFormat.PlainText
    assert c.case_files_label.text() == "<b>Acme</b> & Co.docx"


def test_the_card_follows_a_deleted_case(
    qtbot: QtBot, app_ctx: AppContext, agree: list[str]
) -> None:
    app_ctx.case_store.save(a_case("K4F7", OCT_17))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    c.table.selectRow(0)
    c.delete_case_action.trigger()
    assert ids(c) == ["B2C3"] and not c.detail_card.isVisibleTo(c)  # nothing is selected now


# ---- the keyboard and the names -------------------------------------------------------------------


def test_the_arrow_keys_move_from_case_to_case_and_a_case_can_be_restored_from_the_keyboard(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7", OCT_17))
    app_ctx.case_store.save(a_case("B2C3", OCT_10))
    c = cases_screen_of(qtbot, app_ctx)
    c.show()
    qtbot.waitExposed(c)
    c.table.setFocus()
    c.table.selectRow(0)
    qtbot.keyClick(c.table, Qt.Key.Key_Down)
    assert c._selected_case() == "B2C3" and c.case_kicker.text() == "Case B2C3"
    qtbot.keyClick(c.table, Qt.Key.Key_Up)
    assert c._selected_case() == "K4F7"
    c.restore_button.setFocus()
    with qtbot.waitSignal(c.restoreRequested, timeout=1000) as asked:
        qtbot.keyClick(c.restore_button, Qt.Key.Key_Space)
    assert asked.args == ["K4F7"]


def test_every_part_of_the_screen_has_a_name_a_reader_can_say(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    c = cases_screen_of(qtbot, app_ctx)
    assert c.table.accessibleName() == "Cases"
    assert c.detail_card.accessibleName() == "The selected case"
    assert c.filter_edit.accessibleName() == "Filter cases"
    assert c.delete_button.accessibleName() and c.restore_button.text() and c.add_button.text()


# ---- the look -----------------------------------------------------------------------------------------


def test_the_cases_screen_is_drawn_in_the_colours_of_its_appearance(
    qtbot: QtBot,
    app_ctx: AppContext,
    d3_appearance: str,
    d3_shot: Callable[[QWidget, str, str], QImage],
) -> None:
    t = theme.tokens(d3_appearance)
    mockup_cases(app_ctx)
    c = cases_screen_of(qtbot, app_ctx)
    c.table.selectRow(0)
    c.show()
    qtbot.waitExposed(c)
    c.table.setFocus()
    qtbot.wait(50)
    image = d3_shot(c, "cases", d3_appearance)
    assert (image.width(), image.height()) == (1180, 760)
    assert image.pixelColor(2, 2) == QColor(t.ground)
    table = QRect(c.table.mapTo(c, c.table.rect().topLeft()), c.table.size())
    assert shows(image, t.panel, table) and shows(image, t.table_head, table)
    assert shows(image, t.accent_soft, cell_rect(c, 0, 1))  # the chosen row
    assert shows(image, t.danger, cell_rect(c, 2, 3))  # P3XM runs out in three days
    assert shows(image, t.secondary, cell_rect(c, 3, 1))  # the grey row
    assert shows(
        image,
        t.notice_bg,
        QRect(
            c.unreadable_label.mapTo(c, c.unreadable_label.rect().topLeft()),
            c.unreadable_label.size(),
        ),
    )
    assert appears_in(image, t.panel, c.detail_card, c)  # the card of the case
    assert not c.table.verticalScrollBar().isVisible()


def test_the_cases_screen_fits_the_narrowest_window_of_the_app(
    qtbot: QtBot,
    app_ctx: AppContext,
    d3_appearance: str,
    d3_shot: Callable[[QWidget, str, str], QImage],
) -> None:
    mockup_cases(app_ctx)
    c = cases_screen_of(qtbot, app_ctx)
    c.resize(660, 700)  # a 880-point window less the 220 of its sidebar
    c.table.selectRow(0)
    c.show()
    qtbot.waitExposed(c)
    c.table.setFocus()
    qtbot.wait(50)
    d3_shot(c, "cases-narrow", d3_appearance)
    assert c.minimumSizeHint().width() <= 660  # the window may be that narrow
    for part in (c.filter_edit, c.restore_button, c.add_button, c.delete_button):
        assert part.mapTo(c, part.rect().bottomRight()).x() <= 660 - 32 + 1, part.objectName()
    assert c.filter_edit.width() < 260  # the filter gave way, not the buttons
    assert not c.table.horizontalScrollBar().isVisible()
    assert c.holds_label.isVisibleTo(c) and c.detail_card.width() <= 660


def test_the_table_follows_the_system_from_light_to_dark(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    palette, sheet, font = qapp.palette(), qapp.styleSheet(), qapp.font()
    try:
        monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "light")
        theme.apply(qapp)
        c = cases_screen_of(qtbot, app_ctx)
        c.show()
        qtbot.waitExposed(c)
        row = cell_rect(c, 0, 1)
        assert shows(c.grab().toImage(), theme.tokens("light").panel, row)
        qapp.setPalette(theme.palette("dark"))  # what the follower does when the system changes
        qapp.setStyleSheet(theme.stylesheet("dark"))
        qtbot.waitUntil(
            lambda: shows(c.grab().toImage(), theme.tokens("dark").panel, row), timeout=2000
        )
        image = c.grab().toImage()
        assert shows(
            image,
            theme.tokens("dark").table_head,
            QRect(c.table.mapTo(c, c.table.rect().topLeft()), c.table.size()),
        )
        assert shows(image, theme.tokens("dark").accent, cell_rect(c, 0, 0))  # the code, in dark
        assert not c.filter_edit.actions()[0].icon().isNull()
    finally:
        qapp.setPalette(palette)
        qapp.setStyleSheet(sheet)
        qapp.setFont(font)


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
