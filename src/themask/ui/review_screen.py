"""The review screen: what the analysis found, for the owner to check before anything is masked.

Two panes. On the left the text of the files on a page of its own, each active find marked in the
colour of its type; a find the analysis was not sure of has a dotted underline and the tooltip
"check". On the right the inspector (``review_inspector``): a find field and the buttons for the
text selected in the document, the finds as a list of groups in sections by kind of value (a row
for each group with a switch that hides the whole group, a "CHECK" pill beside a group to look at,
and under the row a line for each place, closed until the owner opens it), and the counts.
Groups the analysis was not sure of that are switched off are asked about first, under "Not
sure — hide?". The actions for a group are in its context menu: put its value on the always-hide
or the never-hide list, split places off it, merge it with another group.

The ``ReviewState`` holds every decision. The screen shows it, passes the owner's clicks on to it
and draws everything again after each change (the state re-sorts its groups and findings, so
nothing is kept between two changes but the ids of the groups). The file name and the summary
line are not on this screen: the window shows them in its tool bar (``title``, ``titleChanged``),
with the toolbar's "Export…" button that goes on to the export (``exportRequested``).

The text pane shows the combined text as it is, with a header line before the text of each file.
Positions in the pane count UTF-16 units from the start of the pane, and indexes in the text count
characters, so ``_TextMap`` converts between them exactly: a character outside the BMP is two
units, a header or the gap between files has no index, and each file's text is checked to take
exactly the room it should. What the owner selects is read from the text by index, never from the
pane (which shows a no-break space as a plain space).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QHelpEvent,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPalette,
    QPixmap,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QToolTip,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.detect.lists import CaseLists, UserLists, on_never_hide_list
from themask.detect.pipeline import CombinedText
from themask.labels import LabelError, clean_label
from themask.model import Finding, Group, PlaceholderType
from themask.review import ReviewState, asks_about
from themask.ui.review_inspector import (
    CHECK_TIP,
    NAME_STORED,
    FooterCounts,
    GroupRow,
    Inspector,
    RowData,
    Section,
    collapse,
    sections,
)
from themask.ui.theme import TYPE_COLOURS, appearance_of, body_font, serif_font, tokens_of

NOTHING_SELECTED = "Select the text to hide in the document first."
ONE_FILE = "Select text from one file at a time."
NOT_TEXT = "Select some of the document's text, not a file name."
LOADED_ON_ANOTHER_TEXT = "The review was not made on this text."
DOCUMENT_NOTE = (
    "Headers and footers follow the body. Hidden text and pictures were taken out before this view."
)

CONTEXT_CHARACTERS = 28  # of the text before and after an occurrence, in the list
GROUP_ROLE = Qt.ItemDataRole.UserRole  # the id of the group, on its line and on those under it
OCCURRENCE_ROLE = Qt.ItemDataRole.UserRole + 1  # the index of an occurrence, on its line only
_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
_STRESS = 120  # the occurrences of a selected group are this per cent darker (QColor.darker)
_UNDERLINE = 300  # the dots under a find to check: its tint this per cent darker
_BLACK = QColor(Qt.GlobalColor.black)  # the ink on the tints, in either appearance
_HEADER = int(QTextFormat.Property.UserProperty) + 1  # marks the block of a file's name
_PAGE_MARGINS = (44, 36)  # left and right, top and bottom, of the text on its page
_PARAGRAPH_GAP = 14
_LINE_HEIGHT = 14.5 * 1.7  # pixels: the text is 14.5 pixels high and a line takes 1.7 times that


def show_notice(parent: QWidget | None, message: str) -> None:
    """Tell the owner why something could not be done, in a sentence."""
    QMessageBox.information(parent, APP_NAME, message)


def _sans(pixels: int) -> QFont:
    """The system font at ``pixels`` pixels."""
    font = body_font()
    font.setPixelSize(pixels)
    return font


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _displayable(text: str) -> str:
    """``text`` as the pane can show it, character for character.

    A carriage return and the line feed after it would become one line break, and a lone
    surrogate half cannot be encoded (it is shown as a question mark).
    """
    return text.replace("\r", " ").encode("utf-8", "replace").decode("utf-8")


_SWATCHES: dict[PlaceholderType, QIcon] = {}


def _swatch(kind: PlaceholderType) -> QIcon:
    """A small square in the colour of ``kind``."""
    if kind not in _SWATCHES:
        pixmap = QPixmap(14, 14)
        pixmap.fill(QColor(TYPE_COLOURS[kind]))
        painter = QPainter(pixmap)
        painter.setPen(QColor(TYPE_COLOURS[kind]).darker(150))
        painter.drawRect(0, 0, 13, 13)
        painter.end()
        _SWATCHES[kind] = QIcon(pixmap)
    return _SWATCHES[kind]


@dataclass(frozen=True)
class _Placed:
    """A file's text in the pane: ``start`` to ``end`` of the combined text, from ``anchor`` on."""

    start: int
    end: int
    anchor: int


class _TextMap:
    """Where each file's text stands in the pane, and the conversion in both directions.

    ``text`` is the combined text; ``add`` says where each file's text was put.
    """

    def __init__(self, text: str) -> None:
        self._placed: list[_Placed] = []
        self._starts: list[int] = []
        self._astral = [i for i, character in enumerate(text) if ord(character) > 0xFFFF]

    def add(self, start: int, end: int, anchor: int) -> None:
        """The text from ``start`` to ``end`` was put in the pane at position ``anchor``."""
        self._placed.append(_Placed(start, end, anchor))
        self._starts.append(start)

    def width(self, first: int, last: int) -> int:
        """The number of UTF-16 units of ``text[first:last]``."""
        return (last - first) + bisect_left(self._astral, last) - bisect_left(self._astral, first)

    def position(self, index: int) -> int:
        """The position in the pane of the character at ``index`` of the text (``index`` may be
        the end of a file's text). Raises ValueError for an index between two files.
        """
        k = bisect_right(self._starts, index) - 1
        if k < 0 or index > self._placed[k].end:
            raise ValueError(f"Index {index} is not in the text of any file.")
        part = self._placed[k]
        return part.anchor + self.width(part.start, index)

    def selection(self, first: int, last: int) -> tuple[int, int]:
        """The span of the text that the pane's selection from ``first`` to ``last`` covers.

        What lies outside the files' texts (a header, the gap between files) is left out. Raises
        ValueError, with a message for the owner, when nothing of the text is selected or the
        selection takes in more than one file.
        """
        covered = []
        for part in self._placed:
            low = max(first, part.anchor)
            high = min(last, part.anchor + self.width(part.start, part.end))
            if low < high:
                covered.append((part, low, high))
        if not covered:
            raise ValueError(NOT_TEXT)
        if len(covered) > 1:
            raise ValueError(ONE_FILE)
        part, low, high = covered[0]
        return self._index(part, low), self._index(part, high)

    def _index(self, part: _Placed, position: int) -> int:
        """The index in the text of the character at ``position`` of the pane, within ``part``."""
        indexes = range(part.start, part.end + 1)
        wanted = position - part.anchor
        return part.start + bisect_left(indexes, wanted, key=lambda j: self.width(part.start, j))


@dataclass(frozen=True)
class _Highlight:
    """A find that is drawn: from ``start`` to ``end`` in the pane, of the group ``group_id``."""

    start: int
    end: int
    group_id: str
    needs_check: bool


class ReviewScreen(QWidget):
    """The review of an analysis: ``load`` it, and the owner reviews it.

    ``review`` is the state being reviewed, ``combined`` the text it was made on, ``text`` the
    pane that shows it, ``inspector`` the pane beside it and ``tree`` the list of groups in that.
    ``title()`` is what the window shows above the screen (the file and the summary; the window
    listens to ``titleChanged``), and ``exportRequested`` is sent when the owner chooses to go on
    to the export: the window's "Export…" button does that, and ``export_button`` is the same
    request as a button that is never shown.
    """

    exportRequested = Signal()
    titleChanged = Signal(str, str)  # the two lines of title(), when either changes

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.review = ReviewState("", [], [], UserLists([], []), CaseLists([], [], set()))
        self.combined = CombinedText("", [])
        self._map = _TextMap("")
        self._items: dict[str, QTreeWidgetItem] = {}
        self._rows: dict[str, GroupRow] = {}
        self._highlights: list[_Highlight] = []
        self._starts: list[int] = []
        self._stressed: set[str] = set()
        self._formats: dict[tuple[PlaceholderType, bool, bool], QTextCharFormat] = {}
        self._problem_ids: set[str] = set()  # groups whose name clashes with a masked value
        self._updating = False
        self._from_text = False
        self._by_hand = False  # a switch is being moved by the owner (see _set_by_hand)
        self._regroup_due = False
        self._moved: str | None = None  # the group that has to change sections
        self._title: tuple[str, str] = ("", "")
        self._appearance = ""
        self._regroup_timer = QTimer(self)
        self._regroup_timer.setSingleShot(True)
        self._regroup_timer.timeout.connect(self._regroup)

        self.warnings_label = QLabel()
        self.warnings_label.setObjectName("warnings")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.hide()
        self.note_label = QLabel(DOCUMENT_NOTE)
        self.note_label.setWordWrap(True)
        self.note_label.setFont(_sans(12))
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setUndoRedoEnabled(False)
        self.text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.text.setFont(serif_font())
        self.text.document().setDefaultFont(serif_font())
        self.text.document().setDocumentMargin(0)
        self._page_margins()
        self.text.setFrameShape(QFrame.Shape.NoFrame)
        # The page: the stylesheet of the app gives a text field a frame and a padding.
        self.text.setStyleSheet(
            "QTextEdit { border: none; border-radius: 0; padding: 0; background: palette(base); }"
        )
        self.text.setAccessibleName("Document")
        self.text.viewport().installEventFilter(self)

        self.inspector = Inspector()
        self.tree = self.inspector.tree
        self.find_field = self.inspector.find_field
        self.hide_button = self.inspector.hide_button
        self.hide_name_field = self.inspector.hide_name_field
        self.never_button = self.inspector.never_button
        self.counts_label = self.inspector.counts_label
        self.hint_label = self.inspector.hint_label
        self.hide_button.setMenu(self._build_type_menu())
        self.hide_button.setToolTip("Hide the text selected in the document, wherever it stands.")
        self.never_button.setToolTip(
            "Leave the text selected in the document, or the value of the selected group, visible"
            " in every document from now on."
        )
        self.never_button.clicked.connect(lambda: self._never_hide(from_text=True))
        self.always_action = self._action(
            "Hide always",
            "Hide the value of the selected group in every document from now on.",
            self._always_hide,
        )
        self.never_action = self._action(
            "Show always",
            "Leave the value of the selected group visible in every document from now on.",
            lambda: self._never_hide(from_text=False),
        )
        self._rename_tip = "Choose the name the masked file writes for the selected group."
        self.rename_action = self._action("Rename mask…", self._rename_tip, self._rename)
        self.split_action = self._action(
            "Split", "Move the selected places into a group of their own.", self._split
        )
        self.merge_action = self._action(
            "Merge selected groups", "Make the selected groups one.", self._merge
        )
        self.places_action = self._action(
            "Show places",
            "Show each place of the group, to switch it off or to split it off.",
            self._toggle_places,
        )
        self.export_button = QPushButton("Continue to export", self)
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.exportRequested)
        self.export_button.hide()
        self.find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        self.find_shortcut.activated.connect(self.focus_find)
        self._arrange()

        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.currentItemChanged.connect(self._mark_rows)
        self.tree.focusChanged.connect(self._mark_rows)
        self.tree.toggleRequested.connect(self._toggle_item)
        self.tree.menuRequested.connect(self._open_menu)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.inspector.name_panel.committed.connect(self._name_committed)
        self.find_field.textChanged.connect(self._find_typed)
        self.find_field.returnPressed.connect(self.find_next)
        self.text.selectionChanged.connect(self._refresh_buttons)
        self._restyle()
        self._refresh_buttons()
        self._refresh_summary()

    # ---- the interface the rest of the app uses --------------------------------------------

    def load(self, review: ReviewState, combined: CombinedText) -> None:
        """Show ``review``, which was made on the text ``combined``.

        Raises ValueError for a review made on another text: its places would be someone
        else's.
        """
        if review.text != combined.text:
            raise ValueError(LOADED_ON_ANOTHER_TEXT)
        self.review, self.combined = review, combined
        self.inspector.name_panel.show_group(None)  # nothing of the last review stays
        self.inspector.name_panel.clear_error()
        # Nothing typed for the last review applies to this one: a name for the next hide, the
        # find, and the refusal of a hide.
        self.hide_name_field.clear()
        self.inspector.show_hide_error("")
        self.find_field.clear()
        self._map = self._show_text(combined)
        self._stressed = set()
        self._rebuild()
        self.tree.scrollToTop()
        self._show_warnings()
        self.text.moveCursor(QTextCursor.MoveOperation.Start)
        self.text.verticalScrollBar().setValue(0)

    def title(self) -> tuple[str, str]:
        """What the window shows above the screen: the name of the file (or files) the review is
        of, and under it "Review · 14 values found · 2 to check".
        """
        counts = self.review.counts()
        found = _count(counts.groups, "value")
        asked = sum(asks_about(g, self.review.answered) for g in self.review.groups)
        return self._file_title(), f"Review · {found} found · {counts.needs_check + asked} to check"

    def group_count(self) -> int:
        """How many groups the review has."""
        return len(self.review.groups)

    def highlight_count(self) -> int:
        """How many finds are drawn: the active ones, which the plan will replace."""
        return len(self._highlights)

    def tree_item_for(self, group_id: str) -> QTreeWidgetItem:
        """The line of the list that stands for the group ``group_id``."""
        try:
            return self._items[group_id]
        except KeyError:
            raise ValueError("There is no such group.") from None

    def row_for(self, group_id: str) -> GroupRow:
        """The row of the list that stands for the group ``group_id``."""
        try:
            return self._rows[group_id]
        except KeyError:
            raise ValueError("There is no such group.") from None

    def section_titles(self) -> list[str]:
        """The headings of the list, from the top: "COMPANIES · 2" and so on."""
        rows = (self._rows[g] for g in self._items)
        return [row.heading for row in rows if row.heading is not None]

    def hide_selection(self, type: PlaceholderType, label: str | None = None) -> None:
        """Hide the text selected in the pane as ``type``, wherever it stands.

        With ``label`` (else what the "Name it" field holds) the new group is named at once. What
        the owner cannot hide (nothing selected, a selection that takes in two files or a file
        name, text the review refuses) is explained in a notice and nothing changes; a name that
        is refused is explained under the "Name it" field, and nothing is hidden either.
        """
        if not self.commit_pending_name():
            return
        if label is None:
            label = self.hide_name_field.text()
        cursor = self.text.textCursor()
        if not cursor.hasSelection():
            show_notice(self, NOTHING_SELECTED)
            return
        try:
            start, end = self._map.selection(cursor.selectionStart(), cursor.selectionEnd())
            group = self.review.hide_text(self.review.text[start:end], type, label or None)
        except LabelError as error:
            self.inspector.show_hide_error(str(error))
            return
        except ValueError as error:
            show_notice(self, str(error))
            return
        self.hide_name_field.clear()
        self.inspector.show_hide_error("")
        self.inspector.name_panel.clear_error()
        cursor.clearSelection()  # so that the colour of the new find shows
        self.text.setTextCursor(cursor)
        self._rebuild(select=group.id, scroll=False)

    def tooltip_at(self, point: QPoint) -> str:
        """The tooltip for ``point`` of the pane: over a find of a group the owner named, what will
        be written for it; over a find to check, "check"; else nothing.
        """
        highlight = self._highlight_at(point)
        if highlight is None:
            return ""
        lines = []
        group = self._group(highlight.group_id)
        if group.label is not None:
            lines.append(f"Written as {group.token}")
        if highlight.needs_check:
            lines.append(CHECK_TIP)
        return "\n".join(lines)

    def focus_find(self) -> None:
        """Put the keyboard in the find field (⌘F), with what it holds selected."""
        self.find_field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.find_field.selectAll()

    def find_next(self) -> bool:
        """Select the next place in the document where the find field's text stands, from the
        cursor on and round the end of the document. Says whether it was found; the field's text
        turns red when it is not.
        """
        needle = self.find_field.text()
        found = False
        if needle:
            before = self.text.textCursor()
            found = self.text.find(needle)
            if not found:  # round the end of the document
                self.text.moveCursor(QTextCursor.MoveOperation.Start)
                found = self.text.find(needle)
                if not found:
                    self.text.setTextCursor(before)
        self._mark_no_match(bool(needle) and not found)
        return found

    # ---- building the screen ---------------------------------------------------------------

    def _build_type_menu(self) -> QMenu:
        menu = QMenu(self)
        for kind in PlaceholderType:
            action = menu.addAction(_swatch(kind), kind.value)
            action.triggered.connect(lambda checked=False, kind=kind: self.hide_selection(kind))
        return menu

    def _action(self, text: str, tip: str, slot: Callable[[], None]) -> QAction:
        action = QAction(text, self)
        action.setToolTip(tip)
        action.setStatusTip(tip)
        action.triggered.connect(lambda checked=False: slot())
        return action

    def _arrange(self) -> None:
        page = QWidget()
        page.setBackgroundRole(QPalette.ColorRole.Base)
        page.setAutoFillBackground(True)
        self._warnings_band = QHBoxLayout()
        self._warnings_band.addWidget(self.warnings_label)
        note_band = QHBoxLayout()
        note_band.setContentsMargins(_PAGE_MARGINS[0], 4, _PAGE_MARGINS[0], 14)
        note_band.addWidget(self.note_label)
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addLayout(self._warnings_band)
        column.addWidget(self.text, 1)
        column.addLayout(note_band)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(page, 3)
        layout.addWidget(self.inspector, 1)
        self._show_warnings()
        self.setTabOrder(self.text, self.find_field)

    def _restyle(self) -> None:
        """Take the colours of the appearance the screen is in (the note under the page); the
        rest paints itself from the tokens.
        """
        appearance = appearance_of(self.palette())
        if appearance == self._appearance:
            return
        self._appearance = appearance
        self.note_label.setStyleSheet(f"color: {tokens_of(self).secondary};")
        self._style_headers()

    def _style_headers(self) -> None:
        """Give the bands the files' names stand on the colour of the appearance."""
        band = QBrush(QColor(tokens_of(self).table_head))
        block = self.text.document().begin()
        while block.isValid():
            if block.blockFormat().boolProperty(_HEADER):
                fmt = block.blockFormat()
                fmt.setBackground(band)
                QTextCursor(block).setBlockFormat(fmt)
            block = block.next()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._restyle()
        super().changeEvent(event)

    # ---- the text pane ---------------------------------------------------------------------

    def _page_margins(self) -> None:
        """Set the text on its page: 44 pixels to the sides and 36 above and below (the frame of
        the document is reset each time the document is cleared).
        """
        frame = self.text.document().rootFrame()
        margins = frame.frameFormat()
        margins.setLeftMargin(_PAGE_MARGINS[0])
        margins.setRightMargin(_PAGE_MARGINS[0])
        margins.setTopMargin(_PAGE_MARGINS[1])
        margins.setBottomMargin(_PAGE_MARGINS[1])
        frame.setFrameFormat(margins)

    def _show_text(self, combined: CombinedText) -> _TextMap:
        """Put the files' texts in the pane, each under a header with its name; returns where."""
        document = self.text.document()
        document.clear()
        self._page_margins()
        header_block = QTextBlockFormat()
        header_block.setProperty(_HEADER, True)
        header_block.setBackground(QBrush(QColor(tokens_of(self).table_head)))
        header_block.setBottomMargin(10)
        header_text = QTextCharFormat()
        header_font = _sans(12)
        header_font.setBold(True)
        header_text.setFont(header_font)
        body_block, body_text = QTextBlockFormat(), QTextCharFormat()
        body_block.setLineHeight(_LINE_HEIGHT, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        body_block.setBottomMargin(_PARAGRAPH_GAP)
        cursor = QTextCursor(document)
        cursor.setBlockFormat(header_block)
        cursor.setBlockCharFormat(header_text)
        before = any(name.endswith(" (before)") for name, _, _ in combined.parts)
        where = _TextMap(combined.text)
        for number, (name, start, end) in enumerate(combined.parts):
            if number:
                cursor.insertBlock(body_block, body_text)  # a blank line between two files
                cursor.insertBlock(header_block, header_text)
            title = name if before else name.removesuffix(" (after)")
            cursor.insertText(_displayable(title))
            cursor.insertBlock(body_block, body_text)
            anchor = cursor.position()
            cursor.insertText(_displayable(combined.text[start:end]))
            if cursor.position() - anchor != where.width(start, end):
                # Never: every character takes the room it should. Were that ever not so, the
                # highlights would lie on the wrong text, which is worse than no screen.
                raise RuntimeError("The text pane changed the length of a file's text.")
            where.add(start, end, anchor)
        return where

    def _highlight_at(self, point: QPoint) -> _Highlight | None:
        """The highlight over ``point`` of the pane's viewport, if one is."""
        scrolled = QPointF(
            point.x() + self.text.horizontalScrollBar().value(),
            point.y() + self.text.verticalScrollBar().value(),
        )
        layout = self.text.document().documentLayout()
        position = layout.hitTest(scrolled, Qt.HitTestAccuracy.ExactHit)
        k = bisect_right(self._starts, position) - 1
        if position < 0 or k < 0 or position >= self._highlights[k].end:
            return None
        return self._highlights[k]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Watch the pane's viewport: a click on a find selects its group, and a find to check
        has a tooltip.
        """
        if watched is self.text.viewport():
            if isinstance(event, QHelpEvent) and event.type() == QEvent.Type.ToolTip:
                tip = self.tooltip_at(event.pos())
                if tip:
                    QToolTip.showText(event.globalPos(), tip, self.text.viewport())
                else:
                    QToolTip.hideText()
                return True
            if (
                isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and not self.text.textCursor().hasSelection()
            ):
                self._clicked(event.position().toPoint())
        return super().eventFilter(watched, event)

    def _clicked(self, point: QPoint) -> None:
        highlight = self._highlight_at(point)
        if highlight is None:
            return
        item = self._items[highlight.group_id]
        self._from_text = True  # the owner is in the text already: do not scroll away from it
        try:
            self.tree.clearSelection()
            self.tree.setCurrentItem(item)
            item.setSelected(True)
            self.tree.scrollToItem(item)
        finally:
            self._from_text = False

    def _format(self, kind: PlaceholderType, needs_check: bool, stressed: bool) -> QTextCharFormat:
        key = (kind, needs_check, stressed)
        if key not in self._formats:
            colour = QColor(TYPE_COLOURS[kind])
            fill = colour.darker(_STRESS) if stressed else colour
            fmt = QTextCharFormat()
            fmt.setBackground(QBrush(fill))
            fmt.setForeground(QBrush(_BLACK))  # readable in dark mode too
            if needs_check:
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
                fmt.setUnderlineColor(colour.darker(_UNDERLINE))
            self._formats[key] = fmt
        return self._formats[key]

    def _refresh_highlights(self) -> None:
        """Draw every active find, in one go; the occurrences of the selected groups stand out."""
        document = self.text.document()
        highlights: list[_Highlight] = []
        selections: list[QTextEdit.ExtraSelection] = []
        for group in self.review.groups:
            if not group.enabled:
                continue
            stressed = group.id in self._stressed
            fmt = self._format(group.type, group.needs_check, stressed)
            for index, finding in enumerate(group.findings):
                if index in group.disabled:
                    continue
                start = self._map.position(finding.start)
                end = self._map.position(finding.end)
                highlights.append(_Highlight(start, end, group.id, group.needs_check))
                cursor = QTextCursor(document)
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format = fmt
                selections.append(selection)
        order = sorted(range(len(highlights)), key=lambda k: highlights[k].start)
        self._highlights = [highlights[k] for k in order]
        self._starts = [highlight.start for highlight in self._highlights]
        self.text.setExtraSelections([selections[k] for k in order])

    def _show_occurrence(self, group: Group, index: int) -> None:
        """Put the text cursor at the start of an occurrence, and bring it to the middle of the
        pane.
        """
        cursor = self.text.textCursor()
        cursor.setPosition(self._map.position(group.findings[index].start))
        self.text.setTextCursor(cursor)
        rect = self.text.cursorRect()
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.value() + rect.center().y() - self.text.viewport().height() // 2)

    # ---- the list of groups ----------------------------------------------------------------

    def _rebuild(self, select: str | Iterable[str] | None = None, scroll: bool = True) -> None:
        """Make the list, the highlights and the counts again from the review.

        The groups that were open stay open. ``select`` is the group (or groups) to select
        afterwards, and ``scroll`` whether the pane then goes to the first occurrence of the first.
        """
        self._flush_name()  # a name typed and not yet committed is not lost by the redraw
        self._problem_ids = self._clashing_groups()
        opened = {group_id for group_id, item in self._items.items() if item.isExpanded()}
        width = self.tree.viewport().width()
        bar = self.tree.verticalScrollBar()
        scrolled = bar.value()
        self._updating = True
        try:
            self.tree.clear()
            self._items, self._rows = {}, {}
            # The lines are made apart and put in the list in one go, and then given their rows:
            # a list that is made to lay itself out again for each line takes seconds for 300.
            lines: list[tuple[QTreeWidgetItem, GroupRow]] = []
            for number, section in enumerate(sections(self.review.groups, self.review.answered)):
                for k, group in enumerate(section.groups):
                    lines.append(self._make_group(group, section, k == 0, number == 0, width))
            self.tree.addTopLevelItems([item for item, _ in lines])
            for item, row in lines:
                self.tree.setItemWidget(item, 0, row)
            for group_id in opened & self._items.keys():
                self._items[group_id].setExpanded(True)
        finally:
            self._updating = False
        self._stressed = set()
        self._refresh_highlights()
        self._refresh_summary()
        self._refresh_buttons()
        self._chain_tab_order()
        wanted = [select] if isinstance(select, str) else list(select or [])
        wanted = [group_id for group_id in wanted if group_id in self._items]
        if not wanted:  # nothing to bring into view: the list stays where the owner had it
            self.tree.doItemsLayout()
            bar.setValue(scrolled)
        else:
            self._from_text = not scroll
            try:
                self.tree.clearSelection()
                self.tree.setCurrentItem(self._items[wanted[0]])
                for group_id in wanted:
                    self._items[group_id].setSelected(True)
                self.tree.scrollToItem(self._items[wanted[0]])
            finally:
                self._from_text = False
        self._mark_rows()
        self._refresh_name()

    def _make_group(
        self, group: Group, section: Section, first: bool, leading: bool, width: int
    ) -> tuple[QTreeWidgetItem, GroupRow]:
        """The line of the list for ``group`` and its row (not yet in the list): the line has a
        child for each place. ``first`` says that the group starts its section, which the row
        then names, and ``leading`` that the section is the first of the list.
        """
        data = RowData.of(group, section.question, group.id in self._problem_ids)
        item = QTreeWidgetItem([data.name])
        item.setFlags(_FLAGS)
        item.setCheckState(0, Qt.CheckState.Checked if group.enabled else Qt.CheckState.Unchecked)
        item.setData(0, GROUP_ROLE, group.id)
        item.setData(0, Qt.ItemDataRole.AccessibleTextRole, data.description())
        for index, finding in enumerate(group.findings):
            child = QTreeWidgetItem([self._context(finding)])
            child.setFlags(_FLAGS if group.enabled else _FLAGS & ~Qt.ItemFlag.ItemIsEnabled)
            child.setCheckState(
                0, Qt.CheckState.Unchecked if index in group.disabled else Qt.CheckState.Checked
            )
            child.setData(0, GROUP_ROLE, group.id)
            child.setData(0, OCCURRENCE_ROLE, index)
            item.addChild(child)
        row = GroupRow(data, section.title if first else None, leading and first, width)
        item.setSizeHint(0, QSize(0, row.needed_height()))
        row.switched.connect(
            lambda checked, group_id=group.id: self._switch_moved(group_id, checked)
        )
        row.hideClicked.connect(lambda group_id=group.id: self._answer_hide(group_id))
        row.showClicked.connect(lambda group_id=group.id: self._answer_show(group_id))
        self._items[group.id] = item
        self._rows[group.id] = row
        return item, row

    def _chain_tab_order(self) -> None:
        """Tab goes on from the buttons through the buttons of the "not sure" rows, if any, to
        the list.
        """
        previous: QWidget = self.never_button
        for row in self._rows.values():
            for button in (row.hide_button, row.show_button):
                if button is not None:
                    QWidget.setTabOrder(previous, button)
                    previous = button
        QWidget.setTabOrder(previous, self.tree)

    def _context(self, finding: Finding) -> str:
        """An occurrence as a line of the list: the find with the words around it."""
        text = self.review.text
        line_start = text.rfind("\n", 0, finding.start) + 1
        line_end = text.find("\n", finding.end)
        line_end = len(text) if line_end < 0 else line_end
        first = max(line_start, finding.start - CONTEXT_CHARACTERS)
        last = min(line_end, finding.end + CONTEXT_CHARACTERS)
        shown = " ".join(text[first:last].split())
        return f"{'…' if first > line_start else ''}{shown}{'…' if last < line_end else ''}"

    def _group(self, group_id: str) -> Group:
        return next(group for group in self.review.groups if group.id == group_id)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """A box was ticked or unticked: tell the review, and draw the finds again."""
        if self._updating or column != 0:
            return
        group_id = cast("str", item.data(0, GROUP_ROLE))
        index = item.data(0, OCCURRENCE_ROLE)
        checked = item.checkState(0) == Qt.CheckState.Checked
        if index is None:
            self.review.set_group_enabled(group_id, checked)
            self._grey_occurrences(item, checked)
            row = self._rows[group_id]
            row.set_checked(checked)
            if (
                asks_about(self._group(group_id), self.review.answered) != row.data.question
                or self._clashing_groups() != self._problem_ids
            ):
                self._regroup_later(group_id)  # into or out of "not sure", or a name's clash
        else:
            self.review.set_occurrence_enabled(group_id, cast("int", index), checked)
        self._refresh_highlights()
        self._refresh_summary()

    def _grey_occurrences(self, item: QTreeWidgetItem, enabled: bool) -> None:
        """Grey out the lines under a group that is switched off: their own boxes are kept."""
        self._updating = True  # a change of flags is reported like a change of box
        try:
            for k in range(item.childCount()):
                child = item.child(k)
                if child is not None:
                    flags = child.flags()
                    child.setFlags(
                        flags | Qt.ItemFlag.ItemIsEnabled
                        if enabled
                        else flags & ~Qt.ItemFlag.ItemIsEnabled
                    )
        finally:
            self._updating = False

    def _switch_moved(self, group_id: str, checked: bool) -> None:
        """The owner moved the switch of a row."""
        item = self._items.get(group_id)
        if item is not None:
            self._set_by_hand(item, checked)

    def _toggle_item(self, item: QTreeWidgetItem) -> None:
        """The owner pressed Space on a line of the list."""
        self._set_by_hand(item, item.checkState(0) != Qt.CheckState.Checked)

    def _set_by_hand(self, item: QTreeWidgetItem, checked: bool) -> None:
        """Switch a line the way the owner does, and put a group that moves between sections
        where it belongs at once: this is the owner's own click or key, not a program's call
        from inside the list.
        """
        self._by_hand = True
        try:
            item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self._by_hand = False
        if self._regroup_due:
            self._regroup()

    def _answer_hide(self, group_id: str) -> None:
        """The owner pressed Hide on a group they are asked about: switch it on."""
        item = self._items.get(group_id)
        if item is not None:
            self._set_by_hand(item, True)

    def _answer_show(self, group_id: str) -> None:
        """The owner pressed Show on a group they are asked about: it stays visible, and they are
        not asked about it again.
        """
        self.review.answered.add(group_id)
        self._rebuild(select=group_id, scroll=False)

    def _regroup_later(self, group_id: str) -> None:
        """The group ``group_id`` has to move between the sections: now, when the owner's own
        click or key made it (``_set_by_hand`` does it when it is back from the list), else as
        soon as the list has finished with what it is doing.
        """
        self._moved = group_id
        if self._by_hand:
            self._regroup_due = True
        else:
            self._regroup_timer.start(0)

    def _regroup(self) -> None:
        """Draw the list again, with the groups in the sections they belong in now. What was
        selected stays selected; when the group that moved was not, it is the selection, so
        that the owner sees where it went.
        """
        self._regroup_due = False
        self._regroup_timer.stop()
        moved, self._moved = self._moved, None
        groups, _ = self._selected()
        if moved is not None and moved not in groups:
            groups = [moved]
        self._rebuild(select=groups, scroll=False)

    def _mark_rows(self) -> None:
        """Show each row as selected or not, and the current one with a ring while the list has
        the keyboard.
        """
        if self._updating:  # the list is being made again: its lines are going and coming
            return
        focused = self.tree.hasFocus()
        current = self.tree.currentItem()
        for group_id, row in self._rows.items():
            item = self._items[group_id]
            row.set_marked(item.isSelected(), item is current, focused)

    def _selected(self) -> tuple[list[str], dict[str, list[int]]]:
        """What is selected in the list: the ids of the groups selected as a whole, and for the
        occurrences selected the indexes in their groups.
        """
        groups: list[str] = []
        occurrences: dict[str, list[int]] = {}
        for item in self.tree.selectedItems():
            group_id = cast("str", item.data(0, GROUP_ROLE))
            index = item.data(0, OCCURRENCE_ROLE)
            if index is None:
                groups.append(group_id)
            else:
                occurrences.setdefault(group_id, []).append(cast("int", index))
        return groups, {group_id: sorted(found) for group_id, found in occurrences.items()}

    def _selected_group(self) -> Group | None:
        """The one group the selection is about (a group, or occurrences of it), if it is one."""
        groups, occurrences = self._selected()
        involved = {*groups, *occurrences}
        if len(involved) != 1:
            return None
        wanted = involved.pop()
        return next((group for group in self.review.groups if group.id == wanted), None)

    def _selection_changed(self) -> None:
        if self._updating:
            return
        groups, occurrences = self._selected()
        stressed = {*groups, *occurrences}
        if stressed != self._stressed:
            self._stressed = stressed
            self._refresh_highlights()
        self._refresh_buttons()
        self._mark_rows()
        self._refresh_name()
        items = self.tree.selectedItems()
        if len(items) == 1 and not self._from_text:
            group_id = cast("str", items[0].data(0, GROUP_ROLE))
            index = items[0].data(0, OCCURRENCE_ROLE)
            group = self._group(group_id)
            self._show_occurrence(group, 0 if index is None else cast("int", index))

    def _refresh_buttons(self) -> None:
        groups, occurrences = self._selected()
        has_text = self.text.textCursor().hasSelection()
        self.hide_button.setEnabled(has_text)
        self.merge_action.setEnabled(len(set(groups)) >= 2)
        splittable = False
        if len(occurrences) == 1:
            ((group_id, found),) = occurrences.items()
            group = next((g for g in self.review.groups if g.id == group_id), None)
            splittable = group is not None and 0 < len(found) < len(group.findings)
        self.split_action.setEnabled(splittable)
        group = self._selected_group()
        stored = group is not None and group.placeholder in self.review.reserved
        self.rename_action.setEnabled(group is not None and not stored)
        self.rename_action.setToolTip(NAME_STORED if stored else self._rename_tip)
        self.always_action.setEnabled(group is not None)
        self.never_action.setEnabled(group is not None)
        self.never_button.setEnabled(group is not None or has_text)
        opened = group is not None and self._items[group.id].isExpanded()
        self.places_action.setText("Hide places" if opened else "Show places")
        self.places_action.setEnabled(group is not None)

    def _refresh_summary(self) -> None:
        """Count the groups again (the footer), and tell the window if its title changed."""
        self.inspector.set_counts(FooterCounts.of(self.review.groups, self.review.answered))
        self.inspector.name_panel.show_problems(self.review.label_problems())
        title = self.title()
        if title != self._title:
            self._title = title
            self.titleChanged.emit(*title)

    def _file_title(self) -> str:
        """The name of the file the review is of; of several, the first and how many more."""
        names: list[str] = []
        for name, _, _ in self.combined.parts:
            shown = name.removesuffix(" (after)").removesuffix(" (before)")
            if shown not in names:
                names.append(shown)
        if len(names) <= 1:
            return "".join(names)
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return f"{names[0]} and {len(names) - 1} more"

    def _show_warnings(self) -> None:
        self.warnings_label.setText("\n".join(self.review.warnings))
        shown = bool(self.review.warnings)
        self.warnings_label.setVisible(shown)
        # The page has room above its text when there is a notice, and none when there is not.
        self._warnings_band.setContentsMargins(
            *((_PAGE_MARGINS[0], 20, _PAGE_MARGINS[0], 0) if shown else (0, 0, 0, 0))
        )

    # ---- find ------------------------------------------------------------------------------

    def _find_typed(self, text: str) -> None:
        """The owner types in the find field: go to the first place from the cursor on, starting
        from where the last find began so that a longer text keeps its place. Where the text is
        nowhere, the cursor and what it had selected stay as they were.
        """
        if not text:
            self._mark_no_match(False)
            return
        original = self.text.textCursor()
        start = QTextCursor(original)
        if start.hasSelection():
            start.setPosition(start.selectionStart())
        self.text.setTextCursor(start)
        if not self.find_next():
            self.text.setTextCursor(original)

    def _mark_no_match(self, none: bool) -> None:
        if self.find_field.property("noMatch") != none:
            self.find_field.setProperty("noMatch", none)  # the stylesheet reads it
            self.find_field.style().unpolish(self.find_field)
            self.find_field.style().polish(self.find_field)
        self.find_field.setAccessibleDescription("No match" if none else "")

    # ---- the actions -----------------------------------------------------------------------

    def _open_menu(self, where: QPoint) -> None:
        """Pop the context menu up at ``where``, for the line under it (selected first, unless it
        is part of the selection already).
        """
        item = self.tree.itemAt(self.tree.viewport().mapFromGlobal(where))
        if item is not None and not item.isSelected():
            self.tree.clearSelection()
            self.tree.setCurrentItem(item)
            item.setSelected(True)
        menu = self.context_menu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(where)

    def context_menu(self) -> QMenu:
        """The menu for what is selected in the list: Hide always, Show always, Split, and Merge
        with… (the groups of the same type; with two or more groups selected, a plain Merge). The
        actions that cannot be done now are greyed out.
        """
        self._refresh_buttons()
        menu = QMenu(self.tree)
        menu.addAction(self.rename_action)
        menu.addSeparator()
        menu.addAction(self.always_action)
        menu.addAction(self.never_action)
        menu.addSeparator()
        menu.addAction(self.split_action)
        groups, _ = self._selected()
        if len(set(groups)) >= 2:
            menu.addAction(self.merge_action)
        else:
            menu.addMenu(self._merge_menu(menu))
        menu.addSeparator()
        menu.addAction(self.places_action)
        return menu

    def _merge_menu(self, parent: QMenu) -> QMenu:
        """The submenu "Merge with…": a line for each other group of the selected group's type."""
        menu = QMenu("Merge with…", parent)
        group = self._selected_group()
        found = False
        if group is not None:
            for other in self.review.groups:
                if other.id != group.id and other.type is group.type:
                    found = True
                    action = menu.addAction(f"{collapse(other.canonical)}  {other.token}")
                    action.triggered.connect(
                        lambda checked=False, ids=(group.id, other.id): self._merge_groups(
                            list(ids)
                        )
                    )
        menu.menuAction().setEnabled(found)
        return menu

    def _refresh_name(self) -> None:
        """Show the "Mask name" block for the one group the list has selected, else for none."""
        group = self._selected_group()
        stored = group is not None and group.placeholder in self.review.reserved
        self.inspector.name_panel.show_group(group, stored)

    def _rename(self) -> None:
        """Put the keyboard in the "Mask name" field (the context menu's "Rename mask…")."""
        if self.rename_action.isEnabled():
            self.inspector.name_panel.focus_field()

    def _double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """A double click on a group's row renames it; on a group of an existing case, which
        cannot be renamed, it opens or closes its places, as it did before.
        """
        if item.data(0, OCCURRENCE_ROLE) is not None:
            return
        self._refresh_buttons()
        if self.rename_action.isEnabled():
            self._rename()
        else:
            item.setExpanded(not item.isExpanded())

    def commit_pending_name(self) -> bool:
        """Give the selected group the name that stands in the "Mask name" field if the owner has
        typed one and not yet pressed Return (a button of the toolbar or the buttons beside the
        list do not take the keyboard on a Mac, so the field never loses it). True when there is
        nothing to commit or it was accepted; False when the review refused the name: the reason
        is shown under the field, and the caller must not go on.
        """
        panel = self.inspector.name_panel
        group_id = panel.group_id()
        if group_id is None or not panel.is_editable() or not panel.is_dirty():
            return True
        return self._commit_name(group_id, panel.current_text())

    def _flush_name(self) -> None:
        """Before the list is drawn again: commit a typed name; a refusal is shown and the field
        goes back (the redraw must not drop what the owner typed without a word).
        """
        self.commit_pending_name()

    def _name_committed(self, group_id: str, text: str) -> None:
        """The owner pressed Return in the "Mask name" field, or left it."""
        self._commit_name(group_id, text)

    def _commit_name(self, group_id: str, text: str) -> bool:
        """Give the group the name ``text`` (empty or blank: take its name off). A name the
        review refuses is explained under the field with the name of the group it was for, the
        field goes back to the name the group has, and the result is False.
        """
        group = next((g for g in self.review.groups if g.id == group_id), None)
        if group is None:
            return True
        panel = self.inspector.name_panel
        if not text.strip():
            wanted = None
        else:
            try:
                wanted = clean_label(text)
            except LabelError:
                wanted = text
        if wanted == group.label:
            if not text.strip() and panel.group_id() == group_id:
                panel.show_group(group, group.placeholder in self.review.reserved)
            return True
        try:
            self.review.set_label(group_id, text)
        except LabelError as error:
            panel.show_group(group, group.placeholder in self.review.reserved)
            panel.show_error(f"{collapse(group.canonical)}: {error}")
            return False
        panel.show_group(group, group.placeholder in self.review.reserved)  # the field as stored
        panel.clear_error()
        self._rebuild(select=group_id, scroll=False)
        return True

    def _clashing_groups(self) -> set[str]:
        """The groups whose name clashes with a value that will be masked (the review keeps the
        answer until something changes, so this is cheap to ask again).
        """
        return {group_id for group_id, _ in self.review.label_problem_pairs()}

    def _toggle_places(self) -> None:
        """Open the places of the selected group, or close them."""
        group = self._selected_group()
        if group is not None:
            item = self._items[group.id]
            item.setExpanded(not item.isExpanded())
            self._refresh_buttons()

    def _merge(self) -> None:
        groups, _ = self._selected()
        self._merge_groups(groups)

    def _merge_groups(self, group_ids: list[str]) -> None:
        if not self.commit_pending_name():
            return
        try:
            merged = self.review.merge(group_ids)
        except ValueError as error:
            show_notice(self, str(error))
            return
        self._rebuild(select=merged.id)

    def _split(self) -> None:
        if not self.commit_pending_name():
            return
        _, occurrences = self._selected()
        if len(occurrences) != 1:
            return
        ((group_id, found),) = occurrences.items()
        try:
            new = self.review.split(group_id, found)
        except ValueError as error:
            show_notice(self, str(error))
            return
        self._rebuild(select=new.id)

    def _always_hide(self) -> None:
        if not self.commit_pending_name():
            return
        group = self._selected_group()
        if group is not None:
            self._change_a_list(self.review.add_always_hide, group.canonical, group.id)

    def _never_hide(self, from_text: bool) -> None:
        """Put the text selected in the document on the never-hide list (``from_text``, the
        button), else the value of the selected group. The menu's action passes ``False``: it is
        about the group that was clicked, whatever stays selected in the document.
        """
        if not self.commit_pending_name():
            return
        cursor = self.text.textCursor()
        if from_text and cursor.hasSelection():
            try:
                start, end = self._map.selection(cursor.selectionStart(), cursor.selectionEnd())
            except ValueError as error:
                show_notice(self, str(error))
                return
            self._change_a_list(self.review.add_never_hide, self.review.text[start:end], None, True)
            return
        group = self._selected_group()
        if group is not None:
            self._change_a_list(self.review.add_never_hide, group.canonical, group.id, True)

    def _change_a_list(
        self,
        change: Callable[[str], None],
        value: str,
        group_id: str | None,
        shows: bool = False,
    ) -> None:
        """Put ``value`` on one of the two lists, and draw the review again. ``shows`` says it is
        the never-hide list: the groups it leaves visible are shown on purpose, which answers the
        question about those the analysis was unsure of.
        """
        try:
            change(value)
        except OSError as error:
            show_notice(self, f"The list could not be saved: {error.strerror or error}")
        except ValueError as error:
            show_notice(self, str(error))
        else:
            if shows:
                only_this, no_case = UserLists([], [value]), CaseLists([], [], set())
                self.review.answered |= {
                    group.id
                    for group in self.review.groups
                    if not group.enabled and on_never_hide_list(group.canonical, only_this, no_case)
                }
        self._rebuild(select=group_id, scroll=False)
