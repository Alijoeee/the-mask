"""The review screen: what the analysis found, for the owner to check before anything is masked.

On the left the text of the files, each active find marked in the colour of its type; a find the
analysis was not sure of has a dotted underline and the tooltip "check". On the right the finds
as a list of groups: a line for each group with a box that switches the whole group, a line under
it for each occurrence with a box of its own, and "check" beside a group to look at. Under the
list are the actions: hide text the analysis missed, merge groups, split occurrences off a group,
put a group's value on the always-hide or the never-hide list, and go on to the export.

The ``ReviewState`` holds every decision. The screen shows it, passes the owner's clicks on to it
and draws everything again after each change (the state re-sorts its groups and findings, so
nothing is kept between two changes but the ids of the groups).

The text pane shows the combined text as it is, with a header line before the text of each file.
Positions in the pane count UTF-16 units from the start of the pane, and indexes in the text count
characters, so ``_TextMap`` converts between them exactly: a character outside the BMP is two
units, a header or the gap between files has no index, and each file's text is checked to take
exactly the room it should. What the owner selects is read from the text by index, never from the
pane (which shows a no-break space as a plain space).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QHelpEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME
from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import CombinedText
from themask.model import Finding, Group, PlaceholderType
from themask.review import ReviewState
from themask.ui.theme import TYPE_COLOURS

CHECK_TIP = "check: The MASK is not sure about this one. Have a look at it before you go on."
NOTHING_SELECTED = "Select the text to hide in the document first."
ONE_FILE = "Select text from one file at a time."
NOT_TEXT = "Select some of the document's text, not a file name."
LOADED_ON_ANOTHER_TEXT = "The review was not made on this text."

CONTEXT_CHARACTERS = 28  # of the text before and after an occurrence, in the list
GROUP_ROLE = Qt.ItemDataRole.UserRole  # the id of the group, on its line and on those under it
OCCURRENCE_ROLE = Qt.ItemDataRole.UserRole + 1  # the index of an occurrence, on its line only
_FLAGS = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
_STRESS = 120  # the occurrences of a selected group are this per cent darker (QColor.darker)
_BLACK = QColor("black")
_CHECK_UNDERLINE = QColor("#8A4B00")
_CHECK_BADGE = QColor("#FFD27A")
_HEADER_FILL = QColor("#E4E4E4")


def show_notice(parent: QWidget | None, message: str) -> None:
    """Tell the owner why something could not be done, in a sentence."""
    QMessageBox.information(parent, APP_NAME, message)


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
        painter.setPen(QColor(0, 0, 0, 90))
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
    pane that shows it and ``tree`` the list of its groups. ``exportRequested`` is sent when the
    owner chooses to go on, with something to hide or not.
    """

    exportRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.review = ReviewState("", [], [], UserLists([], []), CaseLists([], [], set()))
        self.combined = CombinedText("", [])
        self._map = _TextMap("")
        self._items: dict[str, QTreeWidgetItem] = {}
        self._highlights: list[_Highlight] = []
        self._starts: list[int] = []
        self._stressed: set[str] = set()
        self._formats: dict[tuple[PlaceholderType, bool, bool], QTextCharFormat] = {}
        self._updating = False
        self._from_text = False

        self.warnings_label = QLabel()
        self.warnings_label.setObjectName("warnings")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.hide()
        self.summary_label = QLabel()
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setUndoRedoEnabled(False)
        self.text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.text.viewport().installEventFilter(self)
        self.tree = self._build_tree()
        self.hide_button = QPushButton("Hide selection")
        self.hide_button.setMenu(self._build_type_menu())
        self.hide_button.setToolTip("Hide the text selected in the document, wherever it stands.")
        self.merge_button = self._button("Merge", "Make the selected groups one.", self._merge)
        self.split_button = self._button(
            "Split", "Move the selected occurrences into a group of their own.", self._split
        )
        self.always_button = self._button(
            "Always hide",
            "Hide the value of the selected group in every document from now on.",
            self._always_hide,
        )
        self.never_button = self._button(
            "Never hide",
            "Leave the value of the selected group visible in every document from now on.",
            self._never_hide,
        )
        self.export_button = QPushButton("Continue to export")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.exportRequested)
        self._arrange()
        self.text.selectionChanged.connect(self._refresh_buttons)
        self._refresh_buttons()

    # ---- the interface the rest of the app uses --------------------------------------------

    def load(self, review: ReviewState, combined: CombinedText) -> None:
        """Show ``review``, which was made on the text ``combined``.

        Raises ValueError for a review made on another text: its places would be someone
        else's.
        """
        if review.text != combined.text:
            raise ValueError(LOADED_ON_ANOTHER_TEXT)
        self.review, self.combined = review, combined
        self._map = self._show_text(combined)
        self._stressed = set()
        self._rebuild()
        self._show_warnings()
        self.text.moveCursor(QTextCursor.MoveOperation.Start)
        self.text.verticalScrollBar().setValue(0)

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

    def hide_selection(self, type: PlaceholderType) -> None:
        """Hide the text selected in the pane as ``type``, wherever it stands.

        What the owner cannot hide (nothing selected, a selection that takes in two files or a
        file name, text the review refuses) is explained in a notice and nothing changes.
        """
        cursor = self.text.textCursor()
        if not cursor.hasSelection():
            show_notice(self, NOTHING_SELECTED)
            return
        try:
            start, end = self._map.selection(cursor.selectionStart(), cursor.selectionEnd())
            group = self.review.hide_text(self.review.text[start:end], type)
        except ValueError as error:
            show_notice(self, str(error))
            return
        cursor.clearSelection()  # so that the colour of the new find shows
        self.text.setTextCursor(cursor)
        self._rebuild(select=group.id, scroll=False)

    def tooltip_at(self, point: QPoint) -> str:
        """The tooltip for ``point`` of the pane: "check" over a find to check, else nothing."""
        highlight = self._highlight_at(point)
        return CHECK_TIP if highlight is not None and highlight.needs_check else ""

    # ---- building the screen ---------------------------------------------------------------

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Confidential values", ""])
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setUniformRowHeights(True)
        # A long value is cut in the middle, so the placeholder at the end of its line shows.
        tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.itemChanged.connect(self._item_changed)
        tree.itemSelectionChanged.connect(self._selection_changed)
        return tree

    def _build_type_menu(self) -> QMenu:
        menu = QMenu(self)
        for kind in PlaceholderType:
            action = menu.addAction(_swatch(kind), kind.value)
            action.triggered.connect(lambda checked=False, kind=kind: self.hide_selection(kind))
        return menu

    @staticmethod
    def _button(text: str, tip: str, action: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(action)
        return button

    def _arrange(self) -> None:
        side = QWidget()
        buttons = QGridLayout()
        buttons.addWidget(self.hide_button, 0, 0)
        buttons.addWidget(self.merge_button, 0, 1)
        buttons.addWidget(self.split_button, 0, 2)
        buttons.addWidget(self.always_button, 1, 0)
        buttons.addWidget(self.never_button, 1, 1)
        column = QVBoxLayout(side)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.summary_label)
        column.addWidget(self.tree, 1)
        column.addLayout(buttons)
        column.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignRight)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.text)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.warnings_label)
        layout.addWidget(splitter, 1)

    # ---- the text pane ---------------------------------------------------------------------

    def _show_text(self, combined: CombinedText) -> _TextMap:
        """Put the files' texts in the pane, each under a header with its name; returns where."""
        document = self.text.document()
        document.clear()
        header_block = QTextBlockFormat()
        header_block.setBackground(QBrush(_HEADER_FILL))
        header_block.setBottomMargin(4)
        header_text = QTextCharFormat()
        header_text.setFontWeight(QFont.Weight.Bold)
        header_text.setForeground(QBrush(_BLACK))
        body_block, body_text = QTextBlockFormat(), QTextCharFormat()
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
                fmt.setUnderlineColor(_CHECK_UNDERLINE)
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

    def _rebuild(self, select: str | None = None, scroll: bool = True) -> None:
        """Make the list, the highlights and the summary again from the review.

        The groups that were open stay open. ``select`` is the group to select afterwards, and
        ``scroll`` whether the pane then goes to its first occurrence.
        """
        opened = {group_id for group_id, item in self._items.items() if item.isExpanded()}
        self._updating = True
        try:
            self.tree.clear()
            self._items = {}
            for group in self.review.groups:
                self._add_group(group)
            for group_id in opened & self._items.keys():
                self._items[group_id].setExpanded(True)
        finally:
            self._updating = False
        self._stressed = set()
        self._refresh_highlights()
        self._refresh_summary()
        self._refresh_buttons()
        if select is not None and select in self._items:
            self._from_text = not scroll
            try:
                self.tree.clearSelection()
                self.tree.setCurrentItem(self._items[select])
                self._items[select].setSelected(True)
                self.tree.scrollToItem(self._items[select])
            finally:
                self._from_text = False

    def _add_group(self, group: Group) -> None:
        occurrences = _count(len(group.findings), "time")
        label = f"{' '.join(group.canonical.split())} — {occurrences} — {group.placeholder}"
        item = QTreeWidgetItem([label, "check" if group.needs_check else ""])
        item.setIcon(0, _swatch(group.type))
        item.setFlags(_FLAGS)
        item.setCheckState(0, Qt.CheckState.Checked if group.enabled else Qt.CheckState.Unchecked)
        item.setData(0, GROUP_ROLE, group.id)
        item.setToolTip(0, label)
        if group.needs_check:
            item.setBackground(1, QBrush(_CHECK_BADGE))
            item.setForeground(1, QBrush(_BLACK))
            item.setToolTip(1, CHECK_TIP)
        for index, finding in enumerate(group.findings):
            child = QTreeWidgetItem([self._context(finding), ""])
            child.setFlags(_FLAGS if group.enabled else _FLAGS & ~Qt.ItemFlag.ItemIsEnabled)
            child.setCheckState(
                0, Qt.CheckState.Unchecked if index in group.disabled else Qt.CheckState.Checked
            )
            child.setData(0, GROUP_ROLE, group.id)
            child.setData(0, OCCURRENCE_ROLE, index)
            item.addChild(child)
        self.tree.addTopLevelItem(item)
        self._items[group.id] = item

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
        items = self.tree.selectedItems()
        if len(items) == 1 and not self._from_text:
            group_id = cast("str", items[0].data(0, GROUP_ROLE))
            index = items[0].data(0, OCCURRENCE_ROLE)
            group = next(g for g in self.review.groups if g.id == group_id)
            self._show_occurrence(group, 0 if index is None else cast("int", index))

    def _refresh_buttons(self) -> None:
        groups, occurrences = self._selected()
        self.hide_button.setEnabled(self.text.textCursor().hasSelection())
        self.merge_button.setEnabled(len(set(groups)) >= 2)
        splittable = False
        if len(occurrences) == 1:
            ((group_id, found),) = occurrences.items()
            group = next((g for g in self.review.groups if g.id == group_id), None)
            splittable = group is not None and 0 < len(found) < len(group.findings)
        self.split_button.setEnabled(splittable)
        one_group = self._selected_group() is not None
        self.always_button.setEnabled(one_group)
        self.never_button.setEnabled(one_group)

    def _refresh_summary(self) -> None:
        counts = self.review.counts()
        self.summary_label.setText(
            f"{_count(counts.groups, 'value')} · {_count(counts.replacements, 'place')} will be"
            f" hidden · {counts.needs_check} to check"
        )

    def _show_warnings(self) -> None:
        self.warnings_label.setText("\n".join(self.review.warnings))
        self.warnings_label.setVisible(bool(self.review.warnings))

    # ---- the actions -----------------------------------------------------------------------

    def _merge(self) -> None:
        groups, _ = self._selected()
        try:
            merged = self.review.merge(groups)
        except ValueError as error:
            show_notice(self, str(error))
            return
        self._rebuild(select=merged.id)

    def _split(self) -> None:
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
        self._change_a_list(lambda group: self.review.add_always_hide(group.canonical))

    def _never_hide(self) -> None:
        self._change_a_list(lambda group: self.review.add_never_hide(group.canonical))

    def _change_a_list(self, change: Callable[[Group], None]) -> None:
        """Put the selected group's value on one of the two lists, and draw the review again."""
        group = self._selected_group()
        if group is None:
            return
        try:
            change(group)
        except OSError as error:
            show_notice(self, f"The list could not be saved: {error.strerror or error}")
        except ValueError as error:
            show_notice(self, str(error))
        self._rebuild(select=group.id, scroll=False)
