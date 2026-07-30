import { CloseIcon } from "../components/icons";
import { controller } from "../state/controller";
import { useStore } from "../state/store";
import ExplanationInfo from "./ExplanationInfo";
import ExplanationVisual from "./ExplanationVisual";
import { activeGroup } from "./explanation";

// The Query Explanation card (tasks/task26.md). A visual explanation of the
// backend's already-computed authoritative result — not a second analysis
// system. It never issues a query, so selecting a group or restoring the full
// result costs nothing and consumes no tokens.
//
// Two content regions, always: the visualization at the left and a persistent
// plain-language information region at the right. A chart or table never
// appears alone (§4).
export default function ExplanationPanel() {
  const explanation = useStore((s) => s.explanation);
  const groupKey = useStore((s) => s.explanationGroupKey);

  if (!explanation) return null;
  const group = activeGroup(explanation, groupKey);

  return (
    <section className="explain-panel" aria-label="Query explanation">
      <div className="tick tick-tl" />
      <div className="tick tick-tr" />
      <header className="ex-head">
        <div className="ex-head-text">
          <h3 className="ex-title">Query explanation</h3>
          <p className="ex-sub" title={explanation.request_label}>
            {explanation.request_label}
          </p>
        </div>
        <div className="ex-head-actions">
          {group && (
            <button
              className="ex-all-btn"
              onClick={() => void controller.showAllExplanationResults()}
              title="Restore the full query result in the viewer"
            >
              All results
            </button>
          )}
          <button
            className="icon-btn"
            onClick={() => void controller.closeExplanation()}
            aria-label="Close query explanation"
            title="Close (also clears this result's highlight)"
          >
            <CloseIcon size={14} />
          </button>
        </div>
      </header>

      <div className="ex-body">
        <ExplanationVisual
          explanation={explanation}
          activeKey={groupKey}
          onSelect={(g) => void controller.selectExplanationGroup(g.key)}
        />
        <ExplanationInfo explanation={explanation} group={group} />
      </div>
    </section>
  );
}
