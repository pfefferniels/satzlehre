# /// script
# requires-python = ">=3.10"
# dependencies = ["verovio"]
# ///
"""Print selected scores as A4 handouts to ../pdf.

Printing goes through headless Chrome: Verovio draws figured-bass accidentals with an embedded web font,
which SVG converters such as rsvg-convert ignore.
"""

import html
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import verovio

SCORES = Path(__file__).resolve().parent
PDF = SCORES.parent / "pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MEI = {"mei": "http://www.music-encoding.org/ns/mei"}

# Wide bars and systems spread over the page, for handouts the students write into.
ROOM_TO_WRITE = {"spacingLinear": 0.5, "justifyVertically": True, "justificationMaxVertical": 0.6}

HANDOUTS = {
    "corelli-op3-1-grave": {},
    "corelli-op3-1-grave-aufgabe": ROOM_TO_WRITE,
    "muffat-sonata-2-grave": {},
}

# A4 in tenths of a millimetre at 100 percent.
A4 = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "pageMarginTop": 120,
    "pageMarginBottom": 320,
    "pageMarginLeft": 150,
    "pageMarginRight": 150,
}
# Verovio lays out in fixed units, so printing smaller means a larger page, shrunk to A4 by the browser.
PRINT_SIZE = 0.8
# Empty staves stay visible: some handouts are for writing into.
OPTIONS = {"breaks": "auto", "header": "auto", "footer": "none", "condense": "none"} | {
    key: round(value / PRINT_SIZE) for key, value in A4.items()
}

PAGE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 0; }}
  body {{ margin: 0; }}
  .page {{ width: 210mm; height: 297mm; position: relative; break-after: page; }}
  .page:last-child {{ break-after: auto; }}
  .page svg {{ width: 210mm; height: 297mm; display: block; }}
  .source {{
    position: absolute; left: 15mm; right: 15mm; bottom: 10mm;
    font: 7.5pt/1.35 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; color: #4b5563;
  }}
</style>
</head>
<body>
{pages}
</body>
</html>
"""


def source_note(mei: Path) -> str:
    """The encoding note and the bibliographic source from the MEI header, for the page footer."""
    head = ET.parse(mei).getroot().find("mei:meiHead", MEI)
    parts = [head.findtext(".//mei:notesStmt/mei:annot", "", MEI), head.findtext(".//mei:sourceDesc//mei:bibl", "", MEI)]
    return " ".join(html.escape(" ".join(part.split())) for part in parts if part)


def score_pages(mei: Path, overrides: dict) -> list[str]:
    toolkit = verovio.toolkit()
    toolkit.setOptions(OPTIONS | overrides)
    if not toolkit.loadFile(str(mei)):
        raise ValueError(f"Verovio could not load {mei}")
    return [toolkit.renderToSVG(n) for n in range(1, toolkit.getPageCount() + 1)]


def handout_html(mei: Path, overrides: dict) -> str:
    first, *rest = score_pages(mei, overrides)
    footer = f'<p class="source">{source_note(mei)}</p>'
    pages = [f'<section class="page">{first}{footer}</section>', *(f'<section class="page">{svg}</section>' for svg in rest)]
    return PAGE.format(pages="\n".join(pages))


def write_pdf(name: str) -> Path:
    target = PDF / f"{name}.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / f"{name}.html"
        page.write_text(handout_html(SCORES / f"{name}.mei", HANDOUTS[name]), encoding="utf-8")
        subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={target}", page.as_uri()],
            check=True,
            capture_output=True,
        )
    return target


if __name__ == "__main__":
    PDF.mkdir(exist_ok=True)
    print(*map(write_pdf, sys.argv[1:] or HANDOUTS), sep="\n")
