"""v001 feature-template system for relationship-description text generation.

Generates deterministic natural-language text from a relationship's canonical_json
and its resolved member rows. No LLM calls — pure template expansion.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

TEMPLATE_VERSION = "v001"
DOCUMENT_TYPE = "relationship_description"
MAX_TEXT_CHARS = 4000

# Scalar attributes omitted from text (administrative, not descriptive)
_SCALAR_SKIP = {"OwnerHistory_step_id"}


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _build_member_lookup(
    members: list[dict[str, Any]] | None,
) -> dict[tuple[str, int | None], int | None]:
    """Map (role, member_order) → entity_id for resolved endpoint lookup."""
    lookup: dict[tuple[str, int | None], int | None] = {}
    for m in members or []:
        key = (m["role"], m.get("member_order"))
        lookup[key] = m.get("entity_id")
    return lookup


def _format_endpoint(ep: dict[str, Any], entity_id: int | None = None) -> str:
    """Format one endpoint summary as a compact string."""
    ifc_class = ep.get("ifc_class", "")
    step_id = ep.get("step_id")
    gid = ep.get("global_id")
    name = ep.get("name")

    inner: list[str] = []
    if step_id is not None:
        inner.append(f"STEP: {step_id}")
    if gid:
        inner.append(f"GlobalId: {gid}")
    if name:
        inner.append(f"Name: '{name}'")
    if entity_id is not None:
        inner.append(f"Entity ID: {entity_id}")

    if inner:
        return f"{ifc_class} ({', '.join(inner)})"
    return ifc_class


def _build_sentences(
    canonical: dict[str, Any],
    member_lookup: dict[tuple[str, int | None], int | None],
) -> list[tuple[str, str]]:
    """Return (priority_key, sentence) pairs — no truncation yet."""
    parts: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(priority: str, sentence: str) -> None:
        s = _clean(sentence)
        if s and s not in seen:
            seen.add(s)
            parts.append((priority, s))

    meta = canonical.get("meta", {})
    identity = canonical.get("identity", {})
    scalars = canonical.get("scalars", {})
    endpoints = canonical.get("endpoints", {})

    ifc_class = meta.get("ifc_class", "IfcRelationship")
    global_id = meta.get("global_id", "")

    add("identity", f"This is an {ifc_class} relationship.")
    add("global_id", f"Its GlobalId is {global_id}.")

    name = identity.get("name")
    if name:
        add("name", f"Its name is '{name}'.")
    desc = identity.get("description")
    if desc:
        add("description", f"Description: {desc}.")

    for attr in sorted(scalars.keys()):
        if attr in _SCALAR_SKIP:
            continue
        val = scalars[attr]
        if val is not None:
            add("scalar", f"{attr}: {val}.")

    # Singular (scalar) endpoints first, then aggregate list endpoints
    singular = {k: v for k, v in endpoints.items() if isinstance(v, dict)}
    aggregate = {k: v for k, v in endpoints.items() if isinstance(v, list)}

    for role in sorted(singular.keys()):
        ep = singular[role]
        eid = member_lookup.get((role, None))
        add("endpoint_scalar", f"{role}: {_format_endpoint(ep, eid)}.")

    for role in sorted(aggregate.keys()):
        ep_list = aggregate[role]
        for i, ep in enumerate(ep_list):
            eid = member_lookup.get((role, i))
            add("endpoint_list", f"{role}[{i}]: {_format_endpoint(ep, eid)}.")

    return parts


_PRIORITY_ORDER = [
    "identity",
    "global_id",
    "name",
    "description",
    "scalar",
    "endpoint_scalar",
    "endpoint_list",
]


def generate_rel_text(
    canonical: dict[str, Any],
    members: list[dict[str, Any]] | None = None,
    tokenizer: Any = None,
) -> tuple[str, bool] | tuple[str, bool, int, int]:
    """Generate relationship-description text from canonical JSON and member rows.

    Args:
        canonical: canonical_json stored in ifc_relationships.
        members: list of member dicts from relationship_members (may be None in tests).
        tokenizer: real BAAI/bge-m3 tokenizer at production time. When omitted,
            returns (text, truncated) — unchanged legacy behavior. When supplied,
            the char-truncated result is further trimmed to a real token budget
            and the return becomes (text, truncated, original_token_count,
            encoded_token_count).

    Returns:
        Deterministic; never raises.
    """
    member_lookup = _build_member_lookup(members)
    all_parts = _build_sentences(canonical, member_lookup)

    priority_index = {k: i for i, k in enumerate(_PRIORITY_ORDER)}
    sorted_parts = sorted(
        all_parts,
        key=lambda t: priority_index.get(t[0], len(_PRIORITY_ORDER)),
    )

    kept: list[str] = []
    char_count = 0
    dropped = 0

    for _, sentence in sorted_parts:
        if char_count + len(sentence) + 1 > MAX_TEXT_CHARS:
            dropped += 1
        else:
            kept.append(sentence)
            char_count += len(sentence) + 1

    truncated = dropped > 0
    original_token_count: int | None = None
    encoded_token_count: int | None = None

    if tokenizer is not None:
        from bim_rag.text_limits import apply_token_budget, count_tokens

        all_sentences = [s for _, s in sorted_parts]
        original_token_count = count_tokens(all_sentences, tokenizer)
        kept, token_dropped, encoded_token_count = apply_token_budget(kept, tokenizer)
        truncated = truncated or token_dropped

    # Restore original insertion order for output
    original_order = {sent: idx for idx, (_, sent) in enumerate(all_parts)}
    kept_ordered = sorted(kept, key=lambda s: original_order.get(s, 9999))

    text = " ".join(kept_ordered)

    if tokenizer is None:
        return text, truncated
    return text, truncated, original_token_count, encoded_token_count
