"""Value normalization against a field's OWN value vocabulary (Task 24 §4.2).

Runs only *after* a field has been selected. Field resolution and value
resolution are separate steps by contract (§1.3): a value is never matched
against unrelated fields, and never against a globally capped "top facts" list.
The caller supplies the chosen field's complete indexed value vocabulary and
this module decides whether the user's wording denotes one of those values.

Matching is a ladder, strongest first, and each rung records HOW it matched so
the caller can report the interpretation and so a weak match can be refused:

    exact  ->  normalized  ->  morphological  ->  boolean/enum  ->  contains

`contains` is opt-in (§4.2 "controlled contains/starts-with behavior only when
requested or semantically necessary") because substring matching silently
widens a result set.

Everything here is general: Unicode/case/punctuation folding, English
morphology, boolean and IFC enum spellings, and numeric/unit parsing. No rule
is conditioned on a particular field name, stored value, or question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.query.binding.lexical import normalize_text, singularize

__all__ = [
    "MatchKind",
    "ValueMatch",
    "normalize_value",
    "parse_boolean",
    "parse_number",
    "is_numeric_value",
    "resolve_value",
    "BOOLEAN_TRUE",
    "BOOLEAN_FALSE",
]


class MatchKind(str, Enum):
    """How a user value was tied to a stored value — reported, never guessed at."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    MORPHOLOGICAL = "morphological"
    BOOLEAN = "boolean"
    CONTAINS = "contains"


#: General boolean/presence spellings, including the IFC logical literals
#: (`.T.`, `.TRUE.`) which normalization reduces to bare words.
BOOLEAN_TRUE: frozenset[str] = frozenset({"true", "t", "yes", "y", "1", "on"})
BOOLEAN_FALSE: frozenset[str] = frozenset({"false", "f", "no", "n", "0", "off"})

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
#: Whole-string numeric test. Distinct from `_NUMBER_RE` on purpose: a stored
#: value like `EI30` or `M12` CONTAINS a number but IS NOT one, and treating it
#: as numeric would give a categorical field comparison operators it cannot
#: honour. User input is searched; stored values are matched in full.
_STRICT_NUMBER_RE = re.compile(r"^\s*-?\d+(?:[.,]\d+)?\s*$")
#: Unit spellings recognized on a user value. The conversion itself is delegated
#: to the existing unit system (`field_registry.normalize_quantity_value`); this
#: only identifies which unit the user wrote.
_UNIT_ALIASES: dict[str, str] = {
    "mm": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "cm": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "m": "m",
    "metre": "m",
    "metres": "m",
    "meter": "m",
    "meters": "m",
    "m2": "m2",
    "sqm": "m2",
    "m3": "m3",
    "deg": "degrees",
    "degree": "degrees",
    "degrees": "degrees",
}


@dataclass(frozen=True)
class ValueMatch:
    """One resolved value: what the user wrote, what the model stores, and how."""

    user_value: str
    stored_value: str
    match_kind: MatchKind

    @property
    def is_exact_identity(self) -> bool:
        """True when the match needs no interpretation caveat in the answer."""
        return self.match_kind in (MatchKind.EXACT, MatchKind.NORMALIZED)


def normalize_value(value: str | None) -> str:
    """Case/Unicode/punctuation-folded form of a stored or user value.

    IFC logical literals arrive as `.T.` / `.TRUE.`; punctuation folding reduces
    them to `t` / `true`, which the boolean sets below then recognize.
    """
    return normalize_text(value)


def _morphological_key(value: str | None) -> str:
    """Normalized value with every token singularized.

    This is what lets a user's "room" reach a stored "Rooms" (and the reverse)
    through general morphology rather than a synonym entry.
    """
    return " ".join(singularize(token) for token in normalize_value(value).split())


def parse_boolean(value: str | None) -> bool | None:
    """True/False for a recognized boolean spelling, else None."""
    normalized = normalize_value(value)
    if normalized in BOOLEAN_TRUE:
        return True
    if normalized in BOOLEAN_FALSE:
        return False
    return None


def is_numeric_value(value: str | None) -> bool:
    """True only when the ENTIRE value is a number.

    Used for data-type inference over stored values, where `EI30` must remain
    text. `parse_number` deliberately differs: it searches inside user wording
    such as "wider than 1 metre".
    """
    return bool(value) and _STRICT_NUMBER_RE.match(value) is not None


def parse_number(value: str | None) -> tuple[float, str | None] | None:
    """`(magnitude, unit)` parsed from a user value, or None.

    The unit is the normalized alias only — conversion stays with the existing
    unit system so there is exactly one place that knows what is convertible
    (§4.2, and `field_registry.normalize_quantity_value` for the real limits).
    """
    if not value:
        return None
    match = _NUMBER_RE.search(value)
    if match is None:
        return None
    try:
        magnitude = float(match.group(0).replace(",", "."))
    except ValueError:  # pragma: no cover - regex already constrains the shape
        return None
    remainder = normalize_value(value[match.end() :])
    unit: str | None = None
    for token in remainder.split():
        if token in _UNIT_ALIASES:
            unit = _UNIT_ALIASES[token]
            break
    return magnitude, unit


def resolve_value(
    user_value: str | None,
    observed_values: list[str] | tuple[str, ...],
    *,
    exact_required: bool = False,
    allow_contains: bool = False,
) -> ValueMatch | None:
    """Tie a user value to one of a field's stored values, or return None.

    Args:
        user_value: the value as the user wrote it.
        observed_values: the chosen field's COMPLETE indexed value vocabulary
            (§4.2 — never a globally capped top-k, never another field's values).
        exact_required: the user demanded exactness (e.g. a quoted value), so
            only an identical stored string is acceptable (§4.2).
        allow_contains: permit the substring rung. Off by default because it
            widens the result set.

    Returns None rather than a weak guess when nothing matches — the caller must
    then report the value as unresolved, never drop the condition (§2.4).
    """
    if not user_value or not observed_values:
        return None

    # 1. Exact identity. Always tried first, and the only rung permitted when
    #    the user asked for an exact value.
    for stored in observed_values:
        if stored == user_value:
            return ValueMatch(user_value, stored, MatchKind.EXACT)
    if exact_required:
        return None

    user_normalized = normalize_value(user_value)
    if not user_normalized:
        return None

    # 2. Case/Unicode/punctuation-insensitive identity.
    for stored in observed_values:
        if normalize_value(stored) == user_normalized:
            return ValueMatch(user_value, stored, MatchKind.NORMALIZED)

    # 3. Morphology (singular/plural).
    user_morph = _morphological_key(user_value)
    if user_morph:
        for stored in observed_values:
            if _morphological_key(stored) == user_morph:
                return ValueMatch(user_value, stored, MatchKind.MORPHOLOGICAL)

    # 4. Boolean/enum equivalence, so "yes"/"true"/"1" all reach a stored
    #    boolean regardless of which spelling the exporter wrote.
    user_bool = parse_boolean(user_value)
    if user_bool is not None:
        for stored in observed_values:
            if parse_boolean(stored) is user_bool:
                return ValueMatch(user_value, stored, MatchKind.BOOLEAN)

    # 5. Substring — opt-in only.
    if allow_contains:
        for stored in observed_values:
            stored_normalized = normalize_value(stored)
            if user_normalized and user_normalized in stored_normalized:
                return ValueMatch(user_value, stored, MatchKind.CONTAINS)

    return None
