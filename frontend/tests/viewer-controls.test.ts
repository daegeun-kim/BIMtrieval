// Camera, controls, pivot, zoom bound, elevation-zero plane, and base-color
// restoration (tasks/task14.md §1, §2, §8).
//
// A fake FragmentsModel/world is injected — no WebGL, no worker.
import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import { ViewerAdapter } from "../src/viewer/ViewerAdapter";
import { BASE_MATERIALS, DIM_MATERIAL, PRIMARY_MATERIAL, VIEWER_CAMERA } from "../src/viewer/viewerTheme";

const ACTION = { NONE: 0, ROTATE: 1, TRUCK: 2, DOLLY: 16 };

interface Harness {
  adapter: ViewerAdapter;
  controls: {
    mouseButtons: { left: number; middle: number; right: number; wheel: number };
    maxDistance: number;
    setOrbitPoint: ReturnType<typeof vi.fn>;
    fitToBox: ReturnType<typeof vi.fn>;
  };
  highlight: ReturnType<typeof vi.fn>;
  scene: THREE.Scene;
}

function makeAdapter(opts?: {
  box?: THREE.Box3;
  raycastPoint?: THREE.Vector3 | null;
  coordination?: THREE.Matrix4;
  categories?: string[];
}): Harness {
  const adapter = new ViewerAdapter(5);
  const box =
    opts?.box ?? new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(30, 12, 40));
  const known: Record<string, number> = { "G-A": 101, "G-B": 102 };

  const highlight = vi.fn(async () => {});
  const model = {
    box,
    getLocalIdsByGuids: async (guids: string[]) => guids.map((g) => known[g] ?? null),
    getGuidsByLocalIds: async (ids: number[]) =>
      ids.map((id) => Object.keys(known).find((k) => known[k] === id) ?? null),
    getMergedBox: async () => box,
    resetHighlight: vi.fn(async () => {}),
    highlight,
    getCategories: async () => opts?.categories ?? ["IFCWALL", "IFCWALLSTANDARDCASE", "IFCROOF"],
    getItemsOfCategories: async () => ({
      IFCWALL: [1, 2],
      IFCWALLSTANDARDCASE: [3],
      IFCROOF: [4],
    }),
    getItemsData: async () => [],
    getCoordinationMatrix: async () => opts?.coordination ?? new THREE.Matrix4(),
    raycast: async () =>
      opts?.raycastPoint === null ? null : { localId: 101, point: opts?.raycastPoint ?? new THREE.Vector3(5, 1, 5) },
  };

  const controls = {
    mouseButtons: { left: ACTION.ROTATE, middle: ACTION.DOLLY, right: ACTION.TRUCK, wheel: ACTION.DOLLY },
    maxDistance: Infinity,
    setOrbitPoint: vi.fn(),
    fitToBox: vi.fn(async () => {}),
  };
  const camera = new THREE.PerspectiveCamera(75, 1.5, 0.1, 1000);
  const scene = new THREE.Scene();

  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world: {
      camera: { controls, three: camera, updateAspect: () => {} },
      scene: { three: scene },
      renderer: { three: { domElement: makeCanvas() } },
    },
    fragments: { core: { update: async () => {} } },
  });
  return { adapter, controls, highlight, scene };
}

function makeCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 }) as DOMRect;
  return c;
}

/** The adapter internals under test, reached without loosening its public API. */
interface AdapterInternals {
  configureControls(): void;
  applyLens(): void;
  applyZoomBound(box: THREE.Box3 | null): void;
  setPivotFromCursor(event: PointerEvent): Promise<void>;
  resolveGroundY(): Promise<void>;
  createBasePlane(): void;
  classifyGeometry(): Promise<{ roof: number[]; wall: number[] }>;
}

function priv(adapter: ViewerAdapter): AdapterInternals {
  return adapter as unknown as AdapterInternals;
}

describe("desktop control mapping (task14 §2)", () => {
  it("maps left to pan, middle to orbit, wheel to zoom", () => {
    const { adapter, controls } = makeAdapter();
    priv(adapter).configureControls();
    expect(controls.mouseButtons.left).toBe(ACTION.TRUCK); // pan, not rotate
    expect(controls.mouseButtons.middle).toBe(ACTION.ROTATE);
    expect(controls.mouseButtons.wheel).toBe(ACTION.DOLLY);
  });
});

describe("50 mm full-frame lens (task14 §2)", () => {
  it("sets the camera from focal length + film gauge rather than a fixed FOV", () => {
    const { adapter } = makeAdapter();
    priv(adapter).applyLens();
    expect(adapter.getFieldOfView()).toBeCloseTo(26.99, 1);
  });

  it("keeps the 50 mm equivalence across a resize", () => {
    const { adapter } = makeAdapter();
    adapter.resize();
    expect(adapter.getFieldOfView()).toBeCloseTo(26.99, 1);
  });
});

describe("zoom-out bound (task14 §2)", () => {
  it("bounds max distance at ~3x the model bbox diagonal", () => {
    const { adapter, controls } = makeAdapter();
    const box = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(30, 12, 40));
    priv(adapter).applyZoomBound(box);
    const diagonal = new THREE.Vector3(30, 12, 40).length(); // ~51.2
    expect(controls.maxDistance).toBeCloseTo(diagonal * 3, 3);
    expect(Number.isFinite(controls.maxDistance)).toBe(true);
  });

  it("applies a safe minimum for tiny/test models", () => {
    const { adapter, controls } = makeAdapter();
    priv(adapter).applyZoomBound(
      new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0.2, 0.2, 0.2)),
    );
    expect(controls.maxDistance).toBe(VIEWER_CAMERA.minMaxDistance);
  });

  it("does not restrict zoom when the model has no box", () => {
    const { adapter, controls } = makeAdapter();
    priv(adapter).applyZoomBound(null);
    expect(controls.maxDistance).toBe(Infinity);
  });
});

describe("rotation pivot (task14 §2)", () => {
  const event = { clientX: 400, clientY: 300 } as PointerEvent;

  it("pivots on the geometry under the cursor", async () => {
    const { adapter, controls } = makeAdapter({ raycastPoint: new THREE.Vector3(7, 2, 9) });
    await priv(adapter).setPivotFromCursor(event);
    expect(controls.setOrbitPoint).toHaveBeenCalledWith(7, 2, 9);
  });

  it("falls back to the elevation-zero plane when no geometry is hit", async () => {
    const { adapter, controls } = makeAdapter({ raycastPoint: null });
    // Camera above the ground, looking down: the ray must meet y = groundY.
    const world = (adapter as unknown as { world: { camera: { three: THREE.PerspectiveCamera } } }).world;
    world.camera.three.position.set(0, 40, 0);
    world.camera.three.lookAt(0, 0, 0);
    world.camera.three.updateMatrixWorld(true);

    await priv(adapter).setPivotFromCursor(event);
    expect(controls.setOrbitPoint).toHaveBeenCalled();
    const [, y] = controls.setOrbitPoint.mock.calls[0]!;
    expect(y).toBeCloseTo(0, 5);
  });

  it("retains the current target when neither geometry nor the plane is valid", async () => {
    const { adapter, controls } = makeAdapter({ raycastPoint: null });
    // Camera below the plane looking further down never meets y=0 going forward.
    const world = (adapter as unknown as { world: { camera: { three: THREE.PerspectiveCamera } } }).world;
    world.camera.three.position.set(0, -10, 0);
    world.camera.three.lookAt(0, -50, 0);
    world.camera.three.updateMatrixWorld(true);

    await priv(adapter).setPivotFromCursor(event);
    expect(controls.setOrbitPoint).not.toHaveBeenCalled();
  });

  it("does not change manual selection to establish a pivot", async () => {
    const { adapter } = makeAdapter({ raycastPoint: new THREE.Vector3(1, 1, 1) });
    const before = adapter as unknown as { manual: Map<string, number> };
    await priv(adapter).setPivotFromCursor(event);
    expect(before.manual.size).toBe(0);
  });
});

describe("elevation-zero base plane (task14 §2)", () => {
  it("derives ground from the coordination matrix, not the bounding box", async () => {
    // Model shifted down 8m in the scene: IFC elevation 0 is scene y = -8.
    const coordination = new THREE.Matrix4().makeTranslation(0, -8, 0);
    const { adapter } = makeAdapter({ coordination });
    await priv(adapter).resolveGroundY();
    expect(adapter.getGroundY()).toBeCloseTo(-8, 5);
  });

  it("places the plane at elevation zero, not the bbox centre or minimum", async () => {
    // A model whose geometry sits well above zero must NOT drag the plane up.
    const box = new THREE.Box3(new THREE.Vector3(0, 20, 0), new THREE.Vector3(30, 40, 40));
    const { adapter, scene } = makeAdapter({ box });
    await priv(adapter).resolveGroundY();
    priv(adapter).createBasePlane();

    expect(adapter.hasBasePlane()).toBe(true);
    const grid = scene.children.find((c) => c.type === "GridHelper");
    expect(grid).toBeDefined();
    expect(grid!.position.y).toBe(0); // not 20 (min), not 30 (centre)
  });

  it("keeps the plane non-occluding so below-zero geometry stays visible", async () => {
    const { adapter, scene } = makeAdapter();
    await priv(adapter).resolveGroundY();
    priv(adapter).createBasePlane();
    const grid = scene.children.find((c) => c.type === "GridHelper") as THREE.GridHelper;
    const mat = grid.material as THREE.Material;
    expect(mat.transparent).toBe(true);
    expect(mat.depthWrite).toBe(false);
  });

  it("removes the plane on unload", async () => {
    const { adapter } = makeAdapter();
    priv(adapter).createBasePlane();
    expect(adapter.hasBasePlane()).toBe(true);
    await adapter.unloadModel();
    expect(adapter.hasBasePlane()).toBe(false);
  });
});

describe("semantic base colors (task14 §1)", () => {
  it("classifies wall subtypes and roofs from the artifact's categories", async () => {
    const { adapter } = makeAdapter();
    const classification = await priv(adapter).classifyGeometry();
    expect(classification.wall.sort()).toEqual([1, 2, 3]); // incl. IfcWallStandardCase
    expect(classification.roof).toEqual([4]);
  });

  it("restores roof/wall/other base colors after query highlights clear", async () => {
    const { adapter, highlight } = makeAdapter();
    Object.assign(adapter as unknown as Record<string, unknown>, {
      classification: { roof: [4], wall: [1, 2, 3] },
    });

    await adapter.applyQueryRoles(["G-A"], []);
    highlight.mockClear();
    await adapter.clearQueryRoles();

    const materials = highlight.mock.calls.map((c) => c[1]);
    // Not one uniform material: all three semantic base roles are re-applied.
    expect(materials).toContain(BASE_MATERIALS.other);
    expect(materials).toContain(BASE_MATERIALS.wall);
    expect(materials).toContain(BASE_MATERIALS.roof);
    expect(materials).not.toContain(DIM_MATERIAL);
  });

  it("dims non-results while query roles are active", async () => {
    const { adapter, highlight } = makeAdapter();
    highlight.mockClear();
    await adapter.applyQueryRoles(["G-A"], []);
    const materials = highlight.mock.calls.map((c) => c[1]);
    expect(materials).toContain(DIM_MATERIAL);
    expect(materials).toContain(PRIMARY_MATERIAL);
    // Base colors are replaced by the dim pass while highlighting.
    expect(materials).not.toContain(BASE_MATERIALS.wall);
  });
});
