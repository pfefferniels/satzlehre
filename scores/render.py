# /// script
# requires-python = ">=3.10"
# dependencies = ["verovio"]
# ///
"""Render every MEI example in this directory to an SVG in ../img, long pieces in several excerpts.

An <annot type="box" plist="…"> frames the notes it lists in red and fades the rest of the example.
A timed rendering marks every note with its onset and offset in quarter notes from the start of the piece
(data-on, data-off), so that js/aligned-score.js can play a recording from the note clicked.
"""

import operator
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from functools import reduce
from itertools import chain
from pathlib import Path
from xml.dom import minidom

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


@dataclass(frozen=True)
class Rendering:
    """How a piece appears on the slides: whole as <stem>.svg, and by bar range as <stem>-1.svg, <stem>-2.svg, …"""

    whole: bool = True
    excerpts: tuple[str, ...] = ()
    staves: tuple[str, ...] = ()  # only these staves; all if empty
    options: dict = field(default_factory=dict)
    timed: bool = False


# Systems of about two bars on a tall page, so that all of them land on the one page render_svg draws.
# A fixed page width lets Verovio justify the last system of a bar range too.
NARROW_SYSTEMS = {
    "breaks": "auto",
    "pageWidth": 2000,
    "pageHeight": 20000,
    "adjustPageWidth": False,
    "minLastJustification": 0,
}

# One width and spacing in proportion to duration, so that stacked on a slide the examples line up beat by beat.
STEP_BY_STEP = NARROW_SYSTEMS | {"pageWidth": 1400, "spacingLinear": 0.05, "spacingNonLinear": 1.0}

RENDERINGS = {
    "artusi-seconda-fermarsi": Rendering(excerpts=("1-2",)),
    "artusi-settima-grave-fermarsi": Rendering(excerpts=("1-2",)),
    "corelli-op3-1-grave": Rendering(
        whole=False, excerpts=("1-4", "5-8", "9-12", "13-16", "17-19", "9-10"), options=NARROW_SYSTEMS, timed=True
    ),
    "corelli-op3-1-grave-aufgabe": Rendering(staves=("1",), options=NARROW_SYSTEMS | {"pageWidth": 2600}),
    "corelli-op3-1-grave-reduktion": Rendering(options=NARROW_SYSTEMS | {"pageWidth": 4200}),
    "corelli-op3-1-grave-reduktion-kadenzen": Rendering(options=NARROW_SYSTEMS | {"pageWidth": 4200}),
    "corelli-op3-1-grave-reduktion-ligatur": Rendering(whole=False, excerpts=("8-9",), options=NARROW_SYSTEMS),
    "doppia-zwei-schritte": Rendering(options=STEP_BY_STEP),
    "doppia-vier-schritte": Rendering(options=STEP_BY_STEP),
    "muffat-sonata-2-grave": Rendering(whole=False, excerpts=("1-4",)),
}


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


def belongs_to(element: minidom.Element, staves: tuple[str, ...]) -> bool:
    if element.tagName in ("staff", "staffDef"):
        return element.getAttribute("n") in staves
    placed_on = element.getAttribute("staff").split()
    return not placed_on or any(n in staves for n in placed_on)


def with_staves(mei: Path, staves: tuple[str, ...]) -> str:
    """The MEI with only the given staves and the control events placed on them."""
    document = minidom.parse(str(mei))
    for element in [e for e in document.getElementsByTagName("*") if not belongs_to(e, staves)]:
        element.parentNode.removeChild(element)
    if len(staves) == 1:
        for group in document.getElementsByTagName("staffGrp"):
            group.setAttribute("symbol", "none")
    return document.toxml()


def duration(event: ET.Element) -> Fraction:
    """In quarter notes; grace notes take no time."""
    if event.get("grace") or not event.get("dur"):
        return Fraction(0)
    dots = int(event.get("dots", 0))
    return Fraction(4, int(event.get("dur"))) * (2 - Fraction(1, 2**dots))


def layer_events(container: ET.Element):
    """Notes, chords, rests and spaces in the order they sound, looking into beams."""
    for child in container:
        tag = child.tag.removeprefix(f"{{{MEI['mei']}}}")
        if tag in ("note", "chord", "rest", "space"):
            yield child
        elif tag == "beam":
            yield from layer_events(child)


def note_times(mei: Path) -> dict[str, tuple[Fraction, Fraction]]:
    """Onset and offset of every note, in quarter notes from the start, for pieces in one metre without upbeat."""
    root = ET.parse(mei).getroot()
    meter = next(e for e in root.iter() if e.get("meter.count") or e.get("count"))
    count, unit = (int(meter.get(f"meter.{key}") or meter.get(key)) for key in ("count", "unit"))
    bar = Fraction(4 * count, unit)
    times = {}
    for n, measure in enumerate(root.iterfind(".//mei:measure", MEI)):
        for layer in measure.iterfind(".//mei:layer", MEI):
            onset = n * bar
            for event in layer_events(layer):
                offset = onset + duration(event)
                notes = [event] if event.tag.endswith("note") else event.iterfind("mei:note", MEI)
                for note in notes:
                    times[note.get("{http://www.w3.org/XML/1998/namespace}id")] = (onset, offset)
                onset = offset
    return times


def with_times(svg: str, times: dict[str, tuple[Fraction, Fraction]]) -> str:
    page = ET.fromstring(svg)
    for note in page.iterfind(f".//{SVG}g[@class='note']"):
        onset, offset = times[note.get("id")]
        note.set("data-on", f"{float(onset):g}")
        note.set("data-off", f"{float(offset):g}")
    return ET.tostring(page, encoding="unicode")


def render_svg(mei: Path, measures: str | None = None, staves: tuple[str, ...] = (), **overrides) -> str:
    """Render the example as one SVG page, if given only the bar range `measures` ("5-8") and the `staves`."""
    toolkit = verovio.toolkit()
    toolkit.setOptions(OPTIONS | overrides)
    loaded = toolkit.loadData(with_staves(mei, staves)) if staves else toolkit.loadFile(str(mei))
    if not loaded:
        raise ValueError(f"Verovio could not load {mei}")
    if measures:
        toolkit.select({"measureRange": measures})
        toolkit.redoLayout()
    svg = toolkit.renderToSVG(1)
    passages = boxed_passages(mei)
    if not passages:
        return svg
    toolkit.setOptions({"svgBoundingBoxes": True})
    measured = ET.fromstring(toolkit.renderToSVG(1))
    boxes = [passage_box(measured, ids).padded(0.8 * STAFF_SPACE) for ids in passages]
    return with_focus(svg, boxes)


def write_image(mei: Path, name: str, rendering: Rendering, measures: str | None = None) -> Path:
    target = IMAGES / name
    svg = render_svg(mei, measures, rendering.staves, **rendering.options)
    if rendering.timed:
        svg = with_times(svg, note_times(mei))
    target.write_text(svg, encoding="utf-8")
    return target


def write_images(mei: Path) -> list[Path]:
    rendering = RENDERINGS.get(mei.stem, Rendering())
    whole = [write_image(mei, f"{mei.stem}.svg", rendering)] if rendering.whole else []
    excerpts = [
        write_image(mei, f"{mei.stem}-{n}.svg", rendering, measures) for n, measures in enumerate(rendering.excerpts, 1)
    ]
    return whole + excerpts


if __name__ == "__main__":
    print(*chain.from_iterable(map(write_images, sorted(SCORES.glob("*.mei")))), sep="\n")
