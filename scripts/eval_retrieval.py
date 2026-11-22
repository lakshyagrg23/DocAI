"""Retrieval-only scoring for scripts/eval.py (eval.md; retrieval.md §5): recall of expected clauses among kept windows."""
from __future__ import annotations

import json
import time
from pathlib import Path

from core import config, db
from core.answer.plan import effective_as_of, make_plan, search_queries
from core.llm.client import ModelClient
from core.models import QueryPlan
from core.retrieval.hybrid import Retriever

GATE = 0.90


def _cache_path() -> Path:
    d = config.DATA_DIR / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "plans.json"


def _load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run(items: list[dict], client: ModelClient, use_cache: bool = True) -> dict:
    """Plan + retrieve for every item that has must_cite. Returns the report dict."""
    conn = db.init_db()
    retriever = Retriever(conn, client)
    cache = _load_cache() if use_cache else {}
    rows, expected_total, found_total = [], 0, 0
    for it in items:
        must = it.get("expect", {}).get("must_cite") or []
        if not must:
            continue
        key = f"{config.LLM_MODEL}|{it['question']}"
        t0 = time.perf_counter()
        if key in cache:
            plan, pv = QueryPlan.model_validate(cache[key]["plan"]), cache[key]["version"]
        else:
            plan, pv = make_plan(it["question"], client)
            cache[key] = {"plan": plan.model_dump(), "version": pv}
        hits = retriever.retrieve(search_queries(plan, it["question"]))
        by_clause: dict[str, int] = {}
        for rank, h in enumerate(hits, 1):
            by_clause.setdefault(h.clause_id, rank)
        found = [c for c in must if c in by_clause]
        missing = [c for c in must if c not in by_clause]
        expected_total += len(must)
        found_total += len(found)
        rows.append({"id": it["id"], "type": it["type"], "question": it["question"], "must": must,
                     "found": found, "missing": missing, "ranks": {c: by_clause[c] for c in found},
                     "plan": plan.model_dump(), "prompt_version": pv, "as_of": effective_as_of(plan, it.get("as_of")),
                     "n_windows": len(hits), "secs": round(time.perf_counter() - t0, 1),
                     "top": [(h.clause_id, round(h.score, 3)) for h in hits[:10]]})
    if use_cache:
        _cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    clause_recall = found_total / expected_total if expected_total else 0.0
    item_recall = sum(1 for r in rows if not r["missing"]) / len(rows) if rows else 0.0
    return {"items": rows, "clause_recall": clause_recall, "item_recall": item_recall,
            "expected": expected_total, "found": found_total, "gate": GATE, "pass": clause_recall >= GATE}


def report(res: dict, verbose: bool = False) -> None:
    for r in res["items"]:
        flag = "ok " if not r["missing"] else "MISS"
        print(f"{flag} {r['id']:<4} {r['type']:<17} found {len(r['found'])}/{len(r['must'])} "
              f"windows={r['n_windows']:<3} {r['secs']:>5.1f}s  {r['question'][:60]}")
        if r["missing"]:
            print(f"       missing {r['missing']}  plan.sub_questions={r['plan']['sub_questions']}")
            print(f"       top: {r['top'][:8]}")
        elif verbose:
            print(f"       ranks {r['ranks']}  subs={r['plan']['sub_questions']}")
    print(f"\nclause recall@8: {res['found']}/{res['expected']} = {res['clause_recall']:.1%}   "
          f"(item recall {res['item_recall']:.1%})   gate >= {res['gate']:.0%}: "
          f"{'PASS' if res['pass'] else 'FAIL'}")


def save(res: dict) -> Path:
    d = config.DATA_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"eval_retrieval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
