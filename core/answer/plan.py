"""Query planner (retrieval.md §1): intent, sub-questions, as-of override, calculator inputs. One LLM call."""
from __future__ import annotations

import re
from datetime import date

from core import i18n
from core.llm.client import ModelClient, ModelUnavailable, get_client
from core.llm.prompt_loader import load_prompt
from core.models import CalcPlan, QueryPlan

MAX_SUB_QUESTIONS = 3
RE_STATES_DATE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.IGNORECASE)


def default_plan(question: str) -> QueryPlan:
    """Used when the LLM is unavailable: search with the question as asked."""
    return QueryPlan(intent="lookup", question_en=question, sub_questions=[question])


def english_question(plan: QueryPlan, question: str) -> str:
    """The question in English. English questions are never rewritten by the model; a Hindi one uses the planner's translation
    (Devanagari digits normalised), falling back to the question as asked if the model gave none."""
    q = i18n.to_ascii_digits(question).strip()
    if i18n.detect_language(q) == "en":
        return q
    return i18n.to_ascii_digits(plan.question_en).strip() or q


def sanitise(plan: QueryPlan, question: str) -> QueryPlan:
    """Enforce the plan contract regardless of what the model produced."""
    question_en = english_question(plan, question)
    question = question_en  # every later check (date guard, fallbacks) works on the English text
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
    return QueryPlan(intent=intent, question_en=question_en, sub_questions=subs, as_of_override=override, calc=calc)


def make_plan(question: str, client: ModelClient | None = None) -> tuple[QueryPlan, str]:
    """Return (plan, prompt_version). Falls back to the default plan (version 'none') if the model is down."""
    version, prompt = load_prompt("plan")
    try:
        raw = (client or get_client()).chat_json(
            [{"role": "system", "content": prompt}, {"role": "user", "content": f"Question: {i18n.to_ascii_digits(question)}"}],
            QueryPlan, max_tokens=300)
    except ModelUnavailable:
        return default_plan(question), "none"
    return sanitise(raw, question), version


def effective_as_of(plan: QueryPlan, chat_as_of: str | None, today: date | None = None) -> str:
    """as_of_override, else the chat's as-of date, else today (ISO)."""
    return plan.as_of_override or chat_as_of or (today or date.today()).isoformat()


def search_queries(plan: QueryPlan, question: str, original: str | None = None) -> list[str]:
    """Sub-questions plus the original question: a sub-question split can drop half of a comparison.
    `question` is the English question; a Hindi `original` is searched too (bge-m3 is cross-lingual)."""
    out = list(plan.sub_questions)
    for q in (question, original):
        if q and q.strip() not in out:
            out.append(q.strip())
    return out
