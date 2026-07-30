"""Per-field measurement facts for the semantic manifest (task27 §3).

The manifest must say, for every supported numeric field, whether that field can
actually be compared and aggregated — and when it cannot, why. This module turns
two inputs into that verdict:

- the per-occurrence measure metadata ingestion wrote into canonical JSON
  (`measure_type`, and an `unit_override_key` only when the IFC supplied one);
- the source model's own unit registry, stored once in
  `ifc_source_models.extraction_metadata.dimension_units`.

It never re-opens the IFC and never infers a measure type from a field name
(§3). A field is safe exactly when every populated occurrence resolves to the
same displayable effective unit::

    effective unit = unit_override_key   otherwise   defaults[measure_type]

Three states, and they are NOT interchangeable:

`uniform`
    One effective unit across every populated occurrence. Comparison and
    aggregation are permitted, and the unit is reported with the result.

`mixed`
    More than one effective unit. Summing them as one scale would produce a
    confident wrong number, so the field is marked unsafe and the observed
    variants are listed (bounded) so the limitation can be explained.

`unknown`
    Some populated occurrence carries no supported measure type, or its measure
    type has no resolvable project default, or the unit definition cannot be
    displayed. The honest answer is "this cannot be calculated", never a
    substituted default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bim_rag.semantic_manifest.schema import (
    UNIT_STATE_MIXED,
    UNIT_STATE_UNIFORM,
    UNIT_STATE_UNKNOWN,
)

#: Cap on the variant list emitted for a mixed-unit field. The COUNT is always
#: exact; only the enumeration is bounded, so a pathological field cannot bloat
#: the manifest while still being reported as unsafe.
MAX_UNIT_VARIANTS = 8

__all__ = [
    "MAX_UNIT_VARIANTS",
    "MeasureFacts",
    "UnitRegistryView",
    "build_measure_facts",
    "empty_measure_facts",
]


class UnitRegistryView:
    """Read-only view of one model's stored `dimension_units` registry."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        payload = payload or {}
        self.contract_version: str | None = payload.get("contract_version")
        self.defaults: dict[str, str | None] = dict(payload.get("defaults") or {})
        self.definitions: dict[str, dict[str, Any]] = dict(payload.get("definitions") or {})
        self.unresolved_defaults: dict[str, str] = dict(payload.get("unresolved_defaults") or {})

    def default_key(self, measure_type: str | None) -> str | None:
        if not measure_type:
            return None
        return self.defaults.get(measure_type)

    def symbol(self, unit_key: str | None) -> str | None:
        if not unit_key:
            return None
        definition = self.definitions.get(unit_key)
        if not definition or not definition.get("resolved", True):
            return None
        symbol = definition.get("symbol")
        return symbol if isinstance(symbol, str) and symbol else None

    def to_content(self) -> dict[str, Any]:
        """The registry as carried in the manifest's global level.

        Bounded by construction — a model declares one default per family and a
        handful of definitions — and key-sorted so the content hash is stable.
        """
        content: dict[str, Any] = {
            "contract_version": self.contract_version,
            "defaults": {k: self.defaults[k] for k in sorted(self.defaults)},
            "definitions": {k: self.definitions[k] for k in sorted(self.definitions)},
        }
        if self.unresolved_defaults:
            content["unresolved_defaults"] = {
                k: self.unresolved_defaults[k] for k in sorted(self.unresolved_defaults)
            }
        return content


@dataclass(frozen=True)
class MeasureFacts:
    """One field's measurement verdict, ready to merge into a field record."""

    #: None when the field carries no supported measure type at all. Such a
    #: field is an ordinary value field and gets no measurement facts.
    measure_type: str | None = None
    unit_state: str = UNIT_STATE_UNKNOWN
    unit_key: str | None = None
    unit_symbol: str | None = None
    comparison_safe: bool = False
    limitation: str | None = None
    variants: tuple[dict[str, Any], ...] = ()
    measure_source: str | None = None
    typed_count: int = 0
    untyped_count: int = 0
    measure_type_variants: tuple[str, ...] = field(default=())

    @property
    def is_measured(self) -> bool:
        """True when this field is dimensional at all."""
        return self.typed_count > 0

    def to_record(self) -> dict[str, Any]:
        """The manifest fragment merged into the field record."""
        if not self.is_measured:
            return {}
        record: dict[str, Any] = {
            "measure_type": self.measure_type,
            "measure_source": self.measure_source,
            "unit_state": self.unit_state,
            "numeric_comparison_safe": self.comparison_safe,
            "typed_value_count": self.typed_count,
        }
        if self.untyped_count:
            record["untyped_value_count"] = self.untyped_count
        if self.measure_type_variants:
            record["measure_type_variants"] = list(self.measure_type_variants)
        if self.unit_key:
            record["unit_key"] = self.unit_key
        if self.unit_symbol:
            record["unit_symbol"] = self.unit_symbol
        if self.variants:
            record["unit_variants"] = list(self.variants)
        if self.limitation:
            record["unit_limitation"] = self.limitation
        return record


def empty_measure_facts() -> MeasureFacts:
    return MeasureFacts()


def build_measure_facts(
    rows: list[tuple[str | None, str | None, int]],
    registry: UnitRegistryView,
    *,
    measure_source: str,
    label: str,
) -> MeasureFacts:
    """Classify one field from its observed `(measure_type, override_key, count)` rows.

    `rows` covers every POPULATED occurrence of the field, including those whose
    `measure_type` is None — a partially-typed field must not be presented as
    fully measured, so the untyped remainder is what forces `unknown`.
    """
    typed = [(m, o, c) for m, o, c in rows if m]
    typed_count = sum(c for _, _, c in typed)
    untyped_count = sum(c for m, _, c in rows if not m)
    if typed_count == 0:
        return MeasureFacts(untyped_count=untyped_count)

    measure_types = sorted({m for m, _, _ in typed if m})
    measure_type = measure_types[0] if len(measure_types) == 1 else None

    # Effective unit per observed group, exactly as the query path resolves it.
    effective: dict[str | None, int] = {}
    for observed_measure, override_key, count in typed:
        key = override_key or registry.default_key(observed_measure)
        effective[key] = effective.get(key, 0) + count

    variants = tuple(
        {
            "unit_key": key,
            "symbol": registry.symbol(key),
            "count": count,
        }
        for key, count in sorted(effective.items(), key=lambda item: (-item[1], str(item[0])))[
            :MAX_UNIT_VARIANTS
        ]
    )

    base = {
        "measure_type": measure_type,
        "measure_source": measure_source,
        "typed_count": typed_count,
        "untyped_count": untyped_count,
        "measure_type_variants": tuple(measure_types) if measure_type is None else (),
    }

    if len(measure_types) > 1:
        return MeasureFacts(
            **base,
            unit_state=UNIT_STATE_UNKNOWN,
            comparison_safe=False,
            variants=variants,
            limitation=(
                f"{label} carries more than one IFC measure type "
                f"({', '.join(measure_types)}) across its recorded values, so its numbers "
                "do not share one physical meaning and cannot be compared or aggregated"
            ),
        )

    if untyped_count:
        return MeasureFacts(
            **base,
            unit_state=UNIT_STATE_UNKNOWN,
            comparison_safe=False,
            variants=variants,
            limitation=(
                f"{untyped_count} of the {typed_count + untyped_count} recorded values for "
                f"{label} carry no IFC measure type, so this field's numbers cannot all be "
                "resolved to a unit and must not be compared or aggregated as one scale"
            ),
        )

    if len(effective) > 1:
        return MeasureFacts(
            **base,
            unit_state=UNIT_STATE_MIXED,
            comparison_safe=False,
            variants=variants,
            limitation=(
                f"{label} is recorded in {len(effective)} different units in this model, so "
                "its values are not on one scale; they are not summed or compared here, and "
                "no conversion is performed"
            ),
        )

    unit_key = next(iter(effective))
    symbol = registry.symbol(unit_key)
    if unit_key is None:
        return MeasureFacts(
            **base,
            unit_state=UNIT_STATE_UNKNOWN,
            comparison_safe=False,
            variants=variants,
            limitation=(
                registry.unresolved_defaults.get(measure_type or "")
                or (
                    f"this model declares no project default {measure_type} unit, so the "
                    f"values of {label} have no known unit and cannot be compared or aggregated"
                )
            ),
        )
    if symbol is None:
        return MeasureFacts(
            **base,
            unit_state=UNIT_STATE_UNKNOWN,
            unit_key=unit_key,
            comparison_safe=False,
            variants=variants,
            limitation=(
                f"the unit recorded for {label} could not be resolved to a displayable IFC "
                "unit, so its values are reported without calculation"
            ),
        )

    return MeasureFacts(
        **base,
        unit_state=UNIT_STATE_UNIFORM,
        unit_key=unit_key,
        unit_symbol=symbol,
        comparison_safe=True,
    )
