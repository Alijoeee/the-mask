"""The look of the app: the colour tokens of the light and dark appearance, the palette and the
stylesheet made from them, the fonts, and the status line the screens say what happened in.

Everything that has a colour reads it from ``Tokens``, so there is one place to change a colour.
``tokens(appearance)`` gives the set of "light" or "dark". ``apply`` installs the look of the
appearance in force (``current_appearance``) on the application: the palette, the stylesheet and
the system font at 13 pixels, and installs it again whenever the system changes between light and
dark. ``THEMASK_APPEARANCE=light`` or ``dark`` forces one, for tests and screenshots. A widget that
paints itself asks its own palette which appearance it is in (``tokens_of``) and so follows the
application without any wiring.

The twelve placeholder colours (``TYPE_COLOURS``) are the backgrounds that mark a find in the
document text and the chips of the review, in both appearances: each is a light tint that reads
with black text, and the text pane sets black text on them itself.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import cache
from string import Template
from typing import Final, Literal

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from themask.model import PlaceholderType

Appearance = Literal["light", "dark"]
APPEARANCES: Final[tuple[Appearance, ...]] = ("light", "dark")
APPEARANCE_VARIABLE = "THEMASK_APPEARANCE"

# Twelve tints that are far enough apart to tell at a glance; black text on each is above 12:1.
TYPE_COLOURS: dict[PlaceholderType, str] = {
    PlaceholderType.PERSON: "#F9B9B7",
    PlaceholderType.COMPANY: "#AECBF0",
    PlaceholderType.AMOUNT: "#C5E8A9",
    PlaceholderType.PERCENT: "#FFF7A8",
    PlaceholderType.QUANTITY: "#8EDCD0",
    PlaceholderType.EMAIL: "#FFD3A0",
    PlaceholderType.PHONE: "#E6C2EE",
    PlaceholderType.ADDRESS: "#C9C5F2",
    PlaceholderType.IBAN: "#F7C6DD",
    PlaceholderType.ID: "#B8E4F5",
    PlaceholderType.URL: "#D8D2B0",
    PlaceholderType.CUSTOM: "#DADADA",
}


@dataclass(frozen=True)
class Tokens:
    """The colours of one appearance, each as ``#RRGGBB``.

    The grounds, from the back to the front: ``ground`` (the window), ``chrome`` (the sidebar and
    the tool bar), ``panel`` (cards, the document, fields), ``control`` (buttons) and
    ``table_head``. ``border`` and ``border_strong`` draw the edge of a card and of a control;
    ``hairline`` the line between rows and the fill of a quiet control under the pointer.
    ``text`` is for reading, ``secondary`` for captions and hints, and ``tertiary`` only for the
    placeholder inside a field and for text that is switched off (neither is held to a contrast).
    The accent is the brand: ``accent`` (buttons, links, the chosen item) with ``on_accent`` for
    text on it (white on the light accent, the dark text colour on the dark one), ``accent_hover``,
    ``accent_soft`` (a chosen row, a drag over a drop zone) and ``accent_text_on_soft`` (text on
    it, such as the code of a case). The notice colours are for a line that asks the owner to look
    (``notice_card_bg`` is the paler one for a whole card); ``success`` and ``danger`` colour a
    mark, ``success_bg`` its background and ``success_text`` a sentence.

    Contrast (ruling R124): every pair of text and ground is 4.5:1 or more in both appearances,
    and tests/ui/test_theme.py computes them: ``text`` and ``secondary`` on every ground and on
    ``accent_soft``, ``on_accent`` on ``accent`` and ``accent_hover``, the accent and its hover as
    text (a link) on ``ground``, ``panel`` and ``control`` (not on ``chrome``: 4.45:1 in the light
    appearance), ``accent_text_on_soft`` on ``accent_soft``, ``notice_text`` on the notice
    backgrounds, and ``danger`` and ``success_text`` on ``ground`` and ``panel``. The mockups'
    light accent (#B5642A, 4.36:1 under white) and white text on the dark accent (2.88:1) gave way
    to the light accent #A85A24 and, in the dark appearance, the dark text colour on the accent.
    """

    ground: str
    chrome: str
    panel: str
    control: str
    border: str
    border_strong: str
    hairline: str
    text: str
    secondary: str
    tertiary: str
    accent: str
    accent_hover: str
    accent_soft: str
    accent_text_on_soft: str
    on_accent: str
    notice_bg: str
    notice_card_bg: str
    notice_border: str
    notice_text: str
    success: str
    success_bg: str
    success_text: str
    danger: str
    table_head: str


_LIGHT = Tokens(
    ground="#FBFAF8",
    chrome="#F3F0EB",
    panel="#FFFFFF",
    control="#FFFFFF",
    border="#E6E1DA",
    border_strong="#D9D2C8",
    hairline="#EFEBE5",
    text="#1F1D1A",
    secondary="#6B655E",
    tertiary="#9B948B",
    accent="#A85A24",  # the mockups' #B5642A is 4.36:1 under white: R124
    accent_hover="#8F4C1D",
    accent_soft="#F4E4D8",
    accent_text_on_soft="#7A4019",
    on_accent="#FFFFFF",
    notice_bg="#FFF4CE",
    notice_card_bg="#FFF9E6",
    notice_border="#ECD48B",
    notice_text="#5B4300",
    success="#2E9E5B",
    success_bg="#EAF4E6",
    success_text="#2E7D4F",
    danger="#B3261E",
    table_head="#F7F4EF",
)

_DARK = Tokens(
    ground="#1E1D1B",
    chrome="#262523",
    panel="#2C2A27",
    control="#33312D",
    border="#3A3733",
    border_strong="#4A4640",
    hairline="#3A3733",
    text="#F2EEE8",
    secondary="#A39B91",
    tertiary="#7E776E",
    accent="#D9834A",
    accent_hover="#F0A370",
    accent_soft="#3F2E24",
    accent_text_on_soft="#F0C9A8",
    on_accent="#1F1D1A",  # white on #D9834A is 2.88:1, the dark text colour 5.8:1: R124
    notice_bg="#3D3320",
    notice_card_bg="#3D3320",
    notice_border="#5A4A1E",
    notice_text="#F3D8A0",
    success="#3FB46F",
    success_bg="#1F3326",
    success_text="#5CC27F",
    danger="#FF6B61",
    table_head="#302E2A",
)

_TOKENS: dict[str, Tokens] = {"light": _LIGHT, "dark": _DARK}


def tokens(appearance: str) -> Tokens:
    """The colours of ``appearance``, "light" or "dark"."""
    try:
        return _TOKENS[appearance]
    except KeyError:
        raise ValueError(f"Not an appearance: {appearance!r} (light or dark).") from None


def appearance_of(palette: QPalette) -> Appearance:
    """The appearance a palette is in: dark when its window is dark."""
    return "dark" if palette.color(QPalette.ColorRole.Window).lightness() < 128 else "light"


def tokens_of(widget: QWidget) -> Tokens:
    """The colours of the appearance ``widget`` is shown in, by its palette."""
    return tokens(appearance_of(widget.palette()))


# ---- the palette --------------------------------------------------------------------------------


def palette(appearance: str) -> QPalette:
    """The application palette of ``appearance``: what Qt draws with wherever the stylesheet does
    not say otherwise (the window, text fields, selections, links, disabled text).
    """
    t = tokens(appearance)
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.ground,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.panel,
        QPalette.ColorRole.AlternateBase: t.ground,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.control,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.BrightText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: t.control,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.tertiary,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.on_accent,
        QPalette.ColorRole.Accent: t.accent,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.LinkVisited: t.accent_hover,
        QPalette.ColorRole.Light: t.panel,
        QPalette.ColorRole.Midlight: t.border,
        QPalette.ColorRole.Mid: t.border_strong,
        QPalette.ColorRole.Dark: t.secondary,
        QPalette.ColorRole.Shadow: t.text,
    }
    for role, colour in roles.items():
        result.setColor(role, colour)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        result.setColor(QPalette.ColorGroup.Disabled, role, t.tertiary)
    result.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, t.border_strong)
    return result


# ---- the stylesheet -----------------------------------------------------------------------------

# The stylesheet of both appearances; $name is a token. The rules start with the text, then the
# buttons, the fields and the lists, then the parts of the window.
_TEMPLATE = Template("""
QToolTip {
    background: $control;
    color: $text;
    border: 1px solid $border_strong;
    padding: 4px 6px;
}

QLabel#heading { font-size: 18px; font-weight: 600; }
QLabel#status { font-size: 13px; }
QLabel#preview { font-size: 12px; }
QLabel#dropTitle { font-size: 22px; font-weight: 600; }
QLabel#dropHint { color: $secondary; }
QLabel#dropShortcut { color: $secondary; font-size: 12px; }
QLabel#step { color: $secondary; font-size: 11px; }

QLabel#notice, QLabel#warnings, QLabel#status[problem="true"] {
    background: $notice_bg;
    color: $notice_text;
    border: 1px solid $notice_border;
    border-radius: 8px;
    padding: 8px 12px;
}

QFrame#dropZone {
    background: $panel;
    border: 1px solid $border;
    border-radius: 16px;
}
QFrame#dropZone[dragOver="true"] {
    background: $accent_soft;
    border-color: $accent;
}
QFrame#dropZone QLabel#status:disabled,
QFrame#dropZone QLabel#step:disabled { color: $secondary; }

QPushButton {
    background: $control;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 7px;
    padding: 0 12px;
    min-height: 26px;
    font-weight: 600;
}
QPushButton:hover { background: $hairline; }
QPushButton:pressed { background: $border; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { color: $tertiary; border-color: $border; background: $control; }
QPushButton#primary {
    background: $accent;
    color: $on_accent;
    border-color: $accent;
}
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:pressed { background: $accent_hover; }
QPushButton#primary:focus { border-color: $text; }
QPushButton#primary:disabled { background: $border; color: $tertiary; border-color: $border; }
QPushButton#chooseButton { min-height: 30px; padding: 0 16px; border-radius: 8px; }

QLineEdit, QPlainTextEdit, QTextEdit {
    background: $panel;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border-color: $accent; }

QAbstractItemView {
    background: $panel;
    color: $text;
    alternate-background-color: $ground;
    border: 1px solid $border;
    border-radius: 8px;
    gridline-color: $hairline;
    selection-background-color: $accent_soft;
    selection-color: $text;
    outline: none;
}
QHeaderView::section {
    background: $table_head;
    color: $secondary;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
}

QGroupBox {
    background: $panel;
    border: 1px solid $border;
    border-radius: 12px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: $secondary;
}

QProgressBar {
    background: $border;
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}
QProgressBar::chunk { background: $accent; border-radius: 3px; }
""")


# The parts of the window: the tool bar, the sidebar's notes, the home screen. The tool bar's
# primary action is a button whose name is primaryAction; the sidebar's sections and the toggle
# paint themselves from the palette.
_SHELL = Template("""
QToolBar#mainToolBar {
    background: $chrome;
    border: none;
    border-bottom: 1px solid $border;
    spacing: 12px;
    padding: 0 16px;
}
QToolBar#mainToolBar QToolButton#primaryAction {
    background: $accent;
    color: $on_accent;
    border: 1px solid $accent;
    border-radius: 7px;
    padding: 0 14px;
    min-height: 26px;
    font-weight: 600;
}
QToolBar#mainToolBar QToolButton#primaryAction:hover {
    background: $accent_hover;
    border-color: $accent_hover;
}
QToolBar#mainToolBar QToolButton#primaryAction:focus { border-color: $text; }
QToolBar#mainToolBar QToolButton#primaryAction:disabled {
    background: $border;
    border-color: $border;
    color: $tertiary;
}
QLabel#toolbarTitle { color: $text; font-size: 13px; font-weight: 600; }
QLabel#toolbarCaption { color: $secondary; font-size: 11px; }

QFrame#sidebar { background: $chrome; border: none; border-right: 1px solid $border; }
QLabel#sidebarNote { color: $secondary; font-size: 11px; }
QLabel#legendTitle { color: $text; font-size: 11px; font-weight: 600; }

QStackedWidget#screenStack { background: $ground; border: none; }
QScrollArea#homeScroll { background: $ground; border: none; }
QWidget#homeContent { background: transparent; border: none; }
QFrame#dropZone QLabel#dropHint:disabled { color: $tertiary; }
QLabel#sectionTitle { color: $secondary; }
QFrame#recentPanel { background: $panel; border: 1px solid $border; border-radius: 12px; }
QFrame#recentRow { background: transparent; border: none; }
QFrame#recentRow[last="false"] { border-bottom: 1px solid $hairline; }
QLabel#caseCode {
    color: $accent_text_on_soft;
    background: $accent_soft;
    border-radius: 6px;
    padding: 3px 8px;
}
QLabel#caseFiles { font-weight: 600; }
QLabel#caseCaption { color: $secondary; font-size: 12px; }

QPushButton#link {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    min-height: 0;
    color: $accent;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#link:hover { background: transparent; color: $accent_hover; }
QPushButton#link:pressed { background: transparent; color: $accent_hover; }
QPushButton#link:focus { background: transparent; text-decoration: underline; }
QPushButton#link:disabled { background: transparent; color: $tertiary; }
""")


def stylesheet(appearance: str) -> str:
    """The application stylesheet of ``appearance``."""
    values = asdict(tokens(appearance))
    return _TEMPLATE.substitute(values) + _SHELL.substitute(values)


# ---- the fonts ----------------------------------------------------------------------------------


def _pixel_font(font: QFont, pixels: float) -> QFont:
    """``font`` at ``pixels`` pixels. Pixel sizes are whole numbers in Qt, so a fraction goes by
    the point size: on the Mac a point is a pixel, elsewhere the screen's resolution says how many
    points make the pixels.
    """
    screen = QGuiApplication.primaryScreen()
    dpi = screen.logicalDotsPerInchY() if screen is not None else 72.0
    if float(pixels).is_integer():
        font.setPixelSize(int(pixels))
    else:
        font.setPointSizeF(pixels * 72.0 / dpi)
    return font


def body_font() -> QFont:
    """The system font at 13 pixels, the size of the text of the screens."""
    return _pixel_font(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont), 13)


@cache
def _present(*names: str) -> list[str]:
    """The ``names`` of fonts the system has, in the order given. A family that is not installed
    is left out, as Qt would pay to look for an alias of it (and warn) every time a font is made.
    Looked up once (``hasFamily`` is no use: it answers for aliases, which is the cost).
    """
    installed = set(QFontDatabase.families())
    return [name for name in names if name in installed]


def serif_font(pixels: float = 14.5) -> QFont:
    """The font of the document pane: Iowan Old Style, else Palatino, else Georgia (the ones the
    system has)."""
    font = QFont()
    font.setFamilies(_present("Iowan Old Style", "Palatino", "Georgia") or ["Georgia"])
    font.setStyleHint(QFont.StyleHint.Serif)
    return _pixel_font(font, pixels)


def mono_font(pixels: float = 12) -> QFont:
    """The font of codes and placeholders: the system's fixed font (SF Mono, Menlo or the like)."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return _pixel_font(font, pixels)


# ---- the appearance in force --------------------------------------------------------------------


def system_scheme() -> Qt.ColorScheme:
    """What the system says: light, dark, or unknown (no application yet, or a platform that does
    not tell). Tests replace it.
    """
    if QGuiApplication.instance() is None:
        return Qt.ColorScheme.Unknown
    return QGuiApplication.styleHints().colorScheme()


def current_appearance() -> Appearance:
    """The appearance to show: the one ``THEMASK_APPEARANCE`` names ("light" or "dark"), else the
    system's, else light.
    """
    forced = os.environ.get(APPEARANCE_VARIABLE, "").strip().lower()
    if forced == "light":
        return "light"
    if forced == "dark":
        return "dark"
    return "dark" if system_scheme() == Qt.ColorScheme.Dark else "light"


class AppearanceFollower(QObject):
    """Installs the look again when the system changes between light and dark. It lives as long
    as the application, which owns it.
    """

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self.setObjectName("appearance-follower")
        self._application = application
        application.styleHints().colorSchemeChanged.connect(self._changed)

    def _changed(self) -> None:
        _install(self._application)


def _install(application: QApplication) -> None:
    appearance = current_appearance()
    application.setPalette(palette(appearance))
    application.setStyleSheet(stylesheet(appearance))
    application.setFont(body_font())


def apply(application: QApplication) -> None:
    """Give the application its look, and keep it in step with the system's light and dark."""
    _install(application)
    if application.findChild(AppearanceFollower) is None:
        AppearanceFollower(application)


def set_status(label: QLabel, text: str, problem: bool = False) -> None:
    """Say ``text`` in the status line ``label`` (its object name is "status"); an empty text hides
    the line, and a problem is drawn in the colours of a notice.
    """
    label.setText(text)
    if label.property("problem") != problem:
        label.setProperty("problem", problem)  # the stylesheet reads it
        label.style().unpolish(label)
        label.style().polish(label)
    label.setVisible(bool(text))
