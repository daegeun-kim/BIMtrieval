import { controller } from "../state/controller";
import { useStore } from "../state/store";
import type { ModelCandidate } from "../api/types";

// Compact in-chat candidate controls (spec_v006 §12.2) — NOT a catalog page.
// A candidate loads only on explicit user click (spec_v006 §8.2).
export default function ModelCandidates({ candidates }: { candidates: ModelCandidate[] }) {
  const models = useStore((s) => s.models);
  const pending = useStore((s) => s.loadPhase);
  const loading = pending !== "idle" && pending !== "ready" && pending !== "error";

  return (
    <div className="candidates" role="group" aria-label="Model candidates">
      {candidates.map((c) => {
        const known = models.find((m) => m.source_model_id === c.source_model_id);
        const label = c.display_name || known?.display_name || `Model ${c.source_model_id}`;
        return (
          <button
            key={c.source_model_id}
            className="candidate"
            disabled={loading}
            onClick={() => {
              const model = known;
              if (model) void controller.confirmAndLoadModel(model);
            }}
          >
            <span className="candidate-name">{label}</span>
            <span className="candidate-cta">Load</span>
          </button>
        );
      })}
    </div>
  );
}
