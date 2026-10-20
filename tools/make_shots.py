"""Takes pictures of the windows of The MASK, offscreen, in the light and the dark appearance: the
home screen, the Restore and Cases screens, the Settings window and, with a Word file to analyse,
the review.

    uv run python tools/make_shots.py OUT_DIR [--review FILE.docx] [--named-review] [--size 1180x760]

writes ``home-light.png``, ``home-dark.png``, ``restore-light.png``, ... into ``OUT_DIR``. The
screens show made-up data: two saved cases (K4F7 and Z8Q2, as in the mockups) in a case store in a
temporary folder with its key in memory, so that nothing of the owner's own data (or Keychain) is
touched, and the clock is fixed at 15:30, so that "Exported today at 14:02" says what the mockup
says. The window is as the Mac shows it, minus the system's menu bar and title bar: the picture is
``QWidget.grab`` of the window at the size asked (1180 by 760 by default), without the crossfade.
With ``--named-review`` (no engine needed) a made-up review is shown with one value named
"Provider" (``review-named-*.png``) and with the field's refusal on show
(``review-name-refused-*.png``). With ``--review`` the engine is loaded (a few seconds) and the file analysed, for the picture of
the review. Qt draws offscreen; nothing opens on the screen.

``take`` is what the tests run (tests/ui/test_shots.py).
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import CombinedText
from themask.keystore.cases import CaseStore
from themask.keystore.secrets import MemoryKeyStore
from themask.model import Case, Finding, Group, KeyEntry, PlaceholderType
from themask.review import ReviewState
from themask.ui import home_screen, main_window, theme
from themask.ui.app import AppContext, Settings
from themask.ui.main_window import MainWindow

if TYPE_CHECKING:
    from themask.detect.engine import Engine

DEFAULT_SIZE = (1180, 760)
APPEARANCES = ("light", "dark")
# The clock of the pictures: the owner's afternoon, so that a case made at 14:02 is "today".
NOW = datetime.now().astimezone().replace(hour=15, minute=30, second=0, microsecond=0)


def made_up_case(
    code: str, files: list[str], created: datetime, values: int, retention_days: int = 30
) -> Case:
    """A case with ``values`` entries in its key, of nobody."""
    entries = [
        KeyEntry(f"[PERSON_{i}]", PlaceholderType.PERSON, f"Person {i}", [])
        for i in range(1, values + 1)
    ]
    return Case(code, created, files, [], entries, retention_days)


def made_up_context(folder: Path, engine: Engine | None) -> AppContext:
    """The context of the pictures: the two cases of the mockups, in a store of their own."""
    store = CaseStore(folder / "cases", MemoryKeyStore())
    store.save(made_up_case("K4F7", ["supply-01.docx"], NOW.replace(hour=14, minute=2), 14))
    yesterday = (NOW - timedelta(days=1)).replace(hour=11, minute=40)
    store.save(made_up_case("Z8Q2", ["nda-02.docx", "nda-02-annex.docx"], yesterday, 21))
    # The screens do not use the engine until a file is analysed: a stand-in does for the pictures
    # of the others.
    return AppContext(
        engine=engine if engine is not None else cast("Engine", object()),
        user_lists=UserLists([], []),
        case_store=store,
        # The folder is only shown: nothing is written to it, and no home folder is named.
        settings=Settings(out_dir=Path("~/Documents/The MASK")),
    )


_CONTRACT = (
    "This Agreement is made between Northwind Trading B.V. and Acme Supplies Ltd, represented by"
    " Mr John Carter (Mr Carter). The price is EUR 1,250,000 and a late payment bears 8 % a year."
    " Notices go to j.carter@acme.example."
)


def made_up_review() -> tuple[CombinedText, ReviewState]:
    """A review of a made-up contract: one group for each value, none named."""
    combined = CombinedText.join([("supply-01.docx (after)", _CONTRACT)])
    specs = [
        (PlaceholderType.COMPANY, "Northwind Trading B.V.", ["Northwind Trading B.V."]),
        (PlaceholderType.COMPANY, "Acme Supplies Ltd", ["Acme Supplies Ltd"]),
        (PlaceholderType.PERSON, "Mr John Carter", ["Mr John Carter", "Mr Carter"]),
        (PlaceholderType.AMOUNT, "EUR 1,250,000", ["EUR 1,250,000"]),
        (PlaceholderType.EMAIL, "j.carter@acme.example", ["j.carter@acme.example"]),
    ]
    groups: list[Group] = []
    numbers: dict[PlaceholderType, int] = {}
    for k, (kind, canonical, forms) in enumerate(specs):
        found = [
            Finding(kind, at, at + len(form), form, 1.0, "pattern")
            for form in forms
            for at in [_CONTRACT.index(form)]
        ]
        numbers[kind] = numbers.get(kind, 0) + 1
        placeholder = f"[{kind.value}_{numbers[kind]}]"
        groups.append(Group(f"g{k}", kind, canonical, set(forms), found, placeholder))
    state = ReviewState(combined.text, groups, [], UserLists([], []), CaseLists([], [], set()))
    return combined, state


def show_made_up_review(window: MainWindow) -> ReviewState:
    """Put the made-up review on the window's review screen, as if a file had been analysed."""
    combined, state = made_up_review()
    window.review_screen.load(state, combined)
    window._review_ready = True
    window._review_title_changed(*window.review_screen.title())
    window.show_screen("review")
    return state


def settle(milliseconds: int = 50) -> None:
    """Let the application handle what is waiting, and what the next moments bring."""
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def analyse(window: MainWindow, path: Path) -> None:
    """Open ``path`` in ``window`` and wait until its review is showing."""
    loop = QEventLoop()
    window.analysisFinished.connect(loop.quit)
    window.analysisFailed.connect(lambda message: (print(message, file=sys.stderr), loop.quit()))
    window.open_files([path], redline_split=False)
    loop.exec()


def take(
    out_dir: Path,
    *,
    review: Path | None = None,
    size: tuple[int, int] = DEFAULT_SIZE,
    engine: Engine | None = None,
    named_review: bool = False,
) -> list[Path]:
    """Take the pictures into ``out_dir`` (made if it is not there) and return their files.

    ``review`` is a Word file to analyse for the picture of the review; ``engine`` is the engine
    to do it with (the default one is loaded when there is none). ``named_review`` adds the
    pictures of a made-up review whose first company is named.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # nothing opens on the screen
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    application.setStyle("Fusion")  # the pictures look the same on every machine, not native
    if review is not None and engine is None:
        from themask.detect.engine import Engine as DefaultEngine

        engine = DefaultEngine()
    written: list[Path] = []
    # What the pictures change is put back: the appearance, the clock and the crossfade.
    appearance_before = os.environ.get(theme.APPEARANCE_VARIABLE)
    clock_before, animations_before = home_screen.current_time, main_window.ANIMATIONS
    home_screen.current_time = lambda: NOW.astimezone()
    main_window.ANIMATIONS = False
    try:
        for appearance in APPEARANCES:
            os.environ[theme.APPEARANCE_VARIABLE] = appearance
            theme.apply(application)
            with tempfile.TemporaryDirectory() as folder:
                ctx = made_up_context(Path(folder), engine)
                written += _pictures(ctx, appearance, out_dir, size, review, named_review)
    finally:
        home_screen.current_time, main_window.ANIMATIONS = clock_before, animations_before
        if appearance_before is None:
            os.environ.pop(theme.APPEARANCE_VARIABLE, None)
        else:
            os.environ[theme.APPEARANCE_VARIABLE] = appearance_before
    return written


def _pictures(
    ctx: AppContext,
    appearance: str,
    out_dir: Path,
    size: tuple[int, int],
    review: Path | None,
    named_review: bool = False,
) -> list[Path]:
    window = MainWindow(ctx)
    window.menuBar().hide()  # the Mac shows the menus in the system's menu bar, not in the window
    window.resize(*size)
    window.show()
    settle()
    shots: dict[str, Callable[[], object]] = {
        "home": window.show_home,
        "restore": window.show_restore,
        "cases": window.show_cases,
    }
    written = []
    for name, show in shots.items():
        show()
        settle()
        written.append(_save(window, out_dir / f"{name}-{appearance}.png"))
    if review is not None:
        analyse(window, review)
        settle()
        written.append(_save(window, out_dir / f"review-{appearance}.png"))
    if named_review:
        written += _named_pictures(window, appearance, out_dir)
    window.show_home()
    window.show_settings()
    settle()
    written.append(_save(window.settings_window, out_dir / f"settings-{appearance}.png"))
    window.settings_window.close()
    window.close()
    return written


def _named_pictures(window: MainWindow, appearance: str, out_dir: Path) -> list[Path]:
    """The made-up review with a value named, and with the field's refusal under the field."""
    state = show_made_up_review(window)
    screen = window.review_screen
    group = state.groups[0]
    screen.tree_item_for(group.id).setSelected(True)
    screen.tree.setCurrentItem(screen.tree_item_for(group.id))
    state.set_label(group.id, "Provider")
    screen._rebuild(select=group.id, scroll=False)
    settle()
    written = [_save(window, out_dir / f"review-named-{appearance}.png")]
    panel = screen.inspector.name_panel
    panel.name_field.setText("Acme [Ltd]")
    panel.name_field.editingFinished.emit()
    settle()
    written.append(_save(window, out_dir / f"review-name-refused-{appearance}.png"))
    return written


def _save(widget: object, path: Path) -> Path:
    grab = widget.grab()  # type: ignore[attr-defined]
    if not grab.save(str(path)):
        raise OSError(f"The picture could not be written to {path}.")
    return path


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    review: Path | None = None
    size = DEFAULT_SIZE
    named = False
    paths: list[str] = []
    try:
        while arguments:
            argument = arguments.pop(0)
            if argument == "--named-review":
                named = True
            elif argument == "--review":
                review = Path(arguments.pop(0))
            elif argument == "--size":
                width, height = arguments.pop(0).split("x")
                size = (int(width), int(height))
            else:
                paths.append(argument)
    except (IndexError, ValueError):
        print(__doc__, file=sys.stderr)
        return 2
    if len(paths) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    for path in take(Path(paths[0]), review=review, size=size, named_review=named):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
