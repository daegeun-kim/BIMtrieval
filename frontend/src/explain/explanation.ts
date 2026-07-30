// Pure derivations for the query-explanation card (tasks/task26.md §4).
//
// Everything here is descriptive: it restates fields the backend already
// computed for the accepted answer. Nothing in this file introduces a new
// interpretation or factual claim, and nothing derives a count that the
// payload did not supply.
import type { AnswerExplanation, ExplanationGroup } from "../api/types";

/** The subgroup currently applied to the viewer, or `null` for the full result. */
export function activeGroup(
  explanation: AnswerExplanation | null,
  key: string | null,
): ExplanationGroup | null {
  if (!explanation || key === null) return null;
  return (explanation.groups ?? []).find((g) => g.key === key) ?? null;
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

/** Largest bucket count, for proportional bar widths. Never below 1. */
export function maxBucketCount(explanation: AnswerExplanation): number {
  const counts = (explanation.distribution ?? []).map((b) => b.count ?? 0);
  return Math.max(1, ...counts);
}

/** Largest group size, for proportional bar widths. Never below 1. */
export function maxGroupCount(explanation: AnswerExplanation): number {
  const counts = (explanation.groups ?? []).map((g) => g.exact_count ?? g.shown_count ?? 0);
  return Math.max(1, ...counts);
}
