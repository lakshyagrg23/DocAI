import importlib.util
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
PDFS = ROOT / "corpus" / "pdfs"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module", autouse=True)
def corpus():
    if not (PDFS / "D1_loan_agreement.pdf").exists():
        sys.path.insert(0, str(ROOT))
        _load("corpus_generate", "corpus/generate.py").main()


def text(name: str) -> list[str]:
    with pymupdf.open(PDFS / name) as d:
        return [p.get_text() for p in d]


def test_six_pdfs_exist():
    names = sorted(p.name for p in PDFS.glob("D*.pdf"))
    assert len(names) == 6 and names[0].startswith("D1") and names[-1].startswith("D6")


def test_rupee_is_extractable():
    assert any("₹" in t for t in text("D1_loan_agreement.pdf"))
    assert any("₹" in t for t in text("D2_schedule_of_charges.pdf"))


def test_d1_clause_7_2_spans_pages_3_and_4():
    p = text("D1_loan_agreement.pdf")
    assert len(p) == 6
    assert "7.2 A prepayment charge of 4%" in p[2]
    assert p[3].lstrip().startswith("The prepayment charge shall be paid")
    assert "8.1" in p[3] and "₹500" in p[3]


def test_d6_is_scanned_without_text_layer():
    with pymupdf.open(PDFS / "D6_faq_scanned.pdf") as d:
        assert len(d) == 1
        assert d[0].get_text().strip() == ""
        assert d[0].get_images()


def test_footers_present_on_digital_docs():
    assert "Financial Conduct Board · Page 1 of 1" in text("D5_fcb_circular.pdf")[0]
    assert "Kestrel Finance Ltd. · Page 6 of 6" in text("D1_loan_agreement.pdf")[5]


def test_only_fictional_orgs():
    for p in PDFS.glob("D*.pdf"):
        for t in text(p.name):
            assert "Reserve Bank" not in t and "SEBI" not in t


def test_qa_yaml_loadable_and_well_formed():
    spec = importlib.util.spec_from_file_location("evalmod", ROOT / "scripts" / "eval.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    defaults, items = ev.load_qa()
    ids = [i["id"] for i in items]
    assert len(items) == 40 and len(set(ids)) == 40
    assert all(i["as_of"] and i["question"] and i["expect"]["status"] for i in items)
    assert defaults["as_of"] == "2026-11-22"
    assert sum(1 for i in items if i["expect"]["status"] == "abstained") == 6
    assert len(ev.select(items, None, None, "scanned,hindi")) < 40
