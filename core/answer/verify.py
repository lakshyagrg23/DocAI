"""Claim verification (answering.md §2). Checks (a)-(d) are pure functions; (e) is one batched /nli call.

Nothing reaches the answer body unless `verify_claims` marks it supported. Check (f), conflicts, arrives in M6.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from rapidfuzz import fuzz

from core import config
from core.llm.client import ModelClient, ModelUnavailable
from core.models import ClaimCheck, DraftClaim, VerifiedClaim
from core.normalize import missing_numbers
from core.retrieval.evidence import EvidencePack, EvidenceSpan

NLI_PREMISE_CHARS = 2000
RE_QUOTED = re.compile(r"[\"“”‘'`]([^\"“”]{8,}?)[\"“”’'`]")
RE_ID_PREFIX = re.compile(r"^\[[^\]]+\]\s*")


def context_of(span: EvidenceSpan) -> str:
    """Verifiable context of a span: its evidence header plus its text (the span-id prefix is dropped)."""
    return RE_ID_PREFIX.sub("", span.line)


# ---- pure checks ----------------------------------------------------------------

def spans_valid(span_ids: Iterable[str], allowed: set[str]) -> bool:
    ids = list(span_ids)
    return bool(ids) and all(s in allowed for s in ids)


def numbers_ok(claim: str, context: str, extra: str = "") -> tuple[bool, list[str]]:
    bad = missing_numbers(claim, context, extra)
    return not bad, bad


def quote_ok(claim: str, context: str) -> bool:
    """Every quoted passage (>= 8 chars) of the claim must appear (fuzzily) in the cited text."""
    for q in RE_QUOTED.findall(claim):
        if fuzz.partial_ratio(q.lower(), context.lower()) < config.QUOTE_FUZZ_MIN:
            return False
    return True


def version_ok(statuses: Iterable[str], kind: str) -> bool:
    """Cited spans must be in force at the as-of date; history claims may cite any version."""
    return kind == "history" or all(s == "in_force" for s in statuses)


# ---- orchestration ----------------------------------------------------------------

def verify_claims(claims: list[DraftClaim], pack: EvidencePack, client: ModelClient, question: str = "",
                  threshold: float | None = None) -> list[VerifiedClaim]:
    """Run (a)-(d) for every claim, then one batched NLI call for the survivors; return a verdict per claim."""
    threshold = config.HHEM_THRESHOLD if threshold is None else threshold
    by_id = {s.span_id: s for s in pack.spans}
    all_status = {s.span_id: s.status for s in pack.spans + pack.context_spans}
    results: list[VerifiedClaim] = []
    pending: list[tuple[int, str, str]] = []  # (index into results, premise, hypothesis)
    for claim in claims:
        valid = spans_valid(claim.span_ids, set(by_id))
        spans = [by_id[s] for s in claim.span_ids if s in by_id]
        ctx = " ".join(context_of(s) for s in spans)
        reason = None
        if not valid:
            reason = "cites evidence that wasn't retrieved"
            nums, quote, ver = False, False, False
        else:
            extra = question if claim.kind == "calc_input" else ""
            nums, bad = numbers_ok(claim.text, ctx, extra)
            quote = quote_ok(claim.text, ctx)
            ver = version_ok((all_status.get(s, "in_force") for s in claim.span_ids), claim.kind)
            if not nums:
                reason = f"{', '.join(bad)} not found in cited text"
            elif not quote:
                reason = "quoted text doesn't match the source"
            elif not ver:
                reason = "cites a superseded clause"
        check = ClaimCheck(spans_valid=valid, numbers_ok=nums, quote_ok=quote, version_ok=ver)
        vc = VerifiedClaim(text=claim.text, span_ids=claim.span_ids, verdict="unsupported", checks=check, reason=reason)
        results.append(vc)
        if reason is None:
            pending.append((len(results) - 1, ctx[:NLI_PREMISE_CHARS], claim.text))
    if pending:
        try:
            scores = client.nli([(p, h) for _, p, h in pending])
        except ModelUnavailable:
            scores = [None] * len(pending)
        for (i, _, _), score in zip(pending, scores):
            vc = results[i]
            vc.checks.hhem = score
            if score is None:
                vc.reason = "could not be checked (model unavailable)"
            elif score >= threshold:
                vc.verdict = "supported"
            else:
                vc.reason = f"not entailed by the cited text ({score:.2f})"
    return results


def apply_threshold(vc: VerifiedClaim, threshold: float) -> VerifiedClaim:
    """Re-decide a verified claim at another HHEM threshold (used by the eval sweep; checks (a)-(d) unchanged)."""
    c = vc.checks
    passes_pure = c.spans_valid and c.numbers_ok and c.quote_ok and c.version_ok
    ok = passes_pure and c.hhem is not None and c.hhem >= threshold
    return vc.model_copy(update={"verdict": "supported" if ok else "unsupported"})
