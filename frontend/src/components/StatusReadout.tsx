import { useStore, type LoadPhase } from "../state/store";
import { HomeIcon } from "./icons";
import { controller } from "../state/controller";

// CAD-style technical readout, bottom-left of the viewer (spec_v006 §7.3). Model
// name, short fingerprint, entity/asset status — set in mono. This is the
// "measured drawing" status bar, not a metadata inspector.
const PHASE_TEXT: Record<LoadPhase, string> = {
  idle: "no model",
  metadata: "reading metadata…",
  downloading: "downloading artifact…",
  cached: "loading (cached)…",
  initializing: "initializing scene…",
  ready: "ready",
  error: "load failed",
};

const STATUS_DOT: Record<string, string> = {
  ready: "ok",
  missing: "warn",
  stale: "warn",
  unavailable: "warn",
};

export default function StatusReadout() {
  const model = useStore((s) => s.activeModel);
  const phase = useStore((s) => s.loadPhase);
  const backendReachable = useStore((s) => s.backendReachable);

  return (
    <div className="readout" role="status" aria-live="polite">
      <div className="readout-line">
        <span className={`sdot ${backendReachable ? STATUS_DOT[model?.viewer_asset_status ?? ""] ?? "idle" : "err"}`} />
        <span className="readout-name">{model ? model.display_name : "BIM Model Explorer"}</span>
      </div>
      <div className="readout-meta">
        {!backendReachable && <span className="readout-err">backend offline</span>}
        {model && (
          <>
            <span className="readout-fp" title={model.source_fingerprint}>
              #{model.source_fingerprint.slice(0, 8)}
            </span>
            <span className="readout-phase">{PHASE_TEXT[phase]}</span>
          </>
        )}
      </div>
      {model && phase === "ready" && (
        <>
          <button className="readout-fit" onClick={() => void controller.fitAll()} title="Fit model">
            <HomeIcon size={14} /> Fit
          </button>
        </>
      )}
    </div>
  );
}
