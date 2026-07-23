"""task26 §17.3 — phrase-level ledger skeleton tests (offline, no DB)."""

from __future__ import annotations

from app.query.binding.ledger_v2 import (
    RequirementRole,
    build_ledger_skeleton,
)


def _roles(ledger):
    return [r.role for r in ledger.requirements]


def _by_role(ledger, role):
    return [r for r in ledger.requirements if r.role is role]


def test_multiword_phrase_is_one_target_not_per_word_items():
    ledger = build_ledger_skeleton("how many external walls are there?")
    targets = _by_role(ledger, RequirementRole.TARGET)
    assert len(targets) == 1
    assert targets[0].source_text == "external walls"
    # No per-word CONDITION explosion.
    assert not _by_role(ledger, RequirementRole.FILTER)


def test_this_building_is_topic_context_not_a_target():
    ledger = build_ledger_skeleton("what is the construction cost of this building?")
    topic = _by_role(ledger, RequirementRole.TOPIC_CONTEXT)
    assert any("building" in t.source_text.lower() for t in topic)
    # "construction cost" is a requested output metric, not a subject.
    assert any(
        r.role is RequirementRole.OUTPUT and "cost" in r.source_text.lower()
        for r in ledger.requirements
    )


def test_floor_reference_is_a_scope():
    ledger = build_ledger_skeleton("how many spaces are on the second floor?")
    scope = _by_role(ledger, RequirementRole.SCOPE)
    assert scope and scope[0].span_kind == "floor_reference"


def test_how_many_floors_has_no_floor_scope():
    ledger = build_ledger_skeleton("how many floors does this building have?")
    assert not any(r.span_kind == "floor_reference" for r in ledger.requirements)


def test_compound_question_splits_into_peer_parts():
    ledger = build_ledger_skeleton(
        "how many doors, how many windows and which floor has the most doors?"
    )
    parts = ledger.part_hints()
    assert len(parts) == 3


def test_grouped_extremum_creates_group_target_and_order():
    ledger = build_ledger_skeleton("which floor has the most doors?")
    roles = _roles(ledger)
    assert RequirementRole.GROUP in roles
    assert RequirementRole.TARGET in roles
    assert RequirementRole.ORDER in roles
    order = _by_role(ledger, RequirementRole.ORDER)[0]
    assert order.limit_value == 1


def test_sample_operation_creates_a_limit_one():
    ledger = build_ledger_skeleton("show me one example of a door")
    limit = _by_role(ledger, RequirementRole.LIMIT)
    assert limit and limit[0].limit_value == 1
    target = _by_role(ledger, RequirementRole.TARGET)
    assert any("door" in t.source_text.lower() for t in target)


def test_materials_of_the_doors_is_output_plus_target():
    ledger = build_ledger_skeleton("what are the materials of the doors?")
    assert any(
        r.role is RequirementRole.OUTPUT and "material" in r.source_text.lower()
        for r in ledger.requirements
    )
    assert any(
        r.role is RequirementRole.TARGET and "door" in r.source_text.lower()
        for r in ledger.requirements
    )


def test_traversal_language_creates_a_traversal_requirement():
    ledger = build_ledger_skeleton("which spaces are connected to stairs?")
    assert _by_role(ledger, RequirementRole.TRAVERSAL)


def test_inherited_scope_is_a_ledger_item():
    ledger = build_ledger_skeleton(
        "how many of those are external?", previous_scope=object()
    )
    scope = [r for r in ledger.requirements if r.source == "inherited_scope"]
    assert scope and scope[0].role is RequirementRole.SCOPE


def test_or_qualifiers_share_a_bool_group():
    ledger = build_ledger_skeleton("walls that are external or load bearing")
    grouped = [r for r in ledger.requirements if r.bool_group]
    assert len(grouped) >= 2
    assert len({r.bool_group for r in grouped}) == 1


def test_raw_text_is_preserved_for_non_ascii():
    ledger = build_ledger_skeleton("hur många bärande väggar finns det?")
    assert any("bärande" in r.source_text for r in ledger.requirements)
