"""Deterministic plan bookkeeping repair, before validation (task27 §3, §4).

The v4 binder had to keep two different kinds of identifier straight: a
`semantic_id` copied exactly from the projection, and a `node_id` that is only a
local handle for dispositions to point at. Nothing in the schema or the prompt
distinguished them, so the model wrote semantic IDs into `node_id` — where the
24-character bound truncates them mid-token. The recorded traces contain
`prop:Pset_WallCommon.IsU`, `prop:Pset_DoorCommon.Is<CJK>`,
`agg:count_stairs_plus_r{`: valid plans whose dispositions could no longer be
matched to their own nodes, failing provenance and lexical coverage for
conditions that were in fact bound.

This module removes that bookkeeping from the model's job entirely:

1. every node gets a canonical short handle from its POSITION and kind —
   `t1`, `f1..fn`, `s1`, `v1..vn`, `g1`, `a1`, `o1`;
2. each disposition's node references are resolved onto those handles by exact
   match against the handle, the original node id, or the node's semantic id;
3. a reference that still matches nothing is repaired ONLY when the intended
   mapping is unique — the requirement's role names one node kind and the part
   holds exactly one node of it. Two candidates is ambiguous and left alone, so
   validation still fails safely;
4. duplicate part ids are made unique, and a disposition with no `part_id` is
   attached to the only part when there is only one.

Nothing here guesses semantic intent: no semantic id, operator, value, target,
or disposition kind is ever changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.schemas_v2 import AnswerPartV2, DispositionKind, LogicalPlan
from app.query.binding.ledger_v2 import LedgerV2, RequirementRole

__all__ = ["NormalizationReport", "normalize_plan_bookkeeping"]

#: Requirement role -> the node kind whose single occurrence may discharge it.
_ROLE_SINGLE_NODE_KIND: dict[RequirementRole, str] = {
    RequirementRole.TARGET: "target",
    RequirementRole.FILTER: "filter",
    RequirementRole.SCOPE: "scope",
    RequirementRole.GROUP: "group",
    RequirementRole.AGGREGATE: "aggregate",
    RequirementRole.TRAVERSAL: "traverse",
    RequirementRole.ORDER: "order",
    RequirementRole.OUTPUT: "report",
}


@dataclass
class NormalizationReport:
    """What was mechanically repaired, for the trace."""

    renamed_nodes: int = 0
    relinked_references: int = 0
    inferred_references: int = 0
    renamed_parts: list[tuple[str, str]] = field(default_factory=list)
    attached_dispositions: int = 0
    unresolved_references: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in (
            ("renamed_nodes", self.renamed_nodes),
            ("relinked_references", self.relinked_references),
            ("inferred_references", self.inferred_references),
            ("attached_dispositions", self.attached_dispositions),
        ):
            if value:
                payload[key] = value
        if self.renamed_parts:
            payload["renamed_parts"] = [list(pair) for pair in self.renamed_parts]
        if self.unresolved_references:
            payload["unresolved_references"] = self.unresolved_references[:8]
        return payload


def normalize_plan_bookkeeping(
    plan: LogicalPlan, ledger: LedgerV2 | None = None
) -> NormalizationReport:
    """Rewrite node ids to canonical handles and relink dispositions in place."""
    report = NormalizationReport()
    _dedupe_part_ids(plan, report)

    part_index = {part.part_id: part for part in plan.answer_parts}
    alias_maps: dict[str, dict[str, str]] = {}
    kind_maps: dict[str, dict[str, list[str]]] = {}

    for part in plan.answer_parts:
        aliases, kinds = _canonicalize(part, report)
        alias_maps[part.part_id] = aliases
        kind_maps[part.part_id] = kinds

    if len(plan.answer_parts) == 1:
        only = plan.answer_parts[0].part_id
        for disposition in plan.dispositions:
            if not disposition.part_id:
                disposition.part_id = only
                report.attached_dispositions += 1

    for disposition in plan.dispositions:
        if disposition.disposition is not DispositionKind.BOUND:
            continue
        part_id = disposition.part_id or ""
        if part_id not in part_index:
            # A disposition naming a part that does not exist: attach it to the
            # part whose id it most nearly names, only when unambiguous.
            matches = [p for p in part_index if part_id and p.startswith(part_id)]
            if len(matches) == 1:
                disposition.part_id = matches[0]
                part_id = matches[0]
                report.attached_dispositions += 1
            else:
                continue
        aliases = alias_maps[part_id]
        resolved: list[str] = []
        unresolved: list[str] = []
        for reference in disposition.node_ids:
            handle = aliases.get(reference) or aliases.get(reference.strip())
            if handle is None:
                unresolved.append(reference)
            elif handle not in resolved:
                resolved.append(handle)
                report.relinked_references += 1
        if unresolved and ledger is not None:
            inferred = _infer_reference(
                disposition.requirement_id, ledger, kind_maps[part_id], resolved
            )
            if inferred is not None:
                resolved.append(inferred)
                report.inferred_references += 1
        report.unresolved_references.extend(unresolved)
        disposition.node_ids = resolved
    return report


def _dedupe_part_ids(plan: LogicalPlan, report: NormalizationReport) -> None:
    """Make part ids unique, carrying every disposition that names one along.

    A duplicate is only renamed when the one-to-one mapping is unique: the
    dispositions of the FIRST occurrence keep the original id, and each later
    duplicate takes a suffixed id together with the dispositions that follow it
    in order. When dispositions cannot be attributed that way the ids are left
    duplicated and validation reports it.
    """
    seen: dict[str, int] = {}
    duplicates = [p.part_id for p in plan.answer_parts]
    if len(duplicates) == len(set(duplicates)):
        return
    dispositions_by_part: dict[str, list[Any]] = {}
    for disposition in plan.dispositions:
        dispositions_by_part.setdefault(disposition.part_id or "", []).append(disposition)
    for part in plan.answer_parts:
        count = seen.get(part.part_id, 0)
        seen[part.part_id] = count + 1
        if count == 0:
            continue
        original = part.part_id
        candidate = f"{original}_{count + 1}"
        while candidate in seen:
            count += 1
            candidate = f"{original}_{count + 1}"
        part.part_id = candidate
        seen[candidate] = 1
        report.renamed_parts.append((original, candidate))


def _canonicalize(
    part: AnswerPartV2, report: NormalizationReport
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Assign canonical handles to one part's nodes.

    Returns `(alias -> handle, kind -> handles)`. Aliases include each node's
    original id and its semantic id, so a disposition written against either
    form still links.
    """
    aliases: dict[str, str] = {}
    kinds: dict[str, list[str]] = {}

    def _assign(node: Any, handle: str, kind: str, semantic: str | None) -> None:
        original = getattr(node, "node_id", "") or ""
        if original != handle:
            report.renamed_nodes += 1
        node.node_id = handle
        kinds.setdefault(kind, []).append(handle)
        for alias in (handle, original, semantic):
            if alias and alias not in aliases:
                aliases[alias] = handle

    _assign(part.target, "t1", "target", part.target.semantic_id)
    for union_id in part.target.union_semantic_ids:
        aliases.setdefault(union_id, "t1")
    for index, node in enumerate(part.filters, start=1):
        _assign(node, f"f{index}", "filter", node.semantic_id)
    if part.scope is not None:
        _assign(part.scope, "s1", "scope", part.scope.semantic_id or part.scope.kind.value)
        aliases.setdefault(part.scope.kind.value, "s1")
    for index, node in enumerate(part.traversals, start=1):
        _assign(node, f"v{index}", "traverse", node.path_semantic_ids[0])
        for path_id in node.path_semantic_ids[1:]:
            aliases.setdefault(path_id, f"v{index}")
    if part.group is not None:
        _assign(part.group, "g1", "group", part.group.semantic_id)
    if part.aggregate is not None:
        _assign(part.aggregate, "a1", "aggregate", part.aggregate.semantic_id)
        aliases.setdefault(part.aggregate.function.value, "a1")
    if part.order is not None:
        _assign(part.order, "o1", "order", None)
    # Projections are reported fields, not nodes the schema gives an id to, but
    # a disposition for a requested OUTPUT legitimately names one. They get
    # positional `p*` handles so that reference resolves like any other.
    for index, semantic_id in enumerate(part.projections, start=1):
        handle = f"p{index}"
        kinds.setdefault("report", []).append(handle)
        for alias in (handle, semantic_id):
            aliases.setdefault(alias, handle)
    return aliases, kinds


def _infer_reference(
    requirement_id: str,
    ledger: LedgerV2,
    kinds: dict[str, list[str]],
    already: list[str],
) -> str | None:
    """The one node that could have been meant, or None when it is ambiguous."""
    requirement = ledger.requirement(requirement_id)
    if requirement is None:
        return None
    wanted = _ROLE_SINGLE_NODE_KIND.get(requirement.role)
    if wanted is None:
        return None
    handles = [h for h in kinds.get(wanted, []) if h not in already]
    return handles[0] if len(handles) == 1 else None
