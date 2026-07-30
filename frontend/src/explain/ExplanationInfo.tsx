import type { AnswerExplanation, ExplanationGroup } from "../api/types";
import {
  basisLabel,
  coverageLine,
  fullResultLine,
  highlightedLine,
  operationLabel,
  showingLabel,
  statusLabel,
  truncationLine,
} from "./explanation";

// The persistent basic-information region at the card's right (task26 §4).
//
// It is present for EVERY presentation — a chart or table never appears alone —
// and it is descriptive only: every line restates a field the backend already
// established. It introduces no interpretation and no factual claim of its own.
export default function ExplanationInfo({
  explanation,
  group,
}: {
  explanation: AnswerExplanation;
  group: ExplanationGroup | null;
}) {
  const truncation = truncationLine(explanation, group);
  const coverage = coverageLine(explanation);
  const known = explanation.known_parts ?? [];
  const unknown = explanation.unknown_parts ?? [];

  return (
    <aside className="ex-info" aria-label="What is shown">
      <section className="ex-info-block ex-info-showing">
        <p className="ex-info-label">Showing</p>
        <p className="ex-info-strong" data-testid="ex-showing">
          {showingLabel(group)}
        </p>
        <p className="ex-info-line" data-testid="ex-highlighted">
          {highlightedLine(explanation, group)}
        </p>
        {group && (
          <p className="ex-info-line ex-info-muted" data-testid="ex-full-result">
            Full result: {fullResultLine(explanation)}
          </p>
        )}
      </section>

      <section className="ex-info-block">
        <p className="ex-info-label">Question part</p>
        <p className="ex-info-line">{explanation.request_label}</p>
      </section>

      {explanation.interpretation && (
        <section className="ex-info-block">
          <p className="ex-info-label">Read as</p>
          <p className="ex-info-line">{explanation.interpretation}</p>
        </section>
      )}

      <section className="ex-info-block">
        <p className="ex-info-label">Result</p>
        <p className="ex-info-line">
          {operationLabel(explanation.operation)} · {statusLabel(explanation.result_status)}
        </p>
        <p className="ex-info-line ex-info-muted">{basisLabel(explanation.answer_basis)}</p>
      </section>

      {truncation && (
        <p className="ex-info-note" data-testid="ex-truncation">
          {truncation}
        </p>
      )}
      {coverage && <p className="ex-info-note">{coverage}</p>}
      {explanation.limitation && <p className="ex-info-note">{explanation.limitation}</p>}

      {(known.length > 0 || unknown.length > 0) && (
        <section className="ex-info-block">
          {known.length > 0 && (
            <>
              <p className="ex-info-label">Known</p>
              {known.map((k) => (
                <p className="ex-info-line" key={`k-${k}`}>
                  {k}
                </p>
              ))}
            </>
          )}
          {unknown.length > 0 && (
            <>
              <p className="ex-info-label">Not available</p>
              {unknown.map((u) => (
                <p className="ex-info-line ex-info-muted" key={`u-${u}`}>
                  {u}
                </p>
              ))}
            </>
          )}
        </section>
      )}
    </aside>
  );
}
