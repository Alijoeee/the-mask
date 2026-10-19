"""The parts of the export sheet, the restore screen and the cases screen: the style sheet that
follows the appearance, the colours that no token names, the badges and the glyph that draw
themselves, the tick, the folder written as a trail, and the layout that wraps cards.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget

from themask.ui import theme
from themask.ui.cards import (
    DocGlyph,
    FlowLayout,
    MarkBadge,
    Themed,
    TickLabel,
    appearance_name,
    blend,
    folder_trail,
    style_vars,
)

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

APPEARANCES = ["light", "dark"]


def luminance(colour: QColor) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(colour.redF())
        + 0.7152 * linear(colour.greenF())
        + 0.0722 * linear(colour.blueF())
    )


def contrast(foreground: str, background: str) -> float:
    """The WCAG contrast ratio of two colours, 1 to 21."""
    lighter, darker = sorted(
        (luminance(QColor(foreground)), luminance(QColor(background))), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


# ---- the colours ---------------------------------------------------------------------------------


def test_a_blend_goes_from_the_bottom_colour_to_the_top_one() -> None:
    assert blend("#000000", "#FFFFFF", 0) == "#FFFFFF"
    assert blend("#000000", "#FFFFFF", 1) == "#000000"
    assert blend("#FF0000", "#0000FF", 0.5) == "#800080"
    assert (
        blend("#b3261e", "#ffffff", 0.1).startswith("#") and len(blend("#b3261e", "#fff", 0.1)) == 7
    )


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_style_values_are_every_token_and_the_colours_the_mockups_add(appearance: str) -> None:
    t = theme.tokens(appearance)
    values = style_vars(t)
    assert all(values[name] == value for name, value in vars(t).items())
    for name in (
        "soft_ground",
        "soft_text",
        "change_text",
        "glyph_fill",
        "glyph_stroke",
        "glyph_fold",
        "accent_ink",
        "danger_bg",
        "danger_disc",
        "danger_border",
    ):
        assert QColor(values[name]).isValid(), name
    assert appearance_name(t) == appearance


def test_the_two_appearances_have_colours_of_their_own() -> None:
    light, dark = style_vars(theme.tokens("light")), style_vars(theme.tokens("dark"))
    for name in ("soft_ground", "soft_text", "change_text", "glyph_fill", "danger_bg"):
        assert light[name] != dark[name], name


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_texts_these_screens_add_are_easy_to_read_on_their_grounds(appearance: str) -> None:
    t = theme.tokens(appearance)
    v = style_vars(t)
    pairs = [
        (v["soft_text"], t.accent_soft),  # the instruction on the export sheet's box
        (t.accent_text_on_soft, t.accent_soft),
        (v["change_text"], t.notice_card_bg),  # an explanation on the restore screen's notice card
        (t.notice_text, t.notice_card_bg),
        (t.secondary, v["soft_ground"]),  # a caption on the file card
        (t.danger, v["danger_bg"]),  # the headline of a block
        (t.secondary, v["danger_bg"]),
        (t.success_text, t.panel),  # "Chosen from the file name"
        (t.danger, t.panel),  # an expiry in danger colour, a Delete button
        (t.danger, t.accent_soft),  # the same on the chosen row
        (v["accent_ink"], t.accent_soft),  # a code on the chosen row
        (v["accent_ink"], t.panel),  # and on the other rows
    ]
    for ink, ground in pairs:
        assert contrast(ink, ground) >= 4.5, (appearance, ink, ground)


# ---- folders -------------------------------------------------------------------------------------


def test_a_folder_in_the_home_is_written_from_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert (
        folder_trail(tmp_path / "Documents" / "The MASK")
        == "Documents \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} The MASK"
    )
    assert folder_trail(tmp_path) == "Home"


def test_another_folder_is_written_from_its_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "somebody"))
    trail = folder_trail(Path("/Volumes/Work/Contracts"))
    assert (
        trail
        == "Volumes \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Work \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Contracts"
    )


# ---- the style sheet that follows the appearance --------------------------------------------------


def test_a_themed_widget_gets_the_sheet_of_its_appearance_and_a_new_one_when_it_changes(
    qtbot: QtBot, qapp: QApplication
) -> None:
    made: list[str] = []

    def build(t: theme.Tokens) -> str:
        made.append(t.panel)
        return f"QFrame#card {{ background: {t.panel}; }}"

    palette = qapp.palette()
    try:
        qapp.setPalette(theme.palette("light"))
        widget = QWidget()
        qtbot.addWidget(widget)
        Themed(widget, build)
        assert made == [theme.tokens("light").panel]
        assert theme.tokens("light").panel in widget.styleSheet()
        qapp.setPalette(theme.palette("dark"))  # the system went dark
        qtbot.waitUntil(lambda: len(made) == 2)  # the palette reaches the widgets in the event loop
        assert made == [theme.tokens("light").panel, theme.tokens("dark").panel]
        assert theme.tokens("dark").panel in widget.styleSheet()
    finally:
        qapp.setPalette(palette)


def test_a_themed_widget_is_not_styled_again_while_the_appearance_stays(
    qtbot: QtBot, qapp: QApplication
) -> None:
    made: list[int] = []
    palette = qapp.palette()
    try:
        qapp.setPalette(theme.palette("light"))
        widget = QWidget()
        qtbot.addWidget(widget)
        themed = Themed(widget, lambda t: made.append(1) or "")
        widget.setStyleSheet("QLabel { color: red; }")  # a style sheet that changes the palette too
        widget.show()
        qapp.setPalette(theme.palette("light"))  # the same look again
        qapp.processEvents()
        themed.refresh()
        assert made == [1]
    finally:
        qapp.setPalette(palette)


def test_what_a_sheet_cannot_reach_is_told_the_new_tokens(qtbot: QtBot, qapp: QApplication) -> None:
    told: list[str] = []
    palette = qapp.palette()
    try:
        qapp.setPalette(theme.palette("light"))
        widget = QWidget()
        qtbot.addWidget(widget)
        Themed(widget, lambda t: "", after=lambda t: told.append(t.accent))
        qapp.setPalette(theme.palette("dark"))
        qtbot.waitUntil(lambda: len(told) == 2)
        assert told == [theme.tokens("light").accent, theme.tokens("dark").accent]
    finally:
        qapp.setPalette(palette)


# ---- what draws itself ----------------------------------------------------------------------------


def centre_colours(widget: QWidget) -> set[int]:
    image = widget.grab().toImage()
    return {image.pixel(x, y) for x in range(image.width()) for y in range(image.height())}


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_check_badge_is_a_green_disc_with_a_green_check(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    badge = MarkBadge("check", 56)
    qtbot.addWidget(badge)
    badge.setPalette(theme.palette(appearance))
    colours = centre_colours(badge)
    assert QColor(t.success_bg).rgb() in colours and QColor(t.success).rgb() in colours
    assert (badge.width(), badge.height()) == (56, 56)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_alert_badge_is_a_red_disc_with_a_red_mark(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    badge = MarkBadge("alert", 56)
    qtbot.addWidget(badge)
    badge.setPalette(theme.palette(appearance))
    colours = centre_colours(badge)
    assert (
        QColor(style_vars(t)["danger_disc"]).rgb() in colours and QColor(t.danger).rgb() in colours
    )
    assert QColor(t.success).rgb() not in colours


def test_a_badge_can_show_the_other_mark_and_has_any_size(qtbot: QtBot) -> None:
    badge = MarkBadge("check", 36)
    qtbot.addWidget(badge)
    before = badge.grab().toImage()
    badge.set_kind("alert")
    assert badge.grab().toImage() != before and badge.width() == 36


def test_the_glyph_is_a_document_34_by_40(qtbot: QtBot) -> None:
    glyph = DocGlyph()
    qtbot.addWidget(glyph)
    glyph.setPalette(theme.palette("light"))
    assert (glyph.width(), glyph.height()) == (34, 40)
    values = style_vars(theme.tokens("light"))
    assert QColor(values["glyph_fill"]).rgb() in centre_colours(glyph)
    dark = DocGlyph()
    qtbot.addWidget(dark)
    dark.setPalette(theme.palette("dark"))
    assert QColor(style_vars(theme.tokens("dark"))["glyph_fill"]).rgb() in centre_colours(dark)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_tick_label_draws_its_tick_in_the_success_text_colour(
    qtbot: QtBot, appearance: str
) -> None:
    label = TickLabel("Chosen from the file name")
    qtbot.addWidget(label)
    label.setPalette(theme.palette(appearance))
    label.resize(label.sizeHint())
    assert label.text() == "Chosen from the file name"
    assert label.contentsMargins().left() == 18  # the room the tick has
    assert QColor(theme.tokens(appearance).success_text).rgb() in centre_colours(label)


# ---- the layout that wraps -----------------------------------------------------------------------


def cards(count: int, height: int = 100) -> tuple[QWidget, FlowLayout, list[QFrame]]:
    host = QWidget()
    layout = FlowLayout(host, min_width=300, spacing=16)
    made = []
    for _ in range(count):
        card = QFrame()
        card.setMinimumHeight(height)
        layout.addWidget(card)
        made.append(card)
    return host, layout, made


def test_two_cards_sit_side_by_side_when_there_is_room_and_share_the_width(qtbot: QtBot) -> None:
    host, _, (one, two) = cards(2)
    qtbot.addWidget(host)
    host.resize(700, 300)
    host.show()
    assert one.y() == two.y() and one.x() == 0
    assert one.width() == two.width() == (700 - 16) // 2
    assert two.x() == one.width() + 16


def test_two_cards_wrap_one_under_the_other_when_the_window_is_narrow(qtbot: QtBot) -> None:
    host, _, (one, two) = cards(2)
    qtbot.addWidget(host)
    host.resize(600, 400)  # not room for two of 300 and the gap between them
    host.show()
    assert one.x() == two.x() == 0 and two.y() == one.y() + one.height() + 16
    assert one.width() == two.width() == 600


def test_the_layout_says_how_tall_it_is_at_each_width(qtbot: QtBot) -> None:
    host, layout, _ = cards(2, height=100)
    qtbot.addWidget(host)
    assert layout.hasHeightForWidth()
    assert layout.heightForWidth(700) == 100  # side by side
    assert layout.heightForWidth(500) == 216  # one under the other, with the gap
    assert layout.minimumSize().width() == 300  # the window may be as narrow as one card


def test_a_row_is_as_tall_as_its_tallest_card_and_the_others_stretch_to_it(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, min_width=300, spacing=16)
    short, tall = QFrame(), QFrame()
    short.setMinimumHeight(80)
    tall.setMinimumHeight(140)
    layout.addWidget(short)
    layout.addWidget(tall)
    host.resize(700, 200)
    host.show()
    assert short.height() == tall.height() == 140 and short.y() == tall.y()


def test_a_hidden_card_takes_no_room(qtbot: QtBot) -> None:
    host, layout, (one, two) = cards(2)
    qtbot.addWidget(host)
    two.hide()
    host.resize(700, 300)
    host.show()
    assert one.width() == 700 and layout.heightForWidth(700) == 100
    two.show()
    assert layout.count() == 2 and layout.itemAt(0) is not None and layout.itemAt(5) is None


def test_an_empty_flow_has_no_height_and_items_can_be_taken_out(qtbot: QtBot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host)
    assert layout.heightForWidth(500) == 0
    label = QLabel("x")
    layout.addWidget(label)
    taken = layout.takeAt(0)
    assert taken is not None and layout.count() == 0 and layout.takeAt(0) is None
    assert layout.expandingDirections() == Qt.Orientation(0)
    assert isinstance(layout.sizeHint().width(), int) and QRect(0, 0, 1, 1).isValid()
