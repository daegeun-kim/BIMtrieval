// The demo's stand-in for `src/chat/Composer.tsx` (spec_v013 §4.5).
//
// The real composer is a free-text field. This one offers exactly the three
// questions that were recorded, because a static demo that accepted arbitrary
// input could only answer it by fabricating — which is the one thing this
// project is built not to do.
//
// `SelectionChips` is the real component, imported unchanged, so the selection
// UI above the picker is the genuine one.
import { useState } from "react";

import SelectionChips from "../../src/chat/SelectionChips";
import { controller } from "../../src/state/controller";
import { useStore } from "../../src/state/store";
import type { ResolvedEntity } from "../../src/api/types";
import { demoQuestions, resolveFixture, type DemoQuestion } from "./fixtures";

/**
 * How the retrieval method reads on a badge.
 *
 * The badge shows `answer_basis`, not `route`. In the current pipeline every
 * active-model question returns `route: "hybrid"` — retrieval mode is derived
 * from the bound operation rather than classified up front
 * (`app/llm/schemas.py` §5.1) — so a route badge would print the same word three
 * times and say nothing. `answer_basis` is what actually produced the evidence.
 */
function basisLabel(basis: string): string {
  switch (basis) {
    case "exact_sql":
      return "exact SQL";
    case "graph_traversal":
      return "graph traversal";
    case "hybrid_evidence":
      return "SQL + semantic";
    case "semantic_retrieval":
      return "semantic retrieval";
    case "general_knowledge":
      return "general knowledge";
    case "insufficient_evidence":
      return "insufficient evidence";
    default:
      return basis.replace(/_/g, " ");
  }
}

export default function DemoComposer() {
  const pending = useStore((s) => s.pending);
  const [asked, setAsked] = useState<string[]>([]);

  /**
   * `graph-01` was recorded with a storey already selected in the viewer, and
   * the question ("what elements are contained in *this* storey?") is
   * meaningless without it (spec_v013 §5.3). Restoring the selection before
   * replaying keeps the transcript coherent and the chip UI truthful.
   *
   * `setManualGuids` and `setResolvedChips` are public store actions, so this
   * needs no change under `src/`.
   */
  const applyPreSelection = (question: DemoQuestion) => {
    const store = useStore.getState();
    if (!question.preSelection) {
      store.clearSelection();
      return;
    }
    const { globalIds } = question.preSelection;
    const byGuid = new Map<string, ResolvedEntity>(
      (resolveFixture.resolved ?? []).map((e) => [e.global_id, e]),
    );
    const chips: Record<string, ResolvedEntity> = {};
    for (const guid of globalIds) {
      const entity = byGuid.get(guid);
      if (entity) chips[guid] = entity;
    }
    store.setManualGuids(globalIds);
    store.setResolvedChips(chips);
  };

  const ask = (question: DemoQuestion) => {
    if (pending) return;
    applyPreSelection(question);
    setAsked((prev) => (prev.includes(question.id) ? prev : [...prev, question.id]));
    // The identical entry point the real composer uses.
    void controller.submitQuestion(question.text);
  };

  return (
    <div className="composer demo-composer">
      <SelectionChips />

      <p className="demo-picker-label">
        {pending ? "Replaying a recorded answer…" : "Pick a question"}
      </p>

      <ul className="demo-picker">
        {demoQuestions.map((q) => {
          const answered = asked.includes(q.id);
          return (
            <li key={q.id}>
              <button
                className={`demo-question${answered ? " is-answered" : ""}`}
                onClick={() => ask(q)}
                disabled={pending}
                aria-label={`Ask: ${q.text}`}
              >
                <span className="demo-question-text">{q.text}</span>

                {/* The route is DELIBERATELY hidden until the question has been
                    asked (spec_v013 §5.1). Labelling each button "SQL" or "RAG"
                    up front gives away the answer to the thing the demo exists
                    to show — that the system decides, per question, which of
                    three retrieval paths the question actually needs. Revealed
                    on submit, it reads as a result; printed in advance, it reads
                    as a category. */}
                {answered && (
                  <span className="demo-routed">
                    <span className="demo-routed-label">answered by</span>
                    <span className={`demo-route demo-route-${q.basis}`}>{basisLabel(q.basis)}</span>
                    {q.operation && <span className="demo-op">{q.operation.replace(/_/g, " ")}</span>}
                    <span className="demo-question-cost">
                      took {(q.recorded.latencyMs / 1000).toFixed(1)} s
                    </span>
                  </span>
                )}
                {answered && <span className="demo-question-blurb">{q.blurb}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      <p className="composer-hint">
        Three recorded answers · no live backend ·{" "}
        <a href="https://github.com/daegeun-kim/BIMtrieval" target="_blank" rel="noreferrer">
          run it yourself
        </a>
      </p>
    </div>
  );
}
