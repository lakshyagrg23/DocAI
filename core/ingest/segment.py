"""Clause segmentation: numbered clauses, sub-clauses, FAQ pairs, paragraphs, table rows (ingest.md §4).

Generic: nothing here knows about any particular document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core import config
from core.ingest.parse import Line, PageContent, Table
from core.ingest.spans import CWord, build_spans, clause_text
from core.models import Clause, Span

NUM = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})(?P<sep>[.)]?)\s+(?P<rest>\S.*)$")
ALPHA = re.compile(r"^\((?P<a>[a-z])\)\s+\S")
ROMAN = re.compile(r"^\((?P<r>i{1,3}|iv|v|vi{0,3}|ix|x)\)\s+\S")
KEYWORD = re.compile(r"^(?:Clause|Article|Para(?:graph)?|Section)\s+(?P<kw>\d+(?:\.\d+)*)\s*(?:[:)–—-]|\.(?=\s|$)|$)")
SCHED = re.compile(r"^(?:Schedule|Annexure|Appendix)\s+[IVX\d]+\b", re.IGNORECASE)
FAQ_Q = re.compile(r"^(?:Q\s?\d*[:.)]\s|Q\.\s|\d+\.\s*(?:What|Who|How|Can|Is|Are|When|Where|Why)\b)")
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
KIND_RULES = [  # first match wins; amendment first (substituted text is not a fee), penalty before fee
    ("amendment", r"\b(amend\w*|substitut\w*|supersed\w*|supersession)\b"),
    ("penalty", r"\b(penal\w*|late)\b"),
    ("fee", r"\b(fees?|charges?)\b"),
    ("eligibility", r"\b(age|aged|eligib\w*)\b"),
    ("rate", r"\b(interest|rate)\b"),
    ("definition", r"\bmeans\b"),
]


def classify_kind(heading_trail: str, text: str) -> str:
    """Keyword heuristic on the clause text; the heading trail is only a fallback (it carries the document title)."""
    for hay in (text.lower(), heading_trail.lower()):
        for kind, pat in KIND_RULES:
            if re.search(pat, hay):
                return kind
    return "other"


@dataclass
class _Open:
    path: str
    words: list[CWord] = field(default_factory=list)
    parent_id: str | None = None
    numbered: bool = False
    last_line: Line | None = None


class Segmenter:
    def __init__(self, doc_id: str, pages: list[PageContent]) -> None:
        self.doc_id = doc_id
        self.pages = pages
        self.clauses: list[Clause] = []
        self.spans: list[Span] = []
        self._ids: set[str] = set()
        self.cur: _Open | None = None
        self.heading = ""
        self.top: int | None = None
        self.base: str | None = None  # last numbered clause path (for sub-clauses)
        self.alpha: str | None = None  # last alpha sub-clause path
        self.last_alpha_letter = ""
        self.n_para: dict[int, int] = {}
        self.n_q: dict[int, int] = {}
        self.n_table = 0
        self.prev_item: str = ""  # "heading" | "text" | "table"
        self.prev_line: Line | None = None
        self.faq = sum(1 for p in pages for ln in p.lines if FAQ_Q.match(ln.text)) >= 2

    # ---- clause lifecycle -------------------------------------------------
    def _unique(self, clause_id: str) -> str:
        cid, n = clause_id, 2
        while cid in self._ids:
            cid = f"{clause_id}~{n}"
            n += 1
        return cid

    def _trail(self, path: str) -> str:
        return f"{self.heading} > {path}" if self.heading else path

    def flush(self) -> None:
        c, self.cur = self.cur, None
        if c is None or not c.words:
            return
        cid = self._unique(f"{self.doc_id}:{c.path}")
        self._ids.add(cid)
        trail = self._trail(c.path)
        text = clause_text(c.words)
        self.clauses.append(Clause(
            clause_id=cid, doc_id=self.doc_id, path=c.path, heading_trail=trail,
            kind=classify_kind(trail, text), text=text, page_start=c.words[0].page,
            page_end=c.words[-1].page, parent_id=c.parent_id, version_key=cid, ord=len(self.clauses)))
        self.spans.extend(build_spans(cid, self.doc_id, c.words))

    def _begin(self, path: str, ln: Line, parent_id: str | None = None, numbered: bool = False) -> None:
        self.flush()
        self.cur = _Open(path=path, parent_id=parent_id, numbered=numbered)
        self._append(ln)

    def _append(self, ln: Line) -> None:
        assert self.cur is not None
        self.cur.words.extend(CWord(w.text, w.bbox, ln.page_no, ln.idx) for w in ln.words)
        self.cur.last_line = ln

    # ---- numbering --------------------------------------------------------
    def _numbered_start(self, ln: Line) -> tuple[str, bool] | None:
        """Return (path, is_heading_like) if the line starts a numbered clause/heading, else None."""
        m = NUM.match(ln.text)
        if not m:
            k = KEYWORD.match(ln.text)
            return (k.group("kw"), False) if k else None
        first_rest = m.group("rest").split()[0].strip(".,;:").lower()
        rest = m.group("rest")
        if first_rest in MONTHS or not (rest[0].isupper() or rest[0] in "\"“"):
            return None
        parts = [int(x) for x in m.group("num").split(".")]
        if len(parts) == 1:
            if not m.group("sep") and not ln.bold:  # "7 EMIs" is text, not clause 7
                return None
            ok = self.top is None or self.top + 1 <= parts[0] <= self.top + 2
        else:
            ok = self.top is None or parts[0] in (self.top, self.top + 1)
        return (m.group("num"), ln.bold) if ok else None

    def _sub_start(self, ln: Line) -> str | None:
        """(a) / (i) sub-clause start. A roman-looking '(i)' right after '(h)' is alphabetic."""
        if self.cur is None or self.base is None:
            return None
        a, r = ALPHA.match(ln.text), ROMAN.match(ln.text)
        if r:
            letter = r.group("r")
            continues_alpha = (len(letter) == 1 and bool(self.last_alpha_letter)
                               and ord(letter) == ord(self.last_alpha_letter) + 1)
            if not continues_alpha:
                return f"{self.alpha or self.base}({letter})"
        if a:
            self.last_alpha_letter = a.group("a")
            self.alpha = f"{self.base}({a.group('a')})"
            return self.alpha
        return None

    # ---- main loop --------------------------------------------------------
    def _heading(self, ln: Line, number: str | None) -> None:
        self.flush()
        if number is not None:
            title = NUM.match(ln.text).group("rest") if NUM.match(ln.text) else ln.text
            self.heading = f"{number} {title}".strip()
            if "." not in number:
                self.top = int(number)
            self.base = self.alpha = None
        elif (self.prev_item == "heading" and self.prev_line is not None and self.prev_line.page_no == ln.page_no
              and abs(self.prev_line.font_size - ln.font_size) < 0.5):
            self.heading = f"{self.heading} {ln.text}"  # wrapped heading
        else:
            self.heading = ln.text
            if SCHED.match(ln.text):
                self.top = None
        self.prev_item, self.prev_line = "heading", ln

    def _para_break(self, ln: Line) -> bool:
        prev = self.cur.last_line if self.cur else None
        if prev is None:
            return True
        if prev.page_no != ln.page_no:
            return prev.text.rstrip().endswith((".", ";", ":", "?", "!", '"', "”")) or not ln.text[:1].islower()
        return ln.bbox[1] - prev.bbox[3] > config.PARA_GAP_FONT_RATIO * prev.font_size

    def _line(self, ln: Line) -> None:
        if self.faq and FAQ_Q.match(ln.text):
            self.n_q[ln.page_no] = n = self.n_q.get(ln.page_no, 0) + 1
            self._begin(f"p{ln.page_no}.q{n}", ln, numbered=True)  # Q+A always continues
        elif ln.bold:
            ns = self._numbered_start(ln)
            self._heading(ln, ns[0] if ns else None)
            return
        elif (ns := self._numbered_start(ln)) is not None:
            path = ns[0]
            self.top = int(path.split(".")[0])
            self.base, self.alpha, self.last_alpha_letter = path, None, ""
            parent = path.rsplit(".", 1)[0] if "." in path else None
            parent_id = f"{self.doc_id}:{parent}" if parent and f"{self.doc_id}:{parent}" in self._ids else None
            self._begin(path, ln, parent_id, numbered=True)
        elif (sub := self._sub_start(ln)) is not None:
            parent = self.alpha if sub != self.alpha and self.alpha else self.base
            self._begin(sub, ln, f"{self.doc_id}:{parent}" if parent else None, numbered=True)
        elif self.cur is not None and (self.cur.numbered or not self._para_break(ln)):
            self._append(ln)
        else:
            self.n_para[ln.page_no] = n = self.n_para.get(ln.page_no, 0) + 1
            self._begin(f"p{ln.page_no}.{n}", ln)
        self.prev_item, self.prev_line = "text", ln

    def _table(self, t: Table) -> None:
        self.flush()
        self.n_table += 1
        tn = self.n_table
        heading = self.prev_line.text if self.prev_line is not None and self.prev_item != "table" else self.heading
        tid = self._unique(f"{self.doc_id}:table{tn}")
        self._ids.add(tid)
        self.clauses.append(Clause(clause_id=tid, doc_id=self.doc_id, path=f"table{tn}", heading_trail=heading,
                                   kind="table", text="", page_start=t.page_no, page_end=t.page_no,
                                   version_key=tid, ord=len(self.clauses)))
        header = t.rows[0].cells
        for r, row in enumerate(t.rows):
            path = f"table{tn}.row{r}"
            cid = self._unique(f"{self.doc_id}:{path}")
            self._ids.add(cid)
            if r == 0:
                text = " | ".join(c for c in row.cells if c)
            else:
                text = " | ".join(f"{h}: {c}" if h else c for h, c in zip(header, row.cells, strict=False) if c)
            trail = f"{heading} > {path}" if heading else path
            self.clauses.append(Clause(
                clause_id=cid, doc_id=self.doc_id, path=path, heading_trail=trail,
                kind="table_header" if r == 0 else classify_kind(trail, text), text=text, page_start=t.page_no,
                page_end=t.page_no, parent_id=tid, version_key=cid, ord=len(self.clauses)))
            self.spans.append(Span(span_id=f"{cid}#s1", clause_id=cid, doc_id=self.doc_id, page=t.page_no,
                                   text=text, bboxes=[list(row.bbox)], char_start=0, char_end=len(text),
                                   is_table_row=True))
        self.prev_item = "table"

    def run(self) -> tuple[list[Clause], list[Span]]:
        for pc in self.pages:
            items: list[tuple[float, int, object]] = [(ln.bbox[1], 0, ln) for ln in pc.lines]
            items += [(t.bbox[1], 1, t) for t in pc.tables]
            for _, kind, obj in sorted(items, key=lambda x: (x[0], x[1])):
                if kind == 1:
                    self._table(obj)  # type: ignore[arg-type]
                else:
                    self._line(obj)  # type: ignore[arg-type]
        self.flush()
        return self.clauses, self.spans


def segment(doc_id: str, pages: list[PageContent]) -> tuple[list[Clause], list[Span]]:
    return Segmenter(doc_id, pages).run()
