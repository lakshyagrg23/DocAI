"""M2 ingest tests: parse + segment + spans + index + pipeline. Offline (fake embeddings, no model service)."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from core import db
from core.ingest import ocr, pipeline, register, store
from core.ingest.parse import Line, PageContent, Word, parse_pdf
from core.ingest.segment import segment
from core.ingest.spans import CWord, build_spans, ends_sentence
from core.llm.client import ModelUnavailable
from core.models import Clause, RegisterMeta, Span
from core.retrieval import index

ROOT = Path(__file__).resolve().parents[1]
PDFS = ROOT / "corpus" / "pdfs"
DIM = 32


@pytest.fixture(scope="module", autouse=True)
def corpus():
    if not (PDFS / "D1_loan_agreement.pdf").exists():
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location("corpus_generate", ROOT / "corpus" / "generate.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()


def fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).normal(size=DIM)
        out.append((v / np.linalg.norm(v)).tolist())
    return out


class StubClient:
    """Stands in for ModelClient: no LLM (heuristic metadata), deterministic fake embeddings."""

    def __init__(self, meta: RegisterMeta | None = None):
        self.meta = meta

    def chat_json(self, messages, model_cls, max_tokens=900):
        if self.meta is None:
            raise ModelUnavailable("no llm in tests")
        return self.meta

    def embed(self, texts, batch_size=32):
        return fake_embed(texts)

    def rerank(self, query, passages):
        """Fake cross-encoder: share of query tokens present in the passage."""
        q = set(index.tokenize(query))
        return [len(q & set(index.tokenize(p))) / (len(q) or 1) for p in passages]


@pytest.fixture(scope="module")
def parsed():
    out = {}
    for p in sorted(PDFS.glob("D[1-5]*.pdf")):
        did = p.name[:2]
        pages = parse_pdf(p)
        clauses, spans = segment(did, pages)
        out[did] = (pages, {c.clause_id: c for c in clauses}, spans)
    return out


# ---- real corpus -----------------------------------------------------------

def test_d1_clause_7_2_spans_pages_3_to_4(parsed):
    c = parsed["D1"][1]["D1:7.2"]
    assert (c.page_start, c.page_end) == (3, 4)
    assert "4%" in c.text and c.text.startswith("7.2 ")
    assert "exclusive of applicable taxes" in c.text
    spans = [s for s in parsed["D1"][2] if s.clause_id == "D1:7.2"]
    assert [s.page for s in spans] == [3, 4]
    assert c.heading_trail == "7 Prepayment and Foreclosure > 7.2"


def test_d1_clause_8_1_has_rupee_500(parsed):
    c = parsed["D1"][1]["D1:8.1"]
    assert "₹500" in c.text and c.kind == "penalty"
    assert [s.span_id for s in parsed["D1"][2] if s.clause_id == "D1:8.1"] == ["D1:8.1#s1"]


def test_d1_numbered_clauses_complete(parsed):
    ids = set(parsed["D1"][1])
    expected = {"1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "5.1", "5.2", "6.1", "6.2", "7.1", "7.2", "8.1",
                "8.2", "9.1", "10.1"}
    assert {f"D1:{p}" for p in expected} <= ids


def test_d2_table_rows_are_one_span_each(parsed):
    clauses, spans = parsed["D2"][1], parsed["D2"][2]
    rows = [s for s in spans if s.is_table_row]
    assert len(rows) == 6  # header + 5 data rows
    late = clauses["D2:table1.row2"]
    assert "Late payment fee" in late.text and "₹750" in late.text and late.text.startswith("Charge: ")
    assert [s.span_id for s in spans if s.clause_id == late.clause_id] == ["D2:table1.row2#s1"]
    assert clauses["D2:table1.row3"].text.count("₹590") == 1
    assert clauses["D2:table1.row0"].kind == "table_header"


def test_amendment_docs_are_single_clauses_with_quoted_span(parsed):
    d3 = parsed["D3"][1]
    assert {"D3:1", "D3:2"} <= set(d3)
    s = [x for x in parsed["D3"][2] if x.clause_id == "D3:1"]
    assert len(s) == 2 and "3%" in s[1].text and s[1].text.startswith('"7.2 ')
    assert "D4:7" not in parsed["D4"][1] and "D4:7.2" not in parsed["D4"][1]  # 'Clause 7.2 of the...' is text
    assert "No prepayment charge" in parsed["D4"][1]["D4:1"].text


def test_d5_numbered_paragraphs(parsed):
    c = parsed["D5"][1]
    assert {"D5:1", "D5:2", "D5:3"} <= set(c) and "₹600" in c["D5:1"].text


def test_no_clause_path_is_a_date_fragment(parsed):
    for _, clauses, _ in parsed.values():
        for c in clauses.values():
            assert c.path not in {"15", "10", "1", "2025"} or c.text.split()[1][0].isupper()
            assert not any(m in c.text.split()[:2] for m in ("January", "April", "December"))


def test_running_footers_removed(parsed):
    for _, clauses, _ in parsed.values():
        assert not any("Page " in c.text and " of " in c.text for c in clauses.values())
        assert not any("Kestrel Finance Ltd. ·" in c.text for c in clauses.values())


def test_every_span_has_bbox_inside_page(parsed):
    for did, (pages, _, spans) in parsed.items():
        size = {p.page_no: (p.width, p.height) for p in pages}
        assert spans
        for s in spans:
            assert s.bboxes, s.span_id
            w, h = size[s.page]
            for x0, y0, x1, y1 in s.bboxes:
                assert 0 <= x0 < x1 <= w + 0.5 and 0 <= y0 < y1 <= h + 0.5, (did, s.span_id)


def test_span_text_matches_pdf_words_at_bbox(parsed):
    """Quote exactness: every word of a non-table span is a word PyMuPDF finds inside the span's boxes."""
    for did, (_, _, spans) in parsed.items():
        pdf = next(PDFS.glob(f"{did}_*.pdf"))
        with pymupdf.open(pdf) as doc:
            for s in spans:
                if s.is_table_row:
                    continue
                page = doc[s.page - 1]
                found = set()
                for b in s.bboxes:
                    found |= {w[4] for w in page.get_text("words", clip=pymupdf.Rect(b))}
                assert set(s.text.split()) <= found, s.span_id


def test_span_offsets_index_into_clause_text(parsed):
    for _, clauses, spans in parsed.values():
        for s in spans:
            if not s.is_table_row:
                assert clauses[s.clause_id].text[s.char_start:s.char_end] == s.text


# ---- synthetic segmentation (no demo ids/strings) ---------------------------

def page_of(specs, page_no=1):
    """specs: (text, bold) or (text, bold, gap). gap = vertical space above the line (default: same paragraph)."""
    lines, y = [], 100.0
    for i, spec in enumerate(specs):
        text, bold, gap = (*spec, 5.0)[:3]
        y += (10 + gap) if i else 0
        words, x = [], 50.0
        for w in text.split():
            words.append(Word(w, (x, y, x + 5 * len(w), y + 10)))
            x += 5 * len(w) + 3
        lines.append(Line(text, (50, y, x, y + 10), words, 10.5, bold, page_no, i))
    return PageContent(page_no, 600, 800, lines=lines)


def seg(specs_per_page):
    pages = [page_of(s, i) for i, s in enumerate(specs_per_page, 1)]
    clauses, spans = segment("X", pages)
    return {c.clause_id: c for c in clauses}, spans


def test_date_and_number_lines_do_not_start_clauses():
    c, _ = seg([[("4. Fees", True), ("4.1 The fee is payable monthly, due from", False),
                 ("15 January 2024 onwards for all borrowers.", False),
                 ("6 EMIs are required before prepayment.", False), ("4.2 Another rule applies.", False)]])
    assert set(c) == {"X:4.1", "X:4.2"}
    assert "15 January 2024" in c["X:4.1"].text and "6 EMIs" in c["X:4.1"].text


def test_subclauses_alpha_and_roman():
    c, _ = seg([[("5. Terms", True), ("5.1 The borrower shall:", False), ("(a) pay on time;", False),
                 ("(b) give notice; and", False), ("(i) first roman item", False), ("(ii) second roman item", False),
                 ("5.2 Next.", False)]])
    assert {"X:5.1", "X:5.1(a)", "X:5.1(b)", "X:5.1(b)(i)", "X:5.1(b)(ii)", "X:5.2"} <= set(c)
    assert c["X:5.1(a)"].parent_id == "X:5.1" and c["X:5.1(b)(i)"].parent_id == "X:5.1(b)"


def test_alpha_i_after_h_is_alphabetic():
    specs = [("2. Items", True), ("2.1 List:", False)]
    specs += [(f"({ch}) item {ch}", False) for ch in "abcdefghi"]
    c, _ = seg([specs])
    assert "X:2.1(i)" in c and "X:2.1(h)(i)" not in c


def test_clause_continues_across_pages():
    c, spans = seg([[("1. A", True), ("1.1 First part of a rule that goes on", False)],
                    [("and finishes on the next page. Then more text.", False), ("1.2 Next.", False)]])
    assert (c["X:1.1"].page_start, c["X:1.1"].page_end) == (1, 2)
    assert {s.page for s in spans if s.clause_id == "X:1.1"} == {1, 2}


def test_faq_pairs_become_clauses():
    c, spans = seg([[("FAQ TITLE", True), ("Q1. Who can apply?", True), ("Adults can apply.", False),
                     ("Q2. What is the limit?", True), ("Up to ten units.", False)]])
    assert {"X:p1.q1", "X:p1.q2"} <= set(c)
    assert "Adults" in c["X:p1.q1"].text and "ten units" in c["X:p1.q2"].text
    assert [s.text for s in spans if s.clause_id == "X:p1.q1"] == ["Q1. Who can apply?", "Adults can apply."]


def test_unnumbered_paragraphs_split_on_gaps():
    c, _ = seg([[("Heading line", True), ("first paragraph line one", False), ("still first paragraph", False),
                 ("second paragraph here", False, 12.0)]])
    assert set(c) == {"X:p1.1", "X:p1.2"}
    assert c["X:p1.1"].text == "first paragraph line one still first paragraph"


def test_heading_only_lines_are_not_clauses_and_set_trail():
    c, _ = seg([[("7. Prepayment and Foreclosure", True), ("7.1 Some rule.", False)]])
    assert set(c) == {"X:7.1"} and c["X:7.1"].heading_trail == "7 Prepayment and Foreclosure > 7.1"


def test_duplicate_paths_get_unique_ids():
    c, _ = seg([[("1. Part A", True), ("1.1 One.", False), ("SCHEDULE I", True), ("1. Part B", True),
                 ("1.1 Another one.", False)]])
    assert "X:1.1" in c and "X:1.1~2" in c


# ---- spans -----------------------------------------------------------------

def cw(text, page=1, line=0):
    return [CWord(w, (i * 10.0, 0, i * 10.0 + 9, 10), page, line) for i, w in enumerate(text.split())]


@pytest.mark.parametrize("word,nxt,expected", [
    ("Loan.", "The", True), ("Ltd.", "Mumbai", False), ("No.", "5", False), ("p.a.", "Interest", False),
    ("1.", "With", False), ("A.", "Kumar", False), ("following:", '"7.2', True), ("Rs.", "500", False),
    ("loan,", "The", False), ('Loan."', "Next", True), ("done.", "next", False), ("clause?", "Yes", True),
    ("No.:", "KF/2024", False),
])
def test_ends_sentence(word, nxt, expected):
    assert ends_sentence(word, nxt) is expected


def test_build_spans_never_crosses_pages_and_keeps_offsets():
    words = cw("Rule one applies. Rule two", page=1) + cw("continues here.", page=2)
    spans = build_spans("X:1", "X", words)
    assert [s.page for s in spans] == [1, 1, 2]
    text = " ".join(w.text for w in words)
    assert all(text[s.char_start:s.char_end] == s.text for s in spans)
    assert [s.span_id for s in spans] == ["X:1#s1", "X:1#s2", "X:1#s3"]


# ---- register ---------------------------------------------------------------

def test_register_helpers():
    assert register.make_doc_id("D3_amendment_1.pdf", "abc") == "D3"
    assert register.make_doc_id("My file.pdf", "deadbeefcafe") == "Udeadbe"
    assert register.normalise_date("15 January 2024") == "2024-01-15"
    assert register.normalise_date("June 2025") == "2025-06-01"
    assert register.normalise_date("03/04/2025") == "2025-04-03"  # DMY
    assert register.normalise_date("nonsense") is None
    assert register.ref_variants("KF/PLA/2024") == ["KF/PLA/2024", "kf/pla/2024", "kfpla2024"]


def test_heuristic_meta_reads_reference_and_dates():
    text = "AMENDMENT No. 1 TO LOAN\nReference No.: KF/PLA/2024/AMD-1 · Dated: 10 March 2025 · Effective: 1 April 2025\n"
    m = register.heuristic_meta(text)
    assert m.ref_no == "KF/PLA/2024/AMD-1" and m.doc_type == "amendment"
    assert register.normalise_date(m.issue_date) == "2025-03-10" and register.normalise_date(m.effective_date) == "2025-04-01"


def test_llm_meta_is_verified_against_page_text():
    text = "LOAN AGREEMENT\nReference No.: AB/12/2024\nDated: 1 May 2024\n"
    wrong = RegisterMeta(title="Loan Agreement", doc_type="agreement", ref_no="ZZ/99/9999", issue_date="1 May 2024")
    meta, src = register.extract_meta(text, "x.pdf", StubClient(wrong))
    assert src == "llm" and meta.ref_no == "AB/12/2024"  # invented ref replaced by the one on the page
    meta, src = register.extract_meta(text, "x.pdf", StubClient(None))
    assert src == "heuristic" and meta.ref_no == "AB/12/2024"


def test_effective_date_falls_back_to_issue_then_today():
    from datetime import date
    m = RegisterMeta(title="T", issue_date="1 May 2024")
    assert register.build_document("U1", Path("a.pdf"), "s", m).effective_date == "2024-05-01"
    d = register.build_document("U1", Path("a.pdf"), "s", RegisterMeta(title="T"), today=date(2026, 1, 2))
    assert d.effective_date == "2026-01-02" and "defaulted" in d.status_detail


# ---- index ------------------------------------------------------------------

def test_make_windows_splits_long_clause_at_span_boundaries_with_overlap():
    spans = [Span(span_id=f"X:1#s{i}", clause_id="X:1", doc_id="X", page=1, text=" ".join(["word"] * 100) + ".",
                  bboxes=[[0, 0, 1, 1]]) for i in range(1, 7)]
    clause = Clause(clause_id="X:1", doc_id="X", path="1", heading_trail="H > 1", text="t", page_start=1, page_end=1)
    ws = index.make_windows(clause, spans)
    assert len(ws) > 1 and all(w.text.startswith("H > 1\n") for w in ws)
    covered = [sid for w in ws for sid in w.span_ids]
    assert set(covered) == {s.span_id for s in spans}
    assert ws[0].span_ids[-1] in ws[1].span_ids or index.approx_tokens(spans[0].text) > 50  # overlap or too big


def test_tokenizer_keeps_numbers_and_currency():
    # spec regex: decimals stay whole ("13.5", "7.2"), the % sign becomes its own token (same on query and document side)
    assert index.tokenize("Fee ₹750 at 13.5% under 7.2") == ["fee", "₹750", "at", "13.5", "%", "under", "7.2"]


@pytest.fixture()
def ingested(tmp_path):
    conn = db.init_db(tmp_path / "corpus.db")
    client = StubClient()
    for p in sorted(PDFS.glob("D*.pdf")):
        pipeline.enqueue(p, conn, start_worker=False)
    pipeline.run_pending(conn, client, tmp_path)
    return conn, tmp_path, client


def test_pipeline_ingests_digital_docs_and_ocrs_scanned(ingested):
    conn, _, _ = ingested
    status = {d.doc_id: d for d in db.list_documents(conn)}
    assert [status[f"D{i}"].status for i in range(1, 6)] == ["Ready"] * 5
    assert status["D1"].pages == 6 and status["D1"].effective_date == "2024-01-15"
    assert status["D3"].effective_date == "2025-04-01" and status["D1"].ref_no == "KF/PLA/2024"
    assert status["D6"].has_ocr
    if not ocr.available():  # parked until Tesseract is installed
        assert status["D6"].status == "Queued" and status["D6"].status_detail.startswith("needs OCR")
        return
    assert status["D6"].status == "Ready" and status["D6"].effective_date == "2025-06-01"
    q1 = conn.execute("SELECT text FROM clauses WHERE clause_id='D6:p1.q1'").fetchone()["text"]
    assert "21" in q1 and "60" in q1
    assert all(r["ocr_conf"] is not None for r in conn.execute("SELECT ocr_conf FROM spans WHERE doc_id='D6'"))
    assert conn.execute("SELECT is_ocr FROM pages WHERE doc_id='D6'").fetchone()["is_ocr"] == 1


def test_scanned_doc_is_parked_without_tesseract(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ocr_available", lambda: False)
    conn = db.init_db(tmp_path / "c.db")
    job = pipeline.enqueue(PDFS / "D6_faq_scanned.pdf", conn, start_worker=False)
    assert pipeline.process_job(conn, job, StubClient(), tmp_path) == "needs_ocr"
    d = db.get_document(conn, conn.execute("SELECT doc_id FROM documents").fetchone()["doc_id"])
    assert d.status == "Queued" and d.status_detail.startswith("needs OCR") and d.effective_date is None


def test_dense_rows_align_with_windows_and_bm25(ingested):
    conn, tmp, _ = ingested
    idx = index.load_index(tmp)
    n = conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
    assert idx.dense.shape == (n, DIM) and len(idx.window_ids) == n
    rows = conn.execute("SELECT window_id,row_idx FROM windows ORDER BY row_idx").fetchall()
    assert [r["row_idx"] for r in rows] == list(range(n))
    assert [r["window_id"] for r in rows] == idx.window_ids
    # row_idx -> vector really is that window's text embedding
    w = conn.execute("SELECT text,row_idx FROM windows WHERE window_id='D1:8.1@w1'").fetchone()
    assert np.allclose(idx.dense[w["row_idx"]], fake_embed([w["text"]])[0], atol=1e-2)
    scores = idx.bm25.get_scores(index.tokenize("late payment fee ₹750"))
    top = idx.window_ids[int(np.argmax(scores))]
    assert top == "D2:table1.row2@w1"


def test_reingest_is_idempotent_and_remove_doc_shrinks_index(ingested):
    conn, tmp, client = ingested
    before = conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
    n_clauses = conn.execute("SELECT COUNT(*) FROM clauses WHERE doc_id='D1'").fetchone()[0]
    store.delete_doc_content(conn, "D1")
    index.remove_doc(conn, "D1", tmp)
    assert conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0] < before
    assert index.load_index(tmp).dense.shape[0] == conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
    pipeline.process_job(conn, conn.execute("SELECT job_id FROM ingest_jobs WHERE doc_id='D1'").fetchone()[0], client, tmp)
    assert conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM clauses WHERE doc_id='D1'").fetchone()[0] == n_clauses
    assert index.load_index(tmp).dense.shape[0] == before


def test_enqueue_same_file_twice_returns_same_job(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    a = pipeline.enqueue(PDFS / "D2_schedule_of_charges.pdf", conn, start_worker=False)
    b = pipeline.enqueue(PDFS / "D2_schedule_of_charges.pdf", conn, start_worker=False)
    assert a == b and len(db.list_documents(conn)) == 1


def test_failed_job_marks_document_failed(tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    job = pipeline.enqueue(bad, conn, start_worker=False)
    pipeline.run_pending(conn, StubClient(), tmp_path)
    doc = db.list_documents(conn)[0]
    assert doc.status == "Failed" and doc.status_detail
    assert conn.execute("SELECT state FROM ingest_jobs WHERE job_id=?", (job,)).fetchone()[0] == "failed"
