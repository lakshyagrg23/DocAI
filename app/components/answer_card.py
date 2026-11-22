"""The answer card (ui.md §Chat page, items 1-9). Renders one `answer_json` dict."""
from __future__ import annotations

import json
import sqlite3

import streamlit as st

from app.components import cards, evidence
from app.i18n import t

CHIP = {"answered": ("✅", "green"), "partial": ("◐", "orange"), "conflict": ("⚠", "red"), "abstained": ("⛔", "gray")}


def _pill_factory(conn: sqlite3.Connection):
    def pill(span_id: str, label: str, key: str) -> None:
        info = evidence.span_info(conn, span_id)
        text = f"{info['doc_id']} · p.{info['page']}" if info else label
        evidence.cite_button(span_id, text, key)
    return pill


def render(conn: sqlite3.Connection, ans: dict, key: str, lang: str = "en") -> None:
    pill = _pill_factory(conn)
    icon, color = CHIP.get(ans["status"], ("", "gray"))
    st.badge(f"{icon} {t(ans['status'], lang)}", color=color)
    if ans.get("faithfulness_pct") is not None:
        st.caption(f"{t('faithfulness', lang)} {ans['faithfulness_pct']:.0f}% · {ans['passed']} of {ans['drafted']} drafted "
                   f"claims verified · as of {ans['as_of_date']}")
    else:
        st.caption(f"{t('faithfulness', lang)} — · as of {ans['as_of_date']}")

    if ans["status"] == "abstained":
        st.info(t("abstain_text", lang))
    for i, c in enumerate(ans["claims"]):
        st.markdown(f"{'⚠ ' if c['verdict'] == 'contradicted' else ''}{c['text']}")
        cols = st.columns(min(max(len(c["span_ids"]), 1), 4) + 1)
        for j, sid in enumerate(c["span_ids"][:4]):
            with cols[j]:
                pill(sid, sid, f"{key}-c{i}-{j}")
        with st.expander(t("quote", lang)):
            for sid in c["span_ids"]:
                info = evidence.span_info(conn, sid)
                if info:
                    st.caption(f"{info['title']} · {info['clause_id']} · p.{info['page']}")
                    cards.quote_block(info["text"])

    for i, card in enumerate(ans.get("disagreements", [])):
        cards.disagreement_card(card, f"{key}-d{i}", lang, pill)
    for i, chain in enumerate(ans.get("chains", [])):
        cards.timeline(chain, f"{key}-t{i}", lang, pill)
    if ans.get("calculation"):
        _calculation(ans["calculation"], key, lang, pill)
    if ans.get("missing_evidence"):
        st.markdown(f"**{t('missing', lang)}**")
        for m in ans["missing_evidence"]:
            st.markdown(f"- {m}")
    if ans.get("blocked_claims"):
        with st.expander(f"{t('blocked', lang)} ({len(ans['blocked_claims'])})"):
            for c in ans["blocked_claims"]:
                ch = c["checks"]
                st.markdown(f"~~{c['text']}~~  \n:red[{c.get('reason') or 'blocked'}]")
                st.caption(f"numbers_ok={ch['numbers_ok']} · quote_ok={ch['quote_ok']} · version_ok={ch['version_ok']} · "
                           f"hhem={None if ch.get('hhem') is None else round(ch['hhem'], 2)}")
    with st.expander(t("audit", lang)):
        st.download_button("Download answer JSON", json.dumps(ans, ensure_ascii=False, indent=2),
                           file_name="answer.json", mime="application/json", key=f"{key}-dl")


def _calculation(calc: dict, key: str, lang: str, pill) -> None:
    st.markdown(f"**{t('calculation', lang)}**")
    if calc.get("formula"):
        st.latex(calc["formula"])
    rows = [{"input": i["name"], "value": i["value"], "source": i.get("span_id") or "from your question"}
            for i in calc.get("inputs", [])]
    if rows:
        st.table(rows)
    for s in calc.get("steps", []):
        st.markdown(f"- {s}")
    if calc.get("result") is not None:
        st.markdown(f"**= {calc['result']:,.0f} {calc.get('unit', '')}**")
    for i, inp in enumerate(calc.get("inputs", [])):
        if inp.get("span_id"):
            pill(inp["span_id"], inp["span_id"], f"{key}-calc{i}")
