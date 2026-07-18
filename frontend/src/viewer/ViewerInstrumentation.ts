// Dev-only viewer performance instrumentation (tasks/task18.md §1).
//
// Negligible cost when disabled: `import.meta.env.DEV` dead-code-eliminates
// the constructing call from production builds (see ViewerAdapter.init), and
// a runtime opt-in (`?perf=1` or a persisted flag) keeps it off during a plain
// `npm run dev` session too. Never sends telemetry externally and never adds
// backend logging for browser frame measurements.
import * as OBC from "@thatopen/components";
import * as THREE from "three";

const STORAGE_KEY = "bimrag.viewerPerf";
const RING_SIZE = 120;

export type MotionLabel = "resting" | "moving";

export interface InstrumentationSnapshot {
  fps: number;
  fpsAvg: number;
  frameTimeMs: number;
  frameTimeAvgMs: number;
  frameTimeWorstMs: number;
  drawCalls: number;
  triangles: number;
  lines: number;
  points: number;
  canvasWidth: number;
  canvasHeight: number;
  pixelRatio: number;
  longTaskCount: number;
  longTaskWorstMs: number;
  fragmentsUpdateMs: number | null;
  forcedFragmentsUpdates: number;
  throttledFragmentsUpdates: number;
  edgeBuildMs: number | null;
  edgeVertexCount: number;
  edgeChunkCount: number;
  modelItemCount: number;
  motion: MotionLabel;
  profile: string;
}

/**
 * Runtime opt-in check: `?perf=1` persists the flag (so a reload keeps
 * instrumentation on), `?perf=0` clears it. Read once at construction time —
 * toggling requires a reload, which keeps the check itself free of a storage
 * listener.
 */
export function instrumentationRequested(): boolean {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("perf") === "1") {
      window.localStorage?.setItem(STORAGE_KEY, "1");
      return true;
    }
    if (params.get("perf") === "0") {
      window.localStorage?.removeItem(STORAGE_KEY);
      return false;
    }
    return window.localStorage?.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Frame-time ring buffer + counters, fed from `SimpleRenderer.onAfterUpdate`
 * (one tick per Components update, whether or not a WebGL frame was actually
 * drawn) and a `PerformanceObserver("longtask")` where supported. Other
 * viewer systems report into it via optional-chained calls so a disabled
 * instrumentation instance costs nothing beyond a null check at the call
 * site (ViewerAdapter never constructs this class unless enabled).
 */
export class ViewerInstrumentation {
  private frameTimes = new Float32Array(RING_SIZE);
  private cursor = 0;
  private filled = 0;
  private lastTickAt: number | null = null;
  private longTaskObserver: PerformanceObserver | null = null;
  private longTaskCount = 0;
  private longTaskWorstMs = 0;
  private forcedFragmentsUpdates = 0;
  private throttledFragmentsUpdates = 0;
  private fragmentsUpdateMs: number | null = null;
  private edgeBuildMs: number | null = null;
  private edgeVertexCount = 0;
  private edgeChunkCount = 0;
  private modelItemCount = 0;
  private motion: MotionLabel = "resting";
  private profile = "balanced";
  private disposed = false;

  private readonly onTick = (): void => {
    const now = performance.now();
    if (this.lastTickAt !== null) {
      const dt = now - this.lastTickAt;
      this.frameTimes[this.cursor] = dt;
      this.cursor = (this.cursor + 1) % RING_SIZE;
      if (this.filled < RING_SIZE) this.filled += 1;
    }
    this.lastTickAt = now;
  };

  constructor(private readonly renderer: OBC.SimpleRenderer) {
    renderer.onAfterUpdate.add(this.onTick);
    if (typeof PerformanceObserver !== "undefined") {
      try {
        this.longTaskObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            this.longTaskCount += 1;
            if (entry.duration > this.longTaskWorstMs) this.longTaskWorstMs = entry.duration;
          }
        });
        this.longTaskObserver.observe({ entryTypes: ["longtask"] });
      } catch {
        // "longtask" is unsupported in some browsers/test environments; the
        // rest of instrumentation stays useful without it.
      }
    }
  }

  recordForcedFragmentsUpdate(ms: number): void {
    this.forcedFragmentsUpdates += 1;
    this.fragmentsUpdateMs = ms;
  }

  recordThrottledFragmentsUpdate(ms: number): void {
    this.throttledFragmentsUpdates += 1;
    this.fragmentsUpdateMs = ms;
  }

  recordEdgeBuild(buildMs: number, vertexCount: number, chunkCount: number): void {
    this.edgeBuildMs = buildMs;
    this.edgeVertexCount = vertexCount;
    this.edgeChunkCount = chunkCount;
  }

  setModelItemCount(count: number): void {
    this.modelItemCount = count;
  }

  setMotion(state: MotionLabel): void {
    this.motion = state;
  }

  setProfile(profile: string): void {
    this.profile = profile;
  }

  snapshot(): InstrumentationSnapshot {
    const n = this.filled;
    let sum = 0;
    let worst = 0;
    for (let i = 0; i < n; i++) {
      const v = this.frameTimes[i]!;
      sum += v;
      if (v > worst) worst = v;
    }
    const avgMs = n > 0 ? sum / n : 0;
    const lastIdx = (this.cursor - 1 + RING_SIZE) % RING_SIZE;
    const lastMs = n > 0 ? this.frameTimes[lastIdx]! : 0;

    const three = this.renderer.three as THREE.WebGLRenderer | undefined;
    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let drawCalls = 0;
    let triangles = 0;
    let lines = 0;
    let points = 0;
    try {
      if (three) {
        const size = three.getDrawingBufferSize(new THREE.Vector2());
        width = size.x;
        height = size.y;
        pixelRatio = three.getPixelRatio();
        drawCalls = three.info.render.calls;
        triangles = three.info.render.triangles;
        lines = three.info.render.lines;
        points = three.info.render.points;
      }
    } catch {
      // renderer may not be attached to a real canvas (tests) — leave zeros
    }

    return {
      fps: lastMs > 0 ? Math.round(1000 / lastMs) : 0,
      fpsAvg: avgMs > 0 ? Math.round(1000 / avgMs) : 0,
      frameTimeMs: Math.round(lastMs * 10) / 10,
      frameTimeAvgMs: Math.round(avgMs * 10) / 10,
      frameTimeWorstMs: Math.round(worst * 10) / 10,
      drawCalls,
      triangles,
      lines,
      points,
      canvasWidth: width,
      canvasHeight: height,
      pixelRatio,
      longTaskCount: this.longTaskCount,
      longTaskWorstMs: Math.round(this.longTaskWorstMs * 10) / 10,
      fragmentsUpdateMs: this.fragmentsUpdateMs,
      forcedFragmentsUpdates: this.forcedFragmentsUpdates,
      throttledFragmentsUpdates: this.throttledFragmentsUpdates,
      edgeBuildMs: this.edgeBuildMs,
      edgeVertexCount: this.edgeVertexCount,
      edgeChunkCount: this.edgeChunkCount,
      modelItemCount: this.modelItemCount,
      motion: this.motion,
      profile: this.profile,
    };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.renderer.onAfterUpdate.remove(this.onTick);
    this.longTaskObserver?.disconnect();
    this.longTaskObserver = null;
  }
}
