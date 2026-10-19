"""Draws The MASK's icon: a pale eye mask on a dark rounded square, as a Mac app icon.

    uv run python packaging/make_icon.py [out_dir]

writes ``themask-1024.png``, the picture, and ``themask.icns``, the same picture at every size a
Mac app icon needs (16 to 1024 pixels, and the @2x forms), built from it by macOS's ``iconutil``.
The default folder is ``icon/`` beside this file, which is where Briefcase looks
(``icon = "packaging/icon/themask"`` in pyproject.toml). Both files are committed, so the build
does not need to run this: run it again only to change the picture.

The same picture comes out every time. Only Pillow and ``iconutil`` are needed. There is no
``__init__.py`` here on purpose: a package called ``packaging`` would hide the one pip and pytest
import.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

NAME = "themask"
DEFAULT_OUT = Path(__file__).resolve().parent / "icon"

SIZE = 1024  # the picture, in pixels
SUPERSAMPLE = 2  # everything is drawn at twice the size and reduced, which smooths the edges

# Apple's grid for a Mac app icon: the rounded square is 824 pixels of the 1024, in the middle,
# and the margin holds its soft shadow.
BODY = 824
BODY_RADIUS = 185

TOP = (46, 58, 78)  # the square, lighter at the top...
BOTTOM = (18, 23, 34)  # ...and darker at the bottom
MASK = (244, 240, 230)  # the mask: warm white

Point = tuple[float, float]

# The right half of the mask, from the middle of its top edge to the middle of its bottom edge,
# in pixels from the centre of the mask (x to the right, y down): each piece is the four points
# of a cubic Bezier curve, and each one starts where the one before ended. The top edge rises to
# the tip of the wing, the outer edge comes round the cheek, and the lower edge goes in to the
# notch for the nose. The mask is as high as it is, so that its middle is the picture's middle.
HALF_OUTLINE: Sequence[tuple[Point, Point, Point, Point]] = (
    ((0, -96), (110, -128), (225, -156), (322, -136)),
    ((322, -136), (352, -48), (318, 80), (214, 134)),
    ((214, 134), (150, 164), (80, 122), (0, 74)),
)
# The eye holes: an ellipse (half width, half height) tilted so that the outer corner is the
# higher one, with the centre of the right one; the left one is its mirror image.
EYE_CENTRE: Point = (152, 0)
EYE_RADII: Point = (92, 50)
EYE_TILT_DEGREES = -14


def bezier(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = 48) -> list[Point]:
    """Points along the cubic curve from ``p0`` to ``p3``, ``p0`` included and ``p3`` not."""
    points = []
    for i in range(steps):
        t = i / steps
        u = 1 - t
        points.append(
            (
                u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return points


def mask_outline() -> list[Point]:
    """The mask as a closed polygon, in pixels from its centre."""
    right = [point for piece in HALF_OUTLINE for point in bezier(*piece)]
    right.append(HALF_OUTLINE[-1][3])
    left = [(-x, y) for x, y in reversed(right[1:-1])]
    return right + left


def eye_outline(mirrored: bool) -> list[Point]:
    """One eye hole as a polygon, in pixels from the centre of the mask: the right one, or the
    left one, its mirror image.
    """
    tilt = math.radians(EYE_TILT_DEGREES)
    points = []
    for i in range(96):
        angle = 2 * math.pi * i / 96
        x = EYE_RADII[0] * math.cos(angle)
        y = EYE_RADII[1] * math.sin(angle)
        x, y = x * math.cos(tilt) - y * math.sin(tilt), x * math.sin(tilt) + y * math.cos(tilt)
        x += EYE_CENTRE[0]
        y += EYE_CENTRE[1]
        points.append((-x if mirrored else x, y))
    return points


def on_canvas(points: Sequence[Point]) -> list[Point]:
    """``points``, given from the centre of the picture, as positions on the drawing board."""
    middle = SIZE * SUPERSAMPLE / 2
    return [(middle + x * SUPERSAMPLE, middle + y * SUPERSAMPLE) for x, y in points]


def shadow_of(shape: Image.Image, down: int, blur: int, opacity: float) -> Image.Image:
    """A black layer in the form of ``shape`` (a mask), moved ``down`` pixels, blurred by ``blur``
    and ``opacity`` (0 to 1) dense. The numbers are for the finished picture, not the drawing.
    """
    moved = ImageChops.offset(shape, 0, down * SUPERSAMPLE)
    soft = moved.filter(ImageFilter.GaussianBlur(blur * SUPERSAMPLE))
    layer = Image.new("RGBA", shape.size, (0, 0, 0, 0))
    layer.paste((0, 0, 0, round(255 * opacity)), mask=soft)
    return layer


def draw_master() -> Image.Image:
    """The picture of the icon: ``SIZE`` pixels square, RGBA, with a transparent margin."""
    size = SIZE * SUPERSAMPLE
    margin = (SIZE - BODY) / 2 * SUPERSAMPLE

    # The dark square: a gradient from top to bottom, cut to a rounded square.
    body = Image.new("L", (size, size), 0)
    ImageDraw.Draw(body).rounded_rectangle(
        (margin, margin, size - margin, size - margin), radius=BODY_RADIUS * SUPERSAMPLE, fill=255
    )
    ramp = Image.linear_gradient("L").resize((size, size))  # black at the top, white at the foot
    gradient = Image.composite(
        Image.new("RGB", (size, size), BOTTOM), Image.new("RGB", (size, size), TOP), ramp
    )

    # The mask, with the holes of its eyes cut out.
    glyph = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(glyph)
    draw.polygon(on_canvas(mask_outline()), fill=255)
    for mirrored in (False, True):
        draw.polygon(on_canvas(eye_outline(mirrored)), fill=0)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(shadow_of(body, down=12, blur=14, opacity=0.35))
    canvas.paste(gradient, mask=body)
    canvas.alpha_composite(shadow_of(glyph, down=10, blur=9, opacity=0.43))
    canvas.paste(Image.new("RGBA", (size, size), (*MASK, 255)), mask=glyph)
    return canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def write_iconset(master: Image.Image, folder: Path) -> None:
    """The ten files of a Mac app icon in ``folder`` (named ``*.iconset``), from ``master``."""
    for points in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{points}x{points}{'@2x' if scale == 2 else ''}.png"
            pixels = points * scale
            master.resize((pixels, pixels), Image.Resampling.LANCZOS).save(folder / name)


def make_icon(out_dir: Path) -> tuple[Path, Path]:
    """Write the picture and the ``.icns`` to ``out_dir``; return their paths (png, icns)."""
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        raise SystemExit("iconutil was not found: the .icns can only be built on a Mac.")
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{NAME}-{SIZE}.png"
    icns = out_dir / f"{NAME}.icns"
    master = draw_master()
    master.save(png)
    with tempfile.TemporaryDirectory() as scratch:
        iconset = Path(scratch) / f"{NAME}.iconset"  # iconutil wants the folder to end like this
        iconset.mkdir()
        write_iconset(master, iconset)
        subprocess.run(
            [iconutil, "--convert", "icns", "--output", str(icns), str(iconset)],
            check=True,
            capture_output=True,
        )
    return png, icns


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) > 1:
        print(__doc__, file=sys.stderr)
        return 2
    out_dir = Path(arguments[0]) if arguments else DEFAULT_OUT
    for path in make_icon(out_dir):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
