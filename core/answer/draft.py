"""Draft (answering.md §1): one guided-JSON LLM call that turns the evidence pack into cited atomic claims."""
from __future__ import annotations

from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import Draft
from core.retrieval.evidence import EvidencePack

CALC_NEEDS = {"emi": "the annual interest rate",
              "late_fee_total": "the late fee per instalment (every value the evidence gives)",
              "prepayment_charge": "the prepayment charge that applies: its percentage, or that no charge applies"}


def calc_note(calc_kind: str) -> str:
    need = CALC_NEEDS.get(calc_kind)
    if not need:
        return ""
    return ("\nCalculation: a calculator computes the result itself. Your only job is to return, as claims of kind "
            f'"calc_input", what the evidence states about {need}, in a plain sentence such as '
            '"The interest rate is 13.5% per annum". Do not calculate, do not return the result, and do not list the '
            'result or any number given in the question under "missing". Rule 11 still applies: if the evidence is about a '
            'different product or topic than the question asks about, return "claims": [].\n')


def build_messages(question: str, as_of: str, pack: EvidencePack, system: str,
                   calc_kind: str = "none") -> list[dict[str, str]]:
    user = f"Question: {question}\nAs-of date: {as_of}\n{calc_note(calc_kind)}\nEvidence spans:\n{pack.render()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def make_draft(question: str, as_of: str, pack: EvidencePack, client: ModelClient,
               calc_kind: str = "none") -> tuple[Draft | None, str]:
    """Return (draft, prompt_version). draft is None when drafting failed (the caller abstains with 'drafting failed')."""
    version, system = load_prompt("draft")
    try:
        draft = client.chat_json(build_messages(question, as_of, pack, system, calc_kind), Draft, max_tokens=900)
    except (ModelUnavailable, ValueError):
        return None, version
    draft.claims = [c for c in draft.claims if c.text.strip()][:8]
    for c in draft.claims:  # models often copy ids with the brackets from the evidence line; the id itself must still match
        c.span_ids = [s.strip().strip("[]").strip() for s in c.span_ids]
    return draft, version
