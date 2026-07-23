"""Typed relational compiler over the access contract (task26 §10).

Compiles one validated `AnswerPartV2` into a `CompiledPart`: SQLAlchemy
expressions for the target family, filters (including REAL `is_present` /
`is_missing` predicates), effective spatial membership scope, floor/field
grouping, aggregates, order/limit, sample selection, projections, and
traversal specs — plus a serializable diagnostic form and a coverage proof.

The registry `COMPILER_ADAPTERS` maps each symbolic accessor ID from the
access contract to its adapter declaration. Bidirectional completeness (§3.3)
is tested against the contract: every declared accessor has an adapter here,
and no adapter accepts an operator or use it did not declare.

No query-specific SQL strings; every physical path comes from the manifest's
backend-only `physical` addressing, compiled through allowlisted expression
builders with bound parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import EntitySpatialMembership, IfcEntity
from app.llm.schemas_v2 import (
    AnswerPartV2,
    FilterNode,
    LogicalOperator,
    ResultKind,
    ScopeKindV2,
)
from app.query.semantic.manifest_v002.schema import (
    Capability,
    FloorBand,
    ManifestV002,
    Traversal,
)
from app.query.semantic.roles import family_closure
from app.query.sql.compiler import path_array_param

__all__ = [
    "COMPILER_ADAPTERS",
    "AdapterSpec",
    "CompileFailure",
    "CompiledPart",
    "CoverageProof",
    "TraversalSpec",
    "compile_part",
]

_ET = IfcEntity.__table__
_ESM = EntitySpatialMembership.__table__


class CompileFailure(Exception):
    """One mechanical compile failure, attributable to a logical node."""

    def __init__(self, node_id: str, code: str, detail: str) -> None:
        self.node_id = node_id
        self.code = code
        self.detail = detail
        super().__init__(f"{code} at {node_id}: {detail}")


@dataclass(frozen=True)
class AdapterSpec:
    """Declares what one accessor's adapter supports (contract mirror)."""

    accessor: str
    uses: frozenset[str]
    operators: frozenset[str]
    result_shapes: frozenset[str]


_TEXT_OPS = frozenset(
    {"equals", "not_equals", "contains", "starts_with", "one_of", "is_present", "is_missing"}
)
_NUM_OPS = frozenset(
    {
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "between",
        "one_of",
        "is_present",
        "is_missing",
    }
)

COMPILER_ADAPTERS: dict[str, AdapterSpec] = {
    "entity.class": AdapterSpec(
        "entity.class",
        frozenset({"target", "topic_context"}),
        frozenset(),
        frozenset({"entity_set", "scalar", "sample", "distribution"}),
    ),
    "json.attribute": AdapterSpec(
        "json.attribute",
        frozenset({"filter", "group", "report", "order", "aggregate"}),
        _TEXT_OPS | _NUM_OPS,
        frozenset({"entity_set", "scalar", "distribution"}),
    ),
    "json.property_value": AdapterSpec(
        "json.property_value",
        frozenset({"filter", "group", "report", "order", "aggregate"}),
        _TEXT_OPS | _NUM_OPS,
        frozenset({"entity_set", "scalar", "distribution"}),
    ),
    "json.quantity_value": AdapterSpec(
        "json.quantity_value",
        frozenset({"filter", "group", "report", "order", "aggregate"}),
        _NUM_OPS,
        frozenset({"entity_set", "scalar", "distribution"}),
    ),
    "json.material_name": AdapterSpec(
        "json.material_name",
        frozenset({"filter", "group", "report"}),
        _TEXT_OPS,
        frozenset({"entity_set", "distribution"}),
    ),
    "json.classification_field": AdapterSpec(
        "json.classification_field",
        frozenset({"filter", "group", "report"}),
        _TEXT_OPS,
        frozenset({"entity_set", "distribution"}),
    ),
    "spatial.effective_membership": AdapterSpec(
        "spatial.effective_membership",
        frozenset({"scope", "group"}),
        frozenset(),
        frozenset({"entity_set", "distribution"}),
    ),
    "relationship.member_edge": AdapterSpec(
        "relationship.member_edge",
        frozenset({"traverse"}),
        frozenset(),
        frozenset({"graph_endpoints", "entity_set"}),
    ),
    "derived.physical_floor": AdapterSpec(
        "derived.physical_floor",
        frozenset({"scope", "group", "target"}),
        frozenset(),
        frozenset({"entity_set", "scalar", "distribution"}),
    ),
    "derived.building_profile": AdapterSpec(
        "derived.building_profile",
        frozenset({"target"}),
        frozenset(),
        frozenset({"profile"}),
    ),
    "derived.thematic_profile": AdapterSpec(
        "derived.thematic_profile",
        frozenset({"target"}),
        frozenset(),
        frozenset({"profile", "qualitative_evidence"}),
    ),
}


# ---------------------------------------------------------------------------
# Compiled shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageProof:
    """Whether the compiled predicate can justify an exact result (§9.3)."""

    complete: bool
    reasons: tuple[str, ...] = ()
    #: (capability_id, subject, known, eligible) rows the proof rests on.
    facts: tuple[tuple[str, str, int, int], ...] = ()


@dataclass(frozen=True)
class TraversalSpec:
    node_id: str
    hops: tuple[Traversal, ...]
    endpoint_classes: tuple[str, ...] = ()


@dataclass
class GroupSpec:
    node_id: str
    kind: str  # "floor" | "field"
    label_expr: Any = None
    bands: tuple[FloorBand, ...] = ()
    capability: Capability | None = None


@dataclass
class ProjectionSpec:
    capability: Capability
    value_expr: Any


@dataclass
class CompiledPart:
    """The one executable description of an answer part's result sets (§10.7)."""

    part_id: str
    result_kind: ResultKind
    source_model_id: int
    target_semantic_id: str
    target_classes: tuple[str, ...] = ()
    filter_expr: Any = None
    scope_expr: Any = None
    scope_entity_ids: tuple[int, ...] | None = None
    group: GroupSpec | None = None
    aggregate_function: str | None = None
    aggregate_expr: Any = None
    aggregate_capability: Capability | None = None
    order_direction: str | None = None
    limit: int | None = None
    projections: list[ProjectionSpec] = field(default_factory=list)
    traversals: list[TraversalSpec] = field(default_factory=list)
    evidence_theme: str | None = None
    viewer_set: str = "none"
    context_reason: str | None = None
    interpretation_notes: list[str] = field(default_factory=list)
    coverage: CoverageProof = CoverageProof(complete=True)
    #: Serializable diagnostics: node ids, accessors, symbolic tables, caps.
    diagnostics: dict[str, Any] = field(default_factory=dict)

    # -- derived SQL pieces --------------------------------------------------

    def base_where(self) -> Any:
        """The ONE where-clause every consumer of this part shares (§10.6)."""
        where = _ET.c.source_model_id == self.source_model_id
        if self.target_classes:
            where = sa.and_(where, _ET.c.ifc_class.in_(list(self.target_classes)))
        if self.scope_expr is not None:
            where = sa.and_(where, self.scope_expr)
        if self.scope_entity_ids is not None:
            where = sa.and_(where, _ET.c.id.in_(list(self.scope_entity_ids)))
        if self.filter_expr is not None:
            where = sa.and_(where, self.filter_expr)
        return where

    def scanned_where(self) -> Any:
        """The scanned/eligible set: target + scope, WITHOUT value filters."""
        where = _ET.c.source_model_id == self.source_model_id
        if self.target_classes:
            where = sa.and_(where, _ET.c.ifc_class.in_(list(self.target_classes)))
        if self.scope_expr is not None:
            where = sa.and_(where, self.scope_expr)
        if self.scope_entity_ids is not None:
            where = sa.and_(where, _ET.c.id.in_(list(self.scope_entity_ids)))
        return where

    def id_select(self) -> Any:
        """A database-side subquery of matching entity ids — the same logical
        predicate seeds SQL, RAG, graph, and viewer work without materializing
        an ID list in Python (§10.6)."""
        return sa.select(_ET.c.id).where(self.base_where())


# ---------------------------------------------------------------------------
# Field expressions
# ---------------------------------------------------------------------------


def _json_text_expr(path: tuple[str, ...]) -> Any:
    return _ET.c.canonical_json.op("#>>")(path_array_param(path))


def field_value_expr(capability: Capability) -> Any:
    """The value expression for one field capability, from its physical block."""
    physical = capability.physical or {}
    source = physical.get("source")
    if source in ("attribute", "type_fact"):
        path = tuple(physical.get("path") or ())
        if not path:
            raise CompileFailure(
                capability.semantic_id, "COMPILER_ACCESS_GAP", "attribute has no path"
            )
        return _json_text_expr(path)
    if source in ("property_sets", "quantity_sets"):
        set_name = physical.get("set")
        field_name = physical.get("field")
        if not set_name or not field_name:
            raise CompileFailure(
                capability.semantic_id, "COMPILER_ACCESS_GAP", "field has no set/field address"
            )
        return _json_text_expr((source, set_name, field_name, "value"))
    raise CompileFailure(
        capability.semantic_id,
        "COMPILER_ACCESS_GAP",
        f"no scalar value expression for physical source {source!r}",
    )


def _numeric_value_expr(capability: Capability) -> Any:
    return sa.cast(field_value_expr(capability), sa.Numeric)


def _array_element_exists(
    source_model_id: int,
    array_key: str,
    element_field: str,
    predicate: Callable[[Any], Any] | None,
) -> Any:
    """EXISTS over a canonical JSON array (materials / classifications)."""
    element = sa.func.jsonb_array_elements(_ET.c.canonical_json[array_key]).table_valued(
        "value", joins_implicitly=True
    )
    value_expr = element.c.value.op("->>")(element_field)
    condition = sa.true() if predicate is None else predicate(value_expr)
    return sa.exists(sa.select(sa.literal(1)).select_from(element).where(condition))


# ---------------------------------------------------------------------------
# Filter compilation
# ---------------------------------------------------------------------------


def _string_predicate(value_expr: Any, node: FilterNode) -> Any:
    op = node.operator
    values = node.value_list or ([node.value_text] if node.value_text is not None else [])
    if op in (LogicalOperator.IS_PRESENT, LogicalOperator.IS_MISSING):
        present = sa.and_(value_expr.isnot(None), value_expr != "")
        return present if op is LogicalOperator.IS_PRESENT else sa.not_(present)
    if not values:
        raise CompileFailure(node.node_id, "COMPILER_ACCESS_GAP", "filter carries no value")
    if op is LogicalOperator.EQUALS:
        if len(values) == 1:
            return sa.func.lower(value_expr) == values[0].casefold()
        return sa.func.lower(value_expr).in_([v.casefold() for v in values])
    if op is LogicalOperator.NOT_EQUALS:
        return sa.or_(
            value_expr.is_(None),
            sa.func.lower(value_expr).notin_([v.casefold() for v in values]),
        )
    if op is LogicalOperator.ONE_OF:
        return sa.func.lower(value_expr).in_([v.casefold() for v in values])
    if op is LogicalOperator.CONTAINS:
        return sa.func.lower(value_expr).contains(values[0].casefold(), autoescape=True)
    if op is LogicalOperator.STARTS_WITH:
        return sa.func.lower(value_expr).startswith(values[0].casefold(), autoescape=True)
    raise CompileFailure(
        node.node_id, "COMPILER_ACCESS_GAP", f"operator {op.value} unsupported for text"
    )


def _numeric_predicate(value_expr: Any, node: FilterNode) -> Any:
    op = node.operator
    if op in (LogicalOperator.IS_PRESENT, LogicalOperator.IS_MISSING):
        present = value_expr.isnot(None)
        return present if op is LogicalOperator.IS_PRESENT else sa.not_(present)
    raw = node.value_list or ([node.value_text] if node.value_text is not None else [])
    try:
        numbers = [float(str(v).replace(",", ".")) for v in raw]
    except ValueError as exc:
        raise CompileFailure(
            node.node_id, "COMPILER_ACCESS_GAP", f"non-numeric value for numeric field: {exc}"
        ) from None
    if not numbers:
        raise CompileFailure(node.node_id, "COMPILER_ACCESS_GAP", "numeric filter carries no value")
    mapping = {
        LogicalOperator.EQUALS: lambda: value_expr == numbers[0],
        LogicalOperator.NOT_EQUALS: lambda: value_expr != numbers[0],
        LogicalOperator.GREATER_THAN: lambda: value_expr > numbers[0],
        LogicalOperator.GREATER_OR_EQUAL: lambda: value_expr >= numbers[0],
        LogicalOperator.LESS_THAN: lambda: value_expr < numbers[0],
        LogicalOperator.LESS_OR_EQUAL: lambda: value_expr <= numbers[0],
        LogicalOperator.ONE_OF: lambda: value_expr.in_(numbers),
    }
    if op is LogicalOperator.BETWEEN:
        if len(numbers) != 2:
            raise CompileFailure(node.node_id, "COMPILER_ACCESS_GAP", "between needs two bounds")
        return value_expr.between(numbers[0], numbers[1])
    builder = mapping.get(op)
    if builder is None:
        raise CompileFailure(
            node.node_id, "COMPILER_ACCESS_GAP", f"operator {op.value} unsupported for number"
        )
    return builder()


def compile_filter(
    node: FilterNode, capability: Capability, source_model_id: int
) -> Any:
    """One filter node -> a real predicate. `is_present`/`is_missing` never
    return None and disappear (§10.3)."""
    accessor = capability.accessor
    physical = capability.physical or {}

    if accessor == "json.material_name":
        if node.operator is LogicalOperator.IS_PRESENT:
            expr = _array_element_exists(source_model_id, "materials", "name", None)
        elif node.operator is LogicalOperator.IS_MISSING:
            expr = sa.not_(_array_element_exists(source_model_id, "materials", "name", None))
        else:
            expr = _array_element_exists(
                source_model_id,
                "materials",
                "name",
                lambda value: _string_predicate(value, node),
            )
        return sa.not_(expr) if node.negated else expr

    if accessor == "json.classification_field":
        element_field = physical.get("field", "code")
        if node.operator is LogicalOperator.IS_PRESENT:
            expr = _array_element_exists(source_model_id, "classifications", element_field, None)
        elif node.operator is LogicalOperator.IS_MISSING:
            expr = sa.not_(
                _array_element_exists(source_model_id, "classifications", element_field, None)
            )
        else:
            expr = _array_element_exists(
                source_model_id,
                "classifications",
                element_field,
                lambda value: _string_predicate(value, node),
            )
        return sa.not_(expr) if node.negated else expr

    if capability.data_type == "number":
        expr = _numeric_predicate(_numeric_value_expr(capability), node)
    else:
        expr = _string_predicate(field_value_expr(capability), node)
    return sa.not_(expr) if node.negated else expr


# ---------------------------------------------------------------------------
# Spatial scope (§10.2)
# ---------------------------------------------------------------------------


def spatial_membership_expr(source_model_id: int, storey_global_ids: tuple[str, ...]) -> Any:
    """Effective floor membership: the union of the denormalized scalar and the
    normalized relationship-backed membership, one shape for every class."""
    storeys = list(storey_global_ids)
    scalar = _json_text_expr(("storey", "global_id")).in_(storeys)
    membership = sa.exists(
        sa.select(sa.literal(1))
        .select_from(_ESM)
        .where(
            _ESM.c.source_model_id == source_model_id,
            _ESM.c.entity_id == _ET.c.id,
            _ESM.c.storey_global_id.in_(storeys),
        )
    )
    return sa.or_(scalar, membership)


def floor_group_spec(node_id: str, manifest: ManifestV002) -> GroupSpec:
    """Group-by-floor: every storey maps onto its derived band label (§10.5)."""
    bands = tuple(manifest.floors.bands)
    if not bands:
        raise CompileFailure(node_id, "COMPILER_ACCESS_GAP", "model derives no floor bands")
    storey_expr = sa.func.coalesce(
        _json_text_expr(("storey", "global_id")),
        sa.select(_ESM.c.storey_global_id)
        .where(
            _ESM.c.source_model_id == manifest.source_model_id,
            _ESM.c.entity_id == _ET.c.id,
            _ESM.c.is_primary.is_(True),
        )
        .limit(1)
        .correlate(_ET)
        .scalar_subquery(),
    )
    whens = []
    for band in bands:
        whens.append((storey_expr.in_(list(band.storey_global_ids)), band.semantic_id))
    label_expr = sa.case(*whens, else_=sa.literal(None))
    return GroupSpec(node_id=node_id, kind="floor", label_expr=label_expr, bands=bands)


# ---------------------------------------------------------------------------
# Part compilation
# ---------------------------------------------------------------------------


def compile_part(
    session: Session,
    part: AnswerPartV2,
    manifest: ManifestV002,
    *,
    selection_entity_ids: list[int] | None = None,
    previous_scope_entity_ids: list[int] | None = None,
) -> CompiledPart:
    """Compile one validated answer part. Raises CompileFailure on the first
    mechanical gap (dry compilation runs this same function, §9.1 layer 8)."""
    compiled = CompiledPart(
        part_id=part.part_id,
        result_kind=part.result_kind,
        source_model_id=manifest.source_model_id,
        target_semantic_id=part.target.semantic_id,
        viewer_set=part.viewer_set.value,
        context_reason=part.context_reason,
        evidence_theme=part.evidence_theme,
        limit=part.limit,
    )
    coverage_reasons: list[str] = []
    coverage_facts: list[tuple[str, str, int, int]] = []
    accessors_used: dict[str, str] = {}

    # -- target -------------------------------------------------------------
    target = manifest.get(part.target.semantic_id)
    if isinstance(target, Capability) and target.kind == "class":
        classes: set[str] = set()
        for semantic_id in (part.target.semantic_id, *part.target.union_semantic_ids):
            capability = manifest.capabilities.get(semantic_id)
            if capability is None or capability.kind != "class" or not capability.ifc_class:
                raise CompileFailure(
                    part.target.node_id, "COMPILER_ACCESS_GAP", f"{semantic_id} is not a class"
                )
            family = family_closure(
                capability.ifc_class,
                manifest.present_classes(),
                manifest.ifc_schema or "IFC2X3",
            )
            classes.update(family or (capability.ifc_class,))
        compiled.target_classes = tuple(sorted(classes))
        accessors_used[part.target.node_id] = "entity.class"
        family_only = compiled.target_classes != (target.ifc_class,)
        if family_only:
            compiled.interpretation_notes.append(
                f"counted the {target.label} family: {', '.join(compiled.target_classes)}"
            )
    elif part.target.semantic_id in manifest.profiles:
        accessors_used[part.target.node_id] = manifest.profiles[part.target.semantic_id].accessor
        if part.result_kind not in (ResultKind.PROFILE, ResultKind.QUALITATIVE_EVIDENCE):
            raise CompileFailure(
                part.target.node_id,
                "COMPILER_ACCESS_GAP",
                "a profile target requires a profile result kind",
            )
    elif manifest.floors.band(part.target.semantic_id) is not None:
        accessors_used[part.target.node_id] = "derived.physical_floor"
    else:
        raise CompileFailure(
            part.target.node_id,
            "COMPILER_ACCESS_GAP",
            f"{part.target.semantic_id} has no target adapter",
        )

    # -- scope --------------------------------------------------------------
    if part.scope is not None:
        kind = part.scope.kind
        if kind is ScopeKindV2.SELECTED_OBJECTS:
            compiled.scope_entity_ids = tuple(selection_entity_ids or ())
            compiled.interpretation_notes.append(
                f"restricted to the {len(compiled.scope_entity_ids)} selected object(s)"
            )
        elif kind is ScopeKindV2.PREVIOUS_RESULT:
            compiled.scope_entity_ids = tuple(previous_scope_entity_ids or ())
            compiled.interpretation_notes.append("restricted to the previous result")
        elif kind is ScopeKindV2.FLOOR_BAND:
            band = manifest.floors.band(part.scope.semantic_id or "")
            if band is None:
                raise CompileFailure(
                    part.scope.node_id,
                    "COMPILER_ACCESS_GAP",
                    f"{part.scope.semantic_id!r} is not a derived floor band",
                )
            compiled.scope_expr = spatial_membership_expr(
                manifest.source_model_id, band.storey_global_ids
            )
            accessors_used[part.scope.node_id] = "spatial.effective_membership"
            compiled.interpretation_notes.append(f"floor interpreted as {band.describe()}")
            coverage_facts.extend(_spatial_coverage(manifest, compiled.target_classes))
            incomplete = [
                f"{cls}: {summary.effective_count}/{summary.total_count} resolve to a storey"
                for cls, summary in manifest.spatial_by_class.items()
                if cls in compiled.target_classes
                and summary.effective_count < summary.total_count
            ]
            if incomplete:
                coverage_reasons.append(
                    "spatial membership is incomplete for: " + "; ".join(incomplete[:4])
                )
        elif kind is ScopeKindV2.STOREY:
            storey = manifest.storeys.get(part.scope.semantic_id or "")
            if storey is None:
                raise CompileFailure(
                    part.scope.node_id,
                    "COMPILER_ACCESS_GAP",
                    f"{part.scope.semantic_id!r} is not a storey",
                )
            compiled.scope_expr = spatial_membership_expr(
                manifest.source_model_id, (storey.global_id,)
            )
            accessors_used[part.scope.node_id] = "spatial.effective_membership"
            compiled.interpretation_notes.append(
                f"restricted to storey {storey.name or storey.global_id!r} (explicit raw storey)"
            )

    # -- filters ------------------------------------------------------------
    grouped: dict[str, list[Any]] = {}
    ungrouped: list[Any] = []
    for node in part.filters:
        capability = manifest.capabilities.get(node.semantic_id)
        if capability is None or capability.kind != "field":
            raise CompileFailure(
                node.node_id, "COMPILER_ACCESS_GAP", f"{node.semantic_id} is not a field"
            )
        expr = compile_filter(node, capability, manifest.source_model_id)
        accessors_used[node.node_id] = capability.accessor
        (grouped.setdefault(node.bool_group, []) if node.bool_group else ungrouped).append(expr)
        for entry in capability.applicability:
            subject = entry.subject[4:] if entry.subject.startswith("cls:") else entry.subject
            if not compiled.target_classes or subject in compiled.target_classes:
                coverage_facts.append(
                    (capability.semantic_id, entry.subject, entry.known_count, entry.eligible_count)
                )
                if not entry.can_prove_absence:
                    coverage_reasons.append(
                        f"{capability.semantic_id} cannot prove absence for {entry.subject}"
                    )
        # A value filter over a partially covered field cannot prove an exact
        # zero for the WHOLE eligible set; presence/missing can (§9.3).
        if node.operator not in (LogicalOperator.IS_PRESENT, LogicalOperator.IS_MISSING):
            partial = [
                a
                for a in capability.applicability
                if (a.subject[4:] if a.subject.startswith("cls:") else a.subject)
                in compiled.target_classes
                and not a.complete
            ]
            if partial:
                coverage_reasons.append(
                    f"{capability.semantic_id} is partially covered on the target classes; a "
                    "zero match cannot prove real-world absence"
                )

    nodes: list[Any] = list(ungrouped)
    for members in grouped.values():
        nodes.append(members[0] if len(members) == 1 else sa.or_(*members))
    if nodes:
        compiled.filter_expr = (
            sa.and_(*nodes) if part.filter_bool_op == "and" else sa.or_(*nodes)
        )

    # -- group / aggregate / order / sample ---------------------------------
    if part.group is not None:
        if part.group.semantic_id == "spatial:floor_membership":
            compiled.group = floor_group_spec(part.group.node_id, manifest)
            accessors_used[part.group.node_id] = "spatial.effective_membership"
        else:
            capability = manifest.capabilities.get(part.group.semantic_id)
            if capability is None or capability.kind != "field":
                raise CompileFailure(
                    part.group.node_id,
                    "COMPILER_ACCESS_GAP",
                    f"{part.group.semantic_id} is not groupable",
                )
            compiled.group = GroupSpec(
                node_id=part.group.node_id,
                kind="field",
                label_expr=field_value_expr(capability),
                capability=capability,
            )
            accessors_used[part.group.node_id] = capability.accessor

    if part.aggregate is not None:
        compiled.aggregate_function = part.aggregate.function.value
        if part.aggregate.semantic_id:
            capability = manifest.capabilities.get(part.aggregate.semantic_id)
            if capability is None or capability.data_type != "number":
                raise CompileFailure(
                    part.aggregate.node_id,
                    "COMPILER_ACCESS_GAP",
                    f"{part.aggregate.semantic_id} is not a numeric field",
                )
            unit_states = {a.unit_state for a in capability.applicability}
            if part.aggregate.function.value != "count" and not (
                unit_states <= {"known", "unitless"}
            ):
                raise CompileFailure(
                    part.aggregate.node_id,
                    "COVERAGE_PROOF_GAP",
                    f"{capability.semantic_id} has an unproven unit contract and cannot be "
                    "aggregated",
                )
            compiled.aggregate_expr = _numeric_value_expr(capability)
            compiled.aggregate_capability = capability
            accessors_used[part.aggregate.node_id] = capability.accessor

    if part.order is not None:
        compiled.order_direction = part.order.direction

    # -- projections ---------------------------------------------------------
    for semantic_id in part.projections:
        capability = manifest.capabilities.get(semantic_id)
        if capability is None or capability.kind != "field":
            raise CompileFailure(
                part.part_id, "COMPILER_ACCESS_GAP", f"projection {semantic_id} is not a field"
            )
        if capability.accessor == "json.material_name":
            compiled.projections.append(ProjectionSpec(capability=capability, value_expr=None))
        else:
            compiled.projections.append(
                ProjectionSpec(capability=capability, value_expr=field_value_expr(capability))
            )
        accessors_used[f"proj:{semantic_id}"] = capability.accessor

    # -- traversals ----------------------------------------------------------
    for node in part.traversals:
        hops: list[Traversal] = []
        for path_id in node.path_semantic_ids:
            traversal = manifest.traversals.get(path_id)
            if traversal is None:
                raise CompileFailure(
                    node.node_id, "COMPILER_ACCESS_GAP", f"{path_id} is not a traversal contract"
                )
            hops.append(traversal)
        for previous, following in zip(hops, hops[1:]):
            if not set(previous.to_classes) & set(following.from_classes):
                raise CompileFailure(
                    node.node_id,
                    "COMPILER_ACCESS_GAP",
                    f"{previous.semantic_id} endpoints do not connect to "
                    f"{following.semantic_id}",
                )
        endpoint_classes: tuple[str, ...] = ()
        if node.endpoint_semantic_id:
            endpoint = manifest.capabilities.get(node.endpoint_semantic_id)
            if endpoint is None or endpoint.kind != "class" or not endpoint.ifc_class:
                raise CompileFailure(
                    node.node_id,
                    "COMPILER_ACCESS_GAP",
                    f"{node.endpoint_semantic_id} is not an endpoint class",
                )
            endpoint_classes = tuple(
                family_closure(
                    endpoint.ifc_class,
                    manifest.present_classes(),
                    manifest.ifc_schema or "IFC2X3",
                )
                or (endpoint.ifc_class,)
            )
        compiled.traversals.append(
            TraversalSpec(node_id=node.node_id, hops=tuple(hops), endpoint_classes=endpoint_classes)
        )
        accessors_used[node.node_id] = "relationship.member_edge"

    compiled.coverage = CoverageProof(
        complete=not coverage_reasons,
        reasons=tuple(coverage_reasons[:6]),
        facts=tuple(coverage_facts[:24]),
    )
    compiled.diagnostics = {
        "part_id": part.part_id,
        "result_kind": part.result_kind.value,
        "target_classes": list(compiled.target_classes),
        "accessors": accessors_used,
        "filter_count": len(part.filters),
        "has_scope": part.scope is not None,
        "group": part.group.semantic_id if part.group else None,
        "aggregate": compiled.aggregate_function,
        "limit": part.limit,
        "coverage_complete": compiled.coverage.complete,
        "coverage_reasons": list(compiled.coverage.reasons),
    }
    return compiled


def _spatial_coverage(
    manifest: ManifestV002, target_classes: tuple[str, ...]
) -> list[tuple[str, str, int, int]]:
    out = []
    for ifc_class in target_classes:
        summary = manifest.spatial_by_class.get(ifc_class)
        if summary is not None:
            out.append(
                (
                    "spatial:floor_membership",
                    f"cls:{ifc_class}",
                    summary.effective_count,
                    summary.total_count,
                )
            )
    return out
