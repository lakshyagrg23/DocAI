"""Acceptance eval (eval.md): retrieval-only recall (M3) and full answer scoring (M4+) over tests/qa.yaml."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QA_PATH = ROOT / "tests" / "qa.yaml"


def load_qa(path: Path = QA_PATH) -> tuple[dict, list[dict]]:
    """Return (defaults, items). Each item gets its effective `as_of` filled from defaults."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    items = data["items"]
    for it in items:
        it.setdefault("as_of", defaults.get("as_of"))
    return defaults, items


def select(items: list[dict], only: str | None, type_: str | None, skip_types: str | None) -> list[dict]:
    if only:
        ids = {s.strip() for s in only.split(",")}
        items = [i for i in items if i["id"] in ids]
    if type_:
        items = [i for i in items if i["type"] == type_]
    if skip_types:
        skip = {s.strip() for s in skip_types.split(",")}
        items = [i for i in items if i["type"] not in skip]
    return items


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # questions contain the rupee sign; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--qa", default=str(QA_PATH), help="question file (tests/heldout.yaml for the held-out set; use DATA_DIR=./data_heldout)")
    ap.add_argument("--only")
    ap.add_argument("--type")
    ap.add_argument("--skip-types")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--no-cache", action="store_true", help="re-run the planner instead of using cached plans")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--hhem-sweep")
    args = ap.parse_args()

    _, items = load_qa(Path(args.qa))
    items = select(items, args.only, args.type, args.skip_types)
    if args.retrieval_only:
        import eval_retrieval  # sibling module in scripts/

        from core.llm.client import get_client

        res = eval_retrieval.run(items, get_client(), use_cache=not args.no_cache)
        eval_retrieval.report(res, args.verbose)
        print(f"saved {eval_retrieval.save(res)}")
        return 0 if res["pass"] else 1
    if args.hhem_sweep:
        import eval_answers

        eval_answers.sweep([float(x) for x in args.hhem_sweep.split(",")], {i["id"]: i for i in load_qa()[1]})
        return 0
    import eval_answers

    from core.llm.client import get_client

    res = eval_answers.run(items, get_client())
    eval_answers.report(res, args.verbose)
    print(f"saved {eval_answers.save(res)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
