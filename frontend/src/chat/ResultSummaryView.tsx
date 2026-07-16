import type { ResultSummary } from "../api/types";
import { formatClassSummary } from "./resultSummary";

// Compact result line under an answer (tasks/task14.md §4): the exact total and
// a short class summary — never a dump of every retrieved component. The viewer
// shows the user which objects matched; this states how many.
//
// `sample_detail` is the one exception: the backend sets it only when the user
// explicitly asked for a sample or a specific component's details, so ordinary
// show/count queries never render component details here.
export default function ResultSummaryView({ summary }: { summary: ResultSummary }) {
  const classLine = formatClassSummary(summary.class_counts);
  const total = summary.exact_total;
  const sample = summary.sample_detail;

  const showTotals = typeof total === "number" || classLine.length > 0;
  if (!showTotals && !sample) return null;

  return (
    <div className="result-summary">
      {showTotals && (
        <p className="rs-line">
          {typeof total === "number" && <span className="rs-total">{total.toLocaleString()}</span>}
          {classLine && <span className="rs-classes">{classLine}</span>}
          {summary.truncated && summary.viewer_matches_total ? (
            <span className="rs-trunc">
              highlighting {(summary.viewer_match_count ?? 0).toLocaleString()} of{" "}
              {summary.viewer_matches_total.toLocaleString()}
            </span>
          ) : null}
        </p>
      )}

      {sample && (
        <div className="rs-sample">
          <p className="rs-sample-head">
            <span className="rs-sample-name">{sample.name ?? sample.ifc_class}</span>
            <span className="rs-sample-class">{sample.ifc_class}</span>
          </p>
          {sample.storey_name && (
            <p className="rs-sample-row">
              <span className="rs-k">storey</span>
              <span className="rs-v">{sample.storey_name}</span>
            </p>
          )}
          {(sample.materials ?? []).length > 0 && (
            <p className="rs-sample-row">
              <span className="rs-k">materials</span>
              <span className="rs-v">{(sample.materials ?? []).join(", ")}</span>
            </p>
          )}
          {(sample.quantities ?? []).map((q) => (
            <p className="rs-sample-row" key={`q-${q.source_set ?? ""}-${q.name}`}>
              <span className="rs-k">{q.name}</span>
              <span className="rs-v">
                {q.value}
                {q.unit ? ` ${q.unit}` : ""}
              </span>
            </p>
          ))}
          {(sample.properties ?? []).map((p) => (
            <p className="rs-sample-row" key={`p-${p.source_set ?? ""}-${p.name}`}>
              <span className="rs-k">{p.name}</span>
              <span className="rs-v">{p.value}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
