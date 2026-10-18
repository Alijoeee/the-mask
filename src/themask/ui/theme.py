"""The look of the app: one colour for each type of placeholder, and a small stylesheet.

The colours are the backgrounds that mark a find in the document text, so each is a light tint
that reads with black text. The text pane sets black text on them itself, which keeps them legible
when the Mac is in dark mode. The stylesheet uses the system palette for everything else, so that
it follows light and dark mode as well.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from themask.model import PlaceholderType

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

STYLESHEET = """
QLabel#title { font-size: 30px; font-weight: 600; }
QLabel#tagline { font-size: 14px; }
QLabel#dropTitle { font-size: 20px; font-weight: 600; }
QLabel#status { font-size: 13px; }

QFrame#dropZone {
    border: 2px dashed palette(mid);
    border-radius: 14px;
    background: palette(base);
}
QFrame#dropZone[dragOver="true"] {
    border-color: palette(highlight);
    background: palette(alternate-base);
}
QFrame#dropZone:disabled { border-color: palette(midlight); }

QLabel#notice, QLabel#warnings {
    background: #FFF4CE;
    color: #5B4300;
    border: 1px solid #ECD48B;
    border-radius: 6px;
    padding: 6px 10px;
}

QPushButton#primary { font-weight: 600; padding: 6px 18px; }
"""


def apply_theme(app: QApplication) -> None:
    """Give the application its stylesheet."""
    app.setStyleSheet(STYLESHEET)
