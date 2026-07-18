import { useEffect, useState } from "react";

import { useStore, type LoadPhase } from "../state/store";
import { HomeIcon } from "./icons";
import { controller } from "../state/controller";
import type { Profile } from "../viewer/profileDetection";

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

const PROFILE_LABEL: Record<Profile, string> = {
  balanced: "balanced",
  "large-model": "large model",
};

const POLL_MS = 1000; // profile rarely changes — no need for a fast poll

/**
 * Adaptive-profile indicator/override (tasks/task18.md §11) — discoverable
 * but secondary. `ViewerAdapter`'s profile isn't part of the reactive store
 * (it's decided by geometric signals during load, not user action), so this
 * polls it at a low rate, matching the pattern used by the dev instrumentation
 * overlay for the same reason (ViewerCanvas/ViewerAdapter stay reactive-state
 * free by design).
 */
function useViewerProfile(): { profile: Profile; override: Profile | null } {
  const [profile, setProfile] = useState<Profile>("balanced");
  const [override, setOverride] = useState<Profile | null>(null);
  useEffect(() => {
    const id = window.setInterval(() => {
      setProfile(controller.viewer.getProfile());
      setOverride(controller.viewer.getProfileOverride());
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, []);
  return { profile, override };
}

/** Automatic -> Balanced -> Large model -> Automatic. */
function nextOverride(current: Profile | null): Profile | null {
  if (current === null) return "balanced";
  if (current === "balanced") return "large-model";
  return null;
}

export default function StatusReadout() {
  const model = useStore((s) => s.activeModel);
  const phase = useStore((s) => s.loadPhase);
  const backendReachable = useStore((s) => s.backendReachable);
  const { profile, override } = useViewerProfile();

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
          <button
            className="readout-perf"
            data-override={override !== null}
            onClick={() => controller.viewer.setProfileOverride(nextOverride(override))}
            title="Adaptive rendering profile (pixel ratio, Fragments update rate, edge detail). Click to cycle: automatic, balanced, large model."
          >
            perf: {override ? `${PROFILE_LABEL[override]} (manual)` : `${PROFILE_LABEL[profile]} (auto)`}
          </button>
        </>
      )}
    </div>
  );
}
