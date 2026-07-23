"""Unreliable-source-structure detection (task25 §2.2).

These tests deliberately use synthetic containers with names, languages, and
shapes that resemble NO real authoring tool and share nothing with the models in
this repository. The detector must be a statement about SHAPE — a container
whose field space is unstable and unenumerable — not a rule about any particular
exporter, delimiter, container name, or model.

They also pin the negative half of the contract, which matters more: a pipeline
that flags too eagerly silently withholds real data, which is just as wrong as
one that infers.
"""

from __future__ import annotations

import pytest

from bim_rag.semantic_manifest.coverage import (
    DEFAULT_MAX_SCHEMA_RATIO,
    DEFAULT_MIN_DISTINCT_FIELDS,
    ContainerShape,
    classify_container_structure,
    classify_field_coverage,
)
from bim_rag.semantic_manifest.schema import (
    COVERAGE_ABSENT,
    COVERAGE_PARTIAL,
    COVERAGE_POPULATED,
    COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE,
    NON_QUERYABLE_COVERAGE,
)


def _shape(name: str, fields: int, occurrences: int, fields_each: float) -> ContainerShape:
    return ContainerShape(
        container=name,
        distinct_field_count=fields,
        occurrence_count=occurrences,
        field_instance_count=int(occurrences * fields_each),
    )


# ---------------------------------------------------------------------------
# Well-formed containers are never withheld
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,fields,occurrences,fields_each",
    [
        # A stable schema: every occurrence carries the whole field set.
        ("Egenskaper_Vagg", 6, 1500, 6.0),
        # Stable but sparsely populated — still a schema, still queryable.
        ("PROPRIETES_MUR", 12, 800, 9.0),
        # A single-field container.
        ("設備プロパティ", 1, 400, 1.0),
        # Large but stable AND genuinely shared: 300 fields carried by many
        # more occurrences than there are field names.
        ("bulk_but_consistent", 300, 5000, 300.0),
        # Wide-ish and slightly ragged, still far below the ratio threshold.
        ("mixed_schema", 200, 900, 40.0),
    ],
)
def test_a_container_with_a_stable_field_schema_stays_queryable(
    name, fields, occurrences, fields_each
):
    verdict = classify_container_structure(_shape(name, fields, occurrences, fields_each))

    assert verdict.reliable is True
    assert verdict.coverage == COVERAGE_POPULATED
    assert verdict.diagnostic is None


@pytest.mark.parametrize("fields", [1, 8, 40, DEFAULT_MIN_DISTINCT_FIELDS - 1])
def test_a_small_container_is_never_withheld_however_ragged_its_shape(fields):
    """Below the size floor, completeness is cheap — emit the fields regardless.

    Even a maximally ragged small container (every occurrence carrying exactly
    one of its fields) is fully representable, so withholding it would lose real
    information for no benefit.
    """
    verdict = classify_container_structure(_shape("tiny_ragged", fields, 5000, 1.0))

    assert verdict.reliable is True
    assert verdict.diagnostic is None


# ---------------------------------------------------------------------------
# Flattened bags are reported, never repaired
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,fields,occurrences,fields_each",
    [
        # Different naming conventions, delimiters, and languages — all of which
        # the detector must ignore entirely.
        ("GenericResourceBag", 6000, 3000, 80.0),
        ("attributs::conteneur", 900, 2000, 12.0),
        ("СвойстваОбъекта", 2500, 400, 30.0),
        ("a-b-c_d.e/f", 70, 100, 2.0),
        ("no_delimiters_at_all", 20000, 9000, 100.0),
    ],
)
def test_a_flattened_bag_is_reported_as_unsupported_source_structure(
    name, fields, occurrences, fields_each
):
    verdict = classify_container_structure(_shape(name, fields, occurrences, fields_each))

    assert verdict.reliable is False
    assert verdict.coverage == COVERAGE_UNSUPPORTED_SOURCE_STRUCTURE
    assert verdict.coverage in NON_QUERYABLE_COVERAGE


def test_the_diagnostic_is_bounded_and_never_enumerates_field_names():
    """The whole point of the state: describe the limitation, carry no field data.

    Enumerating thousands of unreliable identifiers would both bloat the binder
    prompt and invite the model to treat them as genuine concepts — exactly the
    inference this state exists to prevent.
    """
    verdict = classify_container_structure(_shape("SomeBag", 6594, 3228, 85.65))
    diagnostic = verdict.diagnostic

    assert set(diagnostic) == {
        "container",
        "distinct_field_count",
        "occurrence_count",
        "mean_fields_per_occurrence",
        "schema_ratio",
        "measured_against",
        "reason",
    }
    # Only counts and prose — nothing field-shaped, nothing unbounded.
    assert diagnostic["distinct_field_count"] == 6594
    assert isinstance(diagnostic["reason"], str)
    assert "fields" not in diagnostic
    assert "field_names" not in diagnostic


def test_the_reason_states_a_source_limitation_not_a_pipeline_failure():
    """A user reading this must understand the IFC did not expose the data.

    "Not represented in a queryable structure" is a different claim from "we
    could not process it", and different again from "it does not exist" (§5).
    """
    verdict = classify_container_structure(_shape("Bag", 5000, 1000, 50.0))
    reason = verdict.diagnostic["reason"].lower()

    assert "source data does not expose" in reason
    assert "reliably queryable" in reason
    assert "rather than guessed" in reason


# ---------------------------------------------------------------------------
# Both thresholds are load-bearing
# ---------------------------------------------------------------------------


def test_a_large_field_space_alone_does_not_trip_the_detector():
    """Size is not the problem — instability is. A big, stable, genuinely
    SHARED schema (more occurrences than field names) is fine."""
    verdict = classify_container_structure(_shape("big_stable", 5000, 20000, 5000.0))

    assert verdict.reliable is True


def test_a_per_instance_schedule_matrix_is_withheld_even_when_consistent():
    """task26 §4.4: a large container whose field names OUTNUMBER the
    occurrences carrying them is per-instance schedule data, not a shared
    property schema — even at schema_ratio ~1.0."""
    verdict = classify_container_structure(_shape("per_instance_bag", 300, 50, 300.0))

    assert verdict.reliable is False


def test_an_unstable_shape_alone_does_not_trip_the_detector():
    """Instability in a small field space is representable, so it is emitted."""
    verdict = classify_container_structure(_shape("small_unstable", 10, 5000, 1.0))

    assert verdict.reliable is True


def test_both_thresholds_must_be_exceeded_together():
    fields = DEFAULT_MIN_DISTINCT_FIELDS + 10
    ratio_ok = fields / (DEFAULT_MAX_SCHEMA_RATIO / 2)
    ratio_bad = fields / (DEFAULT_MAX_SCHEMA_RATIO * 2)

    assert classify_container_structure(_shape("a", fields, 100, ratio_ok)).reliable is True
    assert classify_container_structure(_shape("b", fields, 100, ratio_bad)).reliable is False


def test_thresholds_are_configurable_without_touching_the_rule():
    shape = _shape("borderline", 100, 100, 20.0)  # ratio 5.0

    assert classify_container_structure(shape, max_schema_ratio=8.0).reliable is True
    assert classify_container_structure(shape, max_schema_ratio=4.0).reliable is False
    # Raising the size floor above the container's width exempts it entirely.
    assert (
        classify_container_structure(shape, max_schema_ratio=4.0, min_distinct_fields=500).reliable
        is True
    )


def test_an_empty_container_does_not_raise_or_trip():
    """Degenerate input must not produce a division error or a false verdict."""
    verdict = classify_container_structure(_shape("empty", 0, 0, 0.0))

    assert verdict.reliable is True


# ---------------------------------------------------------------------------
# Ordinary field coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "populated,total,expected",
    [
        (100, 100, COVERAGE_POPULATED),
        (40, 100, COVERAGE_PARTIAL),
        (1, 100, COVERAGE_PARTIAL),
        (0, 100, COVERAGE_ABSENT),
        (0, 0, COVERAGE_ABSENT),
        # Defensive: a denominator smaller than the numerator still resolves.
        (120, 100, COVERAGE_POPULATED),
    ],
)
def test_field_coverage_states(populated, total, expected):
    assert classify_field_coverage(populated, total) == expected


def test_absent_is_an_exact_zero_and_stays_queryable():
    """`absent` means "asked, and the answer is none" — not "cannot tell".

    Collapsing it into the unsupported states would turn a correct zero into a
    false "unavailable", which §2.2 requires to stay distinguishable.
    """
    assert classify_field_coverage(0, 500) == COVERAGE_ABSENT
    assert COVERAGE_ABSENT not in NON_QUERYABLE_COVERAGE
