"""Quote exactness: stored span text equals the PDF text at the span's boxes (eval.md gate)."""
from test_ingest import corpus, ingested  # noqa: F401  (fixtures: build PDFs, ingest them with stub models)

from scripts import quote_check


def test_every_digital_span_matches_its_pdf(ingested):  # noqa: F811
    conn, _, _ = ingested
    ids = [r["span_id"] for r in conn.execute("SELECT span_id FROM spans WHERE ocr_conf IS NULL")]
    assert len(ids) > 40
    assert [i for i in ids if quote_check.span_matches(conn, i) is not True] == []


def test_a_changed_quote_is_caught_and_ocr_spans_are_skipped(ingested):  # noqa: F811
    conn, _, _ = ingested
    conn.execute("UPDATE spans SET text=replace(text,'500','5000') WHERE span_id='D1:8.1#s1'")
    assert quote_check.span_matches(conn, "D1:8.1#s1") is False
    ocr = conn.execute("SELECT span_id FROM spans WHERE ocr_conf IS NOT NULL LIMIT 1").fetchone()
    assert ocr is None or quote_check.span_matches(conn, ocr["span_id"]) is None
    ans = {"claims": [{"span_ids": ["D1:8.1#s1", "D1:3.1#s1"]}], "disagreements": [], "calculation": None}
    checked, bad = quote_check.mismatches(conn, ans)
    assert checked == 2 and bad == ["D1:8.1#s1"]
