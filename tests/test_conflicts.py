"""M6 tests: comparison rules, candidate filters, ingest scan (C1, C2, C3), query-time lookup and cards. Offline."""
from __future__ import annotations

from typing import ClassVar

import pytest
from test_ingest import PDFS, StubClient, corpus  # noqa: F401  (corpus = autouse fixture that builds the PDFs)
from test_versions import Scripted, ingest

from core import db, versions
from core.answer import disagree
from core.conflict_rules import FactView, candidate, compare, merge_ranges, overlap, scopes_compatible
from core.ingest import conflicts
from core.models import ClaimCheck, ExtractedFact, Extraction, FactValue, VerifiedClaim
from core.retrieval.evidence import EvidencePack


def fv(op="eq", vt="money", amount=None, low=None, high=None, flag=None, date=None, clause="X:1", subject="s",
       attribute="amount", scope=None, vk=None, start="2024-01-01", end=None, fid=None, label="Doc, cl. 1", raw="r"):
    return FactView(fid or f"f_{clause}_{op}", clause, f"{clause}#s1", subject, attribute, op, vt,
                    FactValue(amount=amount, low=low, high=high, flag=flag, date=date, unit="INR" if vt == "money" else None),
                    scope or {}, vk or clause, start, end, label, raw)


# ---- comparison table (contradictions.md §2) -----------------------------------------

@pytest.mark.parametrize("a,b,expect", [
    (fv(amount=500), fv(clause="Y:1", amount=750), "numeric"),                            # eq . eq differ
    (fv(amount=500), fv(clause="Y:1", amount=500), None),                                 # eq . eq same
    (fv(amount=750), fv(op="max", clause="Y:1", amount=600), "rule"),                     # eq exceeds max
    (fv(amount=500), fv(op="max", clause="Y:1", amount=600), None),                       # eq within max
    (fv(op="max", clause="Y:1", amount=600), fv(amount=750), "rule"),                     # swapped orientation
    (fv(amount=1), fv(op="min", clause="Y:1", amount=5), "rule"),                         # eq below min
    (fv(amount=9), fv(op="min", clause="Y:1", amount=5), None),
    (fv(op="range", vt="number", low=21, high=58, subject="borrower_age", attribute="age"),
     fv(op="range", vt="number", low=21, high=60, clause="Y:1", subject="borrower_age", attribute="age"), "eligibility"),
    (fv(op="range", vt="number", low=21, high=58), fv(op="range", vt="number", low=21, high=58, clause="Y:1"), None),
    (fv(op="range", vt="number", low=21, high=58), fv(vt="number", amount=65, clause="Y:1"), "numeric"),  # eq outside
    (fv(op="range", vt="number", low=21, high=58), fv(vt="number", amount=30, clause="Y:1"), None),      # eq inside
    (fv(op="bool", vt="bool", flag=False), fv(clause="Y:1", amount=4), "rule"),           # nil vs amount
    (fv(op="bool", vt="bool", flag=False), fv(clause="Y:1", amount=0), None),
    (fv(op="bool", vt="bool", flag=True), fv(op="bool", vt="bool", flag=False, clause="Y:1"), "rule"),
    (fv(op="bool", vt="bool", flag=True), fv(op="bool", vt="bool", flag=True, clause="Y:1"), None),
    (fv(op="eq", vt="date", date="2025-01-01", attribute="date"), fv(op="eq", vt="date", date="2025-02-01", attribute="date", clause="Y:1"), "date"),
    (fv(op="max", clause="X:1", amount=5), fv(op="max", clause="Y:1", amount=9), None),   # max . max: the stricter applies
    (fv(op="min", clause="X:1", amount=5), fv(op="min", clause="Y:1", amount=9), None),
    (fv(amount=5), fv(vt="percent", clause="Y:1", amount=7), None),                       # different kinds are not compared
])
def test_compare_table(a, b, expect):
    v = compare(a, b)
    assert (v.type if v else None) == expect


def test_differing_values_and_explanations():
    v = compare(fv(amount=500, label="Loan Agreement, cl. 8.1", scope={"per": "instalment"}),
                fv(clause="Y:1", amount=750, label="Schedule, row 2", scope={"per": "instalment"}))
    assert v.differing == {"a": [500], "b": [750]} and v.severity == "high"
    assert v.explanation == "₹500 per instalment (Loan Agreement, cl. 8.1) vs ₹750 per instalment (Schedule, row 2)"
    cap = compare(fv(amount=750, label="Schedule, row 2"), fv(op="max", clause="Y:1", amount=600, label="Circular, para 1"))
    assert cap.differing == {"a": [750], "b": [600]} and "exceeds the ₹600 cap (Circular, para 1)" in cap.explanation
    nil = compare(fv(op="bool", vt="bool", flag=False), fv(clause="Y:1", amount=4))
    assert nil.differing == {"a": ["nil"], "b": [4]}
    swapped = compare(fv(op="max", clause="Y:1", amount=600), fv(amount=750))
    assert swapped.differing == {"a": [600], "b": [750]}  # sides stay attached to the facts as passed in


def test_c3_age_differs_only_on_the_upper_bound():
    lo = fv(op="min", vt="number", amount=21, subject="borrower_age", attribute="age", clause="D1:3.1", fid="f1")
    hi = fv(op="max", vt="number", amount=58, subject="borrower_age", attribute="age", clause="D1:3.1", fid="f2")
    merged = merge_ranges([lo, hi])
    assert len(merged) == 1 and (merged[0].value.low, merged[0].value.high) == (21, 58)
    faq = fv(op="range", vt="number", low=21, high=60, subject="borrower_age", attribute="age", clause="D6:p1.q1",
             start="2025-06-01", fid="f3")
    v = compare(merged[0], faq)
    assert v.type == "eligibility" and v.differing == {"a": [58], "b": [60]} and v.overlap_from == "2025-06-01"


# ---- candidate filters ---------------------------------------------------------------

def test_candidate_filters():
    base = fv(amount=500, scope={"per": "instalment"})
    assert candidate(base, fv(clause="Y:1", amount=750, scope={"per": "instance"}))  # instalment ~ instance
    assert not candidate(base, fv(clause="Y:1", amount=750, scope={"per": "month"}))
    assert not candidate(base, fv(clause="Y:1", amount=750, vk=base.version_key))  # same version key: an amendment
    assert not candidate(base, fv(clause="X:1", amount=750))  # same clause
    assert not candidate(fv(amount=1, start="2024-01-01", end="2025-01-01"), fv(clause="Y:1", amount=2, start="2025-01-01"))
    assert candidate(fv(amount=1, scope={"borrower": "individual"}), fv(clause="Y:1", amount=2))  # general vs specific
    assert not scopes_compatible({"rate_type": "fixed"}, {"rate_type": "floating"})
    assert overlap(fv(start="2024-01-01", end="2025-01-01"), fv(start="2024-06-01")) == ("2024-06-01", "2025-01-01")


# ---- ingest scan on the demo documents -------------------------------------------------

class Facts(Scripted):
    """Scripted amendments (from test_versions) plus the facts a competent extractor finds in the demo documents."""

    FACTS: ClassVar[dict] = {
        "[D1:8.1#s1]": ("late payment fee", "amount", "eq", "money", "₹500", "D1:8.1#s1", {"per": "instalment"}),
        "[D2:table1.row2#s1]": ("late payment fee", "amount", "eq", "money", "₹750", "D2:table1.row2#s1", {"per": "instalment"}),
        "[D5:1#s1]": ("penal charges for delayed payment of an instalment", "amount", "max", "money", "₹600", "D5:1#s1", {}),
        "[D1:7.2#s1]": ("prepayment charge", "rate", "eq", "percent", "4%", "D1:7.2#s1", {}),
        "[D3:1#s2]": ("prepayment charge", "rate", "eq", "percent", "3%", "D3:1#s2", {}),
        "[D4:1#s3]": ("prepayment charge", "rate", "eq", "percent", "2%", "D4:1#s3", {"rate_type": "fixed"}),
    }

    def chat_json(self, messages, model_cls, max_tokens=900):
        if model_cls is Extraction:
            user = messages[-1]["content"]
            return Extraction(facts=[ExtractedFact(subject=s, attribute=at, op=op, value_type=vt, value_raw=raw,
                                                   span_id=sid, scope=sc)
                                     for key, (s, at, op, vt, raw, sid, sc) in self.FACTS.items() if key in user])
        return super().chat_json(messages, model_cls, max_tokens)


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m6")
    conn = db.init_db(tmp / "c.db")
    ingest(conn, Facts(), "D1", "D2", "D3", "D4", "D5", tmp=tmp)
    return conn


def pairs(conn):
    return {(f"{r['ca']}~{r['cb']}", r["type"], r["overlap_from"], r["overlap_to"]) for r in conn.execute(
        "SELECT cf.type,cf.overlap_from,cf.overlap_to,fa.clause_id ca,fb.clause_id cb FROM conflicts cf "
        "JOIN facts fa ON fa.fact_id=cf.fact_a JOIN facts fb ON fb.fact_id=cf.fact_b")}


def test_scan_finds_exactly_c1_and_c2(scanned):
    got = {(tuple(sorted(k.split("~"))), t, f, to) for k, t, f, to in pairs(scanned)}
    assert got == {(("D1:8.1", "D2:table1.row2"), "numeric", "2024-01-15", None),
                   (("D2:table1.row2", "D5:1"), "rule", "2025-11-01", None)}  # C1, C2; C3 needs the scanned FAQ (M9)


def test_amendment_versions_and_below_cap_fee_are_not_conflicts(scanned):
    subjects = {r["subject_id"] for r in scanned.execute("SELECT cf.subject_id FROM conflicts cf")}
    assert subjects == {"late_payment_fee"}  # prepayment 4% vs 3% vs 2% are versions of one clause; 500 <= 600
    rows = scanned.execute("SELECT 1 FROM conflicts cf JOIN facts fa ON fa.fact_id=cf.fact_a JOIN facts fb ON fb.fact_id=cf.fact_b "
                           "WHERE fa.clause_id='D1:8.1' AND fb.clause_id='D5:1' OR fa.clause_id='D5:1' AND fb.clause_id='D1:8.1'")
    assert rows.fetchall() == []


def test_scan_is_idempotent_and_ids_are_stable(scanned):
    before = {r["conflict_id"] for r in conflicts.stored(scanned)}
    conflicts.run(scanned, "D5", StubClient())
    assert {r["conflict_id"] for r in conflicts.stored(scanned)} == before and len(before) == 2


# ---- query time ------------------------------------------------------------------------

def claim(text, *span_ids):
    return VerifiedClaim(text=text, span_ids=list(span_ids), verdict="supported",
                         checks=ClaimCheck(spans_valid=True, numbers_ok=True, quote_ok=True, version_ok=True))


def test_lookup_marks_claims_that_assert_a_disputed_value(scanned):
    cs = [claim("The late payment fee is ₹500 per instalment", "D1:8.1#s1"),
          claim("The late payment fee is ₹750 per instalment", "D2:table1.row2#s1"),
          claim("Penal charges must not exceed ₹600 per instalment", "D5:1#s1"),
          claim("Late fees are charged per instalment", "D1:8.1#s1")]  # no disputed value stated
    disagree.mark_contradicted(scanned, cs, "2026-11-22")
    assert [c.verdict for c in cs] == ["contradicted", "contradicted", "contradicted", "supported"]
    assert len(cs[1].checks.conflict_ids) == 2 and len(cs[0].checks.conflict_ids) == 1


def test_lookup_respects_the_as_of_date(scanned):
    cs = [claim("The late payment fee is ₹500 per instalment", "D1:8.1#s1"),
          claim("Penal charges must not exceed ₹600 per instalment", "D5:1#s1")]
    disagree.mark_contradicted(scanned, cs, "2025-06-01")  # the circular takes effect on 2025-11-01
    assert [c.verdict for c in cs] == ["contradicted", "supported"]
    assert disagree.conflict_partners(scanned, ["D1:8.1"], "2025-06-01") == ["D2:table1.row2"]
    assert set(disagree.conflict_partners(scanned, ["D2:table1.row2"], "2026-11-22")) == {"D1:8.1", "D5:1"}


def test_disagreement_card_groups_all_sides_by_subject(scanned):
    cs = [claim("The late payment fee is ₹750 per instalment", "D2:table1.row2#s1")]
    disagree.mark_contradicted(scanned, cs, "2026-11-22")
    cards = disagree.build_disagreements(scanned, cs, "2026-11-22")
    assert len(cards) == 1 and cards[0]["subject"] == "late_payment_fee"
    assert {s["doc"] for s in cards[0]["sides"]} == {"D1", "D2", "D5"}
    assert all(s["status"] == "in_force" and s["text"] for s in cards[0]["sides"]) and "·" in cards[0]["explanation"]
    assert disagree.build_disagreements(scanned, [claim("x", "D1:8.1#s1")], "2026-11-22") == []


def test_asserts_disputed_only_for_values_in_dispute():
    assert not disagree.asserts_disputed("Applicants must be at least 21 years old", [58])
    assert disagree.asserts_disputed("Applicants may be aged 21 to 58", [58])
    assert disagree.asserts_disputed("No prepayment charge applies", ["nil"])
    assert not disagree.asserts_disputed("The fee is 3%", ["nil"])


def test_partners_join_the_evidence_pack(scanned):
    from core.retrieval.evidence import build_pack
    from core.retrieval.hybrid import Hit
    pack = build_pack(scanned, [Hit("D2:table1.row2@w1", "D2:table1.row2", "D2", 1.0, 0.0)], "2026-11-22")
    added = disagree.add_partners(scanned, pack, "2026-11-22")
    assert set(added) == {"D1:8.1", "D5:1"} and {"D1:8.1#s1", "D5:1#s1"} <= pack.span_ids()
    assert isinstance(pack, EvidencePack) and versions.status(scanned, "D5:1", "2026-11-22") == "in_force"


def test_recheck_persists_pairs_missing_from_the_ingest_scan(scanned):
    scanned.execute("DELETE FROM conflicts")
    scanned.commit()
    assert disagree.recheck(scanned, ["D1:8.1", "D2:table1.row2", "D5:1"]) == 2
    assert {r["detected_by"] for r in conflicts.stored(scanned)} == {"query"}
