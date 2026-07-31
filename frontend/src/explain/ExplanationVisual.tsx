import type { AnswerExplanation, ExplanationGroup } from "../api/types";
import RelationshipGraph from "./RelationshipGraph";
import {
  barMagnitude,
  barValueLabel,
  formatCount,
  isSelectable,
  maxBucketCount,
  maxGroupCount,
} from "./explanation";

// The visualization half of the explanation card (tasks/task29.md §3, §4, §5).
// Ordinary React/CSS/SVG — no charting or graph dependency is needed for a bar
// row, a table and a node-link diagram, and none is added.
//
// The presentation is READ from the payload, never inferred here: the backend is
// the single owner of that decision (task29 §2). Three families exist — a
// bounded scrollable table, a compact horizontal bar chart, and the grouped
// relationship diagram. There is no metric card, no aggregate card and no
// partial split: an answer those would have described gets no panel at all, so
// this component never renders for it.
//
// Everything shown comes from the bounded payload. A class group is clickable
// only when the backend supplied its identities; a distribution bucket never is,
// because grouped counts have no identity subset to select.

/** Horizontal bars over the authoritative class groups — the selectable ones. */
function GroupBars({
  explanation,
  activeKey,
  onSelect,
}: {
  explanation: AnswerExplanation;
  activeKey: string | null;
  onSelect: (group: ExplanationGroup) => void;
}) {
  const groups = explanation.groups ?? [];
  if (groups.length === 0) return null;
  const max = maxGroupCount(explanation);

  return (
    <div className="ex-bars" role="list" aria-label="Result breakdown by class">
      {groups.map((g) => {
        const count = g.exact_count ?? g.shown_count ?? 0;
        const active = activeKey === g.key;
        const selectable = isSelectable(g);
        return (
          <button
            key={g.key}
            role="listitem"
            type="button"
            className={`ex-bar${active ? " ex-bar-on" : ""}`}
            aria-pressed={active}
            disabled={!selectable}
            // Named explicitly: the visible label, count and bar are separate
            // spans, so without this the tooltip would become the accessible
            // name and the group's identity would be lost to a screen reader.
            aria-label={`${g.label}, ${formatCount(count)} objects`}
            title={
              selectable
                ? `Highlight only ${g.label}`
                : "No object identities are available for this group"
            }
            onClick={() => onSelect(g)}
          >
            <span className="ex-bar-label">{g.label}</span>
            <span className="ex-bar-track">
              <span className="ex-bar-fill" style={{ width: `${(count / max) * 100}%` }} />
            </span>
            <span className="ex-bar-count">{formatCount(count)}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The compact horizontal bar chart (task29 §4).
 *
 * Every bar carries its exact label and its exact value: the bar length is a
 * visual comparison, never a replacement for the number. Buckets are grouped
 * counts with no identity set, so they are displayed and never selectable.
 */
function BarChart({ explanation }: { explanation: AnswerExplanation }) {
  const buckets = explanation.distribution ?? [];
  if (buckets.length === 0) return null;
  const max = maxBucketCount(explanation);
  const unit = explanation.chart_unit;

  return (
    <div className="ex-bars" role="list" aria-label="Distribution">
      {buckets.map((b, i) => (
        <div className="ex-bar ex-bar-static" role="listitem" key={`${b.key}-${i}`}>
          <span className="ex-bar-label">{b.key}</span>
          <span className="ex-bar-track">
            <span
              className="ex-bar-fill"
              style={{ width: `${(barMagnitude(b) / max) * 100}%` }}
            />
          </span>
          <span className="ex-bar-count">{barValueLabel(b, unit)}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Bounded, scrollable rows of objects the answer already retrieved (task29 §3.1).
 *
 * The caption is an explicit `showing N of total` disclosure whenever the table
 * is capped, so a capped table can never imply it is exhaustive. GlobalId is the
 * final identity fallback when no name was already available.
 */
function RowTable({ explanation }: { explanation: AnswerExplanation }) {
  const rows = explanation.rows ?? [];
  if (rows.length === 0) return null;
  const total = explanation.true_result_count ?? 0;
  return (
    <div className="ex-table-wrap">
      <table className="ex-table">
        <caption className="ex-table-cap">
          {rows.length < total
            ? `Showing ${formatCount(rows.length)} of ${formatCount(total)} results`
            : `${formatCount(rows.length)} results`}
        </caption>
        <thead>
          <tr>
            <th scope="col">Object</th>
            <th scope="col">Class</th>
            <th scope="col">Storey</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.global_id}>
              <td title={r.global_id}>{r.name ?? r.global_id}</td>
              <td>{r.ifc_class}</td>
              <td>{r.storey_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A one-bucket distribution or a heterogeneous structured comparison (task29 §3.2).
 *
 * A single bar carries no comparative value, so the bucket is tabulated instead.
 */
function BucketTable({
  explanation,
  caption,
}: {
  explanation: AnswerExplanation;
  caption: string;
}) {
  const buckets = explanation.distribution ?? [];
  if (buckets.length === 0) return null;
  const unit = explanation.chart_unit;
  const anyValue = buckets.some((b) => b.value !== null && b.value !== undefined);
  return (
    <div className="ex-table-wrap">
      <table className="ex-table">
        <caption className="ex-table-cap">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">Objects</th>
            {anyValue && <th scope="col">Value</th>}
          </tr>
        </thead>
        <tbody>
          {buckets.map((b, i) => (
            <tr key={`${b.key}-${i}`}>
              <td>{b.key}</td>
              <td>{formatCount(b.count ?? 0)}</td>
              {anyValue && (
                <td>
                  {b.value === null || b.value === undefined
                    ? "—"
                    : barValueLabel(b, unit)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The class group summary beside a result table — only when it means something. */
function GroupSummary({
  explanation,
  activeKey,
  onSelect,
}: {
  explanation: AnswerExplanation;
  activeKey: string | null;
  onSelect: (group: ExplanationGroup) => void;
}) {
  // The backend already withholds a single-class breakdown, so a non-empty
  // `groups` is by construction a summary worth showing (task29 §3.1).
  if ((explanation.groups ?? []).length === 0) return null;
  return <GroupBars explanation={explanation} activeKey={activeKey} onSelect={onSelect} />;
}

export default function ExplanationVisual({
  explanation,
  activeKey,
  onSelect,
}: {
  explanation: AnswerExplanation;
  activeKey: string | null;
  onSelect: (group: ExplanationGroup) => void;
}) {
  const summary = (
    <GroupSummary explanation={explanation} activeKey={activeKey} onSelect={onSelect} />
  );

  switch (explanation.presentation) {
    case "bar_chart":
      return (
        <div className="ex-visual" data-presentation="bar_chart">
          <BarChart explanation={explanation} />
        </div>
      );

    case "group_table":
      return (
        <div className="ex-visual" data-presentation="group_table">
          <BucketTable explanation={explanation} caption="Group" />
        </div>
      );

    case "comparison_table":
      return (
        <div className="ex-visual" data-presentation="comparison_table">
          <BucketTable explanation={explanation} caption="Comparison" />
        </div>
      );

    case "relationship_graph":
      return (
        <div className="ex-visual" data-presentation="relationship_graph">
          {explanation.graph && (
            <RelationshipGraph
              graph={explanation.graph}
              activeKey={activeKey}
              onSelect={onSelect}
            />
          )}
        </div>
      );

    case "relationship_table":
      return (
        <div className="ex-visual" data-presentation="relationship_table">
          {summary}
          <RowTable explanation={explanation} />
        </div>
      );

    case "result_table":
    default:
      // `result_table` is the only remaining table family the selector emits.
      // The default arm also carries a Task 26 payload from an older backend,
      // which is a table in every case that still opens the card.
      return (
        <div className="ex-visual" data-presentation="result_table">
          {summary}
          <RowTable explanation={explanation} />
        </div>
      );
  }
}
