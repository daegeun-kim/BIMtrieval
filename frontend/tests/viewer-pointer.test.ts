// Left-click select vs left-drag pan, and the dual-panel layout math
// (tasks/task14.md §2, §5, §8).
import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import {
  COMPONENT_PANEL_WIDTH,
  PANEL_MAX_WIDTH,
  PANEL_MIN_WIDTH,
  PANEL_PAIRED_MAX_WIDTH,
  PANEL_PAIRED_WIDTH,
  effectivePanelWidth,
} from "../src/state/store";
import { ViewerAdapter } from "../src/viewer/ViewerAdapter";
import { VIEWER_CAMERA } from "../src/viewer/viewerTheme";

function makeAdapter() {
  const adapter = new ViewerAdapter(5);
  const known: Record<string, number> = { "G-A": 101 };
  const model = {
    box: new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(10, 10, 10)),
    getLocalIdsByGuids: async (guids: string[]) => guids.map((g) => known[g] ?? null),
    getGuidsByLocalIds: async () => ["G-A"],
    getMergedBox: async () => new THREE.Box3(),
    resetHighlight: vi.fn(async () => {}),
    highlight: vi.fn(async () => {}),
    raycast: vi.fn(async () => ({ localId: 101, point: new THREE.Vector3(1, 1, 1) })),
    getCoordinationMatrix: async () => new THREE.Matrix4(),
  };
  const canvas = document.createElement("canvas");
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 }) as DOMRect;

  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world: {
      camera: {
        controls: { setOrbitPoint: vi.fn(), fitToBox: vi.fn(async () => {}), mouseButtons: {} },
        three: new THREE.PerspectiveCamera(50, 1.5, 0.1, 1000),
        updateAspect: () => {},
      },
      scene: { three: new THREE.Scene() },
      renderer: { three: { domElement: canvas } },
    },
    fragments: { core: { update: async () => {} } },
  });
  (adapter as unknown as { attachPointer: (el: HTMLElement) => void }).attachPointer(canvas);
  return { adapter, canvas, model };
}

function pointer(type: string, init: Partial<PointerEvent>): PointerEvent {
  return new (window as unknown as { PointerEvent: typeof MouseEvent }).PointerEvent(type, {
    bubbles: true,
    ...init,
  } as MouseEventInit) as PointerEvent;
}

// jsdom lacks PointerEvent; MouseEvent carries every field these handlers read.
if (!("PointerEvent" in window)) {
  (window as unknown as Record<string, unknown>).PointerEvent = MouseEvent;
}

describe("left click selects vs left drag pans (task14 §2)", () => {
  it("selects on a plain left click with no meaningful movement", async () => {
    const { adapter, canvas, model } = makeAdapter();
    canvas.dispatchEvent(pointer("pointerdown", { clientX: 100, clientY: 100, button: 0 }));
    canvas.dispatchEvent(pointer("pointerup", { clientX: 101, clientY: 100, button: 0 }));
    await new Promise((r) => setTimeout(r, 0));
    // raycast is the pick path; a 1px jitter must still count as a click
    expect(model.raycast).toHaveBeenCalled();
    void adapter;
  });

  it("does NOT select when the pointer travelled beyond the threshold (a pan)", async () => {
    const { canvas, model } = makeAdapter();
    const far = VIEWER_CAMERA.clickMoveTolerance + 6;
    canvas.dispatchEvent(pointer("pointerdown", { clientX: 100, clientY: 100, button: 0 }));
    canvas.dispatchEvent(pointer("pointerup", { clientX: 100 + far, clientY: 100, button: 0 }));
    await new Promise((r) => setTimeout(r, 0));
    expect(model.raycast).not.toHaveBeenCalled();
  });

  it("does not select on a middle-button release (that was an orbit)", async () => {
    const { canvas, model } = makeAdapter();
    canvas.dispatchEvent(pointer("pointerdown", { clientX: 100, clientY: 100, button: 1 }));
    await new Promise((r) => setTimeout(r, 0));
    model.raycast.mockClear(); // the pivot raycast is expected on middle-down
    canvas.dispatchEvent(pointer("pointerup", { clientX: 100, clientY: 100, button: 1 }));
    await new Promise((r) => setTimeout(r, 0));
    expect(model.raycast).not.toHaveBeenCalled();
  });

  it("sets a grab cursor at rest and grabbing while dragging", () => {
    const { canvas } = makeAdapter();
    expect(canvas.style.cursor).toBe("grab");
    canvas.dispatchEvent(pointer("pointerdown", { clientX: 10, clientY: 10, button: 0 }));
    expect(canvas.style.cursor).toBe("grabbing");
    canvas.dispatchEvent(pointer("pointerup", { clientX: 10, clientY: 10, button: 0 }));
    expect(canvas.style.cursor).toBe("grab");
  });
});

describe("dual-panel layout defaults (task14 §5)", () => {
  it("leaves the chat width untouched when the component panel is closed", () => {
    expect(effectivePanelWidth(520, false)).toBe(520);
    expect(effectivePanelWidth(320, false)).toBe(320);
  });

  it("narrows a wide chat panel when both panels are visible", () => {
    expect(effectivePanelWidth(PANEL_MAX_WIDTH, true)).toBe(PANEL_PAIRED_WIDTH);
    expect(effectivePanelWidth(PANEL_PAIRED_WIDTH, true)).toBe(PANEL_PAIRED_WIDTH);
  });

  it("never widens a chat panel the user made narrow", () => {
    expect(effectivePanelWidth(PANEL_MIN_WIDTH, true)).toBe(PANEL_MIN_WIDTH);
  });

  it("keeps the model the dominant workspace on a 1440px desktop", () => {
    const margins = 20 * 2 + 12; // outer margins + inter-panel gap
    const used = COMPONENT_PANEL_WIDTH + effectivePanelWidth(PANEL_MAX_WIDTH, true) + margins;
    expect(used).toBeLessThan(1440 * 0.55); // viewer keeps the majority
  });

  it("bounds the paired chat width below the solo maximum", () => {
    expect(PANEL_PAIRED_MAX_WIDTH).toBeLessThan(PANEL_MAX_WIDTH);
    expect(PANEL_PAIRED_WIDTH).toBeLessThanOrEqual(PANEL_PAIRED_MAX_WIDTH);
  });
});
