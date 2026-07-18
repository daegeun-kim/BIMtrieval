import { useEffect, useState } from "react";

import { controller } from "../state/controller";
import type { InstrumentationSnapshot } from "./ViewerInstrumentation";

const POLL_MS = 500; // ~2Hz — a per-frame text update would itself be a perf cost

/**
 * Dev-only performance readout (tasks/task18.md §1). Polls
 * `ViewerAdapter.getInstrumentationSnapshot()` on its own low-rate interval —
 * deliberately NOT wired to camera/render events, so it can never itself
 * become a re-render-storm source (ViewerCanvas stays reactive-state-free by
 * design; this is an independent sibling, not a subscriber).
 *
 * Renders nothing when instrumentation is disabled (production builds never
 * construct ViewerInstrumentation at all — see ViewerAdapter.init).
 */
export default function ViewerInstrumentationOverlay() {
  const [snapshot, setSnapshot] = useState<InstrumentationSnapshot | null>(null);

  useEffect(() => {
    const id = window.setInterval(() => {
      setSnapshot(controller.viewer.getInstrumentationSnapshot());
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, []);

  if (!snapshot) return null;

  return (
    <pre className="viewer-instrumentation-overlay" data-testid="viewer-instrumentation">
      {`fps ${snapshot.fps} (avg ${snapshot.fpsAvg})  frame ${snapshot.frameTimeMs}ms (avg ${snapshot.frameTimeAvgMs}, worst ${snapshot.frameTimeWorstMs})
draw ${snapshot.drawCalls}  tris ${snapshot.triangles}  lines ${snapshot.lines}  pts ${snapshot.points}
canvas ${snapshot.canvasWidth}x${snapshot.canvasHeight}  dpr ${snapshot.pixelRatio}
longtasks ${snapshot.longTaskCount} (worst ${snapshot.longTaskWorstMs}ms)
fragments update ${snapshot.fragmentsUpdateMs ?? "-"}ms  forced ${snapshot.forcedFragmentsUpdates}  throttled ${snapshot.throttledFragmentsUpdates}
edges build ${snapshot.edgeBuildMs ?? "-"}ms  verts ${snapshot.edgeVertexCount}  chunks ${snapshot.edgeChunkCount}  items ${snapshot.modelItemCount}
motion ${snapshot.motion}  profile ${snapshot.profile}`}
    </pre>
  );
}
