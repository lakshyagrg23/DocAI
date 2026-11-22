"""Parse a PDF with PyMuPDF: words -> lines (with font info), tables, header/footer removal (ingest.md §2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from core import config

BBox = tuple[float, float, float, float]
PAGE_RE = re.compile(r"\bPage\s+\d+\s+of\s+\d+\b", re.IGNORECASE)


@dataclass
class Word:
    text: str
    bbox: BBox


@dataclass
class Line:
    text: str
    bbox: BBox
    words: list[Word]
    font_size: float
    bold: bool
    page_no: int
    idx: int = 0  # line index within the page (unique per page)


@dataclass
class TableRow:
    cells: list[str]
    bbox: BBox


@dataclass
class Table:
    bbox: BBox
    rows: list[TableRow]
    page_no: int


@dataclass
class PageContent:
    page_no: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    is_ocr: bool = False
    ocr_conf: float | None = None


def _inside(x: float, y: float, b: BBox) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def _clean(s: str | None) -> str:
    return " ".join((s or "").split())


def page_needs_ocr(page: pymupdf.Page) -> bool:
    return len(page.get_text().strip()) < config.OCR_MIN_CHARS and bool(page.get_images())


def _font_spans(page: pymupdf.Page) -> list[tuple[BBox, float, bool]]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for sp in line["spans"]:
                if sp["text"].strip():
                    bold = bool(sp["flags"] & 16) or "bold" in sp["font"].lower()
                    out.append((tuple(sp["bbox"]), float(sp["size"]), bold))
    return out


def _extract_tables(page: pymupdf.Page, page_no: int, words: list[tuple]) -> list[Table]:
    """Rows come from tab.rows; cell text is rebuilt from the page words inside each cell box (extract() drops spaces)."""
    tables = []
    for t in page.find_tables().tables:
        rows = []
        for row in t.rows:
            texts = []
            for cell in row.cells:
                if cell is None:  # merged / missing cell
                    texts.append("")
                    continue
                inside = [w for w in words if _inside((w[0] + w[2]) / 2, (w[1] + w[3]) / 2, tuple(cell))]
                inside.sort(key=lambda w: (round(w[1]), w[0]))
                texts.append(_clean(" ".join(w[4] for w in inside)))
            if any(texts):
                rows.append(TableRow(cells=texts, bbox=tuple(row.bbox)))
        if rows:
            tables.append(Table(bbox=tuple(t.bbox), rows=rows, page_no=page_no))
    return tables


def parse_page(page: pymupdf.Page, page_no: int) -> PageContent:
    pc = PageContent(page_no=page_no, width=page.rect.width, height=page.rect.height)
    all_words = page.get_text("words", sort=True)
    pc.tables = _extract_tables(page, page_no, all_words)
    spans = _font_spans(page)
    groups: dict[tuple[int, int], list[tuple]] = {}
    for w in all_words:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if any(_inside(cx, cy, t.bbox) for t in pc.tables):
            continue
        groups.setdefault((w[5], w[6]), []).append(w)
    lines: list[Line] = []
    for ws in groups.values():
        ws.sort(key=lambda w: w[0])
        words = [Word(w[4], (w[0], w[1], w[2], w[3])) for w in ws]
        sizes, bolds = [], []
        for w in ws:
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            for bb, size, bold in spans:
                if _inside(cx, cy, bb):
                    sizes.append(size)
                    bolds.append(bold)
                    break
        bbox = (min(w.bbox[0] for w in words), min(w.bbox[1] for w in words),
                max(w.bbox[2] for w in words), max(w.bbox[3] for w in words))
        lines.append(Line(text=" ".join(w.text for w in words), bbox=bbox, words=words,
                          font_size=max(sizes) if sizes else 10.0,
                          bold=bool(bolds) and sum(bolds) / len(bolds) >= 0.5, page_no=page_no))
    lines.sort(key=lambda ln: (round(ln.bbox[1]), ln.bbox[0]))
    for i, ln in enumerate(lines):
        ln.idx = i
    pc.lines = lines
    return pc


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def strip_running(pages: list[PageContent]) -> None:
    """Drop 'Page x of y' lines and lines repeated in the top/bottom zone on >= HEADER_FOOTER_REPEAT of pages."""
    def in_zone(ln: Line, pc: PageContent) -> bool:
        z = config.HEADER_FOOTER_ZONE * pc.height
        return ln.bbox[1] < z or ln.bbox[3] > pc.height - z

    counts: dict[str, int] = {}
    for pc in pages:
        for key in {_norm(ln.text) for ln in pc.lines if in_zone(ln, pc)}:
            counts[key] = counts.get(key, 0) + 1
    repeated = {k for k, n in counts.items()
                if len(pages) >= 2 and n / len(pages) >= config.HEADER_FOOTER_REPEAT}
    for pc in pages:
        pc.lines = [ln for ln in pc.lines
                    if not (in_zone(ln, pc) and (PAGE_RE.search(ln.text) or _norm(ln.text) in repeated))]


def parse_pdf(path: Path | str, skip_ocr_pages: bool = True) -> list[PageContent]:
    """Parse every page. Pages that need OCR come back empty with is_ocr=True when skip_ocr_pages (M9 fills them)."""
    pages: list[PageContent] = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            if page_needs_ocr(page) and skip_ocr_pages:
                pages.append(PageContent(page_no=i, width=page.rect.width, height=page.rect.height, is_ocr=True))
            else:
                pages.append(parse_page(page, i))
    strip_running(pages)
    return pages
