"""Versioned prompt loader (spec_v005 §3: keep prompts versioned).

Prompts live as Markdown next to this module. The version string is part of the
filename and is logged with every query, so a stored intent, plan, or answer can
always be traced back to the exact prompt that produced it.

The experiment2_v5 pipeline (task28) has FOUR prompts — three principal roles
plus the conditional repair:

    intent_resolver_v001    planning call 1 — resolve the conversation into one
                            authoritative standalone request
    grounding_planner_v001  planning call 2 — ground that request against this
                            model's capabilities as a typed logical plan
    correction_v003         the conditional one-time mechanical repair
    grounded_answerer_v003  final call — express the adjudicated result

task28 §10: every active prompt contains declarative rules, field definitions,
and output-schema instructions ONLY. No examples, demonstrations, sample
conversations, sample queries, sample plans, benchmark wording, expected
outputs, or model-specific facts. `tests/binding/test_v5_prompts.py` enforces
this; the retired v4 prompts carried all of them and were removed with the
pipeline they served.
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


#: task30 (experiment2_v5) prompts. These are the only prompts the active
#: pipeline uses. The resolver emits a TYPED semantic contract, and grounding
#: binds pre-built slots rather than reconstructing the user's logic.
INTENT_RESOLVER_V2_PROMPT_VERSION = "intent_resolver_v002"
GROUNDING_BINDER_V1_PROMPT_VERSION = "grounding_binder_v001"
CORRECTION_V3_PROMPT_VERSION = "correction_v003"
GROUNDED_ANSWERER_V3_PROMPT_VERSION = "grounded_answerer_v003"

#: Every prompt the active pipeline may send, for the rules-only contract test.
ACTIVE_PROMPT_VERSIONS = (
    INTENT_RESOLVER_V2_PROMPT_VERSION,
    GROUNDING_BINDER_V1_PROMPT_VERSION,
    CORRECTION_V3_PROMPT_VERSION,
    GROUNDED_ANSWERER_V3_PROMPT_VERSION,
)


def intent_resolver_prompt_v2() -> str:
    return load_prompt(INTENT_RESOLVER_V2_PROMPT_VERSION)


def grounding_binder_prompt_v1() -> str:
    return load_prompt(GROUNDING_BINDER_V1_PROMPT_VERSION)


def correction_prompt_v3() -> str:
    return load_prompt(CORRECTION_V3_PROMPT_VERSION)


def grounded_answerer_prompt_v3() -> str:
    return load_prompt(GROUNDED_ANSWERER_V3_PROMPT_VERSION)
