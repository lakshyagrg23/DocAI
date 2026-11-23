"""Query planner (retrieval.md §1): intent, sub-questions, as-of override, calculator inputs. One LLM call."""
from __future__ import annotations

import re
from datetime import date

from core.llm.client import ModelClient, ModelUnavailable, get_client
from core.llm.prompt_loader import load_prompt
from core.models import CalcPlan, QueryPlan

MAX_SUB_QUESTIONS = 3
RE_STATES_DATE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.IGNORECASE)


def default_plan(question: str) -> QueryPlan:
    """Used when the LLM is unavailable: search with the question as asked."""
    return QueryPlan(intent="lookup", sub_questions=[question])


def sanitise(plan: QueryPlan, question: str) -> QueryPlan:
    """Enforce the plan contract regardless of what the model produced."""
    subs = [s.strip() for s in plan.sub_questions if s and s.strip()][:MAX_SUB_QUESTIONS] or [question]
    override = None
    if plan.as_of_override and RE_STATES_DATE.search(question):  # small models invent a date for "today"
        pass
    else:
        plan = plan.model_copy(update={"as_of_override": None})
    if plan.as_of_override:
        try:
            override = date.fromisoformat(plan.as_of_override.strip()).isoformat()
        except ValueError:
            override = None
    calc = plan.calc if plan.calc.kind != "none" else CalcPlan()
    intent = "calculation" if calc.kind != "none" else plan.intent
    if override and intent in ("lookup", "multi"):
        intent = "history"
    return QueryPlan(intent=intent, sub_questions=subs, as_of_override=override, calc=calc)


def make_plan(question: str, client: ModelClient | None = None) -> tuple[QueryPlan, str]:
    """Return (plan, prompt_version). Falls back to the default plan (version 'none') if the model is down."""
    version, prompt = load_prompt("plan")
    try:
        raw = (client or get_client()).chat_json(
            [{"role": "system", "content": prompt}, {"role": "user", "content": f"Question: {question}"}],
            QueryPlan, max_tokens=300)
    except ModelUnavailable:
        return default_plan(question), "none"
    return sanitise(raw, question), version


def effective_as_of(plan: QueryPlan, chat_as_of: str | None, today: date | None = None) -> str:
    """as_of_override, else the chat's as-of date, else today (ISO)."""
    return plan.as_of_override or chat_as_of or (today or date.today()).isoformat()


def search_queries(plan: QueryPlan, question: str) -> list[str]:
    """Sub-questions plus the original question: a sub-question split can drop half of a comparison."""
    out = list(plan.sub_questions)
    if question.strip() not in out:
        out.append(question.strip())
    return out
