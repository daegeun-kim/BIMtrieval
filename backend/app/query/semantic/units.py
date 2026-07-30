"""The ONE deterministic unit decision in the query path (task27 §4.3).

Values are stored in the units the IFC actually used. Nothing here converts
anything, and nothing here asks a model to reason about units — this is a pure
comparison between what the user wrote and what the field is recorded in.

Three questions, one answer each:

- **no unit written** — the number is interpreted in the field's own effective
  IFC unit, and that interpretation is DISCLOSED rather than assumed silently;
- **the same unit, spelled differently** — `metre`, `meter`, `m` and `m.`
  denote one unit, so the request executes and the normalisation is noted;
- **a different unit** — the request is refused with an honest reason. Task 27
  deliberately does not convert, so quietly comparing 900 mm against values
  stored in feet would be exactly the confident wrong answer this replaces.

A field whose unit state is `mixed` or `unknown` is never compared or aggregated
as if it were uniform, with or without a requested unit.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "FieldUnits",
    "UnitDecision",
    "decide_unit",
    "field_units",
    "normalize_unit_token",
    "units_equivalent",
]

#: Spelling variants that denote ONE unit. This is orthography, not conversion:
#: every group maps to a single physical unit, so accepting a member can never
#: change a magnitude. Deliberately no cross-unit entries — `cm` is not `m`.
_SPELLING_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mm", ("mm", "millimetre", "millimetres", "millimeter", "millimeters")),
    ("cm", ("cm", "centimetre", "centimetres", "centimeter", "centimeters")),
    ("m", ("m", "metre", "metres", "meter", "meters")),
    ("km", ("km", "kilometre", "kilometres", "kilometer", "kilometers")),
    (
        "mm²",
        (
            "mm2",
            "mm^2",
            "mm²",
            "sqmm",
            "square millimetre",
            "square millimetres",
            "square millimeter",
            "square millimeters",
        ),
    ),
    (
        "cm²",
        (
            "cm2",
            "cm^2",
            "cm²",
            "sqcm",
            "square centimetre",
            "square centimetres",
            "square centimeter",
            "square centimeters",
        ),
    ),
    (
        "m²",
        (
            "m2",
            "m^2",
            "m²",
            "sqm",
            "sq m",
            "square metre",
            "square metres",
            "square meter",
            "square meters",
        ),
    ),
    (
        "mm³",
        (
            "mm3",
            "mm^3",
            "mm³",
            "cubic millimetre",
            "cubic millimetres",
            "cubic millimeter",
            "cubic millimeters",
        ),
    ),
    (
        "m³",
        ("m3", "m^3", "m³", "cbm", "cubic metre", "cubic metres", "cubic meter", "cubic meters"),
    ),
    ("foot", ("foot", "feet", "ft", "'")),
    ("inch", ("inch", "inches", "in", '"')),
    ("square foot", ("square foot", "square feet", "sqft", "sq ft", "ft2", "ft^2", "ft²")),
    ("cubic foot", ("cubic foot", "cubic feet", "cuft", "cu ft", "ft3", "ft^3", "ft³")),
    ("square inch", ("square inch", "square inches", "sqin", "sq in", "in2", "in^2", "in²")),
    ("cubic inch", ("cubic inch", "cubic inches", "cuin", "cu in", "in3", "in^3", "in³")),
    ("yard", ("yard", "yards", "yd")),
    ("square yard", ("square yard", "square yards", "sqyd", "sq yd", "yd2", "yd²")),
    ("cubic yard", ("cubic yard", "cubic yards", "cuyd", "cu yd", "yd3", "yd³")),
)

_CANONICAL_BY_SPELLING: dict[str, str] = {
    spelling: canonical for canonical, spellings in _SPELLING_GROUPS for spelling in spellings
}

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = re.compile(r"[.\s]+$")


def normalize_unit_token(token: str | None) -> str | None:
    """Fold one written unit onto its canonical spelling, or None.

    Unrecognised text is returned case-folded and whitespace-normalised rather
    than dropped: an unknown unit must still be COMPARABLE, so that requesting
    one the field is not recorded in fails rather than silently matching.
    """
    if token is None:
        return None
    text = unicodedata.normalize("NFKC", str(token))
    text = _WHITESPACE.sub(" ", text).strip()
    text = _TRAILING_PUNCTUATION.sub("", text)
    if not text:
        return None
    folded = text.casefold()
    return _CANONICAL_BY_SPELLING.get(folded, folded)


def units_equivalent(left: str | None, right: str | None) -> bool:
    """True when two written units denote the same physical unit."""
    if left is None or right is None:
        return False
    return normalize_unit_token(left) == normalize_unit_token(right)


@dataclass(frozen=True)
class UnitDecision:
    """Whether a numeric request may execute, and what to say about it."""

    #: False means the request must NOT run. `reason` says why, in plain words.
    ok: bool
    #: The unit the values are actually in, reported with any result.
    unit: str | None = None
    #: Interpretation to disclose to the user when the request does run.
    note: str | None = None
    #: Why the request was refused, when it was.
    reason: str | None = None


def decide_unit(
    *,
    requested_unit: str | None,
    effective_unit: str | None,
    unit_state: str | None,
    measure_type: str | None,
    label: str,
    unit_limitation: str | None = None,
) -> UnitDecision:
    """Decide one numeric comparison/aggregation against one field.

    `effective_unit`/`unit_state`/`measure_type` come from the semantic
    manifest, which derives them from the IFC's own unit registry. No database
    read and no model call happens here, so the same inputs always give the same
    verdict.
    """
    dimensional = measure_type is not None
    uniform = unit_state == "uniform" and bool(effective_unit)

    # A plain number field (a count, an integer property) is not dimensional and
    # has no unit to reconcile — comparing it is ordinary arithmetic.
    if not dimensional:
        if requested_unit:
            return UnitDecision(
                ok=False,
                reason=(
                    f"{label} records no IFC measure type, so a value in {requested_unit} "
                    "cannot be compared against it"
                ),
            )
        return UnitDecision(ok=True)

    if not uniform:
        return UnitDecision(
            ok=False,
            reason=(
                unit_limitation
                or (
                    f"{label} does not resolve to one known unit in this model, so its "
                    "values cannot be compared or aggregated as a single scale"
                )
            ),
        )

    if not requested_unit:
        # §4.3: interpret in the field's own unit AND say so. Leaving this
        # implicit is how a magnitude silently acquires the wrong meaning.
        return UnitDecision(
            ok=True,
            unit=effective_unit,
            note=(f"interpreted in {effective_unit}, the unit this model records {label} in"),
        )

    if units_equivalent(requested_unit, effective_unit):
        note = None
        if requested_unit.strip() != effective_unit:
            note = (
                f"read {requested_unit!r} as {effective_unit}, "
                f"the unit this model records {label} in"
            )
        return UnitDecision(ok=True, unit=effective_unit, note=note)

    return UnitDecision(
        ok=False,
        unit=effective_unit,
        reason=(
            f"{label} is recorded in {effective_unit} in this model, not {requested_unit}; "
            "values are kept in the units the IFC uses and are not converted, so this "
            "comparison cannot be made"
        ),
    )


@dataclass(frozen=True)
class FieldUnits:
    """One field's measurement facts, read from the semantic manifest."""

    measure_type: str | None = None
    unit_state: str | None = None
    unit_symbol: str | None = None
    limitation: str | None = None

    @property
    def uniform(self) -> bool:
        return self.unit_state == "uniform" and bool(self.unit_symbol)


#: `ResolvedField.field_kind` -> the manifest concept kind that describes it.
#: DIMENSION resolves to a quantity-set field, so it shares that kind.
_MANIFEST_KIND_BY_FIELD_KIND: dict[str, str] = {
    "attribute": "attribute",
    "type_fact": "attribute",
    "property": "property",
    "quantity": "quantity",
    "dimension": "quantity",
    "measurement": "measurement",
}


def field_units(session, source_model_id: int, resolved_field) -> FieldUnits:
    """The manifest's measurement facts for one physically-resolved field.

    Returns an empty `FieldUnits` when no manifest is available. That degrades
    to "not dimensional": raw numbers still compare, and any explicitly
    requested unit is refused — never assumed to match.
    """
    from app.query.semantic.manifest.loader import (
        ManifestUnavailableError,
        get_semantic_manifest,
    )

    kind = _MANIFEST_KIND_BY_FIELD_KIND.get(getattr(resolved_field.field_kind, "value", ""))
    if kind is None or session is None:
        return FieldUnits()
    try:
        manifest = get_semantic_manifest(session, source_model_id)
    except ManifestUnavailableError:
        return FieldUnits()
    concept = manifest.field_by_reference(kind, resolved_field.set_name, resolved_field.field_name)
    if concept is None:
        return FieldUnits()
    return FieldUnits(
        measure_type=concept.measure_type,
        unit_state=concept.unit_state,
        unit_symbol=concept.unit_symbol,
        limitation=concept.unit_limitation,
    )
