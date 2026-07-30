import type { AnswerExplanation, ExplanationGroup } from "../api/types";
import {
  formatCount,
  isSelectable,
  maxBucketCount,
  maxGroupCount,
  operationLabel,
} from "./explanation";

// The visualization half of the explanation card (task26 §4.1). Ordinary
// React/CSS — no charting dependency is needed for a bar row and a table, and
// none is added.
//
// Everything rendered comes from the bounded presentation payload. A group is
// clickable only when the backend supplied its identities; a distribution
// bucket never is, because grouped counts have no identity subset to select.

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

/** Existing distribution buckets. Displayed, never selectable (task26 §1.1). */
function DistributionBars({ explanation }: { explanation: AnswerExplanation }) {
  const buckets = explanation.distribution ?? [];
  if (buckets.length === 0) return null;
  const max = maxBucketCount(explanation);

  return (
    <div className="ex-bars" role="list" aria-label="Distribution">
      {buckets.map((b, i) => (
        <div className="ex-bar ex-bar-static" role="listitem" key={`${b.key}-${i}`}>
          <span className="ex-bar-label">{b.key}</span>
          <span className="ex-bar-track">
            <span
              className="ex-bar-fill"
              style={{ width: `${((b.count ?? 0) / max) * 100}%` }}
            />
          </span>
          <span className="ex-bar-count">{formatCount(b.count ?? 0)}</span>
        </div>
      ))}
    </div>
  );
}

/** Bounded, scrollable rows of objects the answer already retrieved. */
function RowTable({ explanation }: { explanation: AnswerExplanation }) {
  const rows = explanation.rows ?? [];
  if (rows.length === 0) return null;
  return (
    <div className="ex-table-wrap">
      <table className="ex-table">
        <caption className="ex-table-cap">
          {rows.length < (explanation.true_result_count ?? 0)
            ? `${formatCount(rows.length)} of ${formatCount(
                explanation.true_result_count ?? 0,
              )} results`
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

function Headline({ explanation }: { explanation: AnswerExplanation }) {
  return (
    <div className="ex-metric">
      <span className="ex-metric-value" data-testid="ex-metric">
        {formatCount(explanation.true_result_count ?? 0)}
      </span>
      <span className="ex-metric-caption">{operationLabel(explanation.operation)}</span>
    </div>
  );
}

function Aggregate({ explanation }: { explanation: AnswerExplanation }) {
  const agg = explanation.aggregate;
  if (!agg) return <Headline explanation={explanation} />;
  return (
    <div className="ex-metric">
      <span className="ex-metric-value" data-testid="ex-aggregate">
        {agg.value === null || agg.value === undefined ? "—" : agg.value.toLocaleString()}
        {agg.unit ? <span className="ex-metric-unit"> {agg.unit}</span> : null}
      </span>
      <span className="ex-metric-caption">
        {agg.function} · {formatCount(agg.coverage_count ?? 0)} of{" "}
        {formatCount(agg.matched_count ?? 0)} matched
      </span>
    </div>
  );
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
  const groups = explanation.groups ?? [];
  // A single-class breakdown adds no information beyond the headline, so the
  // bars appear only when they mean something (task26 §4.1).
  const meaningfulGroups = groups.length > 1;
  const bars = (
    <GroupBars explanation={explanation} activeKey={activeKey} onSelect={onSelect} />
  );

  switch (explanation.presentation) {
    case "distribution":
      return (
        <div className="ex-visual" data-presentation="distribution">
          <DistributionBars explanation={explanation} />
          {meaningfulGroups && bars}
        </div>
      );

    case "aggregate":
      return (
        <div className="ex-visual" data-presentation="aggregate">
          <Aggregate explanation={explanation} />
          {meaningfulGroups && bars}
        </div>
      );

    case "table":
      return (
        <div className="ex-visual" data-presentation="table">
          <Headline explanation={explanation} />
          {meaningfulGroups && bars}
          <RowTable explanation={explanation} />
        </div>
      );

    case "relationship":
      return (
        <div className="ex-visual" data-presentation="relationship">
          <div className="ex-metric">
            <span className="ex-metric-value" data-testid="ex-endpoints">
              {formatCount(explanation.relationship_endpoint_total ?? 0)}
            </span>
            <span className="ex-metric-caption">connected objects</span>
          </div>
          {meaningfulGroups && bars}
          <RowTable explanation={explanation} />
        </div>
      );

    case "partial":
      return (
        <div className="ex-visual" data-presentation="partial">
          <Headline explanation={explanation} />
          <div className="ex-split">
            <div className="ex-split-col">
              <p className="ex-split-head">Known</p>
              {(explanation.known_parts ?? []).map((k) => (
                <p className="ex-split-item" key={`pk-${k}`}>
                  {k}
                </p>
              ))}
            </div>
            <div className="ex-split-col ex-split-unknown">
              <p className="ex-split-head">Not available</p>
              {(explanation.unknown_parts ?? []).map((u) => (
                <p className="ex-split-item" key={`pu-${u}`}>
                  {u}
                </p>
              ))}
            </div>
          </div>
          {meaningfulGroups && bars}
        </div>
      );

    case "metric":
    default:
      return (
        <div className="ex-visual" data-presentation="metric">
          <Headline explanation={explanation} />
          {meaningfulGroups && bars}
        </div>
      );
  }
}
