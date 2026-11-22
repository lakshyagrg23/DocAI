"""M3 tests: RRF, planner contract, version status, hybrid retriever, evidence pack. Offline (fake models)."""
from __future__ import annotations

from datetime import date

import pytest
from test_ingest import PDFS, StubClient, corpus  # noqa: F401  (corpus = autouse fixture that builds the PDFs)

from core import config, db
from core.answer.plan import MAX_SUB_QUESTIONS, effective_as_of, make_plan, sanitise, search_queries
from core.ingest import pipeline
from core.llm.client import ModelUnavailable
from core.models import CalcPlan, QueryPlan
from core.retrieval import evidence
from core.retrieval import expand as ex
from core.retrieval.hybrid import Hit, Retriever, rrf

# ---- pure functions ----------------------------------------------------------


def test_rrf_scores_and_ordering():
    out = rrf([["a", "b", "c"], ["b", "d"]], k=60)
    assert out["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert out["a"] == pytest.approx(1 / 61) and out["d"] == pytest.approx(1 / 62)
    assert max(out, key=out.get) == "b"  # in both lists beats a first place in one list


@pytest.mark.parametrize("vf,vt,as_of,expected", [
    ("2024-01-15", "2025-04-01", "2025-03-31", "in_force"),
    ("2024-01-15", "2025-04-01", "2025-04-01", "superseded"),  # valid_to is exclusive
    ("2025-04-01", "2026-01-01", "2025-04-01", "in_force"),  # valid_from is inclusive
    ("2026-01-01", None, "2025-12-31", "future"),
    ("2026-01-01", None, "2099-01-01", "in_force"),
    (None, None, "1999-01-01", "in_force"),
])
def test_status_on(vf, vt, as_of, expected):
    assert ex.status_on(vf, vt, as_of) == expected


def test_where_label_and_format_span():
    assert evidence.where_label("7.2") == "cl. 7.2"
    assert evidence.where_label("table1.row2") == "table 1 row 2"
    assert evidence.where_label("p1.3") == "para p1.3"
    line = evidence.format_span("D1:7.2#s1", "Loan Agreement", "KF/1", "7.2", 3, "text here", "2024-01-15")
    assert line == "[D1:7.2#s1] (Loan Agreement KF/1, cl. 7.2, p.3, effective 2024-01-15) text here"


# ---- planner ------------------------------------------------------------------

def test_sanitise_enforces_contract():
    p = sanitise(QueryPlan(intent="lookup", sub_questions=["a", " ", "b", "c", "d"], as_of_override="June 2025"), "in June 2025?")
    assert p.sub_questions == ["a", "b", "c"][:MAX_SUB_QUESTIONS] and p.as_of_override is None
    p = sanitise(QueryPlan(intent="multi", sub_questions=[], as_of_override="2025-06-01"), "orig in 2025?")
    assert p.sub_questions == ["orig in 2025?"] and p.as_of_override == "2025-06-01" and p.intent == "history"
    p = sanitise(QueryPlan(intent="lookup", sub_questions=["a"], as_of_override="2025-08-19"), "What is the fee today?")
    assert p.as_of_override is None and p.intent == "lookup"  # a date the question never stated is dropped
    p = sanitise(QueryPlan(intent="lookup", sub_questions=["a"], as_of_override="2025-06-01"), "Fee as of June 2025?")
    assert p.as_of_override == "2025-06-01"
    p = sanitise(QueryPlan(intent="calculation", sub_questions=["x"], calc=CalcPlan(kind="none", given={"a": 1})), "q")
    assert p.calc.given == {}  # a calc without a kind carries no inputs


def test_search_queries_always_include_the_original_question():
    plan = QueryPlan(sub_questions=["part one", "part two"])
    assert search_queries(plan, " the whole question ") == ["part one", "part two", "the whole question"]
    assert search_queries(QueryPlan(sub_questions=["same"]), "same") == ["same"]


def test_effective_as_of_precedence():
    plan = QueryPlan(sub_questions=["q"], as_of_override="2025-01-01")
    assert effective_as_of(plan, "2026-01-01") == "2025-01-01"
    assert effective_as_of(QueryPlan(sub_questions=["q"]), "2026-01-01") == "2026-01-01"
    assert effective_as_of(QueryPlan(sub_questions=["q"]), None, today=date(2030, 5, 6)) == "2030-05-06"


def test_make_plan_uses_llm_then_falls_back():
    class Good:
        def chat_json(self, messages, model_cls, max_tokens=900):
            assert "Question: hello" in messages[-1]["content"]
            return QueryPlan(intent="multi", sub_questions=["s1", "s2"])

    plan, version = make_plan("hello", Good())
    assert plan.intent == "multi" and version == "v1"
    plan, version = make_plan("hello", StubClient())  # StubClient.chat_json raises ModelUnavailable
    assert plan.sub_questions == ["hello"] and version == "none"
    with pytest.raises(ModelUnavailable):
        StubClient().chat_json([], QueryPlan)


# ---- retriever + evidence on the ingested demo corpus ---------------------------

@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m3")
    conn = db.init_db(tmp / "corpus.db")
    client = StubClient()
    for p in sorted(PDFS.glob("D[1-5]*.pdf")):
        pipeline.enqueue(p, conn, start_worker=False)
    pipeline.run_pending(conn, client, tmp)
    return conn, client, tmp


def test_search_finds_lexical_match_and_respects_keep(env):
    conn, client, tmp = env
    hits = Retriever(conn, client, tmp).search("late payment fee per instalment")
    assert 0 < len(hits) <= config.RERANK_KEEP
    assert hits[0].clause_id in {"D2:table1.row2", "D1:8.1"}
    assert {"D2:table1.row2", "D1:8.1"} <= {h.clause_id for h in hits}
    assert hits == sorted(hits, key=lambda h: (-h.score, h.window_id))
    assert all(h.dense_rank or h.bm25_rank for h in hits)


def test_doc_scope_filters_before_fusion(env):
    conn, client, tmp = env
    r = Retriever(conn, client, tmp)
    hits = r.search("late payment fee per instalment", doc_scope=["D5"])
    assert hits and {h.doc_id for h in hits} == {"D5"}
    assert r.search("late payment fee", doc_scope=["NOPE"]) == []


def test_retrieve_unions_sub_questions_keeping_best_score(env):
    conn, client, tmp = env
    r = Retriever(conn, client, tmp)
    a, b = "late payment fee", "prepayment charge percent"
    merged = r.retrieve([a, b])
    ids = {h.window_id for h in merged}
    assert ids == {h.window_id for h in r.search(a)} | {h.window_id for h in r.search(b)}
    best: dict[str, float] = {}
    for h in r.search(a) + r.search(b):
        best[h.window_id] = max(h.score, best.get(h.window_id, float("-inf")))
    assert {h.window_id: h.score for h in merged} == pytest.approx(best)
    assert len(ids) == len(merged)


def test_retriever_reloads_after_reindex(env, tmp_path):
    conn = db.init_db(tmp_path / "c.db")
    client = StubClient()
    r = Retriever(conn, client, tmp_path)
    assert r.search("anything") == []  # empty index
    pipeline.enqueue(PDFS / "D5_fcb_circular.pdf", conn, start_worker=False)
    pipeline.run_pending(conn, client, tmp_path)
    assert {h.doc_id for h in r.search("penal charges instalment")} == {"D5"}


def hits_for(conn, *clause_ids, score=1.0):
    return [Hit(window_id=f"{c}@w1", clause_id=c, doc_id=c.split(":")[0], score=score - i * 0.01, rrf=0.0)
            for i, c in enumerate(clause_ids)]


def test_pack_contains_whole_clauses_with_formatted_lines(env):
    conn, _, _ = env
    pack = evidence.build_pack(conn, hits_for(conn, "D1:7.2", "D2:table1.row2"), "2024-06-01")
    ids = [s.span_id for s in pack.spans]
    assert ids == ["D1:7.2#s1", "D1:7.2#s2", "D2:table1.row2#s1"]
    first = pack.spans[0].line
    assert first.startswith("[D1:7.2#s1] (") and "cl. 7.2" in first and "p.3" in first and "effective 2024-01-15" in first
    assert "table 1 row 2" in pack.spans[2].line and pack.render().count("\n") == 2
    assert pack.span_ids() == set(ids) and not pack.truncated


def test_future_documents_are_context_not_evidence(env):
    conn, _, _ = env
    # D5 takes effect 2025-11-01: not in force on 2025-06-01 -> context only
    pack = evidence.build_pack(conn, hits_for(conn, "D5:1", "D1:8.1"), "2025-06-01")
    assert [s.clause_id for s in pack.spans] == ["D1:8.1"]
    assert [s.clause_id for s in pack.context_spans] == ["D5:1"] and pack.context_spans[0].status == "future"
    later = evidence.build_pack(conn, hits_for(conn, "D5:1"), "2026-01-01")
    assert [s.clause_id for s in later.spans] == ["D5:1"]


def test_pack_caps_by_spans_and_tokens_and_orders_by_score(env):
    conn, _, _ = env
    hits = hits_for(conn, "D1:8.1", "D1:7.2", "D2:table1.row2", "D5:1")
    capped = evidence.build_pack(conn, hits, "2026-11-22", max_spans=3)
    assert len(capped.spans) <= 3 and capped.truncated
    assert capped.spans[0].clause_id == "D1:8.1"  # best score first
    tiny = evidence.build_pack(conn, hits, "2026-11-22", max_tokens=1)
    assert tiny.spans == [] and tiny.truncated
    assert len(evidence.build_pack(conn, hits, "2026-11-22").spans) >= 5  # whole clauses (7.2 has two spans)


def test_expand_uses_version_rows_when_present(env):
    conn, _, _ = env
    conn.executemany("INSERT INTO clause_versions(version_key,version_no,clause_id,valid_from,valid_to,edge_id) "
                     "VALUES(?,?,?,?,?,?)", [("D1:7.2", 0, "D1:7.2", "2024-01-15", "2025-04-01", None),
                                              ("D1:7.2", 1, "D3:1", "2025-04-01", "2026-01-01", None),
                                              ("D1:7.2", 2, "D4:1", "2026-01-01", None, None)])
    try:
        out = ex.expand(conn, ["D1:7.2"], "2025-06-01")
        assert {c: v.status for c, v in out.items()} == {"D1:7.2": "superseded", "D3:1": "in_force", "D4:1": "future"}
        pack = evidence.build_pack(conn, hits_for(conn, "D1:7.2"), "2025-06-01")
        assert {s.clause_id for s in pack.spans} == {"D3:1"}  # the in-force version is pulled in via the version key
        assert {s.clause_id for s in pack.context_spans} == {"D1:7.2", "D4:1"}
    finally:
        conn.execute("DELETE FROM clause_versions")
        conn.commit()
