"""Orchestrates one answer (answering.md §0, §4): plan -> retrieve -> pack -> draft -> verify -> gate -> persist + log.

The calculator (calc.py) runs after verification: its inputs are verified claims or numbers in the question.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable

from core import config, db
from core import versions as version_graph
from core.answer import calc, disagree
from core.answer.draft import make_draft
from core.answer.gate import ABSTAIN_TEXT, gate
from core.answer.plan import effective_as_of, make_plan, search_queries
from core.answer.verify import verify_claims
from core.llm.client import ModelClient, get_client
from core.models import AnswerJSON
from core.retrieval.evidence import build_pack
from core.retrieval.hybrid import Retriever

Stage = Callable[[str], None]


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def answer(conn: sqlite3.Connection, question: str, chat_id: str | None = None, as_of: str | None = None,
           client: ModelClient | None = None, retriever: Retriever | None = None,
           on_stage: Stage | None = None, persist: bool = True) -> AnswerJSON:
    """Answer `question`. `as_of` overrides the chat's date; otherwise the chat's date, else today."""
    client = client or get_client()
    stage = on_stage or (lambda _s: None)
    retriever = retriever or Retriever(conn, client)
    chat = db.get_chat(conn, chat_id) if chat_id else None
    timings: dict[str, int] = {}
    versions: dict[str, str] = {}

    stage("Planning")
    t0 = time.perf_counter()
    plan, versions["plan"] = make_plan(question, client)
    as_of_date = effective_as_of(plan, as_of or (chat.as_of_date if chat else None))
    timings["plan"] = _ms(t0)

    stage("Retrieving")
    t0 = time.perf_counter()
    hits = retriever.retrieve(search_queries(plan, question), chat.doc_scope if chat else None)
    pack = build_pack(conn, hits, as_of_date)
    disagree.recheck(conn, sorted({s.clause_id for s in pack.spans}))
    disagree.add_partners(conn, pack, as_of_date)  # the other half of any conflict in effect must be shown too
    timings["retrieve"] = _ms(t0)

    claims, missing = [], []
    drafted_ok = True
    if pack.spans:
        stage("Drafting")
        t0 = time.perf_counter()
        draft, versions["draft"] = make_draft(question, as_of_date, pack, client, plan.calc.kind)
        timings["draft"] = _ms(t0)
        if draft is None:
            drafted_ok, missing = False, ["Drafting failed"]
        else:
            missing = draft.missing
            stage(f"Verifying {len(draft.claims)} claims")
            t0 = time.perf_counter()
            claims = verify_claims(draft.claims, pack, client, question)
            stage("Checking conflicts")
            disagree.mark_contradicted(conn, claims, as_of_date)
            timings["verify"] = _ms(t0)
    else:
        missing = ["No relevant passages were found in the uploaded documents"]

    cited = [sid.split("#")[0] for c in claims if c.verdict != "unsupported" for sid in c.span_ids]
    if plan.intent in ("current_rule", "history"):  # always show how the rule changed, even if only one version was cited
        cited += [s.clause_id for s in pack.spans]
    chains = version_graph.chains(conn, list(dict.fromkeys(cited)), as_of_date)
    disagreements = disagree.build_disagreements(conn, claims, as_of_date)
    calculation, calc_missing, used = calc.run(plan.calc, question, claims) if plan.calc.kind != "none" else (None, [], set())
    if calculation and calculation["result"] is not None:
        missing = []  # every required input was found, so the draft's own "missing" notes no longer apply
    if missing and not any(c.verdict != "unsupported" for c in claims):
        calc_missing = []  # nothing verified and the draft already says what is missing: don't add calculator noise
    result = gate(claims, missing + calc_missing, plan.sub_questions if drafted_ok and pack.spans else [])
    if calculation and calculation["result"] is not None:
        if result.status == "abstained":
            result.status = "answered"  # all inputs were stated in the question or verified; the working is the answer
        inputs_shown = {id(claims[i]) for i in used}
        result.supported = [c for c in result.supported if id(c) not in inputs_shown]  # shown in the calculation card
    ans = AnswerJSON(
        status=result.status, question=question, question_en=question, as_of_date=as_of_date, intent=plan.intent,
        claims=result.supported + result.contested, blocked_claims=result.blocked, missing_evidence=result.missing,
        disagreements=disagreements, calculation=calculation,
        chains=chains if result.status != "abstained" else [],
        faithfulness_pct=result.faithfulness_pct, drafted=result.drafted, passed=result.passed,
        prompt_versions=versions, timings_ms=timings, evidence_spans=[s.span_id for s in pack.spans])
    stage("Done")
    if persist:
        _persist(conn, chat_id, question, ans, plan.model_dump())
    return ans


def render_text(ans: AnswerJSON) -> str:
    """Plain-text form of the answer (stored as message content, used by exports)."""
    if ans.status == "abstained":
        lines = [ABSTAIN_TEXT]
    else:
        lines = [c.text for c in ans.claims]
    if ans.calculation and ans.calculation.get("result") is not None:
        lines += [f"Result: {calc.inr(ans.calculation['result'])}"]
    if ans.missing_evidence:
        lines += ["Missing: " + "; ".join(ans.missing_evidence)]
    return "\n".join(lines)


def _persist(conn: sqlite3.Connection, chat_id: str | None, question: str, ans: AnswerJSON, plan: dict) -> None:
    if chat_id:
        first = not db.list_messages(conn, chat_id)
        db.add_message(conn, chat_id, "user", question)
        db.add_message(conn, chat_id, "assistant", render_text(ans), ans.model_dump_json())
        if first:
            db.rename_chat(conn, chat_id, " ".join(question.split()[:6]))
    log = config.DATA_DIR / "logs"
    log.mkdir(parents=True, exist_ok=True)
    rec = {"ts": db.now_iso(), "chat_id": chat_id, "plan": plan, "answer": ans.model_dump()}
    with (log / "answers.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
