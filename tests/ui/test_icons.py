"""The line icons of the sidebar, the tool bar and the find fields: drawn as paths, so that they
are as sharp at 1x as at 2x and take any colour.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter

from themask.ui import icons

ACCENT = "#B5642A"


def opaque_pixels(image: QImage) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() == 255
    ]


def test_the_icons_are_the_four_of_the_sidebar_and_the_search_field() -> None:
    assert set(icons.NAMES) == {"mask", "restore", "cases", "sidebar", "search"}


@pytest.mark.parametrize("name", icons.NAMES)
def test_every_icon_is_drawn_at_1x_and_at_2x_at_the_size_asked(qapp: object, name: str) -> None:
    icon = icons.icon(name, ACCENT, 18)
    one = icon.pixmap(QSize(18, 18))
    two = icon.pixmap(QSize(18, 18), 2.0)
    assert one.size() == QSize(18, 18) and one.devicePixelRatio() == 1
    assert two.size() == QSize(36, 36) and two.devicePixelRatio() == 2
    assert not icon.isNull()


@pytest.mark.parametrize("size", [14, 16, 18, 24])
def test_an_icon_is_drawn_at_any_size(qapp: object, size: int) -> None:
    picture = icons.pixmap("mask", ACCENT, size, 1.0)
    assert picture.size() == QSize(size, size)
    assert picture.deviceIndependentSize().width() == size
    assert icons.pixmap("mask", ACCENT, size, 2.0).size() == QSize(2 * size, 2 * size)


@pytest.mark.parametrize("name", icons.NAMES)
def test_an_icon_is_a_line_drawing_in_the_colour_given_on_nothing(qapp: object, name: str) -> None:
    image = icons.pixmap(name, ACCENT, 18, 2.0).toImage()
    assert image.pixelColor(0, 0).alpha() == 0  # nothing at the corner
    inked = opaque_pixels(image)
    assert 40 < len(inked) < 36 * 36 // 2  # a drawing in lines, not a block
    assert {image.pixelColor(x, y).name().upper() for x, y in inked} == {ACCENT}


def test_the_colour_can_be_anything(qapp: object) -> None:
    white = icons.pixmap("cases", "#FFFFFF", 18, 2.0).toImage()
    assert {white.pixelColor(x, y).name() for x, y in opaque_pixels(white)} == {"#ffffff"}
    qcolor = icons.pixmap("cases", QColor("#6B655E"), 18, 2.0).toImage()
    assert {qcolor.pixelColor(x, y).name() for x, y in opaque_pixels(qcolor)} == {"#6b655e"}


def test_the_icons_differ_from_one_another(qapp: object) -> None:
    images = {name: icons.pixmap(name, ACCENT, 18, 2.0).toImage() for name in icons.NAMES}
    for name, image in images.items():
        for other, other_image in images.items():
            if name < other:
                assert image != other_image, (name, other)


def test_the_icons_have_the_shapes_of_the_mockups(qapp: object) -> None:
    def ink(name: str, x: float, y: float) -> int:
        """The alpha at the point (x, y) of the 18-unit drawing, at 2x."""
        return (
            icons.pixmap(name, ACCENT, 18, 2.0)
            .toImage()
            .pixelColor(round(2 * x), round(2 * y))
            .alpha()
        )

    assert ink("mask", 5, 9) == 255  # the left edge of the document
    assert ink("mask", 9, 10.75) == 0  # the inside of the little mask on it
    assert ink("mask", 9, 9) > 100  # its top edge
    assert ink("restore", 3, 9) == 255  # the ring of the key
    assert ink("restore", 6.5, 9) == 0  # its hole
    assert ink("restore", 13, 9) == 255  # its shaft
    assert ink("cases", 2.5, 5.75) == 255  # the side of the lid
    assert ink("cases", 9, 12) == 0  # the inside of the box
    assert ink("cases", 9, 10.5) == 255  # the handle


def test_the_sidebar_icon_is_16_by_14_units_in_the_middle_of_its_square(qapp: object) -> None:
    image = icons.pixmap("sidebar", ACCENT, 16, 2.0).toImage()  # 32 by 32 pixels
    rows = sorted({y for _, y in opaque_pixels(image)})
    assert rows[0] >= 1 and rows[-1] <= 30  # 14 units of 16: a unit of room above and below
    assert any(image.pixelColor(x, 16).alpha() > 0 for x in range(32))


def test_an_icon_can_be_drawn_on_any_painter_in_any_rectangle(qapp: object) -> None:
    image = QImage(60, 60, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    icons.draw(painter, "mask", QRectF(20, 20, 18, 18), QColor(ACCENT))
    painter.end()
    assert image.pixelColor(2, 2).alpha() == 0 and image.pixelColor(50, 50).alpha() == 0
    assert opaque_pixels(image)
    assert all(20 <= x < 38 and 20 <= y < 38 for x, y in opaque_pixels(image))


def test_an_icon_that_does_not_exist_is_refused(qapp: object) -> None:
    with pytest.raises(KeyError):
        icons.icon("unicorn", ACCENT)


# ---- the path data of the mockups ---------------------------------------------------------------


def test_svg_paths_with_lines_and_a_close() -> None:
    path = icons.svg_path("M5 2.5h5.5L14 6v9.5H5z")
    assert path.boundingRect() == QRectF(5, 2.5, 9, 13)
    assert path.elementCount() == 6  # five points, and the line back to the first


def test_svg_relative_commands_continue_from_the_current_point() -> None:
    path = icons.svg_path("M10 9h6M13.5 9v2.5M15.5 9v2")
    assert path.boundingRect() == QRectF(10, 9, 6, 2.5)


def test_svg_numbers_may_run_together_and_repeat_a_command() -> None:
    assert icons.svg_path("M1 1l2 2 2-2").boundingRect() == QRectF(1, 1, 4, 2)  # l with two pairs
    assert icons.svg_path("M0 0L4 0 4 3").boundingRect() == QRectF(0, 0, 4, 3)  # L with two pairs


def test_svg_smooth_curves_take_the_mirror_of_the_last_handle() -> None:
    # The mockup's little mask: two curves and then three smooth ones back to the start.
    path = icons.svg_path("M7 10.5c0-1 .9-1.5 2-1.5s2 .5 2 1.5-.9 2-2 2-2-1-2-2z")
    box = path.boundingRect()
    assert box.left() == pytest.approx(7, abs=0.05) and box.right() == pytest.approx(11, abs=0.05)
    assert box.top() >= 8.9 and box.bottom() <= 12.6
    assert path.currentPosition().x() == pytest.approx(7)  # the close ends where it began


def test_an_svg_command_that_is_not_known_is_refused() -> None:
    with pytest.raises(ValueError, match="Q"):
        icons.svg_path("M0 0Q1 1 2 2")
