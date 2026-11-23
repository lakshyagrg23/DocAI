"""End-to-end answer scoring for scripts/eval.py (eval.md): per-item pass rules, global gates, HHEM threshold sweep."""
from __future__ import annotations

import json
import time
from pathlib import Path

from core import config, db
from core.answer import assemble
from core.answer.gate import gate
from core.answer.verify import apply_threshold, numbers_ok, quote_ok
from core.llm.client import ModelClient
from core.models import AnswerJSON, VerifiedClaim
from core.normalize import RE_NIL_CLAIM, normalize_text, number_tokens, source_values
from core.retrieval.hybrid import Retriever
from scripts import quote_check

NO_EVIDENCE_PREFIX = "No verified evidence for:"


def clause_of(span_id: str) -> str:
    return span_id.split("#")[0]


def cited_clauses(ans: dict) -> set[str]:
    out = {clause_of(s) for c in ans["claims"] for s in c["span_ids"]}
    for d in ans.get("disagreements", []):
        out |= {clause_of(side["span_id"]) for side in d.get("sides", [])}
    for ch in ans.get("chains", []):
        steps = ch.get("steps", [])
        if 0 <= ch.get("in_force_step", -1) < len(steps):
            out.add(steps[ch["in_force_step"]]["clause_id"])
    for i in (ans.get("calculation") or {}).get("inputs", []):
        if i.get("span_id"):
            out.add(clause_of(i["span_id"]))
    return out


def value_present(expected: str, texts: list[str]) -> bool:
    blob = " ".join(texts)
    if expected.strip().lower() == "nil":
        return bool(RE_NIL_CLAIM.search(blob))
    want = number_tokens(expected)
    if want:
        have = source_values(blob)
        return all(any(w[0] == h[0] and w[1] == h[1] for h in have) for w in want)
    return normalize_text(expected) in normalize_text(blob)


def score_item(item: dict, ans: dict) -> dict[str, bool]:
    """One bool per expectation field present on the item (eval.md per-item scoring)."""
    exp = item.get("expect", {})
    checks: dict[str, bool] = {"status": ans["status"] == exp["status"]}
    cited = cited_clauses(ans)
    texts = [c["text"] for c in ans["claims"]] + [d.get("explanation", "") for d in ans.get("disagreements", [])]
    calc = ans.get("calculation")
    if calc and calc.get("result") is not None:
        texts.append(f"{calc['result']:g}")
    if exp.get("must_cite"):
        checks["must_cite"] = all(c in cited for c in exp["must_cite"])
    if exp.get("forbid_cite"):
        checks["forbid_cite"] = not any(c in cited for c in exp["forbid_cite"])
    if exp.get("values"):
        checks["values"] = all(value_present(v, texts) for v in exp["values"])
    if exp.get("forbid_values_in_body"):
        body = [c["text"] for c in ans["claims"]]
        checks["forbid_values_in_body"] = not any(value_present(v, body) for v in exp["forbid_values_in_body"])
    if "conflict_subjects" in exp:
        subjects = {d["subject"] for d in ans.get("disagreements", [])}
        checks["conflict_subjects"] = (not subjects) if not exp["conflict_subjects"] else set(exp["conflict_subjects"]) <= subjects
    if exp.get("chain"):
        checks["chain"] = any([s["clause_id"] for s in ch["steps"]] == exp["chain"] for ch in ans.get("chains", []))
    if "calc_result" in exp:
        r = (calc or {}).get("result")
        checks["calc_result"] = r is not None and abs(r - exp["calc_result"]) <= exp.get("calc_tolerance", 0)
    if exp.get("ocr_badge"):
        checks["ocr_badge"] = False  # needs span rows; filled in by run() when it has the connection
    if "language" in exp:
        checks["language"] = ans.get("language") == exp["language"]
    return checks


def recheck_displayed(conn, ans: dict) -> list[str]:
    """Independent re-check of every displayed claim against raw span text (no evidence-header leniency)."""
    bad = []
    for c in ans["claims"]:
        rows = [conn.execute("SELECT s.text,d.title,d.ref_no,d.effective_date FROM spans s JOIN documents d "
                             "ON d.doc_id=s.doc_id WHERE s.span_id=?", (s,)).fetchone() for s in c["span_ids"]]
        if any(r is None for r in rows):
            bad.append(f"{c['text']} (unknown span)")
            continue
        # raw span text plus the document header (title, ref no, effective date): the verifiable context of design §2
        ctx = " ".join(f"{r['title'] or ''} {r['ref_no'] or ''} effective {r['effective_date'] or ''} {r['text']}" for r in rows)
        if not numbers_ok(c["text"], ctx)[0] or not quote_ok(c["text"], ctx):
            bad.append(c["text"])
    return bad


def run(items: list[dict], client: ModelClient) -> dict:
    conn = db.init_db()
    retriever = Retriever(conn, client)
    rows = []
    for it in items:
        t0 = time.perf_counter()
        ans = assemble.answer(conn, it["question"], None, as_of=it.get("as_of"), client=client, retriever=retriever,
                              persist=False)
        d = ans.model_dump()
        checks = score_item(it, d)
        if "ocr_badge" in checks:
            ids = [s for c in d["claims"] for s in c["span_ids"]]
            checks["ocr_badge"] = any(conn.execute("SELECT ocr_conf FROM spans WHERE span_id=?", (s,)).fetchone()[0]
                                      is not None for s in ids)
        q_checked, q_bad = quote_check.mismatches(conn, d)
        rows.append({"quote_checked": q_checked, "quote_mismatch": q_bad, "id": it["id"], "type": it["type"], "question": it["question"], "expect": it["expect"],
                     "answer": d, "checks": checks, "pass": all(checks.values()), "unsupported_displayed": recheck_displayed(conn, d),
                     "secs": round(time.perf_counter() - t0, 1)})
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    unans = [r for r in rows if r["type"] == "unanswerable"]
    answerable = [r for r in rows if r["expect"]["status"] != "abstained"]
    faith = [r["answer"]["faithfulness_pct"] for r in rows if r["answer"]["status"] != "abstained"
             and r["answer"]["faithfulness_pct"] is not None]
    secs = sorted(r["secs"] for r in rows)
    return {"items": rows, "n": len(rows), "passed": sum(r["pass"] for r in rows),
            "unsupported_displayed": sum(len(r["unsupported_displayed"]) for r in rows),
            "quote_exactness": f"{sum(r.get('quote_checked', 0) - len(r.get('quote_mismatch', [])) for r in rows)}/"
                               f"{sum(r.get('quote_checked', 0) for r in rows)}",
            "abstain_recall": f"{sum(r['answer']['status'] == 'abstained' for r in unans)}/{len(unans)}",
            "false_abstain": f"{sum(r['answer']['status'] == 'abstained' for r in answerable)}/{len(answerable)}",
            "faithfulness_avg": round(sum(faith) / len(faith), 1) if faith else None,
            "p50_s": secs[len(secs) // 2] if secs else None, "p95_s": secs[int(len(secs) * 0.95) - 1] if secs else None}


def report(res: dict, verbose: bool = False) -> None:
    for r in res["items"]:
        failed = [k for k, v in r["checks"].items() if not v]
        a = r["answer"]
        print(f"{'ok  ' if r['pass'] else 'FAIL'} {r['id']:<4} {r['type']:<17} {a['status']:<9} (want {r['expect']['status']:<9}) "
              f"claims={len(a['claims'])} blocked={len(a['blocked_claims'])} {r['secs']:>5.1f}s  {r['question'][:50]}")
        if failed or verbose:
            print(f"       failed={failed}")
            for c in a["claims"]:
                print(f"       + {c['text']}  {c['span_ids']}")
            for c in a["blocked_claims"]:
                print(f"       - {c['text']}  [{c['reason']}]")
            if a["missing_evidence"]:
                print(f"       missing={a['missing_evidence']}")
    print(f"\nitems {res['passed']}/{res['n']}   unsupported displayed: {res['unsupported_displayed']} (gate 0)   "
          f"quote exactness {res.get('quote_exactness')} (gate 100%)   abstention recall {res['abstain_recall']}   false abstain {res['false_abstain']}   "
          f"faithfulness avg {res['faithfulness_avg']}   p50 {res['p50_s']}s p95 {res['p95_s']}s")


def save(res: dict) -> Path:
    d = config.DATA_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def latest_run() -> dict:
    files = sorted((config.DATA_DIR / "logs").glob("eval_2*.json"))
    if not files:
        raise SystemExit("no saved eval run: run scripts/eval.py first")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def sweep(thresholds: list[float], items_by_id: dict[str, dict]) -> None:
    """Re-decide every saved claim at each HHEM threshold, re-gate, re-score. No model calls."""
    res = latest_run()
    print(f"{'thr':>5} {'items':>7} {'false-abst':>11} {'abst-recall':>12} {'blocked-by-hhem':>16}")
    for t in thresholds:
        rows = []
        for r in res["items"]:
            a = r["answer"]
            claims = [apply_threshold(VerifiedClaim.model_validate(c), t) for c in a["claims"] + a["blocked_claims"]]
            miss = [m for m in a["missing_evidence"] if not m.startswith(NO_EVIDENCE_PREFIX)]
            g = gate(claims, miss, [r["question"]])
            new = AnswerJSON.model_validate({**a, "status": g.status, "claims": [c.model_dump() for c in g.supported + g.contested],
                                            "blocked_claims": [c.model_dump() for c in g.blocked], "missing_evidence": g.missing})
            d = new.model_dump()
            checks = score_item(items_by_id[r["id"]], d)
            rows.append({**r, "answer": d, "checks": checks, "pass": all(checks.values())})
        s = summarise(rows)
        hh = sum(1 for r in rows for c in r["answer"]["blocked_claims"] if (c["checks"]["hhem"] is not None))
        print(f"{t:>5} {s['passed']:>3}/{s['n']:<3} {s['false_abstain']:>11} {s['abstain_recall']:>12} {hh:>16}")
