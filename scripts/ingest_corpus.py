"""Ingest corpus/pdfs into DATA_DIR. Usage: python scripts/ingest_corpus.py [--reset] [--pdf-dir DIR]."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config, db
from core.ingest import pipeline

KNOWN = {"corpus.db", "corpus.db-wal", "corpus.db-shm", "index", "pages", "uploads", "logs", "subjects.npy", "cache"}


def reset_data_dir(d: Path) -> None:
    """Wipe DATA_DIR, but only if it looks like ours (refuses to delete arbitrary folders)."""
    if not d.exists():
        return
    foreign = [p.name for p in d.iterdir() if p.name not in KNOWN]
    if foreign:
        raise SystemExit(f"refusing to reset {d}: unexpected entries {foreign[:5]}")
    shutil.rmtree(d)


def count(conn, table: str, doc_id: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE doc_id=?", (doc_id,)).fetchone()[0]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="wipe DATA_DIR first")
    ap.add_argument("--pdf-dir", default=str(Path(__file__).resolve().parents[1] / "corpus" / "pdfs"))
    args = ap.parse_args()

    if args.reset:
        reset_data_dir(config.DATA_DIR)
    conn = db.init_db()
    pdfs = sorted(Path(args.pdf_dir).glob("*.pdf"), key=lambda p: p.name)
    if not pdfs:
        print(f"no PDFs in {args.pdf_dir}; run python corpus/generate.py")
        return 1
    t_all = time.perf_counter()
    for p in pdfs:
        t0 = time.perf_counter()
        job = pipeline.enqueue(p, conn, start_worker=False)
        pipeline.run_pending(conn)
        state = conn.execute("SELECT state,error FROM ingest_jobs WHERE job_id=?", (job,)).fetchone()
        print(f"{p.name:<30} {state['state']:<10} {time.perf_counter() - t0:6.1f}s {state['error'] or ''}")
    print(f"total {time.perf_counter() - t_all:.1f}s\n")
    print(f"{'doc':<5}{'status':<9}{'pages':>6}{'clauses':>9}{'spans':>7}{'windows':>9}  detail")
    for d in db.list_documents(conn):
        counts = [count(conn, t, d.doc_id) for t in ("clauses", "spans", "windows")]
        print(f"{d.doc_id:<5}{d.status:<9}{d.pages or 0:>6}{counts[0]:>9}{counts[1]:>7}{counts[2]:>9}  "
              f"{d.status_detail or ''}  [{d.title} | {d.ref_no} | {d.doc_type} | eff {d.effective_date}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
