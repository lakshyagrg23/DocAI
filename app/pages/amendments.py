"""Amendments page (ui.md): version timelines, view-as-of, and amendments that point at documents we do not have."""
from __future__ import annotations

from datetime import date

import streamlit as st

from app import state
from app.components import cards, evidence
from core import versions

conn = state.get_conn()
st.header("Amendments")
keys = [r[0] for r in conn.execute("SELECT version_key FROM clause_versions GROUP BY version_key HAVING COUNT(*) > 1")]
if not keys:
    st.info("No clause has been amended in the uploaded documents.")
today = date.today().isoformat()
for i, vk in enumerate(keys):
    chain = versions.chains(conn, [vk], today)
    if not chain:
        continue
    with st.container(border=True):
        cards.timeline(chain[0], f"am{i}", "en", evidence.cite_button)
        at = st.date_input("View as of", value=date.today(), key=f"asof-{vk}").isoformat()
        clause_id = versions.clause_in_force(conn, vk, at)
        if clause_id:
            row = conn.execute("SELECT c.text,d.title FROM clauses c JOIN documents d ON d.doc_id=c.doc_id "
                               "WHERE c.clause_id=?", (clause_id,)).fetchone()
            st.markdown(f"**In force on {at}: {row['title']} ({clause_id})**")
            st.markdown(f"> {row['text']}")
        else:
            st.markdown(f"No version of {vk} is in force on {at} (not yet in force, or deleted).")

unresolved = conn.execute("SELECT e.raw_target_ref, e.action, c.doc_id FROM amendment_edges e "
                          "JOIN clauses c ON c.clause_id=e.source_clause_id WHERE e.resolved=0").fetchall()
if unresolved:
    st.subheader("Unresolved amendments")
    for u in unresolved:
        st.warning(f"{u['doc_id']} ({u['action']}) amends {u['raw_target_ref']}, which is not in the library.")
if st.session_state.get("evidence"):
    with st.expander("Evidence", expanded=True):
        evidence.evidence_viewer(conn)
