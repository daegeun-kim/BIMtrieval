// Pure derivations for the query-explanation card (tasks/task26.md §4,
// tasks/task29.md §2, §6).
//
// Everything here is descriptive: it restates fields the backend already
// computed for the accepted answer. Nothing in this file introduces a new
// interpretation or factual claim, and nothing derives a count that the
// payload did not supply. In particular the presentation choice, the graph
// grouping and the graph eligibility are read from the payload — never
// recalculated here (task29 §6).
import type {
  AnswerExplanation,
  ExplanationGraphNode,
  ExplanationGroup,
} from "../api/types";

/**
 * A graph node read as a subgroup, so one selection mechanism serves both.
 *
 * `exact_count` is the node's own distinct-entity count and `shown_count` the
 * bounded GlobalIds actually applied, so a capped node selection discloses the
 * gap exactly as a capped class group does (task29 §5.4).
 */
export function graphNodeAsGroup(node: ExplanationGraphNode): ExplanationGroup {
  const ids = node.global_ids ?? [];
  return {
    key: node.id,
    label: node.label,
    exact_count: node.entity_count ?? ids.length,
    shown_count: ids.length,
    truncated: Boolean(node.global_ids_truncated),
    global_ids: ids,
  };
}

/**
 * Every subgroup the current payload offers: authoritative class groups, plus
 * the selectable grouped graph nodes.
 *
 * Graph-node identity sets may overlap, so this list is explicitly not a
 * partition of the result and must never be summed (task29 §5.2).
 */
export function selectableSubgroups(
  explanation: AnswerExplanation | null,
): ExplanationGroup[] {
  if (!explanation) return [];
  const nodes = (explanation.graph?.nodes ?? [])
    .filter((n) => n.selectable)
    .map(graphNodeAsGroup);
  return [...(explanation.groups ?? []), ...nodes];
}

/** The subgroup currently applied to the viewer, or `null` for the full result. */
export function activeGroup(
  explanation: AnswerExplanation | null,
  key: string | null,
): ExplanationGroup | null {
  if (!explanation || key === null) return null;
  return selectableSubgroups(explanation).find((g) => g.key === key) ?? null;
}

/**
 * Whether the active selection is a graph node rather than a class group.
 *
 * Class groups partition the highlighted set; graph nodes do not. The panel says
 * so when a node is selected, so nothing implies the remaining nodes form a
 * disjoint remainder (task29 §5.4).
 */
export function isGraphNodeSelection(
  explanation: AnswerExplanation | null,
  key: string | null,
): boolean {
  if (!explanation || key === null) return false;
  return (explanation.graph?.nodes ?? []).some((n) => n.id === key);
}

/**
 * A group is offered as clickable only when the backend supplied authoritative
 * identities for it. Without them the row is still displayed — it just cannot
 * pretend to select a set nobody hydrated (task26 §1.1, §5).
 */
export function isSelectable(group: ExplanationGroup): boolean {
  return (group.global_ids ?? []).length > 0;
}

const OPERATION_LABELS: Record<string, string> = {
  count: "Count",
  existence: "Existence check",
  list: "List",
  sample_detail: "Sample detail",
  group_distribution: "Group distribution",
  aggregate: "Aggregate",
  extremum: "Extremum",
  description: "Description",
  comparison: "Comparison",
  relationship: "Relationship",
};

const STATUS_LABELS: Record<string, string> = {
  exact: "exact",
  zero: "none found",
  unavailable: "not available in this model",
  partial: "partial",
  ambiguous: "ambiguous",
};

const BASIS_LABELS: Record<string, string> = {
  exact_sql: "exact structured query",
  hybrid_evidence: "structured query with semantic evidence",
  graph_traversal: "relationship traversal",
  insufficient_evidence: "insufficient evidence",
  general_knowledge: "general knowledge",
};

export function operationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation.replace(/_/g, " ");
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function basisLabel(basis: string): string {
  return BASIS_LABELS[basis] ?? basis.replace(/_/g, " ");
}

export function formatCount(n: number): string {
  return n.toLocaleString();
}

/** "IfcDoor" while a subgroup is applied, "All results" otherwise. */
export function showingLabel(group: ExplanationGroup | null): string {
  return group ? group.label : "All results";
}

/**
 * "5 of 9 query-result objects" — how many objects the viewer is emphasizing
 * right now, against the size of the full query result.
 *
 * The denominator is the TRUE result count, never the capped identity list, so
 * a subgroup can never read as a larger share of the answer than it is.
 */
export function highlightedLine(
  explanation: AnswerExplanation,
  group: ExplanationGroup | null,
): string {
  const total = explanation.true_result_count ?? 0;
  const shown = group
    ? (group.exact_count ?? group.shown_count ?? 0)
    : total;
  const noun = total === 1 ? "query-result object" : "query-result objects";
  if (!group) return `${formatCount(total)} ${noun}`;
  return `${formatCount(shown)} of ${formatCount(total)} ${noun}`;
}

/** "Full result: 9 external doors on floor 3" — always present, so a selected
 * subgroup can never be mistaken for the whole answer. */
export function fullResultLine(explanation: AnswerExplanation): string {
  const total = explanation.true_result_count ?? 0;
  return `${formatCount(total)} · ${explanation.request_label}`;
}

/**
 * The shown-versus-total disclosure, or `null` when nothing was capped.
 *
 * Two distinct truncations can apply: the viewer identity cap on the whole
 * result, and the cap as it falls on the selected group. Both are stated in the
 * same shape so no displayed number can imply the shown objects are exhaustive.
 */
export function truncationLine(
  explanation: AnswerExplanation,
  group: ExplanationGroup | null,
): string | null {
  if (group) {
    if (!group.truncated) return null;
    return `Highlighting ${formatCount(group.shown_count ?? 0)} of ${formatCount(
      group.exact_count ?? 0,
    )} objects in this group; the group's total is unaffected.`;
  }
  if (!explanation.identities_truncated) return null;
  return `Highlighting ${formatCount(
    explanation.shown_identity_count ?? 0,
  )} of ${formatCount(explanation.true_result_count ?? 0)} matching objects; the reported total is unaffected.`;
}

/** The aggregate's coverage caveat, when the value does not cover every match. */
export function coverageLine(explanation: AnswerExplanation): string | null {
  const agg = explanation.aggregate;
  if (!agg || agg.complete) return null;
  return `Based on ${formatCount(agg.coverage_count ?? 0)} of ${formatCount(
    agg.matched_count ?? 0,
  )} matching objects that record this value.`;
}

/** What a bar's length represents: the existing value, else the bucket count. */
export function barMagnitude(bucket: { count?: number; value?: number | null }): number {
  return bucket.value ?? bucket.count ?? 0;
}

/** Largest bar magnitude, for proportional widths. Never below 1. */
export function maxBucketCount(explanation: AnswerExplanation): number {
  const counts = (explanation.distribution ?? []).map(barMagnitude);
  return Math.max(1, ...counts);
}

/** Largest group size, for proportional bar widths. Never below 1. */
export function maxGroupCount(explanation: AnswerExplanation): number {
  const counts = (explanation.groups ?? []).map((g) => g.exact_count ?? g.shown_count ?? 0);
  return Math.max(1, ...counts);
}

/** A bar's exact value with its unit, or its exact count when it has no value. */
export function barValueLabel(
  bucket: { count?: number; value?: number | null },
  unit: string | null | undefined,
): string {
  if (bucket.value === null || bucket.value === undefined) {
    return formatCount(bucket.count ?? 0);
  }
  return unit ? `${bucket.value.toLocaleString()} ${unit}` : bucket.value.toLocaleString();
}
