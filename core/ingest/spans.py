"""Sentence splitting and span construction over a clause's words (ingest.md §4 Spans)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.ingest.parse import BBox
from core.models import Span

ABBREV = {"rs.", "no.", "p.a.", "i.e.", "e.g.", "viz.", "ltd.", "cl.", "w.e.f.", "etc.", "vs.", "inc.", "co.",
          "sr.", "dr.", "mr.", "mrs.", "ms."}
NUMBERLIKE = re.compile(r"^(\d+(\.\d+)*\.?|Q\d*\.?)$")
INITIAL = re.compile(r"^[A-Z]\.$")
QUOTES = "\"'“”‘’()"


@dataclass
class CWord:
    """A word inside a clause, remembering its page and line so bboxes can be grouped per line."""

    text: str
    bbox: BBox
    page: int
    line: int


def ends_sentence(word: str, nxt: str | None) -> bool:
    if nxt is None:
        return False
    w = word.rstrip(QUOTES)
    if not w or w[-1] not in ".;:?!":
        return False
    base = w.rstrip(":;")
    if base.lower() in ABBREV or INITIAL.match(base) or NUMBERLIKE.match(base):
        return False
    return nxt[:1] in "\"“(" or nxt.lstrip(QUOTES)[:1].isupper()


def _union(rects: list[BBox]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def clause_text(words: list[CWord]) -> str:
    return " ".join(w.text for w in words)


def build_spans(clause_id: str, doc_id: str, words: list[CWord]) -> list[Span]:
    """Split into sentence spans (never across pages). One bbox per line covered."""
    spans: list[Span] = []
    start, offset = 0, 0
    starts = []  # char offset of each word in the clause text
    for w in words:
        starts.append(offset)
        offset += len(w.text) + 1
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is not None and not (nxt.page != w.page or ends_sentence(w.text, nxt.text)):
            continue
        chunk = words[start:i + 1]
        by_line: dict[tuple[int, int], list[BBox]] = {}
        for c in chunk:
            by_line.setdefault((c.page, c.line), []).append(c.bbox)
        n = len(spans) + 1
        spans.append(Span(span_id=f"{clause_id}#s{n}", clause_id=clause_id, doc_id=doc_id, page=chunk[0].page,
                          text=clause_text(chunk), bboxes=[_union(r) for r in by_line.values()],
                          char_start=starts[start], char_end=starts[i] + len(w.text)))
        start = i + 1
    return spans
