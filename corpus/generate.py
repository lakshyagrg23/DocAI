"""Build the six demo PDFs into corpus/pdfs/ (demo-corpus.md). Run: python corpus/generate.py"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from corpus import fonts, texts

OUT_DIR = Path(__file__).resolve().parent / "pdfs"
SEED = 7


def _numbered_canvas(footer_name: str):
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._saved: list[dict] = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self.setFont("DocSans", 8.5)
                self.drawCentredString(A4[0] / 2, 1.0 * cm, f"{footer_name} · Page {self._pageNumber} of {total}")
                super().showPage()
            super().save()

    return NumberedCanvas


def build_pdf(path: Path, pages: list[texts.Page], footer_name: str) -> None:
    reg, bold = fonts.register()
    body = ParagraphStyle("body", fontName=reg, fontSize=10.5, leading=15, spaceAfter=6)
    head = ParagraphStyle("head", parent=body, fontName=bold, fontSize=12, leading=16, spaceBefore=8)
    title = ParagraphStyle("title", parent=head, fontSize=14, leading=18, spaceAfter=8)
    cell = ParagraphStyle("cell", parent=body, spaceAfter=0, leading=13)
    cellb = ParagraphStyle("cellb", parent=cell, fontName=bold)

    flow: list = []
    for i, page in enumerate(pages):
        if i:
            flow.append(PageBreak())
        for block in page:
            kind = block[0]
            if kind == "title":
                flow.append(Paragraph(block[1], title))
            elif kind == "h":
                flow.append(Paragraph(block[1], head))
            elif kind == "p":
                flow.append(Paragraph(block[1], body))
            elif kind == "table":
                rows, widths = block[1], block[2]
                data = [[Paragraph(c, cellb if r == 0 else cell) for c in row] for r, row in enumerate(rows)]
                t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, "#444444"),
                                       ("BACKGROUND", (0, 0), (-1, 0), "#E8E8E8"),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
                flow += [Spacer(1, 6), t, Spacer(1, 8)]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm, title=path.stem, author=footer_name)
    doc.build(flow, canvasmaker=_numbered_canvas(footer_name))


def scan_pdf(src: Path, dst: Path) -> None:
    """Rasterise at 200 dpi, rotate/noise/blur/JPEG, then rebuild an image-only PDF (no text layer)."""
    rng = np.random.default_rng(SEED)
    out = pymupdf.open()
    with pymupdf.open(src) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img = img.rotate(0.7, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
            arr = np.asarray(img, dtype=np.float32) + rng.normal(0, 6, (img.height, img.width, 1))
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=buf.getvalue())
    out.save(dst)
    out.close()


def verify(pdfs: dict[str, Path]) -> None:
    def pages(name: str) -> list[str]:
        with pymupdf.open(pdfs[name]) as d:
            return [p.get_text() for p in d]

    d1, d2 = pages("D1_loan_agreement.pdf"), pages("D2_schedule_of_charges.pdf")
    assert len(d1) == 6, f"D1 should have 6 pages, has {len(d1)}"
    assert any("₹" in t for t in d1) and any("₹" in t for t in d2), "rupee sign missing from D1/D2 text layer"
    assert "7.2 A prepayment charge of 4%" in d1[2] and "7.2 A prepayment" not in d1[3], "7.2 must start on p.3"
    assert d1[3].lstrip().startswith("The prepayment charge shall be paid"), "7.2 must continue on p.4"
    assert "₹500" in d1[3], "D1 8.1 fee missing"
    for name, expect in [("D3_amendment_1.pdf", 1), ("D4_amendment_2.pdf", 1), ("D5_fcb_circular.pdf", 1)]:
        assert len(pages(name)) == expect, f"{name} page count"
    for name in pdfs:
        for n, t in enumerate(pages(name), 1):
            if not name.startswith("D6"):
                assert f"Page {n} of {len(pages(name))}" in t, f"{name} footer missing on p.{n}"
    d6 = pages("D6_faq_scanned.pdf")
    assert len(d6) == 1 and all(t.strip() == "" for t in d6), "D6 must have no text layer"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs: dict[str, Path] = {}
    for name, (pages, footer) in texts.FILES.items():
        path = OUT_DIR / name
        if name.startswith("D6"):
            tmp = OUT_DIR / "_d6_digital.pdf"
            build_pdf(tmp, pages, footer)
            scan_pdf(tmp, path)
            tmp.unlink()
        else:
            build_pdf(path, pages, footer)
        pdfs[name] = path
    verify(pdfs)
    for name, p in pdfs.items():
        print(f"ok  {p.relative_to(OUT_DIR.parent.parent)}  ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
