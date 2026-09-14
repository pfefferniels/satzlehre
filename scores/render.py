# /// script
# requires-python = ">=3.10"
# dependencies = ["verovio"]
# ///
"""Render every MEI example in this directory to an SVG in ../img."""

from pathlib import Path

import verovio

SCORES = Path(__file__).resolve().parent
IMAGES = SCORES.parent / "img"

OPTIONS = {
    "adjustPageHeight": True,
    "adjustPageWidth": True,
    "breaks": "none",
    "footer": "none",
    "header": "none",
    "pageMarginBottom": 20,
    "pageMarginLeft": 20,
    "pageMarginRight": 20,
    "pageMarginTop": 20,
    "spacingLinear": 0.5,
    "svgViewBox": True,
}


def render_svg(mei: Path) -> str:
    toolkit = verovio.toolkit()
    toolkit.setOptions(OPTIONS)
    if not toolkit.loadFile(str(mei)):
        raise ValueError(f"Verovio could not load {mei}")
    return toolkit.renderToSVG(1)


def write_svg(mei: Path) -> Path:
    target = IMAGES / f"{mei.stem}.svg"
    target.write_text(render_svg(mei), encoding="utf-8")
    return target


if __name__ == "__main__":
    print(*map(write_svg, sorted(SCORES.glob("*.mei"))), sep="\n")
