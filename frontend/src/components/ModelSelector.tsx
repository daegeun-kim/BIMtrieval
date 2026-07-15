import { useStore } from "../state/store";

// Minimal display-name selector (spec_v006 §8.1). Choosing a model only proposes
// it — geometry never loads without explicit confirmation (spec_v006 §8.2), so
// this sets the pending-confirm id and App shows the confirmation.
export default function ModelSelector() {
  const models = useStore((s) => s.models);
  const activeModelId = useStore((s) => s.activeModelId);
  const loading = useStore((s) => s.modelsLoading);
  const setPendingConfirm = useStore((s) => s.setPendingConfirm);

  return (
    <label className="model-select">
      <span className="model-select-label">Model</span>
      <select
        value={activeModelId ?? ""}
        disabled={loading || models.length === 0}
        onChange={(e) => {
          const id = Number(e.target.value);
          if (Number.isFinite(id) && id !== activeModelId) setPendingConfirm(id);
        }}
      >
        <option value="" disabled>
          {loading ? "Loading…" : models.length === 0 ? "No models" : "Choose a model"}
        </option>
        {models.map((m) => (
          <option key={m.source_model_id} value={m.source_model_id}>
            {m.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}
