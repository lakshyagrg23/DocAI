"""Draft (answering.md §1): one guided-JSON LLM call that turns the evidence pack into cited atomic claims."""
from __future__ import annotations

from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import Draft
from core.retrieval.evidence import EvidencePack


def build_messages(question: str, as_of: str, pack: EvidencePack, system: str) -> list[dict[str, str]]:
    user = f"Question: {question}\nAs-of date: {as_of}\n\nEvidence spans:\n{pack.render()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def make_draft(question: str, as_of: str, pack: EvidencePack, client: ModelClient) -> tuple[Draft | None, str]:
    """Return (draft, prompt_version). draft is None when drafting failed (the caller abstains with 'drafting failed')."""
    version, system = load_prompt("draft")
    try:
        draft = client.chat_json(build_messages(question, as_of, pack, system), Draft, max_tokens=900)
    except (ModelUnavailable, ValueError):
        return None, version
    draft.claims = [c for c in draft.claims if c.text.strip()][:8]
    for c in draft.claims:  # models often copy ids with the brackets from the evidence line; the id itself must still match
        c.span_ids = [s.strip().strip("[]").strip() for s in c.span_ids]
    return draft, version
