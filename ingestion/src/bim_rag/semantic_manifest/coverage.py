"""Coverage classification, including unreliable source structures (task25 §2.2).

Most of this module is ordinary: a field concept is `populated`, `partial`, or
`absent` depending on how many of the occurrences it applies to actually carry
a value, and `absent` is an EXACT ZERO that must never be confused with missing
extraction support.

The interesting part is `classify_container_structure`.

Why it exists
-------------
A property container is only queryable if its field names mean the same thing
from one occurrence to the next. Some authoring tools export a container that
is not a property set at all but a flattened bag: thousands of distinct field
names, each appearing on a handful of occurrences, often with the originating
container's name folded into the field name.

Such a container cannot be represented as queryable properties without INFERRING
what its field names were meant to be. This module deliberately does not infer.
It detects that the structure is unreliable, records a bounded diagnostic, and
marks the container `unsupported_source_structure` so that questions needing it
answer `unavailable` with the limitation stated.

The invariant, and why it generalizes
-------------------------------------
A well-formed property set applies a STABLE FIELD SCHEMA to the occurrences it
covers: every wall carries much the same handful of wall properties. So the
number of distinct field names in the container is close to the number of
fields an individual occurrence carries::

    schema_ratio = distinct_field_names / mean_fields_per_occurrence

    well-formed container -> ratio near 1.0   (every occurrence sees the schema)
    flattened bag         -> ratio very large (each occurrence sees only its own)

This is a property of SHAPE, not of vocabulary. It reads no field name, parses
no delimiter, and knows nothing about any specific authoring tool, container
name, or model. A bag exported under any name, with any internal naming
convention, in any language, trips it identically — which is exactly what makes
it a reusable invariant rather than a patch for one file.

Two thresholds must BOTH be exceeded:

- `max_schema_ratio` — how far from a stable schema the container sits;
- `min_distinct_fields` — a floor that keeps small containers out of it.

The floor matters. A container with 6 fields where each occurrence happens to
carry one has a ratio of 6, but it is still *completely representable* — all six
fields fit in the manifest, so there is nothing to lose and no reason to
withhold them. The state is reserved for containers whose field space is both
unstable AND too large to enumerate meaningfully.
"""

from __future__ import annotations

from dataclasses import dataclass

from bim_rag.semantic_manifest.schema import (
    COVERAGE_ABSENT,
    COVERAGE_PARTIAL,
    COVERAGE_POPULATED,
    COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
)

#: A container must look at least this unlike a stable schema to be rejected.
#: Observed separation on real models is wide — well-formed property sets sit at
#: 1.0-1.3 — so this sits far above the noise without approaching any real value.
DEFAULT_MAX_SCHEMA_RATIO = 8.0

#: ...and must also be too large to simply enumerate. Below this, completeness
#: is cheap and the fields are emitted normally whatever their shape.
DEFAULT_MIN_DISTINCT_FIELDS = 64


@dataclass(frozen=True)
class ContainerShape:
    """Shape statistics for one property/quantity container in one model.

    Carries no field names — only counts — so a diagnostic built from it cannot
    leak an unbounded list of unreliable identifiers into the manifest.
    """

    container: str
    distinct_field_count: int
    occurrence_count: int
    #: Total (occurrence, field) pairs observed in this container.
    field_instance_count: int

    @property
    def mean_fields_per_occurrence(self) -> float:
        if self.occurrence_count <= 0:
            return 0.0
        return self.field_instance_count / self.occurrence_count

    @property
    def schema_ratio(self) -> float:
        """Distinct fields per field-carried-by-one-occurrence. ~1.0 when sane."""
        mean = self.mean_fields_per_occurrence
        if mean <= 0:
            return 0.0
        return self.distinct_field_count / mean


@dataclass(frozen=True)
class StructureVerdict:
    """Whether a container's fields may be treated as queryable concepts."""

    reliable: bool
    coverage: str
    diagnostic: dict[str, object] | None = None


def classify_container_structure(
    shape: ContainerShape,
    *,
    max_schema_ratio: float = DEFAULT_MAX_SCHEMA_RATIO,
    min_distinct_fields: int = DEFAULT_MIN_DISTINCT_FIELDS,
) -> StructureVerdict:
    """Decide whether `shape`'s fields are reliably interpretable.

    Returns a verdict carrying a BOUNDED diagnostic — observed container, field
    count, occurrence count, the measured ratio, and the reason. Never the field
    names themselves: enumerating thousands of unreliable identifiers would both
    bloat the manifest and invite the binder to treat them as real concepts.
    """
    if shape.distinct_field_count < min_distinct_fields:
        return StructureVerdict(reliable=True, coverage=COVERAGE_POPULATED)
    if (
        shape.schema_ratio < max_schema_ratio
        # A large container whose distinct field names OUTNUMBER the
        # occurrences carrying them is a per-instance schedule matrix, not a
        # shared property schema — even when each occurrence carries the whole
        # matrix (ratio near 1.0). Field names that exist for fewer subjects
        # than there are fields cannot be resolved as reusable concepts
        # (task26 §4.4).
        and shape.distinct_field_count <= shape.occurrence_count
    ):
        return StructureVerdict(reliable=True, coverage=COVERAGE_POPULATED)

    return StructureVerdict(
        reliable=False,
        coverage=COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
        diagnostic={
            "container": shape.container,
            "distinct_field_count": shape.distinct_field_count,
            "occurrence_count": shape.occurrence_count,
            "mean_fields_per_occurrence": round(shape.mean_fields_per_occurrence, 2),
            "schema_ratio": round(shape.schema_ratio, 2),
            "measured_against": {
                "max_schema_ratio": max_schema_ratio,
                "min_distinct_fields": min_distinct_fields,
            },
            "reason": (
                "This container does not present a stable field schema across the "
                "occurrences it covers: it holds far more distinct field names than any "
                "single occurrence carries, so its field names cannot be resolved to "
                "queryable properties without inferring what they were intended to mean. "
                "The source data does not expose these properties in a reliably queryable "
                "structure, so they are reported as unavailable rather than guessed."
            ),
        },
    )


def classify_field_coverage(populated_count: int, total_count: int) -> str:
    """Populated / partial / absent for one field concept.

    `absent` is an exact zero — the field is known and simply carried by no
    occurrence. Callers must keep that distinct from the unsupported states,
    which mean the pipeline cannot tell (§2.2).
    """
    if total_count <= 0 or populated_count <= 0:
        return COVERAGE_ABSENT
    if populated_count >= total_count:
        return COVERAGE_POPULATED
    return COVERAGE_PARTIAL
