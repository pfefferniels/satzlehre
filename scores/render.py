# /// script
# requires-python = ">=3.10"
# dependencies = ["verovio"]
# ///
"""Render every MEI example in this directory to an SVG in ../img.

An <annot type="box" plist="…"> frames the notes it lists in red and fades the rest of the example.
"""

import operator
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import reduce
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

MEI = {"mei": "http://www.music-encoding.org/ns/mei"}
SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

STAFF_SPACE = 180  # Verovio's SVG units at the default scale
FADE_OPACITY = 0.75
# Verovio's stylesheet sets stroke: currentColor on every rect, so colour goes through `color`.
FRAME = {"fill": "none", "stroke": "currentColor", "color": "#dc2626", "stroke-width": "50"}
UNSTROKED = {"stroke-width": "0"}


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    def __or__(self, other: "Box") -> "Box":
        return Box(
            min(self.left, other.left),
            min(self.top, other.top),
            max(self.right, other.right),
            max(self.bottom, other.bottom),
        )

    def padded(self, margin: float) -> "Box":
        return Box(self.left - margin, self.top - margin, self.right + margin, self.bottom + margin)

    def to_svg(self, attributes: dict[str, str]) -> ET.Element:
        geometry = {
            "x": f"{self.left:.0f}",
            "y": f"{self.top:.0f}",
            "width": f"{self.right - self.left:.0f}",
            "height": f"{self.bottom - self.top:.0f}",
        }
        return ET.Element(f"{SVG}rect", geometry | attributes)


EVERYWHERE = Box(-1e5, -1e5, 1e5, 1e5)


def boxed_passages(mei: Path) -> list[list[str]]:
    annots = ET.parse(mei).iterfind(".//mei:annot[@type='box']", MEI)
    return [[ref.removeprefix("#") for ref in annot.get("plist").split()] for annot in annots]


def rect_box(rect: ET.Element) -> Box:
    x, y, width, height = (float(rect.get(key)) for key in ("x", "y", "width", "height"))
    return Box(x, y, x + width, y + height)


def is_bounding_box(g: ET.Element) -> bool:
    return "bounding-box" in g.get("class", "")


def bounding_rects(group: ET.Element) -> list[ET.Element]:
    """The non-empty rects Verovio draws with svgBoundingBoxes anywhere inside a group."""
    return [
        rect
        for g in group.iter(f"{SVG}g")
        if is_bounding_box(g)
        for rect in g.iterfind(f"{SVG}rect")
        if float(rect.get("width")) or float(rect.get("height"))
    ]


def own_rect(group: ET.Element) -> ET.Element:
    return next(rect for g in group.iterfind(f"{SVG}g") if is_bounding_box(g) for rect in g.iterfind(f"{SVG}rect"))


def enclosing_staff(parents: dict[ET.Element, ET.Element], element: ET.Element) -> ET.Element:
    while element.get("class") != "staff":
        element = parents[element]
    return element


def passage_box(svg: ET.Element, note_ids: list[str]) -> Box:
    """The notes' extent, stretched vertically to cover the staves they stand on."""
    notes = [svg.find(f".//{SVG}g[@id='{note_id}']") for note_id in note_ids]
    if None in notes:
        raise ValueError(f"box refers to missing notes: {note_ids}")
    parents = {child: parent for parent in svg.iter() for child in parent}
    music = reduce(operator.or_, map(rect_box, (r for note in notes for r in bounding_rects(note))))
    staves = reduce(operator.or_, (rect_box(own_rect(enclosing_staff(parents, note))) for note in notes))
    return Box(music.left, min(music.top, staves.top), music.right, max(music.bottom, staves.bottom))


def focus_layer(boxes: list[Box]) -> ET.Element:
    """A white veil with holes where the boxes are, and a red frame around each hole."""
    layer = ET.Element(f"{SVG}g", {"class": "focus"})
    mask = ET.SubElement(layer, f"{SVG}mask", {"id": "focus"})
    mask.append(EVERYWHERE.to_svg({"fill": "white"} | UNSTROKED))
    mask.extend(box.to_svg({"fill": "black"} | UNSTROKED) for box in boxes)
    veil = {"fill": "white", "fill-opacity": str(FADE_OPACITY), "mask": "url(#focus)"}
    layer.append(EVERYWHERE.to_svg(veil | UNSTROKED))
    layer.extend(box.to_svg(FRAME) for box in boxes)
    return layer


def with_focus(svg: str, boxes: list[Box]) -> str:
    page = ET.fromstring(svg)
    page.find(f".//{SVG}g[@class='page-margin']").append(focus_layer(boxes))
    return ET.tostring(page, encoding="unicode")


def render_svg(mei: Path, **overrides) -> str:
    toolkit = verovio.toolkit()
    toolkit.setOptions(OPTIONS | overrides)
    if not toolkit.loadFile(str(mei)):
        raise ValueError(f"Verovio could not load {mei}")
    svg = toolkit.renderToSVG(1)
    passages = boxed_passages(mei)
    if not passages:
        return svg
    toolkit.setOptions({"svgBoundingBoxes": True})
    measured = ET.fromstring(toolkit.renderToSVG(1))
    boxes = [passage_box(measured, ids).padded(0.8 * STAFF_SPACE) for ids in passages]
    return with_focus(svg, boxes)


def write_svg(mei: Path) -> Path:
    target = IMAGES / f"{mei.stem}.svg"
    target.write_text(render_svg(mei), encoding="utf-8")
    return target


if __name__ == "__main__":
    print(*map(write_svg, sorted(SCORES.glob("*.mei"))), sep="\n")
