"""English -> Hindi for the verified answer (answering.md §6). One batched model call, number-guarded per item.

Safety: this runs *after* verification and only changes how an already-verified sentence is worded. A translation is used
only if its numbers equal the English sentence's numbers; otherwise (or if the model is down) the English sentence is shown.
The Hindi text is stored beside the English (`text_local`), never instead of it, so audit and export keep the verified text.
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from core import i18n
from core.llm.client import ModelClient, ModelUnavailable
from core.llm.prompt_loader import load_prompt
from core.models import VerifiedClaim

MAX_ITEMS = 24  # claims (max 8 drafted) + missing items; anything beyond stays English


class Translation(BaseModel):
    items: list[str]


def to_hindi(texts: list[str], client: ModelClient) -> tuple[list[str | None], str]:
    """Return (translations aligned to `texts`, prompt version). None = keep English (guard failed or model unavailable)."""
    version, system = load_prompt("translate")
    todo = [t for t in texts[:MAX_ITEMS]]
    if not todo:
        return [None] * len(texts), version
    try:
        out = client.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(todo, ensure_ascii=False)}],
            Translation, max_tokens=900)
    except (ModelUnavailable, ValueError):
        return [None] * len(texts), version
    if len(out.items) != len(todo):  # a misaligned list cannot be trusted item by item
        return [None] * len(texts), version
    res: list[str | None] = []
    for en, hi in zip(todo, out.items, strict=True):
        hi = hi.strip()
        ok = hi and i18n.DEVANAGARI.search(hi) and i18n.same_numbers(en, hi)  # number guard + must really be Hindi
        res.append(hi if ok else None)
    return res + [None] * (len(texts) - len(todo)), version


def localize(claims: list[VerifiedClaim], missing: list[str], client: ModelClient) -> tuple[list[str], str]:
    """Fill `claim.text_local` in place and return the Hindi `missing` list (English where translation was refused)."""
    out, version = to_hindi([c.text for c in claims] + missing, client)
    for c, t in zip(claims, out[:len(claims)], strict=True):
        c.text_local = t
    return [t or m for m, t in zip(missing, out[len(claims):], strict=True)], version
