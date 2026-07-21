"""Text and identifier normalization for candidate matching (Task 24 §1.2, §4).

Two separate jobs that must not be collapsed into one comparison (§1.3):

- **Identifier tokenization.** Exporters name fields `IsExternal`,
  `LoadBearing`, `FireRating`, `Pset_WallCommon`, `OverallWidth`. Splitting
  those into word tokens is what lets ordinary wording ("is it external?",
  "load-bearing", "fire rating") reach the right field without a table mapping
  question phrases to database paths (§4.1).
- **Surface normalization.** Unicode, case, punctuation, whitespace, and simple
  English morphology, so a user's singular reaches a stored plural and vice
  versa (§4.2).

Everything here is general-purpose text handling. There is deliberately no
per-question, per-value, or per-model rule: the only vocabulary encoded is
English function words and general morphology, both of which apply to any
question about any model.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "normalize_text",
    "split_identifier",
    "identifier_content_tokens",
    "identifier_tokens",
    "singularize",
    "normalize_token",
    "tokenize",
    "content_tokens",
    "token_overlap",
    "stems_match",
    "stem_affinity",
    "phrase_matches",
    "STOP_WORDS",
]

#: Boundary between a lower/digit run and an upper run, or between an acronym
#: and a following word: `IsExternal` -> `Is|External`, `IFCWall` -> `IFC|Wall`.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_SEPARATORS = re.compile(r"[_\-.:/\\\s]+")

#: General English function words. Removing them keeps candidate matching on the
#: content words of a question. Nothing here is BIM-specific or question-specific
#: — adding a domain noun to this set would be a query-specific rule and is not
#: permitted (§Non-negotiable generalization rule).
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "give",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "many",
        "me",
        "much",
        "of",
        "on",
        "or",
        "please",
        "show",
        "so",
        "some",
        "tell",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "up",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    }
)

#: `Ifc` class prefix, stripped so `IfcDoor` and "door" share a token.
_IFC_PREFIX = "ifc"


def normalize_text(text: str | None) -> str:
    """Unicode-, case-, punctuation- and whitespace-normalized text (§4.2).

    NFKD decomposition followed by combining-mark removal folds accented forms
    onto their base letters, so a question typed without diacritics still
    reaches an accented stored value (and the reverse).
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = stripped.casefold()
    return _NON_ALNUM.sub(" ", lowered).strip()


def split_identifier(identifier: str | None) -> list[str]:
    """Split a stored identifier into lower-case word tokens.

    `IsExternal` -> `["is", "external"]`
    `Pset_WallCommon` -> `["pset", "wall", "common"]`
    `IfcWallStandardCase` -> `["wall", "standard", "case"]`  (Ifc prefix dropped)
    `OverallWidth` -> `["overall", "width"]`

    This is the mechanism that connects exporter naming to ordinary wording
    without binding one user question to one database path (§4.1).
    """
    if not identifier:
        return []
    tokens: list[str] = []
    for chunk in _SEPARATORS.split(identifier):
        if not chunk:
            continue
        for piece in _CAMEL_BOUNDARY.split(chunk):
            normalized = normalize_text(piece)
            for token in normalized.split():
                if token and token != _IFC_PREFIX:
                    tokens.append(token)
    return tokens


def identifier_content_tokens(identifier: str | None) -> list[str]:
    """Identifier tokens with English function words removed.

    Exporters prefix boolean fields grammatically — `IsExternal`, `HasCoverings`,
    `CanBeOpened`. Those prefixes are function words, and a user asking "how many
    external windows" never says "is". Matching must therefore compare CONTENT
    tokens on both sides, or every `Is*`/`Has*` boolean property becomes
    unreachable.

    Falls back to the unfiltered tokens when an identifier is composed entirely
    of function words, so filtering can never produce an empty target that would
    match everything.
    """
    tokens = split_identifier(identifier)
    content = [t for t in tokens if t not in STOP_WORDS]
    return content or tokens


def identifier_tokens(identifier: str | None) -> frozenset[str]:
    """Normalized content-token SET for an identifier, including singular forms.

    Both the surface token and its singular are kept so `Rooms`/`room` and
    `Doors`/`door` match in either direction without the caller choosing which
    side to normalize.
    """
    out: set[str] = set()
    for token in identifier_content_tokens(identifier):
        out.add(token)
        out.add(singularize(token))
    return frozenset(out)


#: Irregular plurals that the suffix rules below would get wrong. General
#: English, not domain vocabulary.
_IRREGULAR_PLURALS: dict[str, str] = {
    "children": "child",
    "feet": "foot",
    "geese": "goose",
    "men": "man",
    "mice": "mouse",
    "people": "person",
    "teeth": "tooth",
    "women": "woman",
}

#: Words ending in "s" that are already singular; naive stripping would corrupt
#: them. General English.
_SINGULAR_S_WORDS: frozenset[str] = frozenset(
    {"gas", "glass", "is", "as", "has", "was", "this", "its", "bus", "class", "status", "axis"}
)


def singularize(token: str) -> str:
    """Best-effort English singular of one normalized token (§4.2).

    Deliberately conservative: general suffix rules only, never a lookup of
    expected values. Returns the token unchanged when no rule applies, so a
    wrong guess degrades to "no extra match" rather than a false match.
    """
    if not token or len(token) <= 2:
        return token
    if token in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[token]
    if token in _SINGULAR_S_WORDS or not token.endswith("s"):
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses") or token.endswith("shes") or token.endswith("ches"):
        return token[:-2]
    if token.endswith("xes") or token.endswith("zes"):
        return token[:-2]
    if token.endswith("ses") and len(token) > 4:
        return token[:-2]
    if token.endswith("ss"):
        return token
    return token[:-1]


def normalize_token(token: str) -> str:
    """Normalize then singularize one token."""
    return singularize(normalize_text(token))


def tokenize(text: str | None) -> list[str]:
    """All normalized word tokens of a free-text string, order preserved."""
    return [t for t in normalize_text(text).split() if t]


def content_tokens(text: str | None) -> list[str]:
    """Normalized, singularized, stop-word-free tokens of a question.

    Order is preserved and duplicates are kept: a compound question that names
    the same concept twice should still weigh it twice.
    """
    return [singularize(t) for t in tokenize(text) if t not in STOP_WORDS]


#: Shortest prefix two tokens must share to count as morphologically related.
#: Four characters is long enough that unrelated short words do not collide
#: ("wall"/"walk" differ at position 4) while still relating real verb/noun
#: forms.
_MIN_STEM_PREFIX = 5


def stems_match(a: str, b: str) -> bool:
    """True when two tokens share a long common prefix.

    English relates concepts across parts of speech by suffix — a question says
    "contained" or "connected" while the schema says "containment" and
    "connects". Singularization alone cannot bridge those, so a bounded shared
    prefix does it: contain|ed / contain|ment, connect|ed / connect|s.

    Deliberately cruder than a real stemmer and used ONLY for ranking, never to
    admit a candidate on its own, so a false relation costs ordering rather than
    correctness.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    shortest = min(len(a), len(b))
    if shortest < _MIN_STEM_PREFIX:
        return False
    return a[:_MIN_STEM_PREFIX] == b[:_MIN_STEM_PREFIX]


def stem_affinity(query_tokens: frozenset[str] | set[str], target: frozenset[str]) -> float:
    """Fraction of `target` tokens morphologically related to the query, in [0, 1]."""
    if not target:
        return 0.0
    related = sum(1 for t in target if any(stems_match(t, q) for q in query_tokens))
    return related / len(target)


def token_overlap(query_tokens: frozenset[str] | set[str], target: frozenset[str]) -> float:
    """Fraction of `target`'s tokens covered by the query, in [0, 1].

    Scoring against the TARGET's size (not the union) is deliberate: a two-token
    field such as `FireRating` should score 1.0 when a question contains both
    "fire" and "rating", regardless of how long the rest of the question is.
    """
    if not target:
        return 0.0
    return len(set(query_tokens) & set(target)) / len(target)


def phrase_matches(query_tokens: frozenset[str] | set[str], identifier: str | None) -> bool:
    """True when every token of `identifier` appears in the query.

    This is the "exact normalized lexical match" test of §1.2 — the class of
    match that must survive before semantic supplements are capped.
    """
    target = frozenset(identifier_content_tokens(identifier))
    if not target:
        return False
    expanded = {singularize(t) for t in target} | target
    query = {singularize(t) for t in query_tokens} | set(query_tokens)
    return expanded <= query or target <= query
