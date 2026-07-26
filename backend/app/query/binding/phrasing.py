"""Plain-language phrasing for user-facing text (task27 §6).

Every string a user can read passes through here: result limitations, coverage
reasons, the deterministic fallback answer, and the unavailable/clarification
prose the pipeline writes itself. The recorded defect was answers built out of
pipeline vocabulary — `prop:Pset_WallCommon.FireRating is partially covered on
the target classes`, `zero match cannot prove real-world absence`, `the packet
does not provide`, `evidence_scope=0` — which is accurate and unreadable.

Two jobs:

- `humanize_semantic_id` turns a manifest ID into the words a person uses:
  `prop:Pset_WallCommon.FireRating` -> "fire rating", `cls:IfcWallStandardCase`
  -> "wall standard case", `mat:material.name` -> "material".
- `humanize_text` rewrites a sentence: semantic IDs become their human phrase
  and the banned internal vocabulary becomes ordinary English.

`BANNED_ANSWER_TERMS` is the same list, used by answer validation to REJECT a
generated answer that reintroduces internal vocabulary. Rules only — the
answerer prompt carries no examples (§6).
"""

from __future__ import annotations

import re

from app.query.binding.lexical import split_identifier

__all__ = [
    "BANNED_ANSWER_TERMS",
    "UNSUPPORTED_ABSENCE_PHRASES",
    "banned_terms_in",
    "humanize_semantic_id",
    "humanize_text",
    "unsupported_absence_phrases_in",
]

#: Any manifest-style semantic ID appearing inside free text.
_SEMANTIC_ID_RE = re.compile(
    r"\b(?:cls|prop|qty|attr|mat|cla|spatial|path|floor|storey|derived|count)"
    r":[A-Za-z0-9_.\-\[\]>]+"
)

#: Terms §6 forbids in a final answer, mapped to ordinary wording. Order
#: matters: longer phrases are rewritten before the words they contain.
_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in (
        (r"\bon the target(?:ed)? classes\b", "on these objects"),
        (r"\bfor the target(?:ed)? class\b", "for these objects"),
        (r"\btarget(?:ed)? classes\b", "these objects"),
        (r"\btarget(?:ed)? class\b", "these objects"),
        (r"\bthe answer packet\b", "this model's recorded data"),
        (r"\bthis packet\b", "this model"),
        (r"\bthe packet\b", "this model"),
        (r"\bpacket\b", "this model"),
        (r"\bzero match(?:es)?\b", "nothing"),
        (r"\bsemantic id(?:entifier)?s?\b", "recorded field"),
        (r"\bpredicates?\b", "condition"),
        (r"\bcoverage is incomplete\b", "the value is not recorded for every object"),
        (r"\bincomplete coverage\b", "values are not recorded for every object"),
        (r"\bcoverage\b", "recorded data"),
        (r"\beligible set\b", "objects of that kind"),
        (r"\bbase set\b", "all objects of that kind"),
        (r"\bevidence scope\b", "the described objects"),
        (r"\bunproven unit contract\b", "no recorded unit"),
        (r"\bmatch\(es\)\b", "objects"),
        (r"\bmatched cardinality\b", "number of objects"),
        (r"\bmatches\b", "objects"),
        (r"\bmatch\b", "object"),
    )
)

#: The vocabulary answer validation rejects outright. Kept separate from the
#: rewrite table because rejection needs exact word boundaries, not a rewrite.
BANNED_ANSWER_TERMS: tuple[str, ...] = (
    "target class",
    "targeted class",
    "zero match",
    "predicate",
    "coverage",
    "semantic id",
    "packet",
    "eligible set",
    "base set",
    "result_kind",
    "entity_set",
    "partial_executable",
    "not_representable",
    "evidence_scope",
    "fact_id",
    "disposition",
)

#: Word-boundary patterns for terms that are ordinary English in other senses
#: ("match", "matches") but internal jargon in an answer about a model.
_BANNED_WORD_RE = re.compile(
    r"\b(?:zero matches|match\(es\)|no matches found|"
    r"exact status|partial status|status: (?:exact|partial|zero|unavailable))\b",
    re.IGNORECASE,
)

#: Phrases that assert the pipeline withheld information. Legitimate only when
#: the cited part really has no answer, which validation checks (§6).
UNSUPPORTED_ABSENCE_PHRASES: tuple[str, ...] = (
    "does not provide",
    "do not provide",
    "does not include a count",
    "is not provided",
    "was not provided",
    "no count is provided",
    "not provided in",
    "not included in",
    "no information was provided",
    "i was not given",
)

_PSET_PREFIX_RE = re.compile(r"^(?:pset|qto|q)[_ ]?", re.IGNORECASE)
_COMMON_SUFFIX_RE = re.compile(r"common$", re.IGNORECASE)


def humanize_semantic_id(semantic_id: str) -> str:
    """The everyday words behind one manifest semantic ID.

    Only the distinguishing tail is kept: a user asking about fire ratings does
    not need `Pset_WallCommon`, which merely says where the exporter stored it.
    """
    if not semantic_id:
        return ""
    prefix, _, rest = semantic_id.partition(":")
    if not rest:
        rest, prefix = semantic_id, ""
    if prefix in ("prop", "qty"):
        _container, _, field = rest.rpartition(".")
        rest = field or rest
    elif prefix in ("attr", "mat", "cla"):
        head, _, field = rest.rpartition(".")
        rest = field if field and field not in ("name", "value") else (head or rest)
    elif prefix == "path":
        rest = rest.split(".")[0]
    elif prefix in ("floor", "count"):
        rest = rest.replace("band:", "floor ").replace("_", " ")
    words = [w for w in split_identifier(_COMMON_SUFFIX_RE.sub("", _PSET_PREFIX_RE.sub("", rest)))]
    return " ".join(words) or rest


def humanize_text(text: str | None) -> str:
    """Rewrite one internal sentence into plain language."""
    if not text:
        return ""
    humanized = _SEMANTIC_ID_RE.sub(lambda m: humanize_semantic_id(m.group(0)), text)
    for pattern, replacement in _REWRITES:
        humanized = pattern.sub(replacement, humanized)
    return re.sub(r"\s{2,}", " ", humanized).strip()


def banned_terms_in(text: str | None) -> list[str]:
    """Internal vocabulary a final answer must not contain (§6)."""
    if not text:
        return []
    lowered = text.casefold()
    found = [term for term in BANNED_ANSWER_TERMS if term in lowered]
    found.extend(m.group(0).casefold() for m in _BANNED_WORD_RE.finditer(text))
    if _SEMANTIC_ID_RE.search(text):
        found.append("semantic id")
    seen: list[str] = []
    for term in found:
        if term not in seen:
            seen.append(term)
    return seen


def unsupported_absence_phrases_in(text: str | None) -> list[str]:
    """Phrases claiming information was withheld (§6)."""
    if not text:
        return []
    lowered = text.casefold()
    return [phrase for phrase in UNSUPPORTED_ABSENCE_PHRASES if phrase in lowered]
