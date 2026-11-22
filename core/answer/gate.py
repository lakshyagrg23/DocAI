"""Display gate (answering.md §3): decides what may be shown and the answer status. Pure."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.models import VerifiedClaim

ABSTAIN_TEXT = "I don't have proof for this in the uploaded documents."


@dataclass
class GateResult:
    status: str
    supported: list[VerifiedClaim] = field(default_factory=list)
    contested: list[VerifiedClaim] = field(default_factory=list)
    blocked: list[VerifiedClaim] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    faithfulness_pct: float | None = None
    drafted: int = 0
    passed: int = 0


def gate(claims: list[VerifiedClaim], draft_missing: list[str], sub_questions: list[str]) -> GateResult:
    supported = [c for c in claims if c.verdict == "supported"]
    contested = [c for c in claims if c.verdict == "contradicted"]
    blocked = [c for c in claims if c.verdict == "unsupported"]
    missing = list(dict.fromkeys(m.strip() for m in draft_missing if m and m.strip()))
    if not supported and not contested:
        # nothing verified: say what was being looked for if the model did not
        if not missing:
            missing = [f"No verified evidence for: {q}" for q in sub_questions]
        status = "abstained"
    elif contested:
        status = "conflict"
    elif missing or blocked:
        status = "partial"
    else:
        status = "answered"
    drafted = len(claims)
    passed = len(supported) + len(contested)  # ADR-009: a contradicted claim is verified text, just disputed
    pct = round(100 * passed / drafted, 1) if drafted else None
    return GateResult(status, supported, contested, blocked, missing, pct, drafted, passed)
