"""Streamlit entry point: `streamlit run app/main.py`. Navigation + sidebar; no business logic (ui.md)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app import state
from app.components import sidebar

st.set_page_config(page_title="Verifiable DocAI", page_icon="🔎", layout="wide")
chat = sidebar.render(state.get_conn())
pages = [st.Page("pages/chat.py", title="Chat", icon="💬", default=True),
         st.Page("pages/documents.py", title="Documents", icon="📄"),
         st.Page("pages/conflicts.py", title="Conflicts", icon="⚠"),
         st.Page("pages/amendments.py", title="Amendments", icon="🕓")]
st.navigation(pages).run()
