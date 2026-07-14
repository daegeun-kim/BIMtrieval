"""Versioned prompt loader (spec_v005 §3: keep prompts versioned).

Prompts live as Markdown next to this module. The version string is part of
the filename and is logged with every query so a stored plan/answer can always
be traced back to the exact prompt that produced it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent

PLANNER_PROMPT_VERSION = "planner_v001"
ANSWERER_PROMPT_VERSION = "answerer_v001"


@lru_cache(maxsize=8)
def load_prompt(version: str) -> str:
    path = _PROMPT_DIR / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt {version!r} not found at {path}")
    return path.read_text(encoding="utf-8")


def planner_prompt() -> str:
    return load_prompt(PLANNER_PROMPT_VERSION)


def answerer_prompt() -> str:
    return load_prompt(ANSWERER_PROMPT_VERSION)
