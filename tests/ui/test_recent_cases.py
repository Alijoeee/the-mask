"""The home screen's list of recent cases: up to three rows from the case store, each with the code,
the file names, a caption worked out from the case, and a link that restores with that case.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QFont

from themask.errors import KeyStoreError
from themask.keystore.cases import CaseStore, CaseSummary
from themask.model import Case, KeyEntry, PlaceholderType
from themask.ui import home_screen
from themask.ui.home_screen import HomeScreen, describe_case
from themask.ui.main_window import MainWindow

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext

NOW = datetime(2026, 10, 19, 15, 30).astimezone()  # the owner's afternoon, in their own zone


def summary(
    created: datetime,
    files: list[str] | None = None,
    values: int = 14,
    retention: int = 30,
    case_id: str = "K4F7",
) -> CaseSummary:
    return CaseSummary(
        case_id,
        created,
        created + timedelta(days=retention),
        ["supply-01.docx"] if files is None else files,
        values,
    )


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """A moment on the day ``day_offset`` days from NOW's day, on the owner's clock."""
    day = NOW + timedelta(days=day_offset)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def a_case(
    case_id: str, created: datetime, files: list[str] | None = None, values: int = 3
) -> Case:
    entries = [
        KeyEntry(f"[PERSON_{i}]", PlaceholderType.PERSON, f"Person {i}", []) for i in range(values)
    ]
    return Case(case_id, created, files if files is not None else [f"{case_id}.docx"], [], entries)


# ---- the caption of a case ----------------------------------------------------------------------


def test_a_case_of_today_says_when_with_the_time_and_how_long_it_is_kept() -> None:
    text = describe_case(summary(at(0, 14, 2)), NOW)
    assert text == "Exported today at 14:02 · 14 values hidden · expires in 30 days"


def test_a_case_of_yesterday_says_so_without_the_time_and_counts_its_files() -> None:
    row = summary(at(-1, 10, 15), ["nda-02.docx", "nda-02-annex.docx"], values=21, case_id="Z8Q2")
    assert describe_case(row, NOW) == (
        "Exported yesterday · 2 files · 21 values hidden · expires in 29 days"
    )


def test_a_case_of_a_few_days_ago_says_how_many() -> None:
    assert describe_case(summary(at(-3, 9)), NOW).startswith("Exported 3 days ago · ")
    assert describe_case(summary(at(-6, 9)), NOW).startswith("Exported 6 days ago · ")


def test_an_older_case_says_the_date() -> None:
    created = at(-7, 9)
    assert describe_case(summary(created), NOW).startswith(f"Exported on {created:%Y-%m-%d} · ")


def test_a_case_of_a_future_moment_is_a_case_of_today() -> None:
    # A clock that went back: not "in the future".
    assert describe_case(summary(at(0, 23, 59)), NOW).startswith("Exported today at 23:59")


def test_the_file_count_is_said_only_for_several_files() -> None:
    assert "files" not in describe_case(summary(at(0, 9), ["a.docx"]), NOW)
    assert "3 files" in describe_case(summary(at(0, 9), ["a.docx", "b.docx", "c.pdf"]), NOW)


@pytest.mark.parametrize(("values", "words"), [(1, "1 value hidden"), (2, "2 values hidden")])
def test_one_value_is_a_value_and_more_are_values(values: int, words: str) -> None:
    assert words in describe_case(summary(at(0, 9), values=values), NOW)


def test_the_days_until_a_case_expires_count_up_to_the_next_day() -> None:
    assert describe_case(summary(at(0, 14, 2)), at(0, 15)).endswith("expires in 30 days")
    assert describe_case(summary(at(-10, 9)), NOW).endswith("expires in 20 days")
    assert describe_case(summary(at(-28, 9)), NOW).endswith("expires in 2 days")  # 1 day 17 hours


def test_one_day_is_a_day() -> None:
    exactly = summary(NOW - timedelta(days=29))
    assert describe_case(exactly, NOW).endswith("expires in 1 day")


def test_a_case_that_expires_within_a_day_and_one_that_has_expired_say_so() -> None:
    soon = summary(NOW - timedelta(days=30) + timedelta(hours=5))
    assert describe_case(soon, NOW).endswith("expires in less than a day")
    gone = summary(NOW - timedelta(days=31))
    assert describe_case(gone, NOW).endswith("expired")


# ---- the section --------------------------------------------------------------------------------


@pytest.fixture
def home(qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> HomeScreen:
    monkeypatch.setattr(home_screen, "current_time", lambda: NOW.astimezone(UTC))
    screen = HomeScreen(app_ctx)
    qtbot.addWidget(screen)
    screen.resize(900, 700)
    return screen


def test_there_is_no_section_when_there_are_no_cases(home: HomeScreen) -> None:
    home.show()
    assert home.recent.isHidden() and home.recent.rows == []


def test_two_saved_cases_are_two_rows_newest_first(home: HomeScreen, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("Z8Q2", at(-1, 10), ["nda-02.docx", "nda-02-annex.docx"], 21))
    app_ctx.case_store.save(a_case("K4F7", at(0, 14, 2), ["supply-01.docx"], 14))
    home.refresh_recent()
    home.show()
    assert not home.recent.isHidden()
    first, second = home.recent.rows
    assert (first.code_label.text(), second.code_label.text()) == ("K4F7", "Z8Q2")
    assert first.files_label.text() == "supply-01.docx"
    assert second.files_label.text() == "nda-02.docx, nda-02-annex.docx"
    assert first.caption_label.text() == (
        "Exported today at 14:02 · 14 values hidden · expires in 30 days"
    )
    assert second.caption_label.text() == (
        "Exported yesterday · 2 files · 21 values hidden · expires in 29 days"
    )


def test_a_row_is_made_of_the_chip_the_files_the_caption_and_the_link(
    home: HomeScreen, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7", at(0, 14, 2)))
    home.refresh_recent()
    row = home.recent.rows[0]
    assert row.code_label.objectName() == "caseCode"
    assert row.files_label.objectName() == "caseFiles"
    assert row.caption_label.objectName() == "caseCaption"
    assert row.restore_button.text() == "Restore"
    assert row.restore_button.accessibleName() == "Restore with case K4F7"
    assert row.code_label.font().styleHint() == QFont.StyleHint.Monospace


def test_at_most_three_cases_are_shown(home: HomeScreen, app_ctx: AppContext) -> None:
    for number, code in enumerate(["AAA2", "BBB3", "CCC4", "DDD5", "EEE6"]):
        app_ctx.case_store.save(a_case(code, at(-number, 12)))
    home.refresh_recent()
    assert [row.code_label.text() for row in home.recent.rows] == ["AAA2", "BBB3", "CCC4"]


def test_a_case_without_file_names_is_shown_by_its_code(
    home: HomeScreen, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7", at(0, 9), files=[]))
    home.refresh_recent()
    assert home.recent.rows[0].files_label.text() == "Case K4F7"


def test_the_section_follows_the_store(home: HomeScreen, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7", at(0, 9)))
    home.refresh_recent()
    assert len(home.recent.rows) == 1
    app_ctx.case_store.delete("K4F7")
    home.refresh_recent()
    assert home.recent.rows == [] and home.recent.isHidden()


def test_the_header_says_recent_cases_in_capitals_and_the_link_says_all_cases(
    home: HomeScreen,
) -> None:
    assert home.recent.header_label.text() == "Recent cases"
    font = home.recent.header_label.font()
    assert font.capitalization() == QFont.Capitalization.AllUppercase
    assert font.letterSpacing() == pytest.approx(0.4, abs=0.02) and font.letterSpacingType() == (
        QFont.SpacingType.AbsoluteSpacing
    )
    assert home.recent.all_cases_button.text() == "All cases"
    assert home.recent.header_label.objectName() == "sectionTitle"


def test_all_cases_asks_for_the_cases_screen(qtbot: QtBot, home: HomeScreen) -> None:
    with qtbot.waitSignal(home.casesRequested, timeout=1000):
        home.recent.all_cases_button.click()


def test_the_restore_link_of_a_row_asks_for_restoring_with_that_case(
    qtbot: QtBot, home: HomeScreen, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7", at(0, 14)))
    app_ctx.case_store.save(a_case("B2C3", at(-2, 9)))
    home.refresh_recent()
    with qtbot.waitSignal(home.restoreRequested, timeout=1000) as asked:
        home.recent.rows[1].restore_button.click()
    assert asked.args == ["B2C3"]


def test_a_store_that_cannot_be_read_leaves_no_section_and_no_error(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    class Locked(CaseStore):
        def list(self) -> list[CaseSummary]:
            raise KeyStoreError("The MASK could not reach the macOS Keychain.")

    screen = HomeScreen(replace(app_ctx, case_store=Locked(Path("/nonexistent"), None)))  # type: ignore[arg-type]
    qtbot.addWidget(screen)
    screen.refresh_recent()
    assert screen.recent.rows == [] and screen.recent.isHidden()


def test_a_case_folder_that_cannot_be_opened_leaves_no_section_and_no_error(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    class Closed(CaseStore):
        def list(self) -> list[CaseSummary]:
            raise PermissionError(13, "Permission denied")

    screen = HomeScreen(replace(app_ctx, case_store=Closed(Path("/nonexistent"), None)))  # type: ignore[arg-type]
    qtbot.addWidget(screen)
    screen.refresh_recent()
    assert screen.recent.isHidden()


# ---- with the window ----------------------------------------------------------------------------


def test_the_cases_of_the_store_are_there_when_the_window_opens(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7", datetime.now(UTC)))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    assert [row.code_label.text() for row in w.home.recent.rows] == ["K4F7"]


def test_an_exported_case_is_on_the_home_screen_and_its_link_restores_with_it(
    qtbot: QtBot, app_ctx: AppContext, exported: tuple[Path, Case]
) -> None:
    masked, case = exported
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show_cases()
    w.show_home()
    row = w.home.recent.rows[0]
    assert row.code_label.text() == case.id
    assert row.files_label.text() == "supply-01.docx"
    assert row.caption_label.text().startswith("Exported today at ")
    assert f"{len(case.entries)} values hidden" in row.caption_label.text()
    assert "expires in 30 days" in row.caption_label.text()
    row.restore_button.click()
    assert w.current_screen_name() == "restore"
    assert w.restore_screen.case_combo.currentData() == case.id
    assert masked.exists()


def test_all_cases_opens_the_cases_screen(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7", datetime.now(UTC)))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.home.recent.all_cases_button.click()
    assert w.current_screen_name() == "cases"


def test_a_case_made_while_another_screen_showed_is_there_when_home_comes_back(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert w.home.recent.rows == []
    w.show_cases()
    app_ctx.case_store.save(a_case("K4F7", datetime.now(UTC)))  # an export made it
    w.show_home()
    assert [row.code_label.text() for row in w.home.recent.rows] == ["K4F7"]


def test_the_header_is_not_shown_with_no_cases_in_the_window(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    assert w.home.recent.isHidden()
    assert not w.home.recent.header_label.isVisible()  # the header goes with the section
    assert not w.home.recent.all_cases_button.isVisible()


def test_the_links_are_off_while_a_file_is_analysed_and_on_again_after(
    home: HomeScreen, app_ctx: AppContext
) -> None:
    # Nothing leads away from the analysis: not the sidebar, not the links of the cases.
    app_ctx.case_store.save(a_case("K4F7", at(0, 14)))
    home.refresh_recent()
    home.show_busy()
    assert not home.recent.isEnabled()
    assert not home.recent.rows[0].restore_button.isEnabled()
    assert not home.recent.all_cases_button.isEnabled()
    home.show_ready()
    assert home.recent.isEnabled() and home.recent.rows[0].restore_button.isEnabled()


def test_the_links_stay_on_while_the_engine_loads(home: HomeScreen, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7", at(0, 14)))
    home.refresh_recent()
    home.show_loading()
    assert home.recent.isEnabled()  # the sidebar is on then too


class Counting(CaseStore):
    """A case store that counts how often it is listed, and fails with ``error`` (or does not)."""

    def __init__(
        self, error: Exception | None = None, purge_error: Exception | None = None
    ) -> None:
        super().__init__(Path("/nonexistent"), None)  # type: ignore[arg-type]
        self.error, self.purge_error, self.listed = error, purge_error, 0

    def list(self) -> list[CaseSummary]:
        self.listed += 1
        if self.error is not None:
            raise self.error
        return []

    def purge_expired(self, now: datetime | None = None) -> list[str]:
        if self.purge_error is not None:
            raise self.purge_error
        return []


def test_a_keychain_that_refused_is_not_asked_again_for_the_recent_cases(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    # Every ask is a prompt of the Keychain: one refusal is enough for the session.
    store = Counting(KeyStoreError("The MASK could not reach the macOS Keychain."))
    screen = HomeScreen(replace(app_ctx, case_store=store))
    qtbot.addWidget(screen)
    screen.refresh_recent()
    screen.refresh_recent()
    screen.refresh_recent()
    assert store.listed == 1 and screen.keychain_refused and screen.recent.isHidden()


def test_a_folder_that_cannot_be_read_is_tried_again_next_time(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    store = Counting(PermissionError(13, "Permission denied"))
    screen = HomeScreen(replace(app_ctx, case_store=store))
    qtbot.addWidget(screen)
    screen.refresh_recent()
    screen.refresh_recent()
    assert store.listed == 2 and not screen.keychain_refused


def test_a_keychain_that_refused_the_clean_up_is_not_asked_for_the_recent_cases(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    store = Counting(purge_error=KeyStoreError("The MASK could not reach the macOS Keychain."))
    w = MainWindow(replace(app_ctx, case_store=store))
    qtbot.addWidget(w)
    after_start = store.listed  # the Cases screen lists when it is made, and asks for itself
    w.show_home()
    w.show_home()
    assert w.home.keychain_refused and store.listed == after_start  # the home did not ask
    assert "Keychain" in w.home.notice_label.text()  # and the notice of the clean-up is there


def test_a_clean_up_that_failed_for_the_disk_does_not_stop_the_recent_cases(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    store = Counting(purge_error=PermissionError(13, "Permission denied"))
    w = MainWindow(replace(app_ctx, case_store=store))
    qtbot.addWidget(w)
    after_start = store.listed
    w.show_home()
    assert not w.home.keychain_refused and store.listed == after_start + 1  # the home asked
