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

@lru_cache(maxsize=8)
def load_prompt(version: str) -> str:
    path = _PROMPT_DIR / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt {version!r} not found at {path}")
    return path.read_text(encoding="utf-8")


#: task26 (experiment2_v4) prompts: typed logical algebra binder over the v002
#: binder projection, compact correction, claim-citing answerer. These are the
#: only prompts the active pipeline uses (the Task 24/25 prompts were retired
#: with the pipeline they served, task26 §16).
BINDER_V3_PROMPT_VERSION = "binder_v003"
CORRECTION_V2_PROMPT_VERSION = "correction_v002"
GROUNDED_ANSWERER_V2_PROMPT_VERSION = "grounded_answerer_v002"


def binder_prompt_v3() -> str:
    return load_prompt(BINDER_V3_PROMPT_VERSION)


def correction_prompt_v2() -> str:
    return load_prompt(CORRECTION_V2_PROMPT_VERSION)


def grounded_answerer_prompt_v2() -> str:
    return load_prompt(GROUNDED_ANSWERER_V2_PROMPT_VERSION)
