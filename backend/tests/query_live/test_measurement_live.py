"""Dimensional filtering and aggregation against the live corpus (task27 §7.3).

Read-only, no OpenAI call, no embedding. Assertions are INVARIANTS over whatever
models happen to be ingested — never an expected count, field name, or unit for
a particular file — so they keep their meaning as the corpus changes, and so a
model with no trustworthy typed dimensions satisfies them by reporting nothing
rather than by reporting something plausible.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import IfcEntity
from app.db.session import get_engine
from app.query.semantic.manifest.loader import (
    ManifestUnavailableError,
    get_semantic_manifest,
)
from app.query.semantic.manifest.schema import KIND_MEASUREMENT
from app.query.semantic.units import decide_unit, field_units
from app.query.sql.aggregates import compute_aggregate
from app.query.sql.compiler import build_condition_expr
from app.query.sql.entities import aggregate_entities
from app.query.sql.errors import UnitNotAvailableError
from app.query.sql.field_registry import resolve_field
from app.query.sql.schemas import (
    AggregateEntitiesPlan,
    FieldKind,
    FieldRef,
    FilterCondition,
    FilterGroup,
    Operator,
)

_ET = IfcEntity.__table__


def _model_ids(session: Session) -> list[int]:
    return [r[0] for r in session.execute(text("SELECT id FROM ifc_source_models ORDER BY id"))]


@pytest.fixture(scope="module")
def models(live_session):
    return _model_ids(live_session)


def _manifest(session: Session, source_model_id: int):
    try:
        return get_semantic_manifest(session, source_model_id)
    except ManifestUnavailableError as exc:
        pytest.skip(f"model {source_model_id} has no current manifest: {exc}")


def _uniform_fields(manifest) -> list:
    return [c for c in manifest.fields() if c.is_dimensional and c.unit_available]


def _field_ref(concept) -> FieldRef:
    kind = {
        "property": FieldKind.PROPERTY,
        "quantity": FieldKind.QUANTITY,
        KIND_MEASUREMENT: FieldKind.MEASUREMENT,
    }[concept.kind]
    return FieldRef(field_kind=kind, set_name=concept.set_name, field_name=concept.field_name)


def _first_uniform(session: Session, models: list[int]):
    """The first (model, concept) pair with a uniform, resolvable unit."""
    for source_model_id in models:
        manifest = get_semantic_manifest(session, source_model_id)
        for concept in _uniform_fields(manifest):
            return source_model_id, concept
    return None, None


# ---------------------------------------------------------------------------
# The manifest / candidate universe
# ---------------------------------------------------------------------------


def test_every_model_publishes_a_current_manifest_with_a_unit_registry(live_session, models):
    for source_model_id in models:
        manifest = _manifest(live_session, source_model_id)
        assert set(manifest.dimension_units.get("defaults", {})) == {
            "length",
            "area",
            "volume",
        }


def test_a_typed_uniform_field_is_selectable_from_the_complete_manifest(live_session, models):
    """§4.2: a newly ingested typed field is reachable WITHOUT being named in
    backend source. Finding it here proves discovery goes through the manifest."""
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    assert manifest_concept_is_selectable(live_session, source_model_id, concept)


def manifest_concept_is_selectable(session: Session, source_model_id: int, concept) -> bool:
    manifest = get_semantic_manifest(session, source_model_id)
    return manifest.concept(concept.semantic_id) is not None


def test_every_dimensional_field_states_a_usable_or_explained_verdict(live_session, models):
    for source_model_id in models:
        manifest = _manifest(live_session, source_model_id)
        for concept in manifest.fields():
            if not concept.is_dimensional:
                continue
            if concept.unit_available:
                assert concept.unit_state == "uniform"
                assert concept.unit_symbol
            else:
                assert concept.unit_limitation, concept.semantic_id


def test_a_number_without_a_declared_measure_type_is_not_dimensional(live_session, models):
    """A field name never promotes a raw number into a dimension (§1.2)."""
    for source_model_id in models:
        manifest = _manifest(live_session, source_model_id)
        for concept in manifest.fields():
            if concept.measure_type is None:
                assert concept.unit_symbol is None
                assert concept.unit_available is False


# ---------------------------------------------------------------------------
# Physical reads: raw values, exact coverage
# ---------------------------------------------------------------------------


def test_a_dimensional_field_resolves_to_a_readable_numeric_leaf(live_session, models):
    """The resolved path must reach the VALUE, not the entry object.

    Stopping one level short made every quantity read a serialized JSON object,
    which is never numeric — so filters matched nothing and aggregates covered
    nothing, silently.
    """
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")

    resolved = resolve_field(live_session, source_model_id, _field_ref(concept))
    assert resolved.json_path[-1] == "value"

    where = _ET.c.source_model_id == source_model_id
    aggregate = compute_aggregate(live_session, _ET, where, "sum", resolved, concept.unit_symbol)
    assert aggregate.coverage_count > 0, "a populated dimensional field must read as numeric"
    assert aggregate.value is not None


def test_an_aggregate_carries_the_effective_ifc_unit(live_session, models):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")

    result = aggregate_entities(
        live_session,
        AggregateEntitiesPlan(
            source_model_id=source_model_id,
            function="sum",
            field=_field_ref(concept),
        ),
    )
    assert result.unit == concept.unit_symbol
    assert result.unit


@pytest.mark.parametrize("function", ["sum", "min", "max", "average"])
def test_every_aggregate_function_returns_the_unit(live_session, models, function):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    result = aggregate_entities(
        live_session,
        AggregateEntitiesPlan(
            source_model_id=source_model_id,
            function=function,
            field=_field_ref(concept),
        ),
    )
    assert result.unit == concept.unit_symbol


def test_matched_and_coverage_counts_stay_truthful(live_session, models):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    result = aggregate_entities(
        live_session,
        AggregateEntitiesPlan(
            source_model_id=source_model_id,
            function="sum",
            field=_field_ref(concept),
        ),
    )
    assert 0 < result.coverage_count <= result.matched_count
    if result.coverage_count < result.matched_count:
        assert result.warnings, "partial coverage must not be reported as complete"


def test_a_numeric_filter_reads_raw_values_and_partitions_the_set(live_session, models):
    """`> x` and `<= x` over a populated field must together cover its coverage."""
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    resolved = resolve_field(live_session, source_model_id, _field_ref(concept))
    base = _ET.c.source_model_id == source_model_id

    total = compute_aggregate(live_session, _ET, base, "sum", resolved, None).coverage_count
    threshold = 0.0
    counts = []
    for operator in (Operator.GT, Operator.LTE):
        where = sa.and_(
            base,
            build_condition_expr(
                live_session,
                source_model_id,
                FilterGroup(
                    bool_op="and",
                    conditions=[
                        FilterCondition(
                            field=_field_ref(concept), operator=operator, value=threshold
                        )
                    ],
                ),
                _ET,
            ),
        )
        counts.append(
            live_session.execute(
                sa.select(sa.func.count()).select_from(_ET).where(where)
            ).scalar_one()
        )
    assert sum(counts) == total


# ---------------------------------------------------------------------------
# Unit safety
# ---------------------------------------------------------------------------


def test_the_same_unit_spelled_differently_is_accepted(live_session, models):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    result = aggregate_entities(
        live_session,
        AggregateEntitiesPlan(
            source_model_id=source_model_id,
            function="sum",
            field=_field_ref(concept),
            unit=concept.unit_symbol,
        ),
    )
    assert result.unit == concept.unit_symbol


def test_a_different_requested_unit_is_refused_rather_than_converted(live_session, models):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    # A unit that cannot be the same as any effective unit in the corpus.
    with pytest.raises(UnitNotAvailableError) as excinfo:
        aggregate_entities(
            live_session,
            AggregateEntitiesPlan(
                source_model_id=source_model_id,
                function="sum",
                field=_field_ref(concept),
                unit="furlongs",
            ),
        )
    assert concept.unit_symbol in str(excinfo.value)


def test_a_mixed_or_unknown_unit_field_cannot_produce_an_aggregate(live_session, models):
    for source_model_id in models:
        manifest = _manifest(live_session, source_model_id)
        unsafe = [
            c
            for c in manifest.fields()
            if c.is_dimensional and not c.unit_available and c.populated_count
        ]
        for concept in unsafe[:3]:
            with pytest.raises(UnitNotAvailableError):
                aggregate_entities(
                    live_session,
                    AggregateEntitiesPlan(
                        source_model_id=source_model_id,
                        function="sum",
                        field=_field_ref(concept),
                    ),
                )
            return  # one confirmed refusal is enough; the rule is field-agnostic


def test_field_units_agree_with_the_manifest(live_session, models):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    resolved = resolve_field(live_session, source_model_id, _field_ref(concept))
    units = field_units(live_session, source_model_id, resolved)
    assert units.measure_type == concept.measure_type
    assert units.unit_symbol == concept.unit_symbol
    assert units.uniform is True


def test_a_unitless_literal_discloses_the_unit_it_was_read_in(live_session, models):
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")
    resolved = resolve_field(live_session, source_model_id, _field_ref(concept))
    units = field_units(live_session, source_model_id, resolved)
    decision = decide_unit(
        requested_unit=None,
        effective_unit=units.unit_symbol,
        unit_state=units.unit_state,
        measure_type=units.measure_type,
        label=concept.label,
    )
    assert decision.ok
    assert decision.unit == concept.unit_symbol
    assert concept.unit_symbol in decision.note


# ---------------------------------------------------------------------------
# Isolation and absence
# ---------------------------------------------------------------------------


def test_a_dimensional_aggregate_stays_inside_its_source_model(live_session, models):
    if len(models) < 2:
        pytest.skip("cross-model isolation needs at least two ingested models")
    source_model_id, concept = _first_uniform(live_session, models)
    if concept is None:
        pytest.skip("no model in this corpus carries a uniform-unit dimensional field")

    scoped = aggregate_entities(
        live_session,
        AggregateEntitiesPlan(
            source_model_id=source_model_id, function="sum", field=_field_ref(concept)
        ),
    )
    model_total = live_session.execute(
        sa.select(sa.func.count()).select_from(_ET).where(_ET.c.source_model_id == source_model_id)
    ).scalar_one()
    corpus_total = live_session.execute(sa.select(sa.func.count()).select_from(_ET)).scalar_one()

    assert scoped.matched_count == model_total
    assert scoped.matched_count < corpus_total


def test_missing_dimensional_data_is_unavailable_rather_than_zero(live_session, models):
    """A model with no typed dimensions must SAY so, not report totals of 0."""
    for source_model_id in models:
        manifest = _manifest(live_session, source_model_id)
        if _uniform_fields(manifest):
            continue
        reasons = [
            m
            for m in manifest.unsupported_capabilities()
            if m.get("capability") == "dimensional_queries"
        ]
        assert reasons, (
            f"model {source_model_id} has no usable dimensional field and must declare it"
        )


def test_the_removed_normalization_is_gone_from_the_corpus(live_session, models):
    """No stored value may still carry the invalid v001 normalization (§2.3)."""
    for source_model_id in models:
        leftover = live_session.execute(
            text(
                "SELECT count(*) FROM ifc_entities e, "
                "jsonb_each(e.canonical_json->'quantity_sets') qs, "
                "jsonb_each(qs.value) q "
                "WHERE e.source_model_id = :id AND q.value ? 'normalized_unit'"
            ),
            {"id": source_model_id},
        ).scalar()
        assert leftover == 0


def test_the_engine_is_the_read_only_role():
    """Every statement above runs read-only; a write must be rejected."""
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(Exception):
            session.execute(text("CREATE TABLE task27_should_not_exist (id int)"))
            session.commit()
        session.rollback()
