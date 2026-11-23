"""OCR for image-only pages (ingest.md §3). One Tesseract pass per page gives words, boxes and confidence.

Boxes are scaled back to PDF page units (72 dpi) so segmentation, highlighting and citations work exactly as for
digital pages. `ocr_conf` is Tesseract's mean word confidence, 0-100. Tables on scanned pages are not rebuilt (limitation).
"""
from __future__ import annotations

import os
import re
import shutil
from functools import lru_cache
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image, ImageOps

from core import config
from core.ingest.parse import Line, PageContent, Word

_WIN_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


class OcrUnavailable(RuntimeError):
    """Tesseract is not installed or has none of the wanted languages."""


@lru_cache(maxsize=1)
def _find_tesseract() -> str:
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract") or (str(_WIN_DEFAULT) if _WIN_DEFAULT.exists() else "")
    if not cmd:
        raise OcrUnavailable("Tesseract is not installed (apt install tesseract-ocr, or winget install UB-Mannheim.TesseractOCR)")
    pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd


@lru_cache(maxsize=1)
def usable_lang() -> str:
    """The wanted OCR_LANG minus packs that are not installed (so a missing Hindi pack does not block English)."""
    _find_tesseract()
    have = set(pytesseract.get_languages(config=""))
    langs = [lang for lang in config.OCR_LANG.split("+") if lang in have]
    if not langs:
        raise OcrUnavailable(f"none of the OCR languages {config.OCR_LANG!r} are installed (have {sorted(have)})")
    return "+".join(langs)


def available() -> bool:
    try:
        usable_lang()
    except (OcrUnavailable, pytesseract.TesseractError, OSError):
        return False
    return True


def preprocess(img: Image.Image) -> Image.Image:
    """Grayscale + autocontrast. Deskew is skipped: Tesseract copes with the small skews of real scans (ingest.md §3)."""
    return ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)


_UPPER_L = re.compile(r"(?<=[A-Z])l(?=s?[.,;:]?$)")  # EMls -> EMIs (capital I read as lowercase l after capitals)


def fix_word(text: str) -> str:
    """Repair the two most common Tesseract confusions for capital I; anything else is left exactly as read."""
    if text == "|":
        return "I"
    return _UPPER_L.sub("I", text) if len(text) > 2 and text[:2].isupper() else text


_UNIT = {"lakh", "lakhs", "crore", "crores"}


def fix_rupee(texts: list[str], confs: list[float], i: int) -> str:
    """The English model has no rupee glyph and reads it as a '2'. Repair only the safe case: a low-confidence
    number starting with 2 right before lakh/crore ('225 lakh' -> '25 lakh' with the sign restored)."""
    t = texts[i]
    nxt = texts[i + 1].strip(".,;").lower() if i + 1 < len(texts) else ""
    if t.isdigit() and t.startswith("2") and len(t) > 1 and confs[i] < config.OCR_RUPEE_FIX_CONF and nxt in _UNIT:
        return "₹" + t[1:]
    return t


def words_to_lines(data: dict[str, list], scale: float, page_no: int) -> tuple[list[Line], float | None]:
    """Group pytesseract `image_to_data` rows into lines (block, paragraph, line) and return them with the mean confidence."""
    groups: dict[tuple[int, int, int], list[Word]] = {}
    confs: list[float] = []
    texts = [fix_word((raw or "").strip()) for raw in data["text"]]
    all_conf = [float(c) for c in data["conf"]]
    for i in range(len(texts)):
        text = fix_rupee(texts, all_conf, i)
        conf = all_conf[i]
        if not text or conf < 0:
            continue
        x, y, w, h = (data[k][i] for k in ("left", "top", "width", "height"))
        bbox = (x * scale, y * scale, (x + w) * scale, (y + h) * scale)
        groups.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(Word(text, bbox))
        confs.append(conf)
    lines: list[Line] = []
    for words in groups.values():
        words.sort(key=lambda w: w.bbox[0])
        bbox = (min(w.bbox[0] for w in words), min(w.bbox[1] for w in words),
                max(w.bbox[2] for w in words), max(w.bbox[3] for w in words))
        lines.append(Line(text=" ".join(w.text for w in words), bbox=bbox, words=words,
                          font_size=bbox[3] - bbox[1], bold=False, page_no=page_no))
    lines.sort(key=lambda ln: (round(ln.bbox[1]), ln.bbox[0]))
    for idx, ln in enumerate(lines):
        ln.idx = idx
    return lines, (sum(confs) / len(confs) if confs else None)


def ocr_page(page: pymupdf.Page, page_no: int) -> PageContent:
    lang = usable_lang()
    pix = page.get_pixmap(dpi=config.OCR_DPI)
    img = preprocess(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    lines, conf = words_to_lines(data, 72.0 / config.OCR_DPI, page_no)
    return PageContent(page_no=page_no, width=page.rect.width, height=page.rect.height, lines=lines,
                       is_ocr=True, ocr_conf=conf)
