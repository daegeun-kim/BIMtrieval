"""Live, read-only model-vocabulary tests (Task 16 §3, §13).

Skips with the rest of query_live when the database is unreachable.
"""

from __future__ import annotations

from app.config.settings import get_settings
from app.query.semantic.vocabulary.builder import build_model_vocabulary
from app.query.semantic.vocabulary.cache import clear_vocabulary_cache, get_model_vocabulary

SID = 1


def test_exact_class_counts(live_session):
    v = build_model_vocabulary(live_session, SID)
    assert v.class_count("IfcDoor") == 205
    assert v.class_count("IfcStair") == 9
    assert v.class_count("IfcCovering") == 1214
    assert v.class_count("IfcSlab") == 279
    # absent classes report exactly zero (not "unknown")
    assert v.class_count("IfcRoof") == 0
    assert v.class_count("IfcSpace") == 0


def test_multilingual_name_stems_preserved(live_session):
    v = build_model_vocabulary(live_session, SID)
    door = next(c for c in v.classes if c.ifc_class == "IfcDoor")
    stems = dict(door.name_stems)
    assert "liftdeur" in stems  # Dutch retained, not translated/dropped
    # name-stem facts keep the original as observed_value and expose a queryable ref
    lift = next(
        f
        for f in v.facts
        if f.ifc_class == "IfcDoor"
        and f.fact_kind == "name_stem"
        and f.observed_value == "liftdeur"
    )
    assert lift.occurrence_count == 36
    assert lift.queryable is not None
    assert lift.queryable.field_kind == "attribute"
    assert lift.queryable.operator == "contains"


def test_roof_representation_discoverable(live_session):
    v = build_model_vocabulary(live_session, SID)
    # roof lives in name stems (Dutch 'dak') and a categorical property value
    dak = [f for f in v.facts if "dak" in (f.normalized_value or "").lower()]
    assert dak, "expected Dutch roof name stems (dak*)"
    roof_prop = [
        f for f in v.facts if f.fact_kind == "property_value" and f.observed_value.lower() == "roof"
    ]
    assert roof_prop, "expected a categorical Type=Roof property value fact"
    assert all(f.queryable is not None for f in roof_prop)


def test_no_quantity_sets_means_no_area_coverage(live_session):
    """This model has no quantity sets, so corridor/usable-area totals are not
    calculable — the vocabulary reflects that truthfully (Task 16 §12 corridor)."""
    v = build_model_vocabulary(live_session, SID)
    assert v.quantities == []


def test_bounded_excerpts_and_no_canonical_json(live_session):
    settings = get_settings()
    v = build_model_vocabulary(live_session, SID)
    for c in v.classes:
        assert len(c.excerpt(settings.vocab_max_profile_excerpt_chars)) <= (
            settings.vocab_max_profile_excerpt_chars
        )
    # no fact leaks full canonical JSON or opaque blobs
    for f in v.facts:
        assert "canonical_json" not in f.observed_value
        assert len(f.observed_value) <= 60
    assert len(v.facts) <= settings.vocab_max_facts_total


def test_deterministic_build(live_session):
    v1 = build_model_vocabulary(live_session, SID)
    v2 = build_model_vocabulary(live_session, SID)
    key1 = [(f.ifc_class, f.fact_kind, f.observed_value, f.occurrence_count) for f in v1.facts]
    key2 = [(f.ifc_class, f.fact_kind, f.observed_value, f.occurrence_count) for f in v2.facts]
    assert key1 == key2


def test_cache_returns_same_instance_until_cleared(live_session):
    clear_vocabulary_cache()
    a = get_model_vocabulary(live_session, SID)
    b = get_model_vocabulary(live_session, SID)
    assert a is b  # cached
    clear_vocabulary_cache()
    c = get_model_vocabulary(live_session, SID)
    assert c is not a  # rebuilt after invalidation
