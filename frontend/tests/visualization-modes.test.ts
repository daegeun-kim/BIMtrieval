// Fine / Standard / Fast visualization modes (Task 31 §2, §8.1).
//
// A fake Fragments model and world are injected — no WebGL, no worker, no
// backend. The adapter's real mode logic runs against them, so the mode's two
// actual effects (the projected-size pair and the feature-edge angle) are
// asserted on the real code path rather than on a double.
import * as THREE from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useStore } from "../src/state/store";
import { ViewerAdapter } from "../src/viewer/ViewerAdapter";
import {
  DEFAULT_VISUALIZATION_MODE,
  EDGES,
  VISUALIZATION_MODES,
  VISUALIZATION_MODE_LABELS,
  VISUALIZATION_MODE_ORDER,
  VIEWER_COLORS,
  VIEWER_NAVIGATION,
  VIEWER_OPACITY,
  type VisualizationMode,
} from "../src/viewer/viewerCustomization";
import { EdgeOverlay } from "../src/viewer/EdgeOverlay";

// ---------------------------------------------------------------------------
// Adapter harness
// ---------------------------------------------------------------------------

function makeCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  Object.defineProperty(c, "clientWidth", { value: 1200, configurable: true });
  Object.defineProperty(c, "clientHeight", { value: 800, configurable: true });
  return c;
}

interface PolicyInternals {
  sizePolicy: { getThresholds(): { enterPx: number; exitPx: number } };
  edgeOverlay: EdgeOverlay | null;
  allLocalIds: number[];
  lastDetectedProfile: "balanced" | "large-model";
  visualizationMode: VisualizationMode;
}

function makeAdapter() {
  const adapter = new ViewerAdapter(5);
  const modelObject = new THREE.Object3D();
  const box = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(10, 10, 10));
  const setVisible = vi.fn(async () => {});
  const update = vi.fn(async () => {});
  const model = {
    box,
    object: modelObject,
    getBoxes: async (ids: number[]) =>
      ids.map(() => new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 1, 1))),
    setVisible,
    getCategories: async () => ["IFCFURNISHINGELEMENT"],
    getItemsOfCategories: async () => ({ IFCFURNISHINGELEMENT: [1, 2] }),
    getItemsData: async () => [{}, {}],
    getLocalIds: async () => [1, 2],
    // One trivial mesh per item, so a real EdgeOverlay build can run.
    getItemsGeometry: async (ids: number[]) =>
      ids.map(() => [
        {
          positions: new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0]),
          indices: new Uint32Array([0, 1, 2]),
          transform: undefined,
        },
      ]),
    getMergedBox: async () => box,
    getLocalIdsByGuids: async () => [],
    resetHighlight: vi.fn(async () => {}),
    highlight: vi.fn(async () => {}),
  };
  const camera = new THREE.PerspectiveCamera(27, 1.5, 0.1, 1000);
  camera.position.set(0, 0, 100);
  camera.updateMatrixWorld();
  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world: {
      camera: { controls: { fitToBox: vi.fn(async () => {}), mouseButtons: {} }, three: camera },
      scene: { three: new THREE.Scene() },
      renderer: { three: { domElement: makeCanvas() } },
    },
    fragments: { core: { update } },
    allLocalIds: [1, 2],
  });
  return { adapter, model, modelObject, setVisible, update, camera };
}

function priv(adapter: ViewerAdapter): PolicyInternals {
  return adapter as unknown as PolicyInternals;
}

/** Let the yielded EdgeOverlay build (MessageChannel ticks) finish. */
async function settle(): Promise<void> {
  for (let i = 0; i < 12; i++) await new Promise((r) => setTimeout(r, 0));
}

// ---------------------------------------------------------------------------
// The customization file is the ONE source (§1, §8.1)
// ---------------------------------------------------------------------------

describe("viewerCustomization is the single constant source (task31 §1)", () => {
  it("re-exports the same object through viewerTheme, never a copy", async () => {
    const theme = await import("../src/viewer/viewerTheme");
    expect(theme.VIEWER_COLORS).toBe(VIEWER_COLORS);
    expect(theme.VIEWER_OPACITY).toBe(VIEWER_OPACITY);
    expect(theme.EDGES).toBe(EDGES);
    // The camera block layers only its internal safety guard on top.
    expect(theme.VIEWER_CAMERA.focalLengthMm).toBe(VIEWER_NAVIGATION.focalLengthMm);
    expect(theme.VIEWER_CAMERA.fitExpand).toBe(VIEWER_NAVIGATION.fitExpand);
  });

  it("leaves no duplicate colour or threshold literal in the modules it was moved out of", async () => {
    const files = ["../src/viewer/viewerTheme.ts", "../src/viewer/ProjectedSizePolicy.ts"];
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    for (const file of files) {
      const source = await fs.readFile(path.resolve(__dirname, file), "utf8");
      expect(source).toContain("viewerCustomization"); // the read really happened
      // No hex colours anywhere: every colour now comes from the customization
      // file, including the plan-wall black.
      expect(source).not.toMatch(/#[0-9a-fA-F]{6}\b/);
      // No inline copy of a mode threshold.
      for (const value of ["20", "24", "32", "38", "48", "58"]) {
        expect(source).not.toMatch(new RegExp(`(enterPx|exitPx)\\s*[:=]\\s*${value}\\b`));
      }
    }
  });

  it("exposes only line values the installed renderer honors", () => {
    // WebGL guarantees 1-px lines, so a `linewidth`/thickness constant would be
    // a knob that does nothing — the file deliberately has none (task31 §1).
    const flat = JSON.stringify(EDGES);
    expect(flat).not.toMatch(/linewidth|thickness|widthPx/i);
    expect(EDGES.darken).toBeGreaterThan(0);
    expect(Object.keys(EDGES.lod).length).toBeGreaterThan(0);
  });

  it("keeps the plan wheel-zoom speed in the customization file", () => {
    expect(VIEWER_NAVIGATION.planWheelZoomSpeed).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Mode matrix + defaults (§2.1, §2.2)
// ---------------------------------------------------------------------------

describe("mode declaration (task31 §2.1, §2.2)", () => {
  it("offers exactly three modes, finest first, with Standard the default", () => {
    expect([...VISUALIZATION_MODE_ORDER]).toEqual(["fine", "standard", "fast"]);
    expect(DEFAULT_VISUALIZATION_MODE).toBe("standard");
    expect(VISUALIZATION_MODE_LABELS).toEqual({
      fine: "Fine",
      standard: "Standard",
      fast: "Fast",
    });
  });

  it("Fine reproduces the pre-task-31 thresholds exactly", () => {
    expect(VISUALIZATION_MODES.fine.projectedSizeHidePx).toBe(20);
    expect(VISUALIZATION_MODES.fine.projectedSizeRestorePx).toBe(24);
    expect(VISUALIZATION_MODES.fine.edgeAngleBalancedDeg).toBe(25);
    expect(VISUALIZATION_MODES.fine.edgeAngleLargeModelDeg).toBe(40);
  });

  it("retains fewer feature edges as the mode coarsens, in both profiles", () => {
    const angles = VISUALIZATION_MODE_ORDER.map((m) => VISUALIZATION_MODES[m]);
    for (let i = 1; i < angles.length; i++) {
      expect(angles[i]!.edgeAngleBalancedDeg).toBeGreaterThan(angles[i - 1]!.edgeAngleBalancedDeg);
      expect(angles[i]!.edgeAngleLargeModelDeg).toBeGreaterThan(
        angles[i - 1]!.edgeAngleLargeModelDeg,
      );
    }
    // A large model is always the stricter angle of its own mode.
    for (const mode of VISUALIZATION_MODE_ORDER) {
      expect(VISUALIZATION_MODES[mode].edgeAngleLargeModelDeg).toBeGreaterThan(
        VISUALIZATION_MODES[mode].edgeAngleBalancedDeg,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Adapter behavior (§2.1, §2.3)
// ---------------------------------------------------------------------------

describe("applying a mode to the loaded model (task31 §2.3)", () => {
  it("starts at Standard and hands Standard's pair to the projected-size policy", () => {
    const { adapter } = makeAdapter();
    expect(adapter.getVisualizationMode()).toBe("standard");
    expect(priv(adapter).sizePolicy.getThresholds()).toEqual({ enterPx: 32, exitPx: 38 });
  });

  it("swaps the projected-size pair and refreshes Fragments once", async () => {
    const { adapter, update } = makeAdapter();
    update.mockClear();
    await adapter.setVisualizationMode("fast");
    expect(adapter.getVisualizationMode()).toBe("fast");
    expect(priv(adapter).sizePolicy.getThresholds()).toEqual({ enterPx: 48, exitPx: 58 });
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("is a no-op when the same mode is re-selected", async () => {
    const { adapter, update } = makeAdapter();
    update.mockClear();
    await adapter.setVisualizationMode("standard");
    expect(update).not.toHaveBeenCalled();
  });

  it("never reloads or reconverts the model", async () => {
    const { adapter, model } = makeAdapter();
    const loadSpy = vi.spyOn(model, "getLocalIds");
    await adapter.setVisualizationMode("fine");
    expect(loadSpy).not.toHaveBeenCalled();
  });

  it("leaves camera pose, plan state and query identities untouched", async () => {
    const { adapter, camera } = makeAdapter();
    await adapter.applyQueryRoles([], []);
    const pose = camera.position.toArray();
    const planBefore = adapter.getPlanBandIndex();
    await adapter.setVisualizationMode("fast");
    expect(camera.position.toArray()).toEqual(pose);
    expect(adapter.getPlanBandIndex()).toBe(planBefore);
    expect(adapter.getSavedPose()).toBeNull();
  });

  it("survives a model switch — only Reset App returns it to Standard", async () => {
    const { adapter } = makeAdapter();
    await adapter.setVisualizationMode("fine");
    await adapter.unloadModel();
    expect(adapter.getVisualizationMode()).toBe("fine");
    expect(priv(adapter).sizePolicy.getThresholds()).toEqual({ enterPx: 20, exitPx: 24 });
  });
});

describe("edge-overlay regeneration (task31 §2.3)", () => {
  /** Mount a real, built overlay at the given angle. */
  async function withOverlay(mode: VisualizationMode) {
    const { adapter, modelObject, model } = makeAdapter();
    priv(adapter).visualizationMode = mode;
    const overlay = new EdgeOverlay();
    priv(adapter).edgeOverlay = overlay;
    await overlay.build(model as never, modelObject, {
      thresholdDeg: VISUALIZATION_MODES[mode].edgeAngleBalancedDeg,
      localIds: [1, 2],
    });
    return { adapter, modelObject, overlay };
  }

  it("regenerates at the selected mode's angle when the angle changes", async () => {
    const { adapter } = await withOverlay("standard");
    expect(adapter.getEdgeThresholdDeg()).toBe(40);
    await adapter.setVisualizationMode("fast");
    await settle();
    expect(adapter.getEdgeThresholdDeg()).toBe(55);
  });

  it("uses the large-model angle of the SELECTED mode when the model is large", async () => {
    const { adapter } = await withOverlay("standard");
    priv(adapter).lastDetectedProfile = "large-model";
    await adapter.setVisualizationMode("fine");
    await settle();
    // Fine's large-model angle (40), not its balanced one (25): the detected
    // signal chooses the angle WITHIN the mode, never the mode.
    expect(adapter.getEdgeThresholdDeg()).toBe(40);
  });

  it("leaves exactly one overlay mounted, with the old one disposed", async () => {
    const { adapter, modelObject, overlay } = await withOverlay("standard");
    const before = modelObject.children.length;
    expect(before).toBeGreaterThan(0);
    await adapter.setVisualizationMode("fine");
    await settle();
    // The superseded overlay released its chunks rather than leaving them in
    // the scene beside the new ones.
    expect(overlay.isBuilt()).toBe(false);
    expect(modelObject.children.length).toBe(before);
    expect(adapter.hasEdgeOverlay()).toBe(true);
  });

  it("discards a rebuild superseded by another mode change", async () => {
    const { adapter, modelObject } = await withOverlay("fine");
    await adapter.setVisualizationMode("standard");
    await adapter.setVisualizationMode("fast");
    await settle();
    expect(adapter.getEdgeThresholdDeg()).toBe(55); // the LAST request wins
    expect(modelObject.children.length).toBeGreaterThan(0);
  });

  it("discards a rebuild superseded by a model unload", async () => {
    const { adapter, modelObject } = await withOverlay("fine");
    void adapter.setVisualizationMode("fast");
    await adapter.unloadModel();
    await settle();
    expect(adapter.hasEdgeOverlay()).toBe(false);
    expect(modelObject.children).toHaveLength(0);
  });

  it("does not rebuild when no overlay exists yet", async () => {
    const { adapter, modelObject } = makeAdapter();
    await adapter.setVisualizationMode("fast");
    await settle();
    expect(modelObject.children).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Store + controller boundary (§2.1)
// ---------------------------------------------------------------------------

describe("mode state lives in the typed store (task31 §2.1)", () => {
  beforeEach(() => {
    useStore.setState({ visualizationMode: DEFAULT_VISUALIZATION_MODE });
  });

  it("initializes to Standard", () => {
    expect(useStore.getState().visualizationMode).toBe("standard");
  });

  it("is not written to session or local storage", () => {
    const session = vi.spyOn(Storage.prototype, "setItem");
    useStore.getState().setVisualizationMode("fast");
    expect(useStore.getState().visualizationMode).toBe("fast");
    expect(session).not.toHaveBeenCalled();
    session.mockRestore();
  });
});
