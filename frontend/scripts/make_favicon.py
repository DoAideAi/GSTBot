"""Generate all app icons from the same nine-dot SVG used for the favicon.

Run from the repository root:

    backend/.venv/bin/python frontend/scripts/make_favicon.py

The SVG matches components/BrandMark.jsx. Reading its geometry and colours
keeps regeneration from bringing back the old receipt or robot artwork.
Pillow is already a backend dependency; no additional renderer is needed for
this mark's rectangles and circles.
"""

from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageDraw

PUBLIC = Path(__file__).resolve().parent.parent / "public"
SVG = ElementTree.parse(PUBLIC / "favicon.svg").getroot()
BACKGROUND = SVG.find("{http://www.w3.org/2000/svg}rect").attrib["fill"]
VIEWBOX = tuple(float(value) for value in SVG.attrib["viewBox"].split())
SS = 4


def draw_icon(px, opaque=False, inset=0):
    """Supersample the source mark, optionally on an OS-masked canvas."""
    assert VIEWBOX == (0, 0, 24, 24), "Review icon geometry if the source viewBox changes"
    n = px * SS
    icon = Image.new("RGBA", (n, n), BACKGROUND if opaque else (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    unit = n * (1 - 2 * inset) / VIEWBOX[2]
    offset = n * inset

    for shape in SVG:
        tag = shape.tag.rsplit("}", 1)[-1]
        fill = shape.attrib["fill"]
        if tag == "rect":
            x = offset + float(shape.get("x", 0)) * unit
            y = offset + float(shape.get("y", 0)) * unit
            width = float(shape.attrib["width"]) * unit
            height = float(shape.attrib["height"]) * unit
            draw.rounded_rectangle(
                (x, y, x + width - 1, y + height - 1),
                radius=float(shape.get("rx", 0)) * unit,
                fill=fill,
            )
        elif tag == "circle":
            x = offset + float(shape.attrib["cx"]) * unit
            y = offset + float(shape.attrib["cy"]) * unit
            radius = float(shape.attrib["r"]) * unit
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        else:
            raise ValueError(f"Unsupported SVG shape: {tag}")

    icon = icon.resize((px, px), Image.Resampling.LANCZOS)
    return icon.convert("RGB") if opaque else icon


def main():
    for size in (16, 32):
        draw_icon(size).save(PUBLIC / f"favicon-{size}x{size}.png", optimize=True)
    for size in (192, 512):
        draw_icon(size).save(PUBLIC / f"icon-{size}.png", optimize=True)

    # iOS supplies its own corner mask. Android's maskable variant keeps all
    # nine dots inside the central safe circle, even with a circular mask.
    draw_icon(180, opaque=True).save(PUBLIC / "apple-touch-icon.png", optimize=True)
    draw_icon(512, opaque=True, inset=0.125).save(PUBLIC / "icon-maskable-512.png", optimize=True)

    draw_icon(48).save(
        PUBLIC / "favicon.ico",
        format="ICO",
        sizes=[(48, 48), (32, 32), (16, 16)],
        append_images=[draw_icon(32), draw_icon(16)],
    )
    print("Generated browser, Apple, and installable app icons from favicon.svg")


if __name__ == "__main__":
    main()
