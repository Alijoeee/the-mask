"""The look: one colour for each type of placeholder, readable with black text."""

from __future__ import annotations

import math
from itertools import combinations
from typing import TYPE_CHECKING

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame

from themask.model import PlaceholderType
from themask.ui.theme import STYLESHEET, TYPE_COLOURS, apply_theme

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


def luminance(colour: QColor) -> float:
    """The relative luminance of a colour (WCAG)."""

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(colour.redF())
        + 0.7152 * linear(colour.greenF())
        + 0.0722 * linear(colour.blueF())
    )


def test_every_type_has_a_colour() -> None:
    assert set(TYPE_COLOURS) == set(PlaceholderType)


def test_the_colours_are_valid() -> None:
    assert all(QColor(colour).isValid() for colour in TYPE_COLOURS.values())


def test_the_colours_differ_from_one_another() -> None:
    colours = {kind: QColor(colour) for kind, colour in TYPE_COLOURS.items()}
    for (a, one), (b, other) in combinations(colours.items(), 2):
        distance = math.dist(
            (one.red(), one.green(), one.blue()), (other.red(), other.green(), other.blue())
        )
        assert distance >= 20, (a, b, distance)


def test_black_text_is_easy_to_read_on_every_colour() -> None:
    for kind, colour in TYPE_COLOURS.items():
        contrast = (luminance(QColor(colour)) + 0.05) / 0.05  # against black
        assert contrast >= 7, (kind, contrast)  # WCAG AAA


def style_messages(qtbot: QtBot, sheet: str) -> list[str]:
    """What Qt says about ``sheet`` when a frame of the drop zone's kind is given it and shown."""
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    try:
        frame = QFrame()
        frame.setObjectName("dropZone")
        frame.setProperty("dragOver", True)
        frame.setStyleSheet(sheet)
        qtbot.addWidget(frame)
        frame.show()
        qtbot.wait(20)
    finally:
        qInstallMessageHandler(previous)
    return [message for message in messages if "stylesheet" in message.lower()]


def test_the_stylesheet_is_understood_by_qt(qtbot: QtBot) -> None:
    assert style_messages(qtbot, STYLESHEET) == []


def test_qt_would_say_so_about_a_stylesheet_it_cannot_read(qtbot: QtBot) -> None:
    # The check above can fail: it sees a broken stylesheet for what it is.
    assert style_messages(qtbot, "QFrame { border: ;;; {{ } QFrame#x[") != []


def test_apply_theme_gives_the_application_the_stylesheet(qapp: QApplication) -> None:
    before = qapp.styleSheet()
    try:
        apply_theme(qapp)
        assert qapp.styleSheet() == STYLESHEET
    finally:
        qapp.setStyleSheet(before)
