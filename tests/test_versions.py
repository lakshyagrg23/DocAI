"""M5 tests: fact validation, subject canonicalisation, amendment edges, version timelines, chains. Offline."""
from __future__ import annotations

import pytest
from test_ingest import PDFS, StubClient, corpus  # noqa: F401  (corpus = autouse fixture that builds the PDFs)

from core import db, versions
from core.ingest import amendments, extract, pipeline
from core.models import AmendExtraction, AmendmentDirective, ExtractedFact, Extraction
from core.retrieval import evidence
from core.retrieval.hybrid import Hit
from core.subjects import canonical_subject, fuzzy_match, normalise_attribute, slug

DOCS = {"D1": "D1_loan_agreement.pdf", "D2": "D2_schedule_of_charges.pdf", "D3": "D3_amendment_1.pdf",
        "D4": "D4_amendment_2.pdf", "D5": "D5_fcb_circular.pdf"}


class Scripted(StubClient):
    """LLM stub that returns the directives/facts a competent model would for the demo amendment documents."""

    def chat_json(self, messages, model_cls, max_tokens=900):
        user = messages[-1]["content"]
        if model_cls is AmendExtraction:
            if "[D3:1#s1]" in user:
                return AmendExtraction(amendments=[AmendmentDirective(
                    action="substitute", target_ref="Personal Loan Agreement KF/PLA/2024", target_path="7.2",
                    effective_date="2025-04-01", new_text_span_ids=["D3:1#s2"], evidence_span_ids=["D3:1#s1"])])
            if "[D4:1#s1]" in user:
                return AmendExtraction(amendments=[
                    AmendmentDirective(action="substitute", target_ref="Personal Loan Agreement KF/PLA/2024",
                                       target_path="7.2", effective_date="2026-01-01", new_text_span_ids=["D4:1#s2"],
                                       evidence_span_ids=["D4:1#s1"]),
                    AmendmentDirective(action="supersede_amendment", target_ref="Amendment No. 1 (KF/PLA/2024/AMD-1)",
                                       target_path=None, effective_date="2026-01-01", evidence_span_ids=["D4:1#s1"])])
            return AmendExtraction()
        if model_cls is Extraction:
            facts = []
            if "[D1:8.1#s1]" in user:
                facts.append(ExtractedFact(subject="late payment fee", attribute="amount", op="eq", value_type="money",
                                           value_raw="₹500", span_id="D1:8.1#s1", scope={"per": "instalment"}))
                facts.append(ExtractedFact(subject="late fee", attribute="amount", op="eq", value_type="money",
                                           value_raw="₹9,999", span_id="D1:8.1#s1"))  # not in the span: must be dropped
            if "[D5:1#s1]" in user:
                facts.append(ExtractedFact(subject="penal charges for delayed payment of an instalment", attribute="amount",
                                           op="max", value_type="money", value_raw="₹600", span_id="D5:1#s1"))
            return Extraction(facts=facts)
        return super().chat_json(messages, model_cls, max_tokens)


def ingest(conn, client, *names, tmp):
    for n in names:
        pipeline.enqueue(PDFS / DOCS[n], conn, start_worker=False)
    pipeline.run_pending(conn, client, tmp)


def timeline(conn, vk="D1:7.2"):
    return [(v["clause_id"], v["valid_from"], v["valid_to"]) for v in versions.versions_for(conn, vk)]


EXPECTED = [("D1:7.2", "2024-01-15", "2025-04-01"), ("D3:1", "2025-04-01", "2026-01-01"), ("D4:1", "2026-01-01", None)]


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m5")
    conn = db.init_db(tmp / "c.db")
    ingest(conn, Scripted(), "D1", "D2", "D3", "D4", "D5", tmp=tmp)
    return conn, tmp


# ---- pure helpers -----------------------------------------------------------------

def test_slug_and_attribute():
    assert slug("The charge for late payment of EMI") == "charge_late_payment_emi"
    assert normalise_attribute("Maximum age", "number") == "age" and normalise_attribute("x", "percent") == "rate"
    assert normalise_attribute("amount", "text") == "amount" and normalise_attribute("zzz", "text") == "other"


def test_validate_fact():
    spans = {"s1": "A late fee of ₹500 per instalment applies."}
    ok = ExtractedFact(subject="late fee", attribute="amount", op="eq", value_type="money", value_raw="₹ 500", span_id="s1")
    assert extract.validate_fact(ok, spans) is None
    assert "not found" in extract.validate_fact(ok.model_copy(update={"value_raw": "₹900"}), spans)
    assert "not in this batch" in extract.validate_fact(ok.model_copy(update={"span_id": "zz"}), spans)
    assert "unparseable" in extract.validate_fact(
        ok.model_copy(update={"value_type": "percent", "value_raw": "late fee"}), {"s1": "late fee"})


def test_directive_validation():
    spans = {"a": "With effect from 1 April 2025, Clause 7.2 of the Agreement shall be substituted."}
    d = AmendmentDirective(action="substitute", target_ref="Agreement", target_path="7.2", evidence_span_ids=["a"])
    assert amendments.validate_directive(d, spans, {"a": "X:1"}) is None
    assert amendments.validate_directive(d.model_copy(update={"target_path": "9.9"}), spans, {"a": "X:1"})
    assert amendments.validate_directive(d.model_copy(update={"evidence_span_ids": ["zz"]}), spans, {"a": "X:1"})
    sup = AmendmentDirective(action="supersede_doc", target_ref="Agreement", evidence_span_ids=["a"])
    assert "supersession wording" in amendments.validate_directive(sup, spans, {"a": "X:1"})


def test_subject_canonicalisation(tmp_path):
    conn = db.init_db(tmp_path / "s.db")
    assert canonical_subject(conn, "Late payment fee") == "late_payment_fee"
    assert canonical_subject(conn, "penal charges for delayed payment of instalments") == "late_payment_fee"
    assert canonical_subject(conn, "prepayment charge for fixed rate loans") == "prepayment_charge"
    assert fuzzy_match(conn, "interest calculation method") is None  # one-word alias must be the whole label
    assert canonical_subject(conn, "interest") == "interest_rate"
    assert canonical_subject(conn, "Grievance officer name") == "grievance_officer_name"  # new subject, no model


# ---- facts + edges + timeline on the demo documents ---------------------------------

def test_facts_are_validated_canonicalised_and_stored(full):
    conn, _ = full
    rows = conn.execute("SELECT subject_id,attribute,value_raw,span_id,scope FROM facts ORDER BY span_id").fetchall()
    got = {(r["span_id"], r["subject_id"], r["value_raw"]) for r in rows}
    assert ("D1:8.1#s1", "late_payment_fee", "₹500") in got and ("D5:1#s1", "late_payment_fee", "₹600") in got
    assert not any(r["value_raw"] == "₹9,999" for r in rows)  # hallucinated value dropped
    assert '"per": "instalment"' in next(r["scope"] for r in rows if r["span_id"] == "D1:8.1#s1")


def test_edges_resolved_to_the_right_documents(full):
    conn, _ = full
    edges = {e["edge_id"]: e for e in conn.execute("SELECT * FROM amendment_edges")}
    assert {(e["action"], e["target_doc_id"], e["target_path"], e["effective_date"]) for e in edges.values()} == {
        ("substitute", "D1", "7.2", "2025-04-01"), ("substitute", "D1", "7.2", "2026-01-01"),
        ("supersede_amendment", "D3", None, "2026-01-01")}
    assert all(e["resolved"] == 1 for e in edges.values())


def test_timeline_matches_the_demo_corpus(full):
    conn, _ = full
    assert timeline(conn) == EXPECTED
    assert conn.execute("SELECT version_key FROM clauses WHERE clause_id='D3:1'").fetchone()[0] == "D1:7.2"


def test_status_at_dates(full):
    conn, _ = full
    assert versions.status(conn, "D1:7.2", "2026-11-22") == "superseded"
    assert versions.status(conn, "D1:7.2", "2024-06-01") == "in_force"
    assert versions.status(conn, "D3:1", "2025-06-01") == "in_force"
    assert versions.status(conn, "D3:1", "2026-11-22") == "superseded"
    assert versions.status(conn, "D4:1", "2026-11-22") == "in_force"
    assert versions.status(conn, "D4:1", "2025-06-01") == "future"
    assert versions.status(conn, "D1:5.1", "2026-11-22") == "in_force"  # never amended
    assert versions.status(conn, "D5:1", "2025-06-01") == "future"  # before the circular's effective date
    assert versions.key_status(conn, "D1:7.2", "2026-11-22") == "active"


def test_chain_output(full):
    conn, _ = full
    ch = versions.chains(conn, ["D4:1", "D1:5.1"], "2026-11-22")
    assert len(ch) == 1 and ch[0]["version_key"] == "D1:7.2" and ch[0]["in_force_step"] == 2
    assert [s["clause_id"] for s in ch[0]["steps"]] == ["D1:7.2", "D3:1", "D4:1"]
    assert [s["action"] for s in ch[0]["steps"]] == ["original", "substituted", "substituted"]
    assert ch[0]["steps"][1]["span_id"] == "D3:1#s2" and ch[0]["steps"][1]["text"].startswith('"7.2')
    assert versions.chains(conn, ["D3:1"], "2025-06-01")[0]["in_force_step"] == 1


def test_expansion_and_evidence_use_real_versions(full):
    conn, _ = full
    hit = [Hit(window_id="D1:7.2@w1", clause_id="D1:7.2", doc_id="D1", score=1.0, rrf=0.0)]
    today = evidence.build_pack(conn, hit, "2026-11-22")
    assert {s.clause_id for s in today.spans} == {"D4:1"} and {s.clause_id for s in today.context_spans} == {"D1:7.2", "D3:1"}
    mid = evidence.build_pack(conn, hit, "2025-06-01")
    assert {s.clause_id for s in mid.spans} == {"D3:1"}
    old = evidence.build_pack(conn, hit, "2024-06-01")
    assert {s.clause_id for s in old.spans} == {"D1:7.2"}


# ---- order independence, unresolved edges, document supersession ---------------------

@pytest.mark.parametrize("order", [("D4", "D3", "D1"), ("D3", "D4", "D1"), ("D1", "D4", "D3")])
def test_ingest_order_independence(tmp_path, order):
    conn = db.init_db(tmp_path / "o.db")
    ingest(conn, Scripted(), *order, tmp=tmp_path)
    assert timeline(conn) == EXPECTED


def test_unresolved_edge_resolves_when_target_arrives(tmp_path):
    conn = db.init_db(tmp_path / "u.db")
    ingest(conn, Scripted(), "D3", tmp=tmp_path)
    e = conn.execute("SELECT resolved,target_doc_id FROM amendment_edges").fetchone()
    assert (e["resolved"], e["target_doc_id"]) == (0, None) and timeline(conn) == []
    ingest(conn, Scripted(), "D1", tmp=tmp_path)
    assert conn.execute("SELECT resolved,target_doc_id FROM amendment_edges").fetchone()["target_doc_id"] == "D1"
    assert timeline(conn) == [("D1:7.2", "2024-01-15", "2025-04-01"), ("D3:1", "2025-04-01", None)]


def test_reingest_of_an_amendment_removes_its_edges(tmp_path):
    conn = db.init_db(tmp_path / "r.db")
    ingest(conn, Scripted(), "D1", "D3", "D4", tmp=tmp_path)
    assert len(timeline(conn)) == 3
    now = db.now_iso()  # a forced re-run (enqueue() dedupes unchanged files by sha); no LLM this time: D4's directives are gone
    conn.execute("INSERT INTO ingest_jobs(job_id,doc_id,path,state,error,created_at,updated_at) VALUES('jx','D4',?,'queued',NULL,?,?)",
                 (str(PDFS / DOCS["D4"]), now, now))
    conn.commit()
    pipeline.run_pending(conn, StubClient(), tmp_path)
    assert [t[0] for t in timeline(conn)] == ["D1:7.2", "D3:1"]


def test_supersede_doc_closes_every_clause(tmp_path):
    conn = db.init_db(tmp_path / "d.db")
    ingest(conn, Scripted(), "D1", "D2", tmp=tmp_path)
    conn.execute("INSERT INTO amendment_edges(edge_id,source_clause_id,target_doc_id,target_path,action,new_text_span_ids,"
                 "effective_date,evidence_span_ids,confidence,resolved,raw_target_ref) VALUES"
                 "('E:D2:table1.row1:1','D2:table1.row1','D1',NULL,'supersede_doc','[]','2025-01-01','[]',1,1,'x')")
    conn.commit()
    versions.rebuild_all(conn)
    assert versions.status(conn, "D1:5.1", "2024-06-01") == "in_force"
    assert versions.status(conn, "D1:5.1", "2025-06-01") == "superseded"
    assert versions.key_status(conn, "D1:5.1", "2025-06-01") == "deleted"


def test_recover_target_path_only_when_unambiguous():
    spans = {"a": "With effect from 1 April 2025, Clause 7.2 of the Agreement shall be substituted.",
             "b": "Clause 7.2 and clause 8.1 are substituted."}
    d = AmendmentDirective(action="substitute", target_ref="Agreement", evidence_span_ids=["a"])
    assert amendments.recover_target_path(d, spans) == "7.2"
    assert amendments.recover_target_path(d.model_copy(update={"evidence_span_ids": ["b"]}), spans) is None
