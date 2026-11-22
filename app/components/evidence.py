"""Evidence viewer (ui.md): the cited page with the span highlighted, OCR badge, page navigation, full clause."""
from __future__ import annotations

import json
import sqlite3

import streamlit as st

from core.render import highlight


def span_info(conn: sqlite3.Connection, span_id: str) -> dict | None:
    r = conn.execute(
        "SELECT s.span_id,s.clause_id,s.doc_id,s.page,s.text,s.bboxes,s.ocr_conf,c.path,c.text AS clause_text,"
        "d.title,d.ref_no,d.pages FROM spans s JOIN clauses c ON c.clause_id=s.clause_id "
        "JOIN documents d ON d.doc_id=s.doc_id WHERE s.span_id=?", (span_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["bboxes"] = json.loads(d["bboxes"] or "[]")
    return d


@st.cache_data(show_spinner=False, max_entries=64)
def _png(path: str, page: int, boxes: tuple, ocr: bool) -> bytes:
    return highlight.render(path, page, [list(b) for b in boxes], dpi=110, ocr=ocr)


def show_page(conn: sqlite3.Connection, doc_id: str, page: int, boxes: list[list[float]] | None = None,
              ocr: bool = False) -> None:
    path = highlight.pdf_path(conn, doc_id)
    if path is None:
        st.warning("The original PDF is not available on this server, so the page image cannot be shown.")
        return
    st.image(_png(str(path), page, tuple(tuple(b) for b in (boxes or [])), ocr), width="stretch")


def cite_button(span_id: str, label: str, key: str) -> None:
    """A citation pill: selects the span in the evidence viewer."""
    if st.button(label, key=key, help=span_id, type="secondary"):
        st.session_state["evidence"] = span_id
        st.session_state["ev_page"] = None


def evidence_viewer(conn: sqlite3.Connection, default_span: str | None = None) -> None:
    span_id = st.session_state.get("evidence") or default_span
    st.subheader("Evidence")
    if not span_id:
        st.caption("Click a citation to see the source page with the quote highlighted.")
        return
    info = span_info(conn, span_id)
    if info is None:
        st.caption(f"Span {span_id} not found.")
        return
    total = info["pages"] or 1
    page = st.session_state.get("ev_page") or info["page"]
    ocr = info["ocr_conf"] is not None
    st.markdown(f"**{info['title']}** · page {page}/{total}"
                + (f" · :orange-badge[OCR {info['ocr_conf']:.0%}]" if ocr else ""))
    left, mid, right = st.columns([1, 3, 1])
    if left.button("◀", key="ev-prev", disabled=page <= 1):
        st.session_state["ev_page"] = page - 1
        st.rerun()
    mid.caption(f"{info['clause_id']} · {span_id}")
    if right.button("▶", key="ev-next", disabled=page >= total):
        st.session_state["ev_page"] = page + 1
        st.rerun()
    show_page(conn, info["doc_id"], page, info["bboxes"] if page == info["page"] else None, ocr)
    with st.expander("Open full clause"):
        st.markdown(info["clause_text"])
