"""OCR: line grouping, word repair, and (when Tesseract is installed) the scanned demo FAQ."""
from pathlib import Path

import pytest

from core.ingest import ocr
from core.ingest.parse import parse_pdf
from core.ingest.segment import segment

D6 = Path("corpus/pdfs/D6_faq_scanned.pdf")


def test_fix_word():
    assert ocr.fix_word("|") == "I"
    assert ocr.fix_word("EMls") == "EMIs"
    assert ocr.fix_word("EMls.") == "EMIs."
    assert ocr.fix_word("EMl") == "EMI"
    assert ocr.fix_word("Salaried") == "Salaried"
    assert ocr.fix_word("lakh") == "lakh"
    assert ocr.fix_word("IL") == "IL"


def test_words_to_lines_scales_and_averages():
    data = {"text": ["Hello", "world", "", "Next"], "conf": ["90", "80", "-1", "70"],
            "left": [100, 300, 0, 100], "top": [100, 100, 0, 400], "width": [100, 100, 0, 80], "height": [30, 30, 0, 30],
            "block_num": [1, 1, 1, 1], "par_num": [1, 1, 1, 2], "line_num": [1, 1, 0, 1]}
    lines, conf = ocr.words_to_lines(data, 0.5, 1)
    assert [ln.text for ln in lines] == ["Hello world", "Next"]
    assert lines[0].bbox == (50.0, 50.0, 200.0, 65.0)
    assert conf == pytest.approx(80.0)


@pytest.mark.skipif(not (ocr.available() and D6.exists()), reason="needs Tesseract and the generated corpus")
def test_scanned_faq_becomes_clauses():
    pages = parse_pdf(D6)
    assert pages[0].is_ocr and pages[0].ocr_conf and pages[0].ocr_conf > 70
    clauses, spans = segment("D6", pages)
    by = {c.clause_id: c.text for c in clauses}
    assert "21" in by["D6:p1.q1"] and "60" in by["D6:p1.q1"]
    assert "documents" in by["D6:p1.q5"].lower()
    assert all(1 <= s.page <= 1 and s.bboxes for s in spans)


def test_fix_rupee_only_when_low_confidence_before_a_unit():
    t = ["up", "to", "225", "lakh."]
    assert ocr.fix_rupee(t, [90, 90, 73, 90], 2) == "₹25"
    assert ocr.fix_rupee(t, [90, 90, 95, 90], 2) == "225"  # confident read: leave it
    assert ocr.fix_rupee(["in", "2025", "June"], [90, 96, 90], 1) == "2025"  # not before lakh/crore
