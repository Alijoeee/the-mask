"""The inspector of the review screen: the right-hand pane that lists what was found.

On top a find field and the two actions for the text selected in the document ("Hide selection",
"Show always"); in the middle the values, in sections by kind of value (companies, people, amounts
and percentages, addresses and the like, other); at the bottom the counts. The pane draws itself
from the tokens of the theme and follows the light or dark appearance without any wiring.

* ``sections`` decides where each group stands: the groups the analysis was unsure of and that are
  switched off first, under "NOT SURE — HIDE?", then one section for each family of types.
* A group is a row (``GroupRow``): a chip in the colour of its type, the value, a caption (its
  placeholder, how many places, the other spellings), a "CHECK" pill when the analysis was not
  sure, and a switch (``ToggleSwitch``; on = hidden). A row in the "not sure" section has a Hide and
  a Show button instead of the switch. The first row of a section draws the section's heading.
* The rows are the item widgets of a ``GroupTree``, a ``QTreeWidget`` whose top-level items are the
  groups (the places of a group are the lines under its row, closed until the owner opens them).
  The tree keeps Qt's selection, arrow keys and scrolling; Space switches a row.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    Signal,
    SignalInstance,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QEnterEvent,
    QFocusEvent,
    QFont,
    QFontMetricsF,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from themask.labels import LabelError, clean_label
from themask.leakcheck import unverifiable
from themask.model import Group, KeyEntry, PlaceholderType
from themask.review import asks_about, key_variants
from themask.ui import icons
from themask.ui.theme import TYPE_COLOURS, Tokens, appearance_of, body_font, tokens_of

CHECK_TIP = "check: The MASK is not sure about this one. Have a look at it before you go on."
FIND_PLACEHOLDER = "Find in document  ⌘F"
FIND_NAME = "Find in document"
HINT = "Space toggles · ↑↓ moves"
NOT_SURE = "NOT SURE — HIDE?"
NAME_TITLE = "Mask name"
NAME_TITLE_SHOWN = "Mask name (selected value)"
NAME_TIP = "The name the masked file writes for the value selected in the list."
NAME_HIDE_PLACEHOLDER = "Name it (optional)"
NAME_HIDE_NAME = "Name for the hidden text, optional"
NAME_HIDE_TIP = (
    "Optional: a name to write instead of the placeholder for this text, such as Provider. "
    "Empty keeps the default."
)
NAME_NONE = "Select a value in the list to give its mask a name."
NAME_STORED = (
    "This value is in the case already, so it keeps the name its earlier files were written with."
)
NAME_CLASH = "its name clashes with a value"
NAME_INVALID = "Press Return to check this name."
MODEL_ONLY = "found by the model only"
TOO_SHORT = "too short for the leak check"
MAX_OTHER_SPELLINGS = 2

# The measures of a row, in pixels (the approved mockup's: a 6 px padding of the list, 7 px and
# 8 px inside a row, 10 px between the chip, the text and the switch, 2 px between two rows).
_INSET = 6
_PAD_X = 8
_PAD_Y = 7
_GAP = 10
_ROW_GAP = 2
_CHIP = 10
_NAME_LINE = 17  # 13 px at a line height of 1.3
_CAPTION_LINE = 14  # 11 px at a line height of 1.3
_MAX_CAPTION_LINES = 3
_BAND_LINE = 16  # a section's heading, 11 px at 1.45
_BAND_FIRST = 8 + 8 + _BAND_LINE + 4  # the list's own 8 px of padding, then the heading's
_BAND_NEXT = 10 + _BAND_LINE + 4
_PILL_HEIGHT = 16
_PILL_GAP = 6
_BUTTON_HEIGHT = 26
_BUTTON_GAP = 6
_OCCURRENCE_HEIGHT = 28
_MESSAGE_LINE = 15  # 11 px at a line height of 1.3, rounded up
_BOX = 14  # the check box of a place


@dataclass(frozen=True)
class Family:
    """A section of the list: the heading and the types of value it holds."""

    title: str
    kinds: frozenset[PlaceholderType]


FAMILIES: tuple[Family, ...] = (
    Family("COMPANIES", frozenset({PlaceholderType.COMPANY})),
    Family("PEOPLE", frozenset({PlaceholderType.PERSON})),
    Family(
        "AMOUNTS, PERCENTAGES",
        frozenset({PlaceholderType.AMOUNT, PlaceholderType.PERCENT, PlaceholderType.QUANTITY}),
    ),
    Family(
        "ADDRESSES, E-MAIL, BANK",
        frozenset(
            {
                PlaceholderType.ADDRESS,
                PlaceholderType.EMAIL,
                PlaceholderType.PHONE,
                PlaceholderType.IBAN,
                PlaceholderType.ID,
                PlaceholderType.URL,
            }
        ),
    ),
    Family("OTHER", frozenset({PlaceholderType.CUSTOM})),
)


@dataclass(frozen=True)
class Section:
    """A heading and the groups under it, in the order of the document."""

    name: str
    groups: tuple[Group, ...]
    question: bool = False  # the "not sure" section: a Hide and a Show button instead of a switch

    @property
    def title(self) -> str:
        """The heading as it is drawn: "COMPANIES · 2"."""
        return f"{self.name} · {len(self.groups)}"


def sections(groups: Iterable[Group], answered: Collection[str] = ()) -> list[Section]:
    """The sections of the list, without the empty ones: the groups the owner is asked about
    (``asks_about``) first, then a section for each family of types, each in the order the groups
    are given (the order of the document).
    """
    everything = list(groups)
    result: list[Section] = []
    asked = tuple(g for g in everything if asks_about(g, answered))
    if asked:
        result.append(Section(NOT_SURE, asked, question=True))
    asked_ids = {g.id for g in asked}
    rest = [g for g in everything if g.id not in asked_ids]
    for family in FAMILIES:
        found = tuple(g for g in rest if g.type in family.kinds)
        if found:
            result.append(Section(family.title, found))
    return result


def collapse(text: str) -> str:
    """``text`` on one line: every run of white space (a line break, a no-break space) is one
    space.
    """
    return " ".join(text.split())


def places(count: int) -> str:
    """How many places, as the caption says it: 1 place, 6 places."""
    return f"{count} place" if count == 1 else f"{count} places"


def other_spellings(group: Group) -> list[str]:
    """How else the document writes the value of ``group``, besides its canonical form: each
    form its finds show, once, in the order they stand in the document.
    """
    canonical = collapse(group.canonical)
    found: list[str] = []
    for finding in group.findings:
        form = collapse(finding.text)
        if form != canonical and form not in found:
            found.append(form)
    return found


def check_reason(group: Group) -> str:
    """Why the analysis was not sure of ``group``, when the group says: only the language model
    found it, or it is too short for the leak check to look for. Else an empty text.
    """
    if not group.needs_check:
        return ""
    if group.findings and all(finding.source == "model" for finding in group.findings):
        return MODEL_ONLY
    entry = KeyEntry(
        group.placeholder,
        group.type,
        group.canonical,
        key_variants(group.type, group.canonical, group.variants),
    )
    return TOO_SHORT if unverifiable([entry]) else ""


def caption_of(group: Group, problem: bool = False) -> str:
    """The line under a group's name: "[COMPANY_1] · 6 places · also “Northwind”, “the Buyer’s
    group”". It names up to two other spellings and then goes on with "…"; a group to check says
    why, when it can.
    """
    parts = [group.token, places(len(group.findings))]
    others = other_spellings(group)
    if others:
        shown = [f"“{form}”" for form in others[:MAX_OTHER_SPELLINGS]]
        if len(others) > MAX_OTHER_SPELLINGS:
            shown.append("…")
        parts.append(f"also {', '.join(shown)}")
    reason = check_reason(group)
    if reason:
        parts.append(reason)
    if problem:
        parts.append(NAME_CLASH)
    return " · ".join(parts)


@dataclass(frozen=True)
class FooterCounts:
    """The numbers of the footer: the groups that are hidden and sure, the ones to check (switched
    on and marked), and the ones the owner shows on purpose (switched off). Together they are all
    the groups.
    """

    hidden: int
    to_check: int
    shown: int

    @classmethod
    def of(cls, groups: Iterable[Group], answered: Collection[str] = ()) -> FooterCounts:
        """The counts; a group the owner is still asked about (``asks_about``) is to check, not
        shown on purpose.
        """
        everything = list(groups)
        asked = [asks_about(g, answered) for g in everything]
        return cls(
            hidden=sum(g.enabled and not g.needs_check for g in everything),
            to_check=sum(
                (g.enabled and g.needs_check) or q for g, q in zip(everything, asked, strict=True)
            ),
            shown=sum(not g.enabled and not q for g, q in zip(everything, asked, strict=True)),
        )

    def text(self) -> str:
        """The footer's line: 12 hidden · 2 to check · 0 shown on purpose."""
        return f"{self.hidden} hidden · {self.to_check} to check · {self.shown} shown on purpose"


@dataclass(frozen=True)
class RowData:
    """What a row shows about a group."""

    group_id: str
    kind: PlaceholderType
    name: str  # the canonical form on one line
    caption: str
    needs_check: bool
    hidden: bool  # the switch: the group is on, its places will be hidden
    question: bool = False  # a row of the "not sure" section

    @classmethod
    def of(cls, group: Group, question: bool = False, problem: bool = False) -> RowData:
        return cls(
            group.id,
            group.type,
            collapse(group.canonical),
            caption_of(group, problem),
            group.needs_check,
            group.enabled,
            question,
        )

    def description(self) -> str:
        """What a screen reader says about the row."""
        text = f"{self.name}, {self.caption}"
        return f"{text}, to check" if self.needs_check else text


# ---- fonts and text -----------------------------------------------------------------------------


def _font(pixels: int, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    """The system font at ``pixels`` pixels, with a ``weight`` and a letter spacing in pixels."""
    font = body_font()
    font.setPixelSize(pixels)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def _elided(text: str, font: QFont, width: float) -> str:
    return QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, max(width, 0.0))


def _wrapped(text: str, font: QFont, width: float, most: int) -> list[str]:
    """``text`` in lines of at most ``width`` pixels, broken at spaces (a word longer than a line
    is broken where it must be). More than ``most`` lines end with "…" on the last one.
    """
    if not text:
        return []
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    spans: list[tuple[int, int]] = []
    layout.beginLayout()
    try:
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(width, 1.0))
            spans.append((line.textStart(), line.textLength()))
    finally:
        layout.endLayout()
    lines = [text[start : start + length].rstrip() for start, length in spans]
    if len(lines) > most:
        lines = lines[:most]
        lines[-1] = _elided(text[spans[most - 1][0] :], font, width)
    return lines


def _left_aligned() -> QTextOption:
    option = QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    option.setWrapMode(QTextOption.WrapMode.NoWrap)
    return option


def _centred() -> QTextOption:
    option = QTextOption(Qt.AlignmentFlag.AlignCenter)
    option.setWrapMode(QTextOption.WrapMode.NoWrap)
    return option


# ---- the switch ---------------------------------------------------------------------------------


class ToggleSwitch(QCheckBox):
    """A check box drawn as a switch: checked, the track is in the accent colour and the knob on
    the right. It is a real ``QCheckBox`` (a screen reader says "checked" and "not checked", and
    Space and a click toggle it); only its look differs.
    """

    WIDTH = 32
    HEIGHT = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, self.HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens_of(self)
        on = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = track.height() / 2
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.accent))
            knob = t.on_accent  # what is drawn on the accent
        else:
            painter.setPen(QPen(QColor(t.secondary), 1))
            painter.setBrush(QColor(t.border_strong))
            knob = t.panel
        painter.drawRoundedRect(track, radius, radius)
        size = track.height() - 5
        left = track.right() - 2.5 - size if on else track.left() + 2.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(knob))
        painter.drawEllipse(QRectF(left, track.top() + 2.5, size, size))
        if self.hasFocus():
            painter.setOpacity(1.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.accent), 2))
            painter.drawRoundedRect(
                track.adjusted(-1.5, -1.5, 1.5, 1.5), radius + 1.5, radius + 1.5
            )


# ---- a row --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    """Where everything of a row stands for a given width; all in the row's own coordinates."""

    width: int
    height: int
    row: QRectF  # the row's box, the one that is coloured when the row is selected
    band: QRectF | None  # the heading of the section, when the row starts one
    chip: QRectF
    name: str  # elided to fit
    name_box: QRectF
    pill: QRectF | None
    caption: tuple[str, ...]
    caption_box: QRectF  # the first line; the others follow
    controls: QPoint  # the top left of the switch, or of the first button


class GroupRow(QWidget):
    """The row of a group: chip, name, caption, "CHECK" pill and switch.

    It paints itself (a widget's ``paintEvent`` with the tokens of its own palette) and lays out
    for the width it is given (``fit``, which also says how tall the row is: a caption may need
    several lines). ``switched`` is sent when the owner moves the switch; a row of the "not sure"
    section has the buttons ``hide_button`` and ``show_button`` instead and sends ``hideClicked``
    and ``showClicked``. A row that starts a section draws the section's ``heading`` above it
    (``leading``: it is the first of the list, which has some room above it).
    """

    switched = Signal(bool)
    hideClicked = Signal()
    showClicked = Signal()

    def __init__(
        self,
        data: RowData,
        heading: str | None = None,
        leading: bool = False,
        width: int = 300,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.data = data
        self.heading = heading
        self.leading = leading
        self._selected = False
        self._current = False
        self._focused = False
        self._plan: _Plan | None = None
        self._name_font = _font(13, QFont.Weight.DemiBold)
        self._caption_font = _font(11)
        self._band_font = _font(11, QFont.Weight.DemiBold, 0.4)
        self._pill_font = _font(10, QFont.Weight.Bold, 0.3)
        self.switch: ToggleSwitch | None = None
        self.hide_button: QPushButton | None = None
        self.show_button: QPushButton | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setAccessibleName(data.name)
        self.setAccessibleDescription(data.description())
        self.setToolTip(f"{data.caption}\n{CHECK_TIP}" if data.needs_check else data.caption)
        if data.question:
            self.hide_button = self._button("Hide", f"Hide {data.name}", self.hideClicked)
            self.show_button = self._button("Show", f"Show {data.name}", self.showClicked)
        else:
            self.switch = ToggleSwitch(self)
            self.switch.setChecked(data.hidden)
            self.switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the list takes the keys
            self.switch.setAccessibleName(f"Hide {data.name}")
            self.switch.setAccessibleDescription(data.caption)
            self.switch.toggled.connect(self.switched)
        self.fit(width)

    def _button(self, text: str, name: str, signal: SignalInstance) -> QPushButton:
        button = QPushButton(text, self)
        button.setFont(_font(12, QFont.Weight.DemiBold))
        button.setFixedHeight(_BUTTON_HEIGHT)
        button.setAccessibleName(name)
        button.clicked.connect(signal)
        return button

    # ---- state --------------------------------------------------------------------------------

    def set_checked(self, checked: bool) -> None:
        """Show the switch as on (the group is hidden) or off, without telling anyone."""
        self.data = replace(self.data, hidden=checked)
        if self.switch is not None and self.switch.isChecked() != checked:
            with QSignalBlocker(self.switch):
                self.switch.setChecked(checked)
        self.update()

    def set_marked(self, selected: bool, current: bool, focused: bool) -> None:
        """Whether the row is selected in the list, whether it is the list's current row and
        whether the list has the keyboard (the current row then shows a ring).
        """
        state = (selected, current, focused)
        if state != (self._selected, self._current, self._focused):
            self._selected, self._current, self._focused = state
            self.update()

    @property
    def selected(self) -> bool:
        return self._selected

    def name_colour(self) -> QColor:
        """The colour of the name: the text colour, and the secondary colour for a value that is
        shown on purpose (on the soft accent of a selected row, the colour the theme has for text
        there).
        """
        t = tokens_of(self)
        if self.data.hidden or self.data.question:
            return QColor(t.text)
        return QColor(t.accent_text_on_soft if self._selected else t.secondary)

    def caption_colour(self) -> QColor:
        """The colour of the caption: the secondary colour, and on the soft accent of a selected
        row the colour the theme has for text there.
        """
        t = tokens_of(self)
        return QColor(t.accent_text_on_soft if self._selected else t.secondary)

    def row_box(self) -> QRectF:
        """The box of the row without its heading and the gap below: what a selection colours."""
        assert self._plan is not None
        return self._plan.row

    def pill_box(self) -> QRectF | None:
        """Where the "CHECK" pill is, or None for a row without one."""
        assert self._plan is not None
        return self._plan.pill

    # ---- layout -------------------------------------------------------------------------------

    def fit(self, width: int) -> int:
        """Lay the row out for ``width`` pixels and return the height it needs."""
        self._plan = self._arrange(max(width, 1))
        self._place_controls(self._plan)
        return self._plan.height

    def needed_height(self) -> int:
        """The height the row needs for the width it was laid out for."""
        assert self._plan is not None
        return self._plan.height

    def sizeHint(self) -> QSize:
        assert self._plan is not None
        return QSize(self._plan.width, self._plan.height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _controls_size(self) -> QSize:
        if self.switch is not None:
            return self.switch.sizeHint()
        assert self.hide_button is not None and self.show_button is not None
        hide, show = self.hide_button.sizeHint(), self.show_button.sizeHint()
        return QSize(hide.width() + _BUTTON_GAP + show.width(), max(hide.height(), show.height()))

    def _arrange(self, width: int) -> _Plan:
        data = self.data
        band_height = 0
        if self.heading:
            band_height = _BAND_FIRST if self.leading else _BAND_NEXT
        row_x = float(_INSET)
        row_w = float(width - 2 * _INSET)
        controls = self._controls_size()
        text_x = row_x + _PAD_X + _CHIP + _GAP
        text_w = max(row_x + row_w - _PAD_X - controls.width() - _GAP - text_x, 0.0)
        pill_w = 0.0
        name_room = text_w
        if data.needs_check:
            pill_w = QFontMetricsF(self._pill_font).horizontalAdvance("CHECK") + 10
            name_room = max(text_w - pill_w - _PILL_GAP, 0.0)
        name = _elided(data.name, self._name_font, name_room)
        name_w = QFontMetricsF(self._name_font).horizontalAdvance(name)
        caption = tuple(_wrapped(data.caption, self._caption_font, text_w, _MAX_CAPTION_LINES))
        row_h = _PAD_Y + _NAME_LINE + len(caption) * _CAPTION_LINE + _PAD_Y
        row_y = float(band_height)
        top = row_y + _PAD_Y
        pill = None
        if data.needs_check:
            pill_y = top + (_NAME_LINE - _PILL_HEIGHT) / 2
            pill = QRectF(text_x + name_w + _PILL_GAP, pill_y, pill_w, _PILL_HEIGHT)
        band = None
        if self.heading:
            band = QRectF(row_x + _PAD_X, band_height - 4 - _BAND_LINE, row_w, _BAND_LINE)
        return _Plan(
            width=width,
            height=band_height + row_h + _ROW_GAP,
            row=QRectF(row_x, row_y, row_w, row_h),
            band=band,
            chip=QRectF(row_x + _PAD_X, row_y + (row_h - _CHIP) / 2, _CHIP, _CHIP),
            name=name,
            name_box=QRectF(text_x, top, name_w + 2, _NAME_LINE),
            pill=pill,
            caption=caption,
            caption_box=QRectF(text_x, top + _NAME_LINE, text_w, _CAPTION_LINE),
            controls=QPoint(
                round(row_x + row_w - _PAD_X - controls.width()),
                round(row_y + (row_h - controls.height()) / 2),
            ),
        )

    def _place_controls(self, plan: _Plan) -> None:
        if self.switch is not None:
            self.switch.move(plan.controls)
            return
        assert self.hide_button is not None and self.show_button is not None
        self.hide_button.move(plan.controls)
        self.show_button.move(
            plan.controls.x() + self.hide_button.sizeHint().width() + _BUTTON_GAP, plan.controls.y()
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        if self._plan is None or event.size().width() != self._plan.width:
            self.fit(event.size().width())
        super().resizeEvent(event)

    # ---- painting -----------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        plan = self._plan
        assert plan is not None
        t = tokens_of(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if plan.band is not None and self.heading:
            painter.setFont(self._band_font)
            painter.setPen(QColor(t.secondary))
            painter.drawText(plan.band, self.heading, _left_aligned())
        self._paint_background(painter, plan, t)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TYPE_COLOURS[self.data.kind]))
        painter.drawRoundedRect(plan.chip, 3, 3)
        painter.setFont(self._name_font)
        painter.setPen(self.name_colour())
        painter.drawText(plan.name_box, plan.name, _left_aligned())
        if plan.pill is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.notice_bg))
            painter.drawRoundedRect(plan.pill, 4, 4)
            painter.setFont(self._pill_font)
            painter.setPen(QColor(t.notice_text))
            painter.drawText(plan.pill, "CHECK", _centred())
        painter.setFont(self._caption_font)
        painter.setPen(self.caption_colour())
        for k, line in enumerate(plan.caption):
            painter.drawText(
                plan.caption_box.translated(0, k * _CAPTION_LINE), line, _left_aligned()
            )

    def _paint_background(self, painter: QPainter, plan: _Plan, t: Tokens) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        if self._selected or self.underMouse():
            painter.setBrush(QColor(t.accent_soft if self._selected else t.hairline))
            painter.drawRoundedRect(plan.row, 8, 8)
        if self._current and self._focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.accent), 1.5))
            painter.drawRoundedRect(plan.row.adjusted(0.75, 0.75, -0.75, -0.75), 7.25, 7.25)

    def enterEvent(self, event: QEnterEvent) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.update()
        super().leaveEvent(event)


# ---- the list -----------------------------------------------------------------------------------


class GroupDelegate(QStyledItemDelegate):
    """Draws the lines under a group's row (a place: a check box and the words round it). A group
    is drawn by its row widget, so the delegate draws nothing for it.
    """

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self._tree = tree

    def updateEditorGeometry(
        self,
        editor: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # A row takes the whole cell: not the part left of the text of a line that has a check
        # box, which is what the default makes of it.
        editor.setGeometry(option.rect)

    @staticmethod
    def box_rect(cell: QRect) -> QRectF:
        """The check box of a place, in the cell of its line (under the name of its group)."""
        left = _INSET + _PAD_X + _CHIP + _GAP
        return QRectF(left, cell.y() + (cell.height() - _BOX) / 2, _BOX, _BOX)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        hint = index.data(Qt.ItemDataRole.SizeHintRole)
        if isinstance(hint, QSize) and hint.height() > 0:
            return hint
        return QSize(0, _OCCURRENCE_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if not index.parent().isValid():
            return
        t = tokens_of(self._tree)
        cell = QRectF(option.rect)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setBrush(QColor(t.accent_soft))
            painter.drawRoundedRect(cell.adjusted(_INSET, 0, -_INSET, 0), 8, 8)
        box = self.box_rect(option.rect)
        painter.setOpacity(1.0 if enabled else 0.45)
        if _is_checked(index.data(Qt.ItemDataRole.CheckStateRole)):
            painter.setBrush(QColor(t.accent))
            painter.drawRoundedRect(box, 4, 4)
            tick = QPainterPath()
            tick.moveTo(box.left() + 3.5, box.center().y() + 0.5)
            tick.lineTo(box.left() + 6, box.bottom() - 3.8)
            tick.lineTo(box.right() - 3, box.top() + 4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.on_accent), 1.6))
            painter.drawPath(tick)
        else:
            painter.setBrush(QColor(t.panel))
            painter.setPen(QPen(QColor(t.secondary), 1))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3.5, 3.5)
        font = _font(12)
        painter.setFont(font)
        painter.setPen(QColor(t.text if enabled else t.secondary))
        left = box.right() + 8
        room = cell.right() - _INSET - _PAD_X - left
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.drawText(
            QRectF(left, cell.y(), room, cell.height()), _elided(text, font, room), _left_aligned()
        )
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """A click on the check box of a place switches it; the rest of the line selects it."""
        if (
            index.parent().isValid()
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and bool(option.state & QStyle.StateFlag.State_Enabled)
            and self.box_rect(option.rect).adjusted(-4, -4, 4, 4).contains(event.position())
        ):
            checked = _is_checked(index.data(Qt.ItemDataRole.CheckStateRole))
            state = Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            return model.setData(index, state.value, Qt.ItemDataRole.CheckStateRole)
        return False


def _is_checked(value: object) -> bool:
    """Whether the data of a check state role says checked (Qt gives the enum or its number)."""
    return value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)


class GroupTree(QTreeWidget):
    """The list of groups: one top-level item for each, a row widget on it, and under it a line
    for each place (closed until the owner opens the group with a double click or the arrow keys).

    Space switches the current line (``toggleRequested`` says which, so that the screen can tell
    the review); a context menu is asked for with ``menuRequested`` (the global position, for a
    right click and for the menu key alike). The rows are laid out again for the width the list
    has (``fit_rows``): a caption of several lines makes a row taller. ``focusChanged`` is sent
    when the list gains or loses the keyboard (the current row shows a ring while it has it).
    """

    toggleRequested = Signal(QTreeWidgetItem)
    menuRequested = Signal(QPoint)
    focusChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fitted = -1
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAnimated(False)
        self.setExpandsOnDoubleClick(False)  # a double click renames; Right and the menu open
        self.setUniformRowHeights(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.setItemDelegate(GroupDelegate(self))
        # The list draws on the ground of the inspector; the stylesheet of the app gives a list
        # a panel and a frame, which this one does not want.
        self.setStyleSheet("QTreeWidget { background: palette(window); border: none; }")
        self.setAccessibleName("Values found")

    def drawRow(
        self,
        painter: QPainter,
        options: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # Only the delegate draws: no fill for the selection behind a row, no branch.
        delegate = self.itemDelegateForIndex(index)
        if delegate is not None:
            delegate.paint(painter, options, index)

    def fit_rows(self, force: bool = False) -> None:
        """Give each row the height it needs for the width of the list."""
        width = self.viewport().width()
        if width == self._fitted and not force:
            return
        self._fitted = width
        self.setColumnWidth(0, width)  # the row widgets are as wide as the column
        with QSignalBlocker(self):  # a new size hint is no change of the review
            for k in range(self.topLevelItemCount()):
                item = self.topLevelItem(k)
                row = self.itemWidget(item, 0) if item is not None else None
                if item is not None and isinstance(row, GroupRow):
                    height = row.fit(width)
                    if item.sizeHint(0).height() != height:
                        item.setSizeHint(0, QSize(0, height))

    def viewportEvent(self, event: QEvent) -> bool:
        handled = super().viewportEvent(event)
        if event.type() == QEvent.Type.Resize:
            self.fit_rows()
        return handled

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select) and not event.modifiers():
            item = self.currentItem()
            flags = item.flags() if item is not None else Qt.ItemFlag.NoItemFlags
            if (
                item is not None
                and flags & Qt.ItemFlag.ItemIsUserCheckable
                and flags & Qt.ItemFlag.ItemIsEnabled
            ):
                self.toggleRequested.emit(item)
                event.accept()
                return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        item = self.currentItem()
        if event.reason() == QContextMenuEvent.Reason.Keyboard and item is not None:
            rect = self.visualItemRect(item)
            self.menuRequested.emit(
                self.viewport().mapToGlobal(QPoint(rect.left() + 40, rect.top() + 20))
            )
        else:
            self.menuRequested.emit(event.globalPos())
        event.accept()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.focusChanged.emit()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.focusChanged.emit()


# ---- the pane -----------------------------------------------------------------------------------


class Rule(QWidget):
    """A line of one pixel across the pane, in the colour of the borders."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(tokens_of(self).border))
        painter.end()


class NamePanel(QWidget):
    """The "Mask name" block under the list: a field for the name of the selected group, the
    token the masked file will write for it, and a line for a refusal or an explanation.

    ``committed`` is sent with the group's id and the text when the owner presses Return or leaves
    the field (the id is the one the text was typed for, also when the selection has moved on by
    then). The panel only shows; the screen asks the review and calls ``show_error``.
    """

    committed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group_id: str | None = None
        self._shown = ""  # what the field was last set to: the name the group has
        self._default = ""
        self._appearance = ""
        self.title_label = QLabel(NAME_TITLE_SHOWN)
        self.title_label.setFont(_font(11, QFont.Weight.DemiBold))
        self.name_field = QLineEdit()
        self.name_field.setFixedHeight(30)
        self.name_field.setAccessibleName(NAME_TITLE)
        self.name_field.setToolTip(NAME_TIP)
        self.name_field.setClearButtonEnabled(True)
        self.token_label = QLabel()
        self.token_label.setFont(_font(11))
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setFont(_font(11))
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setFont(_font(11))
        self.message_label.setAccessibleName("Mask name problem")
        # The line keeps its room (two lines) whether it says something or not: no jump.
        self.message_label.setMinimumHeight(2 * _MESSAGE_LINE)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_label.setFont(_font(11))
        self.problems_label.setTextFormat(Qt.TextFormat.PlainText)
        self.problems_label.setAccessibleName("Names that clash with a value")
        self.problems_label.hide()
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.note_label.setTextFormat(Qt.TextFormat.PlainText)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 10)
        column.setSpacing(6)
        column.addWidget(self.title_label)
        column.addWidget(self.name_field)
        column.addWidget(self.token_label)
        column.addWidget(self.message_label)
        column.addWidget(self.problems_label)
        column.addWidget(self.note_label)
        self.name_field.textEdited.connect(self._edited)
        self.name_field.editingFinished.connect(self._finished)
        self.show_group(None)
        self.restyle()

    def group_id(self) -> str | None:
        """The group the field is about, if any."""
        return self._group_id

    def show_group(self, group: Group | None, stored: bool = False) -> None:
        """Show ``group`` (None: nothing is selected, or several groups are). A ``stored`` group
        belongs to an existing case and cannot be renamed: the field is off and a line says why.
        The refusal being shown stays, whichever group is selected: it names the group it is
        about and goes when the owner types again or a name is accepted.
        """
        self._group_id = None if group is None else group.id
        self._shown = "" if group is None or group.label is None else group.label
        with QSignalBlocker(self.name_field):
            self.name_field.setText(self._shown)
        self._default = "" if group is None else group.placeholder
        self.name_field.setPlaceholderText(self._default)
        self.name_field.setEnabled(group is not None and not stored)
        self.note_label.setText(NAME_NONE if group is None else NAME_STORED if stored else "")
        self.note_label.setVisible(group is None or stored)
        self.token_label.setVisible(group is not None)
        self._preview(self.name_field.text())

    def show_error(self, message: str) -> None:
        """Say why the name was refused, under the field."""
        self.message_label.setText(message)
        self.name_field.setAccessibleDescription(message)

    def show_problems(self, messages: list[str]) -> None:
        """List the names that clash with a value (``ReviewState.label_problems``), or none."""
        self.problems_label.setText("\n".join(messages))
        self.problems_label.setVisible(bool(messages))

    def current_text(self) -> str:
        """What the field holds now, committed or not."""
        return self.name_field.text()

    def is_dirty(self) -> bool:
        """Whether the owner has typed in the field since it showed the group's name."""
        return self.name_field.text() != self._shown

    def is_editable(self) -> bool:
        return self._group_id is not None and self.name_field.isEnabled()

    def commit_now(self) -> None:
        """Send ``committed`` for the text in the field, as Return does."""
        self._finished()

    def clear_error(self) -> None:
        self.show_error("")

    def focus_field(self) -> None:
        """Put the keyboard in the field, with its text selected."""
        self.name_field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.name_field.selectAll()

    def _preview(self, text: str) -> None:
        """What the masked file will write for ``text`` (the default for an empty one)."""
        if not self._default:
            self.token_label.setText("")
            return
        if not text.strip():
            self.token_label.setText(f"Written as {self._default}")
            return
        try:
            self.token_label.setText(f"Written as [{clean_label(text)}]")
        except LabelError:
            self.token_label.setText(NAME_INVALID)

    def _edited(self, text: str) -> None:
        self.clear_error()
        self._preview(text)

    def _finished(self) -> None:
        if self._group_id is not None and self.name_field.isEnabled():
            self.committed.emit(self._group_id, self.name_field.text())

    def restyle(self) -> None:
        """Take the colours of the appearance: captions quiet, the refusal in the danger colour."""
        appearance = appearance_of(self.palette())
        if appearance == self._appearance:
            return
        self._appearance = appearance
        t = tokens_of(self)
        for label in (self.token_label, self.note_label):
            label.setStyleSheet(f"color: {t.secondary};")
        self.message_label.setStyleSheet(f"color: {t.danger};")
        self.problems_label.setStyleSheet(f"color: {t.danger};")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.restyle()
        super().changeEvent(event)


class Inspector(QWidget):
    """The pane on the right of the review: the find field and the two buttons on top, the list
    of groups (``tree``), and the counts and the hint for the keys at the bottom.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("What was found")
        self.setMinimumWidth(300)
        self.setMaximumWidth(360)
        self._appearance = ""

        self.find_field = QLineEdit()
        self.find_field.setPlaceholderText(FIND_PLACEHOLDER)
        self.find_field.setClearButtonEnabled(True)
        self.find_field.setAccessibleName(FIND_NAME)
        self.find_field.setFixedHeight(30)
        self._magnifier = self.find_field.addAction(
            QIcon(), QLineEdit.ActionPosition.LeadingPosition
        )
        self.hide_name_field = QLineEdit()
        self.hide_name_field.setPlaceholderText(NAME_HIDE_PLACEHOLDER)
        self.hide_name_field.setAccessibleName(NAME_HIDE_NAME)
        self.hide_name_field.setToolTip(NAME_HIDE_TIP)
        self.hide_name_field.setFixedHeight(30)
        self.hide_message_label = QLabel()
        self.hide_message_label.setWordWrap(True)
        self.hide_message_label.setFont(_font(11))
        self.hide_message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.hide_message_label.setAccessibleName("Name problem")
        self.hide_message_label.hide()
        self.hide_name_field.textEdited.connect(lambda _text: self.show_hide_error(""))
        self.name_panel = NamePanel()
        self.hide_button = QPushButton("Hide selection")
        self.never_button = QPushButton("Show always")
        for button in (self.hide_button, self.never_button):
            button.setFont(_font(12, QFont.Weight.DemiBold))
            button.setFixedHeight(28)
        self.tree = GroupTree()
        self.counts_label = QLabel(FooterCounts(0, 0, 0).text())
        self.hint_label = QLabel(HINT)
        for label in (self.counts_label, self.hint_label):
            label.setWordWrap(True)
            label.setFont(_font(11))
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top = QVBoxLayout()
        top.setContentsMargins(14, 12, 14, 12)
        top.setSpacing(10)
        top.addWidget(self.find_field)
        top.addWidget(self.hide_name_field)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.hide_button, 1)
        buttons.addWidget(self.never_button, 1)
        top.addLayout(buttons)
        top.addWidget(self.hide_message_label)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 10, 14, 10)
        bottom.setSpacing(8)
        bottom.addWidget(self.counts_label, 9)  # by the length of the texts, 43 and 24 letters
        bottom.addWidget(self.hint_label, 5)
        column = QVBoxLayout(self)
        column.setContentsMargins(1, 0, 0, 0)  # the border on the left is drawn in the margin
        column.setSpacing(0)
        column.addLayout(top)
        column.addWidget(Rule())
        column.addWidget(self.tree, 1)
        column.addWidget(Rule())
        column.addWidget(self.name_panel)
        column.addWidget(Rule())
        column.addLayout(bottom)
        self.setTabOrder(self.find_field, self.hide_name_field)
        self.setTabOrder(self.hide_name_field, self.hide_button)
        self.setTabOrder(self.hide_button, self.never_button)
        self.setTabOrder(self.never_button, self.tree)
        self.setTabOrder(self.tree, self.name_panel.name_field)
        self.restyle()

    def show_hide_error(self, message: str) -> None:
        """Say, under the buttons, why the name for "Hide selection" was refused (empty: clear)."""
        self.hide_message_label.setText(message)
        self.hide_message_label.setVisible(bool(message))
        self.hide_name_field.setAccessibleDescription(message)

    def set_counts(self, counts: FooterCounts) -> None:
        self.counts_label.setText(counts.text())

    def restyle(self) -> None:
        """Take the colours of the appearance the pane is in: the magnifier, the captions and the
        find field's problem colour (as icon and stylesheets: a palette set on a child while the
        application's palette is still going round would be overwritten by it). The rest paints
        itself from the tokens.
        """
        appearance = appearance_of(self.palette())
        if appearance == self._appearance:
            return
        self._appearance = appearance
        t = tokens_of(self)
        self._magnifier.setIcon(icons.icon("search", t.secondary, 14))
        for label in (self.counts_label, self.hint_label):
            label.setStyleSheet(f"color: {t.secondary};")
        self.find_field.setStyleSheet(f'QLineEdit[noMatch="true"] {{ color: {t.danger}; }}')
        self.hide_message_label.setStyleSheet(f"color: {t.danger};")
        self.name_panel.restyle()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.restyle()
        super().changeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens_of(self)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(t.ground))
        painter.fillRect(QRect(0, 0, 1, self.height()), QColor(t.border))
        painter.end()
