"""The small widgets the screens share: a label that cuts a long line short, and a link button."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton

from themask.ui.widgets import ElidedLabel, LinkButton, Swatch, is_keyboard_focus

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

LONG = "nda-02.docx, nda-02-annex.docx, nda-02-schedule-1.docx, nda-02-schedule-2.docx"


def test_an_elided_label_shows_a_line_that_fits_as_it_is(qtbot: QtBot) -> None:
    label = ElidedLabel("supply-01.docx")
    qtbot.addWidget(label)
    label.resize(300, 20)
    assert label.displayed_text() == "supply-01.docx" and label.toolTip() == ""


def test_an_elided_label_cuts_a_long_line_short_and_says_all_of_it_in_the_tooltip(
    qtbot: QtBot,
) -> None:
    label = ElidedLabel(LONG)
    qtbot.addWidget(label)
    label.show()  # a widget that is not shown gets its resize event when it is
    label.resize(150, 20)
    shown = label.displayed_text()
    assert shown.endswith("…") and len(shown) < len(LONG) and LONG.startswith(shown[:-1])
    assert label.toolTip() == LONG
    assert label.text() == LONG  # what a screen reader is given is the whole line


def test_an_elided_label_shows_more_when_it_grows_and_all_when_it_fits(qtbot: QtBot) -> None:
    label = ElidedLabel(LONG)
    qtbot.addWidget(label)
    label.show()
    label.resize(150, 20)
    short = label.displayed_text()
    label.resize(250, 20)
    longer = label.displayed_text()
    assert len(longer) > len(short)
    label.resize(label.sizeHint().width() + 4, 20)
    assert label.displayed_text() == LONG and label.toolTip() == ""


def test_an_elided_label_can_be_made_narrower_than_its_text(qtbot: QtBot) -> None:
    label = ElidedLabel(LONG)
    qtbot.addWidget(label)
    assert label.minimumSizeHint().width() == 0
    assert label.sizeHint().width() > 300  # it asks for the whole line


def test_an_elided_label_can_cut_in_the_middle(qtbot: QtBot) -> None:
    label = ElidedLabel(LONG, elide=Qt.TextElideMode.ElideMiddle)
    qtbot.addWidget(label)
    label.resize(200, 20)
    shown = label.displayed_text()
    assert "…" in shown[1:-1] and shown.startswith("nda") and shown.endswith("docx")


def test_an_elided_label_is_a_label_with_the_text_of_a_label(qtbot: QtBot) -> None:
    label = ElidedLabel("Title")
    qtbot.addWidget(label)
    assert isinstance(label, QLabel)
    label.setText("Other")
    assert label.text() == "Other"
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    assert label.alignment() == Qt.AlignmentFlag.AlignCenter


def test_a_link_button_is_a_flat_button_that_takes_the_focus_by_tab_only(qtbot: QtBot) -> None:
    link = LinkButton("All cases")
    qtbot.addWidget(link)
    assert isinstance(link, QPushButton) and link.isFlat()
    assert link.objectName() == "link" and link.text() == "All cases"
    assert link.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert link.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_a_link_button_clicks_like_a_button(qtbot: QtBot) -> None:
    link = LinkButton("Restore")
    qtbot.addWidget(link)
    link.resize(QSize(60, 20))
    with qtbot.waitSignal(link.clicked, timeout=1000):
        link.click()


def test_a_swatch_is_a_small_rounded_square_in_its_colour(qtbot: QtBot) -> None:
    swatch = Swatch("#AECBF0", size=9)
    qtbot.addWidget(swatch)
    assert swatch.size() == QSize(9, 9)
    image = swatch.grab().toImage()
    assert image.pixelColor(4, 4).name() == "#aecbf0"
    assert image.pixelColor(0, 0).name() != "#aecbf0"  # the corner is rounded off


def test_a_swatch_can_be_any_size(qtbot: QtBot) -> None:
    swatch = Swatch("#F9B9B7", size=10, radius=3)
    qtbot.addWidget(swatch)
    assert swatch.size() == QSize(10, 10)


def test_only_the_keyboard_brings_a_focus_ring() -> None:
    for reason in (
        Qt.FocusReason.TabFocusReason,
        Qt.FocusReason.BacktabFocusReason,
        Qt.FocusReason.ShortcutFocusReason,
    ):
        assert is_keyboard_focus(reason)
    for reason in (
        Qt.FocusReason.MouseFocusReason,
        Qt.FocusReason.ActiveWindowFocusReason,
        Qt.FocusReason.PopupFocusReason,
        Qt.FocusReason.OtherFocusReason,
    ):
        assert not is_keyboard_focus(reason)
