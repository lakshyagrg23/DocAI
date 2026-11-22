"""Locate a regular + bold TTF that contains the rupee sign (U+20B9) and register it with reportlab."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

RUPEE = 0x20B9
WIN = Path("C:/Windows/Fonts")
CANDIDATES: list[tuple[Path, Path]] = [
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    (Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"), Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")),
    (WIN / "segoeui.ttf", WIN / "segoeuib.ttf"),
    (WIN / "arial.ttf", WIN / "arialbd.ttf"),
]


def _has_rupee(path: Path) -> bool:
    try:
        return bool(pymupdf.Font(fontfile=str(path)).has_glyph(RUPEE))
    except (RuntimeError, ValueError, OSError):
        return False


def register() -> tuple[str, str]:
    """Return (regular, bold) reportlab font names. Never falls back to 'Rs.': fails loudly instead."""
    for regular, bold in CANDIDATES:
        if regular.exists() and bold.exists() and _has_rupee(regular) and _has_rupee(bold):
            pdfmetrics.registerFont(TTFont("DocSans", str(regular)))
            pdfmetrics.registerFont(TTFont("DocSans-Bold", str(bold)))
            pdfmetrics.registerFontFamily("DocSans", normal="DocSans", bold="DocSans-Bold",
                                          italic="DocSans", boldItalic="DocSans-Bold")
            return "DocSans", "DocSans-Bold"
    raise RuntimeError("No TTF with U+20B9 found. Install fonts-dejavu-core or Noto Sans and add it to CANDIDATES.")
