"""Conflicts page (ui.md): every conflict in force on a date, grouped by subject, sides side by side."""
from __future__ import annotations

from datetime import date

import streamlit as st

from app import state
from app.components import cards, evidence
from core.answer import disagree

conn = state.get_conn()
st.header("Conflicts")
subjects = [r[0] for r in conn.execute("SELECT DISTINCT subject_id FROM conflicts ORDER BY 1")]
types = [r[0] for r in conn.execute("SELECT DISTINCT type FROM conflicts ORDER BY 1")]
c1, c2, c3 = st.columns(3)
subject = c1.selectbox("Subject", ["(all)", *subjects])
kind = c2.selectbox("Type", ["(all)", *types])
at = c3.date_input("In force at", value=date.today()).isoformat()

ids = [i for i in disagree.active_conflict_ids(conn, at)
       if (subject == "(all)" or conn.execute("SELECT subject_id FROM conflicts WHERE conflict_id=?", (i,)).fetchone()[0] == subject)
       and (kind == "(all)" or conn.execute("SELECT type FROM conflicts WHERE conflict_id=?", (i,)).fetchone()[0] == kind)]
found = disagree.cards_from_ids(conn, ids, at)
if not found:
    st.info("No documents disagree on this date." if subjects else "No conflicts were detected in the uploaded documents.")
for i, card in enumerate(found):
    with st.container(border=True):
        cards.disagreement_card(card, f"cf{i}", "en", evidence.cite_button)
if st.session_state.get("evidence"):
    with st.expander("Evidence", expanded=True):
        evidence.evidence_viewer(conn)
