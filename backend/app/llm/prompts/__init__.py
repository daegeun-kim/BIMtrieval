"""Versioned prompt loader (spec_v005 §3: keep prompts versioned).

Prompts live as Markdown next to this module. The version string is part of
the filename and is logged with every query so a stored plan/answer can always
be traced back to the exact prompt that produced it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent

# planner_v002 / answerer_v002: universal hybrid evidence pipeline (Task 16).
PLANNER_PROMPT_VERSION = "planner_v002"
ANSWERER_PROMPT_VERSION = "answerer_v002"
# Task 17: query-only retrieval-policy planner (call 1) + group-aware answerer (call 2).
POLICY_PLANNER_PROMPT_VERSION = "policy_planner_v001"
GROUP_ANSWERER_PROMPT_VERSION = "group_answerer_v001"


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


def policy_planner_prompt() -> str:
    return load_prompt(POLICY_PLANNER_PROMPT_VERSION)


def group_answerer_prompt() -> str:
    return load_prompt(GROUP_ANSWERER_PROMPT_VERSION)
