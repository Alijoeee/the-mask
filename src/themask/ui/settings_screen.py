"""The Settings screen: the owner's two lists, how long a case is kept, where the masked files
go, and the About box.

The lists are two boxes of text, one value on each line. Always hide holds what is hidden in every
document (``COMPANY:Falcon Freight`` hides it as a company); never hide holds what stays visible.
Saving cleans each list (no blank lines, nothing twice), refuses a value that is on both, writes
the lists and then the settings, and puts the new lists into the ``UserLists`` the app is using,
the very object, because the review and the analysis hold it. The settings the screen changes
(``ctx.settings``) are kept in place the same way. Nothing is kept until the owner saves, and
``reload`` shows what is kept now.

The screen is shown in a window of its own (``SettingsWindow``) that stays open beside the main
window. What is kept can change meanwhile (the review's "Always hide" puts a value on the list),
so the screen knows when it shows something else than what is kept (``is_stale``) and when the
owner has typed something that is not saved (``has_unsaved_edits``), and the window shows the
lists again when it is activated, unless the owner has typed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from themask.about import APP_NAME, OWNER_NAME, VERSION
from themask.detect.lists import UserLists, always_hide_entry, term_key
from themask.paths import lists_path
from themask.ui.theme import set_status

if TYPE_CHECKING:
    from themask.model import PlaceholderType
    from themask.ui.app import AppContext

SAVED = "Saved."
ABOUT = (
    f"{APP_NAME} {VERSION}\n"
    f"Made by {OWNER_NAME}\n\n"
    "Runs fully offline. Restored text you copy is on the clipboard in clear."
)
ALWAYS_HELP = (
    "Hidden in every document, one value on each line. Write COMPANY:Falcon Freight to hide a"
    " value as a company (or PERSON, AMOUNT, EMAIL ...); without a type it is hidden as CUSTOM."
)
NEVER_HELP = "Always left visible, one value on each line."
RETENTION_HELP = "Applies to the cases you make from now on."


def _always_entries(text: str) -> list[str]:
    """The always-hide entries in ``text``: one for each line, trimmed, without the blank ones
    and without any that hides what an earlier one hides.
    """
    entries: list[str] = []
    seen: set[tuple[PlaceholderType, str]] = set()
    for line in text.splitlines():
        entry = line.strip()
        kind, value = always_hide_entry(entry)
        key = (kind, term_key(value))
        if key[1] and key not in seen:
            seen.add(key)
            entries.append(entry)
    return entries


def _never_entries(text: str) -> list[str]:
    """The never-hide values in ``text``, cleaned the same way."""
    entries: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        entry = line.strip()
        key = term_key(entry)
        if key and key not in seen:
            seen.add(key)
            entries.append(entry)
    return entries


def _on_both(always: list[str], never: list[str]) -> str | None:
    """A value (as it is written in the always-hide list) that is on both lists, if there is one:
    a value is on one of the two at a time (``UserLists``).
    """
    kept = {term_key(entry) for entry in never}
    for entry in always:
        value = always_hide_entry(entry)[1]
        if term_key(value) in kept:
            return value
    return None


class SettingsScreen(QWidget):
    """The settings of ``ctx``: ``always_edit`` and ``never_edit`` hold the two lists, one value
    on each line, ``retention_spin`` the days a case is kept (1 to 365) and ``folder_edit`` the
    folder of the masked files, which ``folder_button`` changes. ``save_button`` keeps it all,
    and ``status_label`` says how that went. ``about_label`` is the About box.
    """

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Imported here, not at the top: themask.ui.app imports the window, which imports this
        # module.
        from themask.ui.app import RETENTION_DAYS

        self.ctx = ctx
        heading = QLabel("Settings")
        heading.setObjectName("heading")
        self.always_edit = QPlainTextEdit()
        self.never_edit = QPlainTextEdit()
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(RETENTION_DAYS[0], RETENTION_DAYS[-1])
        self.retention_spin.setSuffix(" days")
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_button = QPushButton("Choose…")
        self.folder_button.clicked.connect(self._choose_folder)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.about_label = QLabel(ABOUT)
        self.about_label.setTextFormat(Qt.TextFormat.PlainText)  # the owner's name may hold < >
        self.about_label.setWordWrap(True)
        self.about_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        lists = QHBoxLayout()
        lists.addWidget(self._box("Always hide", ALWAYS_HELP, self.always_edit))
        lists.addWidget(self._box("Never hide", NEVER_HELP, self.never_edit))
        form = QFormLayout()
        form.addRow("Keep a case for", self.retention_spin)
        form.addRow("Save masked files in", self._folder_row())
        keeping = QGroupBox("Cases and files")
        keeping_layout = QVBoxLayout(keeping)
        keeping_layout.addLayout(form)
        keeping_layout.addWidget(QLabel(RETENTION_HELP))
        about = QGroupBox("About")
        about_layout = QVBoxLayout(about)
        about_layout.addWidget(self.about_label)
        save = QHBoxLayout()
        save.addWidget(self.status_label, 1)
        save.addWidget(self.save_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addLayout(lists, 1)
        layout.addWidget(keeping)
        layout.addLayout(save)
        layout.addWidget(about)
        self._shown: tuple[str, str, int, str] = self._kept()
        self.reload()

    # ---- the interface the rest of the app uses --------------------------------------------

    def reload(self) -> None:
        """Show what is kept now: the lists in use, the days and the folder. The lists may have
        changed since the screen was last shown (the review can put a value on one), and what
        was typed and not saved is dropped.
        """
        always, never, days, folder = self._shown = self._kept()
        self.always_edit.setPlainText(always)
        self.never_edit.setPlainText(never)
        self.retention_spin.setValue(days)
        self.folder_edit.setText(folder)
        set_status(self.status_label, "")

    def has_unsaved_edits(self) -> bool:
        """Whether the owner has typed or chosen something since the screen last showed what is
        kept, that is not saved.
        """
        form = (
            self.always_edit.toPlainText(),
            self.never_edit.toPlainText(),
            self.retention_spin.value(),
            self.folder_edit.text(),
        )
        return form != self._shown

    def is_stale(self) -> bool:
        """Whether what is kept is not what the screen last showed (it changed meanwhile)."""
        return self._kept() != self._shown

    def _kept(self) -> tuple[str, str, int, str]:
        """What ``reload`` shows: the two lists as text, the days and the folder."""
        lists, settings = self.ctx.user_lists, self.ctx.settings
        return (
            "\n".join(lists.always_hide),
            "\n".join(lists.never_hide),
            settings.retention_days,
            str(settings.out_dir),
        )

    # ---- building the screen ---------------------------------------------------------------

    @staticmethod
    def _box(title: str, help_text: str, edit: QPlainTextEdit) -> QGroupBox:
        box = QGroupBox(title)
        help_label = QLabel(help_text)
        help_label.setWordWrap(True)
        column = QVBoxLayout(box)
        column.addWidget(help_label)
        column.addWidget(edit, 1)
        return box

    def _folder_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self.folder_edit, 1)
        row.addWidget(self.folder_button)
        return row

    # ---- the buttons -----------------------------------------------------------------------

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder for the masked files", self.folder_edit.text()
        )
        if folder:
            self.folder_edit.setText(folder)

    def _save(self) -> None:
        """Keep the lists and the settings as they stand in the boxes.

        A value on both lists is refused before anything is written. The lists are written first
        and put in use as soon as they are on disk; then the settings, the same way. What fails is
        said, with what was kept before it. When the lists cannot be written the owner's text stays
        in its boxes, to be saved again.
        """
        # Imported here, not at the top: see __init__.
        from themask.ui.app import settings_path

        always = _always_entries(self.always_edit.toPlainText())
        never = _never_entries(self.never_edit.toPlainText())
        both = _on_both(always, never)
        if both is not None:
            set_status(
                self.status_label,
                f"“{both}” is on both lists. Keep it on one of them.",
                problem=True,
            )
            return
        try:
            UserLists(always, never).save(lists_path())
        except OSError as error:
            set_status(
                self.status_label,
                f"The lists could not be saved: {error.strerror or error}",
                problem=True,
            )
            return
        lists = self.ctx.user_lists
        lists.always_hide, lists.never_hide = always, never  # in place: others hold this object
        wanted = replace(
            self.ctx.settings,
            retention_days=self.retention_spin.value(),
            out_dir=Path(self.folder_edit.text()),
        )
        try:
            wanted.save(settings_path())
        except OSError as error:
            self.reload()
            set_status(
                self.status_label,
                f"The lists were saved, but the settings could not be: {error.strerror or error}",
                problem=True,
            )
            return
        self.ctx.settings.retention_days = wanted.retention_days
        self.ctx.settings.out_dir = wanted.out_dir
        self.reload()
        set_status(self.status_label, SAVED)


class SettingsWindow(QDialog):
    """The settings in a window of their own, titled "Settings": a tool window that does not
    block the main window, closed with Esc. ``settings_screen`` is the screen it holds.

    It shows what is kept each time it opens, and again when it becomes the active window after
    what is kept changed meanwhile, unless the owner has typed something that is not saved: that
    is never thrown away. Return saves (and does nothing else, whatever button has the focus).
    """

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setModal(False)
        self.settings_screen = SettingsScreen(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.settings_screen)
        # A dialog presses its default button on Return. That is Save here, and no other button:
        # Return in the folder field must not open the folder dialog.
        for button in self.settings_screen.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.settings_screen.save_button.setDefault(True)
        self.resize(680, 640)

    def showEvent(self, event: QShowEvent) -> None:
        self.settings_screen.reload()
        super().showEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowActivate:
            screen = self.settings_screen
            if screen.is_stale() and not screen.has_unsaved_edits():
                screen.reload()
        return super().event(event)
