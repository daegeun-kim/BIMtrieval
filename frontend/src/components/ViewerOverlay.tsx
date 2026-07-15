import { controller } from "../state/controller";
import { useStore, type LoadPhase } from "../state/store";

// Centered viewer overlay for load progress and load failures (spec_v006 §8.2,
// §15). Progress is honest and coarse — bounded phases, never fake precision.
const PHASES: { key: LoadPhase; label: string }[] = [
  { key: "metadata", label: "Metadata" },
  { key: "downloading", label: "Download" },
  { key: "cached", label: "Cache" },
  { key: "initializing", label: "Scene" },
  { key: "ready", label: "Ready" },
];

const ORDER: LoadPhase[] = ["metadata", "downloading", "cached", "initializing", "ready"];

export default function ViewerOverlay() {
  const phase = useStore((s) => s.loadPhase);
  const error = useStore((s) => s.loadError);
  const model = useStore((s) => s.activeModel);

  if (phase === "error") {
    return (
      <div className="viewer-overlay">
        <div className="overlay-card">
          <p className="overlay-title">Couldn't load the model</p>
          <p className="overlay-sub">{error ?? "The 3D artifact is unavailable."}</p>
          <p className="overlay-note">You can still ask catalog or general questions.</p>
          <button className="btn-primary" onClick={() => controller.retryLoad()}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (phase === "idle" || phase === "ready") return null;

  const activeIndex = ORDER.indexOf(phase);
  return (
    <div className="viewer-overlay">
      <div className="overlay-card">
        <p className="overlay-title">Loading {model?.display_name ?? "model"}</p>
        <div className="phase-track">
          {PHASES.filter((p) => p.key !== "cached" || phase === "cached").map((p) => {
            const idx = ORDER.indexOf(p.key);
            const state = idx < activeIndex ? "done" : idx === activeIndex ? "active" : "todo";
            return (
              <div className={`phase phase-${state}`} key={p.key}>
                <span className="phase-dot" />
                <span className="phase-label">{p.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
