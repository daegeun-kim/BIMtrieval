"""Model-vocabulary builder unit tests (Task 16 §3, §13 Model vocabulary).

These need no database — they cover the deterministic helpers, profile text,
noise exclusion, fair trimming, and the read-only structural guarantee.
"""

from __future__ import annotations

import inspect

from app.query.semantic.vocabulary import builder as builder_mod
from app.query.semantic.vocabulary.builder import (
    _fair_trim,
    _is_noise_value,
    normalize_name_stem,
)
from app.query.semantic.vocabulary.profiles import (
    ClassProfile,
    ObservedFactProfile,
    QuantityCoverageProfile,
    QueryableRef,
)


def test_normalize_name_stem_strips_exporter_suffix():
    assert normalize_name_stem("liftdeur_(#561846)") == "liftdeur"
    assert normalize_name_stem("plat dak_(#755216)") == "plat dak"
    assert normalize_name_stem("vloerveld") == "vloerveld"  # no suffix, unchanged
    assert normalize_name_stem(None) is None
    assert normalize_name_stem("") is None


def test_is_noise_value_excludes_guids_step_numeric_empty_long():
    assert _is_noise_value(None)
    assert _is_noise_value("")
    assert _is_noise_value("   ")
    assert _is_noise_value("#413689")  # step-id-like
    assert _is_noise_value("12ZjsATRDFReOezU0yxRuU")  # 22-char GlobalId
    assert _is_noise_value("F34066AA-C09F-432C-BF28-6816143B0938")  # UUID tag
    assert _is_noise_value("123.45")  # pure numeric
    assert _is_noise_value("x" * 61)  # too long
    # ...but genuine multilingual terms are kept
    assert not _is_noise_value("plat dak")
    assert not _is_noise_value("Roof")
    assert not _is_noise_value("liftdeur")


def test_fair_trim_balances_across_class_and_kind_buckets():
    facts = []
    # Two classes, each with many property_value facts and a few name_stems.
    for cls in ("IfcA", "IfcZ"):
        for i in range(40):
            facts.append(
                ObservedFactProfile(
                    cls, "property_value", "property", "ps", "f", f"v{i}", None, 100 - i
                )
            )
        for i in range(5):
            facts.append(
                ObservedFactProfile(
                    cls, "name_stem", "attribute", None, "name", f"stem{i}", f"stem{i}", 10 - i
                )
            )
    kept = _fair_trim(facts, 30)
    assert len(kept) == 30
    # both classes represented, and name_stems survive (not starved by values)
    assert {f.ifc_class for f in kept} == {"IfcA", "IfcZ"}
    assert any(f.fact_kind == "name_stem" and f.ifc_class == "IfcZ" for f in kept)


def test_fair_trim_deterministic():
    facts = [
        ObservedFactProfile("IfcA", "property_value", "property", "ps", "f", f"v{i}", None, i)
        for i in range(50)
    ]
    a = [(f.ifc_class, f.observed_value) for f in _fair_trim(list(facts), 10)]
    b = [(f.ifc_class, f.observed_value) for f in _fair_trim(list(facts), 10)]
    assert a == b


def test_class_profile_text_and_excerpt_bounds():
    p = ClassProfile(
        ifc_class="IfcDoor",
        kind="entity",
        instance_count=205,
        name_stems=[("liftdeur", 36), ("stelkozijn", 65)],
        present_in_ontology=True,
        ontology_label="Door",
        ancestors=["IfcBuildingElement", "IfcElement"],
    )
    txt = p.profile_text()
    assert "IfcDoor" in txt and "liftdeur" in txt and "205" in txt
    assert len(p.excerpt(50)) == 50


def test_observed_fact_profile_preserves_provenance():
    f = ObservedFactProfile(
        ifc_class="IfcCovering",
        fact_kind="property_value",
        source="property",
        set_name="SynchroResourceProperty",
        field_name="[ArchiCADProperties]Type",
        observed_value="Roof",
        normalized_value=None,
        occurrence_count=42,
        queryable=QueryableRef(
            "property",
            "SynchroResourceProperty",
            "[ArchiCADProperties]Type",
            "case_insensitive_exact",
            "Roof",
        ),
    )
    txt = f.profile_text()
    assert "IfcCovering" in txt and "Roof" in txt and "42" in txt
    assert f.queryable.operator == "case_insensitive_exact"


def test_quantity_coverage_missing_count():
    q = QuantityCoverageProfile("IfcSpace", "Qto", "NetFloorArea", 3, 10, True)
    assert q.missing_count == 7
    assert "3 populated" in q.profile_text()


def test_builder_is_read_only():
    """No write statement appears in the builder — it is read-only over BIM
    tables (Task 16 §15)."""
    source = inspect.getsource(builder_mod).upper()
    for banned in ("INSERT ", "UPDATE ", "DELETE ", ".ADD(", ".COMMIT(", "CREATE ", "DROP "):
        assert banned not in source
