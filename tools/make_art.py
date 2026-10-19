"""Draws the illustrations of The MASK: a mask on a document (the home screen's drop card) and a
document with a check (the file card of the restore screen), each in a light and a dark form and
at 1x and 2x.

    uv run python tools/make_art.py [out_dir]

writes ``mask-light.png``, ``mask-light@2x.png``, ``mask-dark.png``, ``mask-dark@2x.png`` and the
same four for ``check``. The default folder is ``src/themask/ui/art/``, which is where the app
loads them from (``themask.ui.art``). The files are committed, so nothing needs to run this: run
it again only to change a picture.

The shapes are those of the approved mockups, in the units of their drawings (112 by 88 for the
mask, 64 by 64 for the check). The colours are the accent, the accent-soft and the panel of the
theme (tests/ui/test_art.py checks that they are). The same files come out every time. Only
Pillow is needed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "src" / "themask" / "ui" / "art"

SUPERSAMPLE = 8  # everything is drawn at eight times the size and reduced, which smooths the edges

Colour = tuple[int, int, int]
Point = tuple[float, float]
Bezier = tuple[Point, Point, Point, Point]  # from, the two handles, to


@dataclass(frozen=True)
class Colours:
    """What a picture is drawn in: the accent for every line, the soft accent for the page and the
    colour of the card the picture lies on, for the face and the round mark.
    """

    accent: Colour
    soft: Colour
    panel: Colour


LIGHT = Colours(accent=(0xB5, 0x64, 0x2A), soft=(0xF4, 0xE4, 0xD8), panel=(0xFF, 0xFF, 0xFF))
DARK = Colours(accent=(0xD9, 0x83, 0x4A), soft=(0x3F, 0x2E, 0x24), panel=(0x2C, 0x2A, 0x27))

# The mask's face: four curves, from the left side round the top, the right side and the chin.
FACE: Sequence[Bezier] = (
    ((30, 56), (30, 46), (42, 41), (56, 41)),
    ((56, 41), (70, 41), (82, 46), (82, 56)),
    ((82, 56), (82, 67), (72, 76), (56, 76)),
    ((56, 76), (40, 76), (30, 67), (30, 56)),
)
SMILE: Bezier = ((48, 66), (52, 69), (60, 69), (64, 66))


def curve(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = 48) -> list[Point]:
    """Points along the cubic Bezier curve from ``p0`` to ``p3``, both ends included."""
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        points.append(
            (
                u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return points


class Canvas:
    """A drawing board for a picture ``width`` by ``height`` units that comes out ``scale`` pixels
    to the unit. A stroke is centred on its outline, as in SVG, and has round ends and corners.
    """

    def __init__(self, width: int, height: int, scale: int) -> None:
        self.output = (width * scale, height * scale)
        self.k = scale * SUPERSAMPLE  # drawing pixels to the unit
        self.image = Image.new("RGBA", (width * self.k, height * self.k), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)

    def _at(self, point: Point) -> Point:
        return (point[0] * self.k, point[1] * self.k)

    def rounded_rectangle(
        self, x: float, y: float, width: float, height: float, radius: float, **style: object
    ) -> None:
        """A rounded rectangle filled with ``fill`` and outlined with ``stroke`` ``line`` units
        thick, the outline half inside and half outside the rectangle.
        """
        fill, stroke, line = _style(style)
        half = line / 2
        for grow, radius_, colour in ((half, radius + half, stroke), (-half, radius - half, fill)):
            self.draw.rounded_rectangle(
                [
                    self._at((x - grow, y - grow)),
                    self._at((x + width + grow, y + height + grow)),
                ],
                radius=radius_ * self.k,
                fill=colour,
            )

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, **style: object) -> None:
        """An ellipse filled with ``fill`` and, if ``line`` is more than 0, outlined with
        ``stroke``.
        """
        fill, stroke, line = _style(style)
        half = line / 2
        if line:
            self._ellipse(cx, cy, rx + half, ry + half, stroke)
        self._ellipse(cx, cy, rx - half, ry - half, fill)

    def _ellipse(self, cx: float, cy: float, rx: float, ry: float, colour: Colour) -> None:
        left, top = self._at((cx - rx, cy - ry))
        right, bottom = self._at((cx + rx, cy + ry))
        self.draw.ellipse([left, top, right, bottom], fill=colour)

    def polygon(self, points: Sequence[Point], **style: object) -> None:
        """A closed shape filled with ``fill`` and outlined with ``stroke``."""
        fill, stroke, line = _style(style)
        drawn = [self._at(point) for point in points]
        self.draw.polygon(drawn, fill=fill)
        self._stroke(self.draw, [*drawn, drawn[0]], stroke, line * self.k, closed=True)

    def line(
        self, points: Sequence[Point], colour: Colour, width: float, opacity: float = 1.0
    ) -> None:
        """An open line through ``points``, ``width`` units thick, drawn at ``opacity`` (the
        whole line at once, so that its own overlaps do not show).
        """
        layer = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        drawn = [self._at(point) for point in points]
        colour_with_alpha = (*colour, round(255 * opacity))
        self._stroke(ImageDraw.Draw(layer), drawn, colour_with_alpha, width * self.k, closed=False)
        self.image.alpha_composite(layer)

    @staticmethod
    def _stroke(
        draw: ImageDraw.ImageDraw,
        points: Sequence[Point],
        colour: tuple[int, ...],
        width: float,
        *,
        closed: bool,
    ) -> None:
        draw.line(list(points), fill=colour, width=round(width), joint="curve")
        radius = width / 2
        for x, y in points[:1] if closed else [points[0], points[-1]]:  # round ends
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=colour)

    def finish(self) -> Image.Image:
        """The picture at its output size."""
        return self.image.resize(self.output, Image.Resampling.BOX)


def _style(style: dict[str, object]) -> tuple[Colour, Colour, float]:
    """The ``fill``, the ``stroke`` colour and the ``line`` width a shape was given."""
    fill, stroke, line = style["fill"], style.get("stroke", style["fill"]), style.get("line", 0)
    assert isinstance(fill, tuple) and isinstance(stroke, tuple) and isinstance(line, int | float)
    return fill, stroke, float(line)


def draw_mask(colours: Colours, scale: int) -> Image.Image:
    """The mask on a document, 112 by 88 units."""
    canvas = Canvas(112, 88, scale)
    canvas.rounded_rectangle(
        22, 6, 60, 76, 8, fill=colours.soft, stroke=colours.accent, line=2
    )  # the page
    canvas.line([(34, 24), (70, 24)], colours.accent, 2, opacity=0.5)  # two lines of text
    canvas.line([(34, 34), (62, 34)], colours.accent, 2, opacity=0.5)
    face: list[Point] = []
    for piece in FACE:
        face.extend(curve(*piece)[:-1])
    canvas.polygon(face, fill=colours.panel, stroke=colours.accent, line=2.4)
    canvas.ellipse(46, 55, 5, 3.5, fill=colours.accent)  # the eyes
    canvas.ellipse(66, 55, 5, 3.5, fill=colours.accent)
    canvas.line(curve(*SMILE), colours.accent, 2)
    return canvas.finish()


def draw_check(colours: Colours, scale: int) -> Image.Image:
    """A document with a round check mark on it, 64 by 64 units."""
    canvas = Canvas(64, 64, scale)
    canvas.rounded_rectangle(12, 6, 40, 52, 6, fill=colours.soft, stroke=colours.accent, line=2)
    canvas.line([(22, 30), (42, 30)], colours.accent, 2, opacity=0.5)
    canvas.line([(22, 38), (36, 38)], colours.accent, 2, opacity=0.5)
    canvas.ellipse(44, 46, 9, 9, fill=colours.panel, stroke=colours.accent, line=2)
    canvas.line([(40, 46), (43, 49), (48, 43)], colours.accent, 2)
    return canvas.finish()


# Each picture: its name and how it is drawn, for a colour set and a scale (1 or 2).
PICTURES: dict[str, Callable[[Colours, int], Image.Image]] = {
    "mask": draw_mask,
    "check": draw_check,
}
APPEARANCES = {"light": LIGHT, "dark": DARK}


def make_art(out_dir: Path) -> list[Path]:
    """Write every picture to ``out_dir`` (made if it is not there); return the files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, draw in PICTURES.items():
        for appearance, colours in APPEARANCES.items():
            for scale in (1, 2):
                path = out_dir / f"{name}-{appearance}{'@2x' if scale == 2 else ''}.png"
                draw(colours, scale).save(path, format="PNG", compress_level=9)
                written.append(path)
    return written


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) > 1:
        print(__doc__, file=sys.stderr)
        return 2
    out_dir = Path(arguments[0]) if arguments else DEFAULT_OUT
    for path in make_art(out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
