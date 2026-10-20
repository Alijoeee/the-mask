"""The look: the tokens of the light and dark appearance, the palette and stylesheet made from
them, how the appearance is chosen and followed, and one colour for each type of placeholder,
readable with black text.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import fields
from itertools import combinations
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget

from themask.model import PlaceholderType
from themask.ui import theme
from themask.ui.theme import TYPE_COLOURS, Tokens

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

APPEARANCES = ["light", "dark"]


def luminance(colour: QColor) -> float:
    """The relative luminance of a colour (WCAG)."""

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


@pytest.fixture
def untouched_look(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    """The application's palette, style sheet and font as they were, and no appearance forced:
    whatever a test applies is taken away again.
    """
    monkeypatch.delenv(theme.APPEARANCE_VARIABLE, raising=False)
    palette, sheet, font = qapp.palette(), qapp.styleSheet(), qapp.font()
    yield qapp
    for follower in qapp.findChildren(theme.AppearanceFollower):
        follower.setParent(None)
        follower.deleteLater()
    qapp.setPalette(palette)
    qapp.setStyleSheet(sheet)
    qapp.setFont(font)


# ---- the colours of the placeholder types (unchanged) --------------------------------------------


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
        assert contrast("#000000", colour) >= 7, kind  # WCAG AAA


# ---- the tokens ---------------------------------------------------------------------------------


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_every_token_is_a_colour(appearance: str) -> None:
    for field in fields(Tokens):
        value = getattr(theme.tokens(appearance), field.name)
        assert QColor(value).isValid() and value.startswith("#"), (appearance, field.name)


def test_the_light_tokens_are_the_briefs() -> None:
    light = theme.tokens("light")
    assert (light.ground, light.chrome, light.panel, light.border) == (
        "#FBFAF8",
        "#F3F0EB",
        "#FFFFFF",
        "#E6E1DA",
    )
    assert (light.border_strong, light.text, light.secondary, light.tertiary) == (
        "#D9D2C8",
        "#1F1D1A",
        "#6B655E",
        "#9B948B",
    )
    # The brief's accent is #B5642A; ruling R124 made it #A85A24 so that white text on it is 5.1:1.
    assert (light.accent, light.accent_soft, light.accent_text_on_soft) == (
        "#A85A24",
        "#F4E4D8",
        "#7A4019",
    )
    assert light.on_accent == "#FFFFFF"
    assert (light.notice_bg, light.notice_card_bg, light.notice_border, light.notice_text) == (
        "#FFF4CE",
        "#FFF9E6",
        "#ECD48B",
        "#5B4300",
    )
    assert (light.success, light.success_bg, light.danger, light.table_head) == (
        "#2E9E5B",
        "#EAF4E6",
        "#B3261E",
        "#F7F4EF",
    )


def test_the_dark_tokens_are_the_briefs() -> None:
    dark = theme.tokens("dark")
    assert (dark.ground, dark.chrome, dark.panel, dark.control) == (
        "#1E1D1B",
        "#262523",
        "#2C2A27",
        "#33312D",
    )
    assert (dark.border, dark.border_strong, dark.text, dark.secondary, dark.tertiary) == (
        "#3A3733",
        "#4A4640",
        "#F2EEE8",
        "#A39B91",
        "#7E776E",
    )
    assert (dark.accent, dark.accent_soft, dark.accent_text_on_soft) == (
        "#D9834A",
        "#3F2E24",
        "#F0C9A8",
    )
    assert dark.on_accent == "#1F1D1A"  # R124: not white, which is 2.9:1 on this accent
    assert (dark.notice_bg, dark.notice_border, dark.notice_text) == (
        "#3D3320",
        "#5A4A1E",
        "#F3D8A0",
    )
    assert (dark.success, dark.success_bg, dark.danger, dark.table_head) == (
        "#3FB46F",
        "#1F3326",
        "#FF6B61",
        "#302E2A",
    )


def test_an_unknown_appearance_is_refused() -> None:
    with pytest.raises(ValueError, match="sepia"):
        theme.tokens("sepia")


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_text_is_easy_to_read_on_every_ground(appearance: str) -> None:
    t = theme.tokens(appearance)
    for ground in (t.ground, t.panel, t.chrome, t.control, t.table_head):
        for ink in (t.text, t.secondary):
            assert contrast(ink, ground) >= 4.5, (appearance, ink, ground)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_coloured_texts_are_easy_to_read_on_their_own_backgrounds(appearance: str) -> None:
    t = theme.tokens(appearance)
    assert contrast(t.accent_text_on_soft, t.accent_soft) >= 4.5
    assert contrast(t.notice_text, t.notice_bg) >= 4.5
    assert contrast(t.notice_text, t.notice_card_bg) >= 4.5
    assert contrast(t.danger, t.panel) >= 4.5 and contrast(t.danger, t.ground) >= 4.5
    assert contrast(t.success_text, t.panel) >= 4.5 and contrast(t.success_text, t.ground) >= 4.5
    assert contrast(t.text, t.accent_soft) >= 4.5  # the selected row of a list


# Ruling R124: every pair of text and ground is 4.5:1 or more, in both appearances.


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_text_on_the_accent_is_easy_to_read(appearance: str) -> None:
    # White on the light accent, the dark text colour on the dark one: sidebar, primary buttons.
    t = theme.tokens(appearance)
    assert contrast(t.on_accent, t.accent) >= 4.5
    assert contrast(t.on_accent, t.accent_hover) >= 4.5  # a primary button under the pointer


def test_the_text_on_the_accent_is_white_in_the_light_appearance_and_dark_in_the_dark_one() -> None:
    assert theme.tokens("light").on_accent == "#FFFFFF"
    assert theme.tokens("dark").on_accent == "#1F1D1A"  # the text colour of the light appearance
    assert theme.tokens("dark").accent == "#D9834A"  # the accent itself stays


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_accent_as_text_is_easy_to_read_where_a_link_stands(appearance: str) -> None:
    t = theme.tokens(appearance)
    for ground in (t.ground, t.panel, t.control):  # not on the chrome: 4.45:1 in the light one
        assert contrast(t.accent, ground) >= 4.5, (appearance, ground)
        assert contrast(t.accent_hover, ground) >= 4.5, (appearance, ground)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_text_of_a_card_stays_easy_to_read_when_a_drag_makes_it_the_soft_accent(
    appearance: str,
) -> None:
    t = theme.tokens(appearance)
    assert contrast(t.secondary, t.accent_soft) >= 4.5  # the caption and the hint at the button
    assert contrast(t.text, t.accent_soft) >= 4.5
    assert contrast(t.accent_text_on_soft, t.accent_soft) >= 4.5  # the code chips


def declarations(sheet: str) -> list[tuple[str, dict[str, str]]]:
    """The rules of a stylesheet: each selector (as written, on one line) and its properties."""
    rules = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
        properties = {}
        for declaration in body.split(";"):
            if ":" in declaration:
                name, value = declaration.split(":", 1)
                properties[name.strip()] = value.strip()
        rules.append((" ".join(selector.split()), properties))
    return rules


def rule_of(sheet: str, selector: str) -> dict[str, str]:
    return next(properties for found, properties in declarations(sheet) if found == selector)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_hint_beside_the_button_and_the_code_chip_have_the_colours_of_r124(
    appearance: str,
) -> None:
    t = theme.tokens(appearance)
    sheet = theme.stylesheet(appearance)
    assert rule_of(sheet, "QLabel#dropShortcut")["color"] == t.secondary  # "or press ⌘O"
    assert rule_of(sheet, "QLabel#caseCode")["color"] == t.accent_text_on_soft
    assert rule_of(sheet, "QLabel#caseCode")["background"] == t.accent_soft


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_tertiary_colour_is_only_the_text_of_what_is_switched_off(appearance: str) -> None:
    t = theme.tokens(appearance)
    for selector, properties in declarations(theme.stylesheet(appearance)):
        if properties.get("color") == t.tertiary:
            for part in selector.split(","):
                assert ":disabled" in part, selector


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_palette_has_the_tertiary_colour_for_placeholders_and_disabled_text_only(
    appearance: str,
) -> None:
    t = theme.tokens(appearance)
    palette = theme.palette(appearance)
    text_roles = {
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    }
    found = set()
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        for role in QPalette.ColorRole:
            if role in (QPalette.ColorRole.NoRole, QPalette.ColorRole.NColorRoles):
                continue
            if palette.color(group, role) == QColor(t.tertiary):
                found.add((group, role))
                assert role == QPalette.ColorRole.PlaceholderText or (
                    group == QPalette.ColorGroup.Disabled and role in text_roles
                ), (group, role)
    assert (QPalette.ColorGroup.Active, QPalette.ColorRole.PlaceholderText) in found
    assert (QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText) in found


# ---- the palette --------------------------------------------------------------------------------


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_palette_is_made_of_the_tokens(appearance: str) -> None:
    t = theme.tokens(appearance)
    palette = theme.palette(appearance)
    assert palette.color(QPalette.ColorRole.Window) == QColor(t.ground)
    assert palette.color(QPalette.ColorRole.WindowText) == QColor(t.text)
    assert palette.color(QPalette.ColorRole.Base) == QColor(t.panel)
    assert palette.color(QPalette.ColorRole.Text) == QColor(t.text)
    assert palette.color(QPalette.ColorRole.Button) == QColor(t.control)
    assert palette.color(QPalette.ColorRole.Highlight) == QColor(t.accent)
    assert palette.color(QPalette.ColorRole.Accent) == QColor(t.accent)
    assert palette.color(QPalette.ColorRole.PlaceholderText) == QColor(t.tertiary)
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
    assert disabled == QColor(t.tertiary)


def test_the_two_palettes_differ_in_lightness() -> None:
    light, dark = theme.palette("light"), theme.palette("dark")
    assert light.color(QPalette.ColorRole.Window).lightness() > 200
    assert dark.color(QPalette.ColorRole.Window).lightness() < 60
    assert theme.appearance_of(light) == "light" and theme.appearance_of(dark) == "dark"


def test_a_widget_knows_its_tokens_from_its_palette(qtbot: QtBot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setPalette(theme.palette("dark"))
    assert theme.tokens_of(widget) == theme.tokens("dark")
    widget.setPalette(theme.palette("light"))
    assert theme.tokens_of(widget) == theme.tokens("light")


# ---- the stylesheet -----------------------------------------------------------------------------


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


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_stylesheet_is_understood_by_qt(qtbot: QtBot, appearance: str) -> None:
    assert style_messages(qtbot, theme.stylesheet(appearance)) == []


def test_qt_would_say_so_about_a_stylesheet_it_cannot_read(qtbot: QtBot) -> None:
    # The check above can fail: it sees a broken stylesheet for what it is.
    assert style_messages(qtbot, "QFrame { border: ;;; {{ } QFrame#x[") != []


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_stylesheet_uses_the_tokens_of_its_appearance(appearance: str) -> None:
    t = theme.tokens(appearance)
    sheet = theme.stylesheet(appearance)
    for colour in (t.accent, t.panel, t.border, t.notice_bg, t.accent_soft):
        assert colour in sheet, (appearance, colour)
    other = theme.tokens("dark" if appearance == "light" else "light")
    assert other.border not in sheet and other.accent not in sheet
    assert "$" not in sheet  # every placeholder of the template was filled in


def test_the_drop_card_is_a_panel_with_an_accent_state_for_a_drag() -> None:
    sheet = theme.stylesheet("light")
    card = sheet[sheet.index("QFrame#dropZone {") :]
    assert "border-radius: 16px" in card.split("}")[0]
    assert 'QFrame#dropZone[dragOver="true"]' in sheet


# ---- the appearance in force --------------------------------------------------------------------


@pytest.mark.parametrize("value", ["dark", "DARK", " Dark "])
def test_the_environment_can_force_the_dark_appearance(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Light)
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, value)
    assert theme.current_appearance() == "dark"


def test_the_environment_can_force_the_light_appearance(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Dark)
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "light")
    assert theme.current_appearance() == "light"


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [
        (Qt.ColorScheme.Dark, "dark"),
        (Qt.ColorScheme.Light, "light"),
        (Qt.ColorScheme.Unknown, "light"),
    ],
)
def test_without_the_environment_the_system_decides_and_light_is_the_default(
    untouched_look: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    scheme: Qt.ColorScheme,
    expected: str,
) -> None:
    monkeypatch.setattr(theme, "system_scheme", lambda: scheme)
    assert theme.current_appearance() == expected


@pytest.mark.parametrize("value", ["", "sepia", "1"])
def test_an_environment_value_that_names_no_appearance_is_ignored(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Dark)
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, value)
    assert theme.current_appearance() == "dark"


# ---- installing the look ------------------------------------------------------------------------


def test_apply_installs_the_palette_the_stylesheet_and_the_system_font_at_13_pixels(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "light")
    theme.apply(untouched_look)
    assert untouched_look.styleSheet() == theme.stylesheet("light")
    assert untouched_look.palette().color(QPalette.ColorRole.Window) == QColor("#FBFAF8")
    assert QFontInfo(untouched_look.font()).pixelSize() == 13


def test_apply_installs_the_dark_look_when_the_environment_says_dark(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "dark")
    theme.apply(untouched_look)
    assert untouched_look.styleSheet() == theme.stylesheet("dark")
    assert untouched_look.palette().color(QPalette.ColorRole.Window) == QColor("#1E1D1B")


def test_the_look_follows_the_system_when_it_changes_between_light_and_dark(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Light)
    theme.apply(untouched_look)
    assert untouched_look.styleSheet() == theme.stylesheet("light")
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Dark)
    untouched_look.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert untouched_look.styleSheet() == theme.stylesheet("dark")
    assert theme.appearance_of(untouched_look.palette()) == "dark"
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Light)
    untouched_look.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert untouched_look.styleSheet() == theme.stylesheet("light")


def test_a_forced_appearance_is_not_changed_by_the_system(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "light")
    theme.apply(untouched_look)
    monkeypatch.setattr(theme, "system_scheme", lambda: Qt.ColorScheme.Dark)
    untouched_look.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert untouched_look.styleSheet() == theme.stylesheet("light")


def test_applying_again_does_not_follow_the_system_twice(untouched_look: QApplication) -> None:
    theme.apply(untouched_look)
    theme.apply(untouched_look)
    assert len(untouched_look.findChildren(theme.AppearanceFollower)) == 1


def test_a_widget_made_before_the_change_is_painted_in_the_new_look(
    qtbot: QtBot, untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    label = QLabel("Hello")
    qtbot.addWidget(label)
    label.show()  # a widget that was never shown takes the palette when it is
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "light")
    theme.apply(untouched_look)
    assert label.palette().color(QPalette.ColorRole.Window) == QColor("#FBFAF8")
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "dark")
    theme.apply(untouched_look)
    assert label.palette().color(QPalette.ColorRole.Window) == QColor("#1E1D1B")


# ---- the fonts ----------------------------------------------------------------------------------


def test_the_body_font_is_the_system_font_at_13_pixels(untouched_look: QApplication) -> None:
    font = theme.body_font()
    assert QFontInfo(font).pixelSize() == 13
    assert font.weight() == QFont.Weight.Normal


def test_the_serif_font_for_the_document_names_the_three_families_in_order(
    untouched_look: QApplication,
) -> None:
    font = theme.serif_font()
    # Only the families the system has (an absent one costs Qt an alias lookup and a warning).
    installed = set(QFontDatabase.families())
    wanted = [n for n in ("Iowan Old Style", "Palatino", "Georgia") if n in installed]
    assert font.families()[:3] == (wanted or ["Georgia"])
    dpi = untouched_look.primaryScreen().logicalDotsPerInchY()
    assert font.pointSizeF() * dpi / 72 == pytest.approx(14.5, abs=0.01)  # 14.5 pixels
    assert theme.serif_font(16).pixelSize() == 16  # a whole number of pixels is set as such


def test_the_mono_font_is_fixed_pitch_for_codes_and_placeholders(
    untouched_look: QApplication,
) -> None:
    font = theme.mono_font()
    # No family is asked for by name: it is the system's fixed font, whatever that is.
    assert len(font.families()) <= 1
    assert (
        font.families()[0] == QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    )
    assert QFontInfo(font).pixelSize() == 12


# ---- the status line ----------------------------------------------------------------------------


def test_the_status_line_is_hidden_when_it_says_nothing_and_marks_a_problem(
    qtbot: QtBot,
) -> None:
    label = QLabel()
    label.setObjectName("status")
    qtbot.addWidget(label)
    label.show()
    theme.set_status(label, "Saved.")
    assert label.isVisible() and label.text() == "Saved." and not label.property("problem")
    theme.set_status(label, "Could not save.", problem=True)
    assert label.property("problem") is True
    theme.set_status(label, "")
    assert label.isHidden()


def test_present_keeps_only_the_families_the_system_lists_and_looks_once(
    untouched_look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def families(*args: object) -> list[str]:
        calls.append(1)
        return ["Palatino", "Menlo"]

    theme._present.cache_clear()
    monkeypatch.setattr(QFontDatabase, "families", staticmethod(families))
    assert theme._present("Iowan Old Style", "Palatino", "Georgia") == ["Palatino"]
    assert theme._present("Iowan Old Style", "Palatino", "Georgia") == ["Palatino"]
    assert len(calls) == 1  # cached
    theme._present.cache_clear()
