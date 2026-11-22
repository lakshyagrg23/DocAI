"""Page image with highlight rectangles (ui.md §Chat/evidence). Pure rendering: no Streamlit, no DB writes."""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from core import config

ROOT = Path(__file__).resolve().parents[2]
YELLOW = (255, 214, 0, 90)
ORANGE = (255, 120, 0, 100)


def pdf_path(conn: sqlite3.Connection, doc_id: str) -> Path | None:
    """Where the original PDF lives: the path recorded by the latest ingest job, else uploads/, else corpus/pdfs/."""
    job = conn.execute("SELECT path FROM ingest_jobs WHERE doc_id=? ORDER BY created_at DESC LIMIT 1", (doc_id,)).fetchone()
    doc = conn.execute("SELECT filename FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    candidates = [Path(job["path"])] if job else []
    if doc and doc["filename"]:
        candidates += [config.DATA_DIR / "uploads" / doc["filename"], ROOT / "corpus" / "pdfs" / doc["filename"]]
    return next((p for p in candidates if p.exists()), None)


def render(path: Path | str, page_no: int, bboxes: list[list[float]] | None = None, dpi: int = 110,
           ocr: bool = False) -> bytes:
    """PNG bytes of page `page_no` (1-based) with semi-transparent rectangles over `bboxes` (PDF points)."""
    with pymupdf.open(path) as pdf:
        pix = pdf[page_no - 1].get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    scale = dpi / 72
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for x0, y0, x1, y1 in bboxes or []:
        draw.rectangle([x0 * scale, y0 * scale, x1 * scale, y1 * scale], fill=ORANGE if ocr else YELLOW)
    out = io.BytesIO()
    Image.alpha_composite(img, layer).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def page_count(path: Path | str) -> int:
    with pymupdf.open(path) as pdf:
        return len(pdf)
