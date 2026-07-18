// Camera fitting/centering within the unobstructed left region (task19 §2).
//
// A fake FragmentsModel/world is injected — no WebGL, no worker. `camera` is
// a REAL THREE.PerspectiveCamera so `setViewOffset`/`clearViewOffset` run
// their genuine three.js implementation and can be asserted on directly.
import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import {
  COMPONENT_PANEL_WIDTH,
  PANEL_GAP_PX,
  VIEWER_EDGE_MARGIN_PX,
  effectiveViewportObstructionPx,
} from "../src/state/store";
import { ViewerAdapter } from "../src/viewer/ViewerAdapter";

function makeCanvas(width: number, height: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  Object.defineProperty(c, "clientWidth", { value: width, configurable: true });
  Object.defineProperty(c, "clientHeight", { value: height, configurable: true });
  c.getBoundingClientRect = () => ({ left: 0, top: 0, width, height }) as DOMRect;
  return c;
}

function makeAdapter(canvasW = 1400, canvasH = 900) {
  const adapter = new ViewerAdapter(5);
  const box = new THREE.Box3(new THREE.Vector3(-5, 0, -5), new THREE.Vector3(5, 10, 5));
  const model = {
    box,
    getMergedBox: async () => box,
    getLocalIdsByGuids: async () => [],
    getGuidsByLocalIds: async () => [],
    resetHighlight: vi.fn(async () => {}),
    highlight: vi.fn(async () => {}),
  };
  const camera = new THREE.PerspectiveCamera(26.99, canvasW / canvasH, 0.1, 10000);
  const controls = {
    fitToBox: vi.fn(async () => {}),
    setOrbitPoint: vi.fn(),
    maxDistance: Infinity,
    mouseButtons: {},
  };
  const canvas = makeCanvas(canvasW, canvasH);
  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world: {
      camera: { controls, three: camera, updateAspect: () => {} },
      scene: { three: new THREE.Scene() },
      renderer: { three: { domElement: canvas } },
    },
    fragments: { core: { update: async () => {} } },
  });
  return { adapter, camera, controls, canvas };
}

describe("effective visible-viewport centering (task19 §2)", () => {
  it("uses the full canvas center with no obstructing panels", async () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    await adapter.fitAll();
    expect(camera.view === null || camera.view.enabled === false).toBe(true);
  });

  it("narrows the fit region to the space left of a chat-only panel", async () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    adapter.setViewportObstruction(400); // 20 margin + 380 chat width
    await adapter.fitAll();
    expect(camera.view).not.toBeNull();
    expect(camera.view!.enabled).toBe(true);
    expect(camera.view!.fullWidth).toBeCloseTo(1000, 5); // 1400 - 400
    expect(camera.view!.offsetX).toBe(0);
    expect(camera.view!.width).toBe(1400); // the full, unshrunk render target
    expect(camera.view!.height).toBe(900);
    expect(camera.aspect).toBeCloseTo(1000 / 900, 5);
  });

  it("chat plus the component panel shifts the effective center farther left", async () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    adapter.setViewportObstruction(732); // 20*2 margins + 360 paired chat + 12 gap + 320 component
    await adapter.fitAll();
    expect(camera.view!.fullWidth).toBeCloseTo(1400 - 732, 5); // narrower than chat-only
  });

  it("closing the component panel restores the chat-only region without a refit call", () => {
    const { adapter, camera, controls } = makeAdapter(1400, 900);
    adapter.setViewportObstruction(732);
    controls.fitToBox.mockClear();
    adapter.setViewportObstruction(400);
    expect(camera.view!.fullWidth).toBeCloseTo(1000, 5);
    expect(controls.fitToBox).not.toHaveBeenCalled(); // no camera reset/refit
  });

  it("collapsing/resizing the chat panel uses whatever live width it is called with", () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    adapter.setViewportObstruction(400);
    expect(camera.view!.fullWidth).toBeCloseTo(1000, 5);
    adapter.setViewportObstruction(60); // e.g. collapsed to the 40px restore tab + margin
    expect(camera.view!.fullWidth).toBeCloseTo(1340, 5);
  });

  it("does not move or reset the camera position when only the obstruction changes", () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    camera.position.set(3, 4, 5);
    adapter.setViewportObstruction(200);
    adapter.setViewportObstruction(500);
    expect(camera.position.toArray()).toEqual([3, 4, 5]);
  });

  it("preserves the configured vertical FOV regardless of the obstruction", () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    const before = camera.fov;
    adapter.setViewportObstruction(600);
    expect(camera.fov).toBeCloseTo(before, 6);
  });

  it("clamps to a safe minimum region instead of collapsing toward zero width", async () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    adapter.setViewportObstruction(1390); // absurd — most of the canvas
    await adapter.fitAll();
    expect(camera.view!.fullWidth).toBeGreaterThan(1400 * 0.3);
  });

  it("citation/result/component fits share the same viewport logic as fitAll", async () => {
    const { adapter, camera } = makeAdapter(1400, 900);
    const model = (adapter as unknown as { model: Record<string, unknown> }).model;
    model.getLocalIdsByGuids = async () => [1];
    model.getMergedBox = async () => new THREE.Box3(new THREE.Vector3(-1, 0, -1), new THREE.Vector3(1, 2, 1));
    adapter.setViewportObstruction(400);
    await adapter.fitToGuids(["G-A"]);
    expect(camera.view!.fullWidth).toBeCloseTo(1000, 5);
  });

  it("resize() re-applies the offset from the fresh canvas size without changing the obstruction", () => {
    const { adapter, camera, canvas } = makeAdapter(1400, 900);
    adapter.setViewportObstruction(400);
    expect(camera.view!.fullWidth).toBeCloseTo(1000, 5);
    Object.defineProperty(canvas, "clientWidth", { value: 1800, configurable: true });
    adapter.resize();
    expect(camera.view!.fullWidth).toBeCloseTo(1400, 5); // 1800 - 400
    expect(camera.view!.width).toBe(1800);
  });
});

describe("effectiveViewportObstructionPx (task19 §2)", () => {
  it("is just the margin plus chat width with no component panel", () => {
    expect(effectiveViewportObstructionPx(380, false)).toBe(VIEWER_EDGE_MARGIN_PX + 380);
  });

  it("adds the component panel width and inter-panel gap when it is open", () => {
    expect(effectiveViewportObstructionPx(360, true)).toBe(
      VIEWER_EDGE_MARGIN_PX + 360 + PANEL_GAP_PX + COMPONENT_PANEL_WIDTH,
    );
  });

  it("uses the actual collapsed-tab width when the chat panel is collapsed", () => {
    // App.tsx passes the 40px restore-tab width as chatWidthPx while collapsed.
    expect(effectiveViewportObstructionPx(40, false)).toBe(VIEWER_EDGE_MARGIN_PX + 40);
  });

  it("never goes negative for a degenerate width", () => {
    expect(effectiveViewportObstructionPx(-10, false)).toBe(VIEWER_EDGE_MARGIN_PX);
  });
});
