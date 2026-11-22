"""Shared cards: documents-disagree block and the version timeline (ui.md answer card 4 and 5)."""
from __future__ import annotations

import streamlit as st

from app.i18n import t

STATUS_CHIP = {"in_force": ":green-badge[in force]", "superseded": ":orange-badge[superseded]",
               "future": ":blue-badge[not yet in force]", "deleted": ":red-badge[deleted]"}


def row_table(text: str) -> dict[str, str] | None:
    """A table-row span is stored as 'Header: cell | Header: cell'. Return {header: cell} or None for normal text."""
    parts = [p.strip() for p in text.split(" | ")]
    if len(parts) < 2 or not all(": " in p for p in parts):
        return None
    return dict(p.split(": ", 1) for p in parts)


def quote_block(text: str) -> None:
    table = row_table(text)
    if table:
        st.table([table])
    else:
        st.markdown(f"> {text}")


def disagreement_card(card: dict, key: str, lang: str = "en", on_cite=None) -> None:
    """One card per subject, one column per side: title, clause, page, status, verbatim quote, citation pill."""
    st.markdown(f"**{t('disagree', lang)}: {card['subject'].replace('_', ' ')}** "
                f":gray-badge[{card.get('type', '')}] :red-badge[{card.get('severity', '')}]")
    sides = card["sides"]
    cols = st.columns(max(len(sides), 1))
    for i, (col, side) in enumerate(zip(cols, sides, strict=False)):
        with col, st.container(border=True):
            st.markdown(f"**{side.get('doc_title') or side['doc']}**  \n{side['clause_id']} · p.{side.get('page')}  \n"
                        f"{STATUS_CHIP.get(side.get('status', 'in_force'), '')}"
                        f"{' :orange-badge[OCR]' if side.get('ocr') else ''}")
            if side.get("text"):
                quote_block(side["text"])
            if on_cite:
                on_cite(side["span_id"], f"{side['doc']} · p.{side.get('page')}", f"{key}-side{i}")
    if card.get("explanation"):
        st.caption(card["explanation"])


def timeline(chain: dict, key: str, lang: str = "en", on_cite=None) -> None:
    """Vertical timeline of a version key: one row per step, the in-force step highlighted."""
    st.markdown(f"**{t('rule_in_force', lang)}** · `{chain['version_key']}`")
    for i, step in enumerate(chain["steps"]):
        active = i == chain.get("in_force_step")
        end = step.get("valid_to") or "present"
        title = step.get("doc_title") or step.get("doc_id") or "-"
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            clause = f" ({step['clause_id']})" if step.get("clause_id") else ""
            badge = "  :green-badge[in force]" if active else ""
            c1.markdown(f"{'🟢 ' if active else ''}**{step.get('valid_from') or '…'} → {end}** · {step['action']} · "
                        f"{title}{clause}{badge}")
            if step.get("text"):
                c1.markdown(f"> {step['text']}")
            if on_cite and step.get("span_id"):
                with c2:
                    on_cite(step["span_id"], f"{(step.get('doc_id') or '')} · quote", f"{key}-step{i}")
