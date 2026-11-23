"""Markdown export of a chat (M10). Everything comes from stored answers: quotes are the stored span text, nothing is
regenerated, so the export carries the same evidence the screen showed. Presentation only."""
from __future__ import annotations

import json
import re
import sqlite3

from api import serialize
from core import db
from core.answer.calc import inr
from core.answer.gate import ABSTAIN_TEXT
from core.models import Chat, Message

STATUS = {"answered": "Answered", "partial": "Partly answered", "conflict": "Documents disagree", "abstained": "No proof found"}


def _quote(text: str | None) -> str:
    return "\n".join(f"> {line}" for line in (text or "").strip().splitlines() or [""])


def _place(src: dict) -> str:
    bits = [src["doc_name"], src["clause_label"], f"page {src['page']}"]
    if src.get("ocr"):
        bits.append("scanned page")
    return ", ".join(b for b in bits if b)


def _cites(span_ids: list[str], sources: dict) -> str:
    return " ".join(f"[{sources[s]['n']}]" for s in span_ids if s in sources)


def answer_md(ans: dict) -> list[str]:
    """One enriched answer (serialize.enrich_answer) as Markdown lines."""
    src: dict = ans["sources"]
    out = [f"**{STATUS.get(ans['status'], ans['status'])}** · rules as of {ans['as_of_date']}"]
    if ans.get("faithfulness_pct") is not None and ans.get("drafted"):
        out[0] += f" · {ans['passed']} of {ans['drafted']} drafted statements passed verification ({ans['faithfulness_pct']:.0f}%)"
    out.append("")
    if ans["status"] == "abstained":
        out += [ABSTAIN_TEXT, ""]
    for c in ans.get("claims", []):
        flag = " *(contested: the documents disagree)*" if c["verdict"] == "contradicted" else ""
        out.append(f"- {c['text']} {_cites(c['span_ids'], src)}{flag}".rstrip())
    if ans.get("claims"):
        out.append("")
    calc = ans.get("calculation")
    if calc:
        out.append("**Calculation**" + (f": {calc['formula']}" if calc.get("formula") else ""))
        for i in calc.get("inputs", []):
            where = _cites([i["span_id"]], src) if i.get("span_id") else "from your question"
            out.append(f"- {i['name']}: {i['value']:g} {where}")
        out += [f"- {s}" for s in calc.get("steps", [])]
        out += [f"- **Result: {inr(calc['result'])}**" if calc.get("result") is not None else "- No single result", ""]
    for d in ans.get("disagreements", []):
        out.append(f"**Documents disagree** ({d['subject']}): {d['explanation']}")
        for s in d["sides"]:
            out.append(f"- {s.get('doc_name') or s['doc']}, {s.get('clause_label') or s['clause_id']}: {s['value']} {_cites([s['span_id']], src)}")
        out.append("")
    for ch in ans.get("chains", []):
        out.append(f"**How this rule changed** ({ch.get('label') or ch['version_key']})")
        for i, st in enumerate(ch["steps"]):
            span = f" {_cites([st['span_id']], src)}" if st.get("span_id") else ""
            when = f"from {st['valid_from']}" if st.get("valid_from") else "original"
            mark = " ← in force" if i == ch.get("in_force_step") else ""
            out.append(f"- {st.get('doc_name') or st.get('doc_id') or ''} ({st['action']}, {when}){span}{mark}")
        out.append("")
    if ans.get("missing_evidence"):
        out.append("**Not found in the documents**")
        out += [f"- {m}" for m in ans["missing_evidence"]] + [""]
    if src:
        out.append("**Sources**")
        out.append("")
        for s in src.values():
            out += [f"[{s['n']}] {_place(s)}", "", _quote(s["text"]), ""]
    return out


def chat_markdown(conn: sqlite3.Connection, chat: Chat, messages: list[Message]) -> str:
    lines = [f"# {chat.title}", ""]
    ws = db.get_workspace(conn, chat.workspace_id) if chat.workspace_id else None
    allowed = db.workspace_doc_ids(conn, ws.workspace_id) if ws else None
    meta = ([f"Workspace: {ws.name}"] if ws else []) + [f"Rules as of {chat.as_of_date or 'today'}"]
    if chat.doc_scope:
        names = [serialize.doc_name_for(conn, d) or d for d in chat.doc_scope]
        meta.append("Documents: " + ", ".join(names))
    else:
        meta.append("Documents: all documents in the workspace" if ws else "Documents: all uploaded documents")
    lines += [" · ".join(meta), ""]
    n = 0
    for m in messages:
        if m.role == "user":
            n += 1
            lines += ["---", "", f"## Question {n}", "", m.content, ""]
        elif m.answer_json:
            lines += answer_md(serialize.enrich_answer(conn, json.loads(m.answer_json), allowed))
        else:
            lines += [m.content, ""]
    lines += ["---", "", "*Every statement above was checked against the cited quotation before it was shown.*", ""]
    return "\n".join(lines)


def filename(chat: Chat) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", chat.title).strip("-").lower()[:40] or "chat"
    return f"{slug}.md"


def build(conn: sqlite3.Connection, chat_id: str) -> tuple[str, str] | None:
    chat = db.get_chat(conn, chat_id)
    if chat is None:
        return None
    return filename(chat), chat_markdown(conn, chat, db.list_messages(conn, chat_id))
