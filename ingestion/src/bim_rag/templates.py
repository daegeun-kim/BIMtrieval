"""v001 feature-template system for element-description text generation.

Each semantic feature uses one stable template regardless of IFC class.
Text is generated deterministically from canonical JSON only — no LLM calls.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

TEMPLATE_VERSION = "v001"
DOCUMENT_TYPE = "entity_description"

# BGE-M3 practical input limit; model max is 8192 tokens ≈ ~6000 chars of prose.
# We apply a conservative character limit and truncate with priority ordering.
MAX_TEXT_CHARS = 4000

# ---------------------------------------------------------------------------
# Template strings (stable ordering; same template per feature across all classes)
# ---------------------------------------------------------------------------

_T = {
    "identity": "This is an {ifc_class} entity.",
    "name": "Its name is '{name}'.",
    "global_id": "Its IFC GlobalId is {global_id}.",
    "description": "Description: {description}.",
    "object_type": "Object type: {object_type}.",
    "predefined_type": "Predefined type: {predefined_type}.",
    "tag": "Tag: {tag}.",
    "long_name": "Long name: {long_name}.",
    "composition": "Composition type: {composition_type}.",
    "storey": "Located on storey '{storey_name}'.",
    "type_name": "Element type: '{type_name}'.",
    "material": "Material: '{material_name}'.",
    "classification": "Classification {code} ({system}): {description}.",
    "placement_elev": "Storey elevation: {elevation}.",
    "property": "Property '{property_name}' in '{pset_name}': {value}.",
    "quantity": "Quantity '{quantity_name}' in '{qset_name}': {value}.",
}

# Feature rendering priority (highest first) for truncation policy
_PRIORITY_ORDER = [
    "identity",
    "name",
    "global_id",
    "predefined_type",
    "object_type",
    "tag",
    "long_name",
    "composition",
    "storey",
    "type_name",
    "material",
    "classification",
    "placement_elev",
    "description",
    "property",
    "quantity",
]


def _clean(text: str) -> str:
    """Normalize whitespace and strip control characters."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _fmt_value(v: Any, unit: str | None = None) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if unit and unit not in ("None", "null", ""):
        return f"{s} {unit}"
    return s


def _fmt_norm(entry: dict[str, Any]) -> str:
    """Format a value entry preferring normalized value+unit if available."""
    if "normalized_value" in entry and "normalized_unit" in entry:
        return f"{entry['normalized_value']} {entry['normalized_unit']}"
    v = entry.get("value")
    u = entry.get("unit") or entry.get("normalized_unit")
    return _fmt_value(v, u if u and u not in ("project_unit",) else None)


# ---------------------------------------------------------------------------
# Feature extraction from canonical JSON
# ---------------------------------------------------------------------------


def _build_feature_sentences(canonical: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ordered list of (priority_key, sentence) tuples (no truncation yet)."""
    sentences: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(priority: str, sentence: str) -> None:
        s = _clean(sentence)
        if s and s not in seen:
            seen.add(s)
            sentences.append((priority, s))

    meta = canonical.get("meta", {})
    identity = canonical.get("identity", {})

    ifc_class = meta.get("ifc_class", "IfcRoot")
    global_id = meta.get("global_id", "")
    predefined_type = meta.get("predefined_type")

    add("identity", _T["identity"].format(ifc_class=ifc_class))

    name = identity.get("name")
    if name:
        add("name", _T["name"].format(name=name))

    add("global_id", _T["global_id"].format(global_id=global_id))

    if predefined_type and predefined_type.upper() not in ("NOTDEFINED", "USERDEFINED", "NONE"):
        add("predefined_type", _T["predefined_type"].format(predefined_type=predefined_type))

    obj_type = identity.get("object_type")
    if obj_type:
        add("object_type", _T["object_type"].format(object_type=obj_type))

    tag = identity.get("tag")
    if tag:
        add("tag", _T["tag"].format(tag=tag))

    long_name = identity.get("long_name")
    if long_name:
        add("long_name", _T["long_name"].format(long_name=long_name))

    comp = identity.get("composition_type")
    if comp:
        add("composition", _T["composition"].format(composition_type=comp))

    desc = identity.get("description")
    if desc:
        add("description", _T["description"].format(description=desc))

    # Storey
    storey = canonical.get("storey")
    if storey and storey.get("name"):
        add("storey", _T["storey"].format(storey_name=storey["name"]))

    # Type
    type_info = canonical.get("type")
    if type_info and type_info.get("name"):
        add("type_name", _T["type_name"].format(type_name=type_info["name"]))

    # Materials (deduplicated)
    for mat in canonical.get("materials", []):
        mat_name = mat.get("name")
        if mat_name:
            add("material", _T["material"].format(material_name=mat_name))

    # Classifications
    for clf in canonical.get("classifications", []):
        code = clf.get("code") or ""
        system = clf.get("system") or "unknown"
        clf_desc = clf.get("description") or ""
        if code or clf_desc:
            add(
                "classification",
                _T["classification"].format(code=code, system=system, description=clf_desc),
            )

    # Placement elevation
    placement = canonical.get("placement", {})
    elev = placement.get("elevation")
    if elev is not None:
        add("placement_elev", _T["placement_elev"].format(elevation=f"{elev}"))

    # Property sets (stable key order)
    for pset_name in sorted(canonical.get("property_sets", {}).keys()):
        if pset_name.startswith("_"):
            continue
        props = canonical["property_sets"][pset_name]
        for prop_name in sorted(props.keys()):
            entry = props[prop_name]
            val = entry.get("value")
            if val is None or val == "":
                continue
            add(
                "property",
                _T["property"].format(
                    property_name=prop_name,
                    pset_name=pset_name,
                    value=_fmt_value(val),
                ),
            )

    # Quantity sets (stable key order)
    for qset_name in sorted(canonical.get("quantity_sets", {}).keys()):
        if qset_name.startswith("_"):
            continue
        qtys = canonical["quantity_sets"][qset_name]
        for qty_name in sorted(qtys.keys()):
            entry = qtys[qty_name]
            val_str = _fmt_norm(entry)
            if not val_str:
                continue
            add(
                "quantity",
                _T["quantity"].format(
                    quantity_name=qty_name,
                    qset_name=qset_name,
                    value=val_str,
                ),
            )

    return sentences


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_text(
    canonical: dict[str, Any], tokenizer: Any = None
) -> tuple[str, bool] | tuple[str, bool, int, int]:
    """Generate element-description text from canonical JSON.

    Priority order is defined in _PRIORITY_ORDER; lower-priority sentences
    are dropped first if the total would exceed MAX_TEXT_CHARS.

    Without a tokenizer: returns (text, truncated) — unchanged legacy behavior.
    With a tokenizer (the real BAAI/bge-m3 tokenizer at production time): the
    char-truncated result is further trimmed to a real token budget, and the
    return becomes (text, truncated, original_token_count, encoded_token_count).
    """
    feature_sentences = _build_feature_sentences(canonical)

    # Priority-ordered truncation: build priority index for sorting
    priority_index = {k: i for i, k in enumerate(_PRIORITY_ORDER)}
    sorted_sentences = sorted(
        feature_sentences,
        key=lambda t: priority_index.get(t[0], len(_PRIORITY_ORDER)),
    )

    kept: list[str] = []
    char_count = 0
    dropped = 0

    for _, sentence in sorted_sentences:
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

        all_sentences = [s for _, s in sorted_sentences]
        original_token_count = count_tokens(all_sentences, tokenizer)
        kept, token_dropped, encoded_token_count = apply_token_budget(kept, tokenizer)
        truncated = truncated or token_dropped

    # Restore original feature order for the output text
    feature_order = {sent: idx for idx, (_, sent) in enumerate(feature_sentences)}
    kept_ordered = sorted(kept, key=lambda s: feature_order.get(s, 9999))

    text = " ".join(kept_ordered)

    if tokenizer is None:
        return text, truncated
    return text, truncated, original_token_count, encoded_token_count
