"""Load versioned prompt templates from core/llm/prompts/*.md. First line: <!-- version: vN -->."""
from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent / "prompts"
_VERSION = re.compile(r"^<!--\s*version:\s*(\S+)\s*-->\s*\n")


@cache
def load_prompt(name: str) -> tuple[str, str]:
    """Return (version, body) for prompt `name`."""
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = _VERSION.match(raw)
    if not m:
        raise ValueError(f"prompt {name}: missing '<!-- version: vN -->' header")
    return m.group(1), raw[m.end():].strip()
