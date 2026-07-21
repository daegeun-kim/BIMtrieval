"""Versioned prompt loader (spec_v005 §3: keep prompts versioned).

Prompts live as Markdown next to this module. The version string is part of the
filename and is logged with every query, so a stored binding/answer can always
be traced back to the exact prompt that produced it.

Task 24 leaves exactly TWO prompts, one per principal LLM call (§10.1):

    binder_v001             call 1 — bind the question to candidate slate IDs
    grounded_answerer_v001  call 2 — express already-adjudicated answer parts

The Task 16/17 planner, answerer, policy-planner and group-answerer prompts were
removed with the orchestration they served; §14 requires that no parallel
legacy/new orchestration remains.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent

#: Task 24 LLM call 1: model-aware semantic binder. Selects only candidate IDs
#: the backend computed against the active model; emits no IFC classes, field
#: names, JSON paths, SQL, or graph seeds.
BINDER_PROMPT_VERSION = "binder_v001"
#: Task 24 LLM call 2: expresses already-adjudicated answer parts. It selects
#: nothing, and its structured claims are validated against the answer packet.
GROUNDED_ANSWERER_PROMPT_VERSION = "grounded_answerer_v001"


@lru_cache(maxsize=8)
def load_prompt(version: str) -> str:
    path = _PROMPT_DIR / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt {version!r} not found at {path}")
    return path.read_text(encoding="utf-8")


def binder_prompt() -> str:
    return load_prompt(BINDER_PROMPT_VERSION)


def grounded_answerer_prompt() -> str:
    return load_prompt(GROUNDED_ANSWERER_PROMPT_VERSION)
