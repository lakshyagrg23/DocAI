"""Documents page (ui.md): upload + live ingest status, document table, clause outline with page viewer."""
from __future__ import annotations

import hashlib

import streamlit as st

from app import state
from app.components import evidence
from core import config, versions
from core.ingest import pipeline

conn = state.get_conn()
st.header("Documents")

uploads = st.file_uploader("Upload PDFs", type="pdf", accept_multiple_files=True, key="uploader")
seen = st.session_state.setdefault("uploaded_hashes", set())
for f in uploads or []:
    data = f.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if digest in seen:
        continue
    seen.add(digest)
    dest_dir = config.DATA_DIR / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f.name
    dest.write_bytes(data)
    pipeline.enqueue(dest, conn)
    st.toast(f"{f.name} queued")


def doc_rows() -> list[dict]:
    rows = []
    for d in conn.execute("SELECT * FROM documents ORDER BY doc_id"):
        rows.append({"id": d["doc_id"], "title": d["title"], "type": d["doc_type"], "ref no": d["ref_no"],
                     "issued": d["issue_date"], "effective": d["effective_date"], "pages": d["pages"],
                     "clauses": conn.execute("SELECT COUNT(*) FROM clauses WHERE doc_id=?", (d["doc_id"],)).fetchone()[0],
                     "facts": conn.execute("SELECT COUNT(*) FROM facts f JOIN clauses c ON c.clause_id=f.clause_id "
                                           "WHERE c.doc_id=?", (d["doc_id"],)).fetchone()[0],
                     "OCR": bool(d["has_ocr"]),
                     "status": d["status"] + (f" ({d['status_detail']})" if d["status_detail"] and d["status"] != "Ready" else "")})
    return rows


busy = any(r["status"].split(" (")[0] not in ("Ready", "Failed", "Queued") for r in doc_rows())


@st.fragment(run_every=2 if busy else None)
def table() -> None:
    rows = doc_rows()
    st.dataframe(rows, width="stretch", hide_index=True)
    if busy and all(r["status"].split(" (")[0] in ("Ready", "Failed", "Queued") for r in rows):
        st.rerun()


table()

docs = {r["id"]: r for r in doc_rows() if r["clauses"]}
if docs:
    st.subheader("Outline")
    doc_id = st.selectbox("Document", list(docs), format_func=lambda i: f"{i} · {docs[i]['title']}")
    today = state.today_iso()
    left, right = st.columns([2, 3])
    with left:
        for c in conn.execute("SELECT clause_id,path,text,page_start,version_key FROM clauses WHERE doc_id=? ORDER BY ord",
                              (doc_id,)):
            chip = ""
            if versions.status(conn, c["clause_id"], today) == "superseded":
                nxt = versions.clause_in_force(conn, c["version_key"], today)
                chip = f" :orange-badge[superseded by {nxt or 'deletion'}]"
            with st.expander(f"{c['path']} · p.{c['page_start']}{chip}"):
                st.markdown(c["text"])
                if st.button("Show page", key=f"show-{c['clause_id']}"):
                    st.session_state["doc_page"] = (doc_id, c["page_start"])
    with right:
        shown_doc, page = st.session_state.get("doc_page", (doc_id, 1))
        if shown_doc != doc_id:
            page = 1
        evidence.show_page(conn, doc_id, page)
