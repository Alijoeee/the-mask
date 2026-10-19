"""The light and the dark look for the tests of the export sheet, the restore screen and the cases
screen, and a way to keep what a widget looks like.

``d3_appearance`` runs a test twice, once for each appearance: it forces the appearance the way
``THEMASK_APPEARANCE`` does, installs the look of the application (``theme.apply``) and takes it
away again afterwards, so that the widgets the test makes are drawn the way the app draws them.
``d3_shot`` grabs a widget and returns the picture; when ``THEMASK_SHOTS`` names a folder it also
saves it there as ``<name>-<appearance>.png`` (the pictures of the design report).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QWidget

SHOTS_VARIABLE = "THEMASK_SHOTS"


@pytest.fixture(params=["light", "dark"])
def d3_appearance(
    request: pytest.FixtureRequest, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """The appearance of the test: "light", then "dark". Its look is installed on the application
    for the length of the test.
    """
    from themask.ui import theme

    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, request.param)
    palette, sheet, font = qapp.palette(), qapp.styleSheet(), qapp.font()
    theme.apply(qapp)
    yield str(request.param)
    for follower in qapp.findChildren(theme.AppearanceFollower):
        follower.setParent(None)
        follower.deleteLater()
    qapp.setPalette(palette)
    qapp.setStyleSheet(sheet)
    qapp.setFont(font)


@pytest.fixture
def d3_shot() -> Callable[[QWidget, str, str], QImage]:
    """``shot(widget, name, appearance)``: the picture of ``widget``, saved as
    ``<name>-<appearance>.png`` in the folder ``THEMASK_SHOTS`` names, if it names one.
    """

    def shot(widget: QWidget, name: str, appearance: str) -> QImage:
        image = widget.grab().toImage()
        folder = os.environ.get(SHOTS_VARIABLE)
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            assert image.save(str(Path(folder) / f"{name}-{appearance}.png"))
        return image

    return shot


def appears_in(image: QImage, colour: str, where: QWidget, around: QWidget) -> bool:
    """Whether ``colour`` is the colour of a pixel of ``image`` (a picture of ``around``) inside
    the widget ``where``: a screen is drawn in the colours of its appearance.
    """
    from PySide6.QtGui import QColor

    top_left = where.mapTo(around, where.rect().topLeft())
    wanted = QColor(colour).rgb()
    for dx in range(0, where.width(), 2):
        for dy in range(0, where.height(), 2):
            if image.pixel(top_left.x() + dx, top_left.y() + dy) == wanted:
                return True
    return False
