"""M4 tests: normaliser, verification checks (pure), batched NLI wiring, gate statuses, answer() end to end (offline)."""
from __future__ import annotations

import json

import pytest

from core import config, db
from core.answer import assemble
from core.answer.gate import ABSTAIN_TEXT, gate
from core.answer.verify import apply_threshold, numbers_ok, quote_ok, spans_valid, verify_claims, version_ok
from core.models import ClaimCheck, Draft, DraftClaim, QueryPlan, VerifiedClaim
from core.normalize import missing_numbers, number_tokens, parse_value
from core.retrieval.evidence import EvidencePack, EvidenceSpan

# ---- normaliser ------------------------------------------------------------------


@pytest.mark.parametrize("raw,vt,amount", [
    ("₹ 5,00,000", "money", 500000), ("Rs. 750/-", "money", 750), ("₹25 lakh", "money", 2_500_000),
    ("INR 1.5 crore", "money", 15_000_000), ("13.5% p.a.", "percent", 13.5), ("4 per cent", "percent", 4),
    ("36 months", "duration", 36)])
def test_parse_value_amounts(raw, vt, amount):
    assert parse_value(raw, vt).amount == amount


def test_parse_value_other_types():
    assert parse_value("12 to 60 months", "number").low == 12 and parse_value("12 to 60", "number").high == 60
    assert parse_value("1 April 2025", "date").date == "2025-04-01"
    assert parse_value("Nil", "bool").flag is False and parse_value("prepayment is permitted", "bool").flag is True
    with pytest.raises(ValueError):
        parse_value("none here", "money")


def test_number_tokens_ignore_clause_refs_and_span_ids():
    toks = number_tokens("Under clause 7.2 [D1:7.2#s1] the fee is ₹500 and 4%")
    assert ("num", 500.0) in toks and ("pct", 4.0) in toks and ("num", 7.2) not in toks and ("num", 1.0) not in toks


# ---- (b) numbers ---------------------------------------------------------------------

@pytest.mark.parametrize("claim,ctx,ok", [
    ("The late fee is ₹500", "₹500 per instalment", True),
    ("The late fee is ₹500", "Rs. 500/- per instalment", True),
    ("The late fee is ₹5,000", "₹500 per instalment", False),
    ("The charge is 4%", "a charge of 3% applies", False),
    ("The charge is 4%", "a charge of 4 per cent applies", True),
    ("The maximum loan is ₹25 lakh", "up to ₹25,00,000", True),
    ("EMI is due on the 5th", "due on the 5th day of each month", True),
    ("You may prepay after 6 EMIs", "after six EMIs have been paid", True),
    ("Effective 1 April 2025", "effective 2025-04-01", True),
    ("Effective 1 April 2026", "effective 2025-04-01", False),
    ("The tenure is 12 to 60 months", "tenure of 12 to 60 months", True),
])
def test_numbers_ok(claim, ctx, ok):
    assert numbers_ok(claim, ctx)[0] is ok


def test_numbers_nil_handling_and_extra():
    assert numbers_ok("No prepayment charge applies", "No prepayment charge shall be levied on floating loans")[0]
    assert not numbers_ok("No prepayment charge applies", "A prepayment charge of 4% applies")[0]
    assert not numbers_ok("The principal is ₹2,00,000", "the charge is 3%")[0]
    assert numbers_ok("The principal is ₹2,00,000", "the charge is 3%", extra="on ₹2,00,000 outstanding")[0]
    assert missing_numbers("Fee is ₹590", "fee ₹500") == ["590"]


# ---- (a) (c) (d) -------------------------------------------------------------------

def test_spans_valid():
    assert spans_valid(["a"], {"a", "b"}) and not spans_valid(["z"], {"a"}) and not spans_valid([], {"a"})


def test_quote_ok():
    ctx = "The Borrower shall pay a late payment fee of ₹500 per instalment."
    assert quote_ok('The text says "late payment fee of ₹500 per instalment".', ctx)
    assert not quote_ok('The text says "interest is waived completely".', ctx)
    assert quote_ok("No quotation here", ctx)


def test_version_ok():
    assert version_ok(["in_force"], "fact") and not version_ok(["superseded"], "fact")
    assert version_ok(["superseded"], "history") and not version_ok(["in_force", "future"], "fact")


# ---- (e) batched NLI + verdicts ------------------------------------------------------

def span(sid, text, status="in_force"):
    line = f"[{sid}] (Loan Agreement KF/1, cl. 8.1, p.4, effective 2024-01-15) {text}"
    return EvidenceSpan(sid, sid.split("#")[0], "D1", 4, text, line, status=status)


class NliClient:
    def __init__(self, score=0.9):
        self.calls, self.score = [], score

    def nli(self, pairs):
        self.calls.append(pairs)
        return [self.score for _ in pairs]


def make_pack():
    return EvidencePack(spans=[span("D1:8.1#s1", "A late payment fee of ₹500 is charged per instalment.")],
                        context_spans=[span("D1:7.2#s1", "Prepayment charge is 4%.", "superseded")])


def test_verify_claims_batches_nli_and_skips_failed():
    pack, client = make_pack(), NliClient()
    claims = [DraftClaim(text="The late fee is ₹500 per instalment", span_ids=["D1:8.1#s1"]),
              DraftClaim(text="The late fee is ₹900", span_ids=["D1:8.1#s1"]),  # numbers fail
              DraftClaim(text="Late fee applies", span_ids=["D9:1#s1"]),  # not in the pack
              DraftClaim(text="The charge is 4%", span_ids=["D1:7.2#s1"]),  # context-only span: not citable
              DraftClaim(text="Interest is 13.5%", span_ids=["D1:8.1#s1"])]
    out = verify_claims(claims, pack, client)
    assert [c.verdict for c in out] == ["supported", "unsupported", "unsupported", "unsupported", "unsupported"]
    assert len(client.calls) == 1 and len(client.calls[0]) == 1  # one batched call, only the survivor
    assert out[0].checks.hhem == 0.9 and "₹900" in out[1].reason or "900" in out[1].reason
    assert out[2].reason == "cites evidence that wasn't retrieved"


def test_verify_low_hhem_blocks_and_threshold_sweep():
    pack = make_pack()
    out = verify_claims([DraftClaim(text="Late payment fee is charged", span_ids=["D1:8.1#s1"])], pack, NliClient(0.3))
    assert out[0].verdict == "unsupported" and "0.30" in out[0].reason
    assert apply_threshold(out[0], 0.2).verdict == "supported" and apply_threshold(out[0], 0.5).verdict == "unsupported"


def test_verify_history_may_cite_context_but_not_when_absent_from_pack():
    pack = make_pack()
    pack.spans.append(span("D1:7.2#s1", "Prepayment charge is 4%.", "superseded"))
    out = verify_claims([DraftClaim(text="Until 2025 the prepayment charge was 4%", span_ids=["D1:7.2#s1"], kind="history")],
                        pack, NliClient())
    assert out[0].checks.version_ok is True
    fact = verify_claims([DraftClaim(text="The prepayment charge is 4%", span_ids=["D1:7.2#s1"])], pack, NliClient())
    assert fact[0].checks.version_ok is False and fact[0].reason == "cites a superseded clause"


# ---- gate ---------------------------------------------------------------------------

def vc(verdict):
    return VerifiedClaim(text="t", span_ids=["s"], verdict=verdict,
                         checks=ClaimCheck(spans_valid=True, numbers_ok=True, quote_ok=True, version_ok=True))


def test_gate_statuses():
    assert gate([vc("supported")], [], ["q"]).status == "answered"
    assert gate([vc("supported"), vc("unsupported")], [], ["q"]).status == "partial"
    assert gate([vc("supported")], ["GST rate"], ["q"]).status == "partial"
    assert gate([vc("supported"), vc("contradicted")], [], ["q"]).status == "conflict"
    r = gate([vc("unsupported")], [], ["What is the GST?"])
    assert r.status == "abstained" and r.missing == ["No verified evidence for: What is the GST?"]
    assert gate([], ["GST rate"], ["q"]).missing == ["GST rate"]
    assert gate([], [], []).faithfulness_pct is None
    g = gate([vc("supported"), vc("supported"), vc("unsupported")], [], ["q"])
    assert g.faithfulness_pct == 66.7 and (g.drafted, g.passed) == (3, 2)
    assert "proof" in ABSTAIN_TEXT


# ---- answer() end to end with a scripted model ----------------------------------------

class Scripted:
    """Planner + drafter + NLI stub; embed/rerank are the hashed fakes from test_ingest."""

    def __init__(self, base, draft):
        self.base, self.draft = base, draft

    def chat_json(self, messages, model_cls, max_tokens=900):
        if model_cls is QueryPlan:
            return QueryPlan(sub_questions=["late payment fee per instalment"])
        return self.draft

    def __getattr__(self, name):
        return getattr(self.base, name)

    def nli(self, pairs):
        return [0.95] * len(pairs)


@pytest.fixture(scope="module")
def ingested(tmp_path_factory):
    from test_ingest import PDFS, StubClient

    from core.ingest import pipeline
    tmp = tmp_path_factory.mktemp("m4")
    conn = db.init_db(tmp / "c.db")
    stub = StubClient()
    for p in sorted(PDFS.glob("D[1-5]*.pdf")):
        pipeline.enqueue(p, conn, start_worker=False)
    pipeline.run_pending(conn, stub, tmp)
    return conn, stub, tmp


def test_answer_displays_only_verified_claims(ingested, monkeypatch):
    conn, stub, tmp = ingested
    monkeypatch.setattr(config, "DATA_DIR", tmp)
    from core.retrieval.hybrid import Retriever
    draft = Draft(claims=[DraftClaim(text="The late payment fee is ₹500 per instalment", span_ids=["D1:8.1#s1"]),
                          DraftClaim(text="The late payment fee is ₹999", span_ids=["D1:8.1#s1"])],
                  missing=["GST rate"])
    client = Scripted(stub, draft)
    chat = db.create_chat(conn)
    stages: list[str] = []
    ans = assemble.answer(conn, "What is the late payment fee?", chat.chat_id, as_of="2026-11-22", client=client,
                          retriever=Retriever(conn, stub, tmp), on_stage=stages.append)
    assert ans.status == "partial"
    assert [c.text for c in ans.claims] == ["The late payment fee is ₹500 per instalment"]
    assert len(ans.blocked_claims) == 1 and "999" in ans.blocked_claims[0].reason
    assert ans.missing_evidence == ["GST rate"] and ans.faithfulness_pct == 50.0
    assert stages[0] == "Planning" and stages[-1] == "Done" and any(s.startswith("Verifying") for s in stages)
    msgs = db.list_messages(conn, chat.chat_id)
    assert [m.role for m in msgs] == ["user", "assistant"] and json.loads(msgs[1].answer_json)["status"] == "partial"
    assert db.get_chat(conn, chat.chat_id).title == "What is the late payment fee?"
    log = (tmp / "logs" / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    from core.llm.prompt_loader import load_prompt
    assert json.loads(log[-1])["answer"]["prompt_versions"]["draft"] == load_prompt("draft")[0]


def test_answer_abstains_when_nothing_verifies(ingested, monkeypatch):
    conn, stub, tmp = ingested
    monkeypatch.setattr(config, "DATA_DIR", tmp)
    from core.retrieval.hybrid import Retriever
    client = Scripted(stub, Draft(claims=[], missing=["GST rate on the processing fee"]))
    ans = assemble.answer(conn, "What is the GST rate?", None, as_of="2026-11-22", client=client,
                          retriever=Retriever(conn, stub, tmp))
    assert ans.status == "abstained" and ans.claims == [] and ans.missing_evidence == ["GST rate on the processing fee"]
    assert assemble.render_text(ans).startswith(ABSTAIN_TEXT)


def test_answer_abstains_when_drafting_fails(ingested, monkeypatch):
    conn, stub, tmp = ingested
    monkeypatch.setattr(config, "DATA_DIR", tmp)
    from core.retrieval.hybrid import Retriever
    ans = assemble.answer(conn, "late fee?", None, as_of="2026-11-22", client=stub,  # StubClient.chat_json raises
                          retriever=Retriever(conn, stub, tmp))
    assert ans.status == "abstained" and ans.missing_evidence == ["Drafting failed"]


# ---- eval scoring (scripts/eval_answers.py) ------------------------------------------

def test_eval_scoring_rules():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import eval_answers as ea

    ans = {"status": "answered", "claims": [{"text": "No prepayment charge applies", "span_ids": ["D4:1#s1"]},
                                            {"text": "EMI is due on the 5th", "span_ids": ["D1:6.2#s1"]}],
           "disagreements": [], "chains": [{"steps": [{"clause_id": "D1:7.2"}, {"clause_id": "D4:1"}], "in_force_step": 1}]}
    item = {"expect": {"status": "answered", "must_cite": ["D4:1", "D1:6.2"], "values": ["nil", "5th"],
                       "forbid_values_in_body": ["4%"], "forbid_cite": ["D5:1"], "conflict_subjects": [],
                       "chain": ["D1:7.2", "D4:1"]}}
    checks = ea.score_item(item, ans)
    assert all(checks.values()), checks
    bad = ea.score_item({"expect": {"status": "conflict", "must_cite": ["D9:1"], "values": ["6%"],
                                    "conflict_subjects": ["late_payment_fee"]}}, ans)
    assert not any(bad.values())
