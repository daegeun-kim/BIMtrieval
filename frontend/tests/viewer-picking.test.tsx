// Query-result-only picking, focused/unfocused primary appearance, edge roles,
// and the doubled preview height (tasks/task15.md §2–§4, §Tests).
//
// A fake FragmentsModel/world is injected — no WebGL, no worker.
import { render, screen } from "@testing-library/react";
import * as THREE from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ComponentPreview from "../src/components/ComponentPreview";
import { ViewerAdapter } from "../src/viewer/ViewerAdapter";
import { EdgeOverlay } from "../src/viewer/EdgeOverlay";
import {
  DIM_MATERIAL,
  EDGES,
  MANUAL_MATERIAL,
  PREVIEW,
  PRIMARY_MATERIAL,
  PRIMARY_UNFOCUSED_MATERIAL,
  VIEWER_COLORS,
  VIEWER_OPACITY,
} from "../src/viewer/viewerTheme";

vi.mock("../src/state/controller", () => ({
  controller: { viewer: { extractItemGeometry: vi.fn(async () => null) } },
}));

// GUID -> localId: A/B/C are primary results, X is context, Z is dimmed.
const KNOWN: Record<string, number> = { "G-A": 1, "G-B": 2, "G-C": 3, "G-X": 8, "G-Z": 9 };

function makeAdapter() {
  const adapter = new ViewerAdapter(5);
  const highlight = vi.fn(async (_ids: number[] | undefined, _mat: unknown) => {});
  let nextPick: number | null = null;

  const model = {
    box: new THREE.Box3(new THREE.Vector3(), new THREE.Vector3(10, 10, 10)),
    getLocalIdsByGuids: async (guids: string[]) => guids.map((g) => KNOWN[g] ?? null),
    getGuidsByLocalIds: async (ids: number[]) =>
      ids.map((id) => Object.keys(KNOWN).find((k) => KNOWN[k] === id) ?? null),
    getMergedBox: async () => new THREE.Box3(new THREE.Vector3(), new THREE.Vector3(1, 1, 1)),
    resetHighlight: vi.fn(async () => {}),
    highlight,
    raycast: async () => (nextPick === null ? null : { localId: nextPick, point: new THREE.Vector3() }),
  };
  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world: {
      camera: {
        controls: { fitToBox: vi.fn(async () => {}), setOrbitPoint: vi.fn(), mouseButtons: {} },
        three: new THREE.PerspectiveCamera(),
        updateAspect: () => {},
      },
      scene: { three: new THREE.Scene() },
      renderer: { three: { domElement: document.createElement("canvas") } },
    },
    fragments: { core: { update: async () => {} } },
  });

  const manualGuids = () =>
    [...(adapter as unknown as { manual: Map<string, number> }).manual.keys()];
  const pick = async (localId: number | null, additive = false) => {
    nextPick = localId;
    await (
      adapter as unknown as { handlePick: (e: Partial<PointerEvent>) => Promise<void> }
    ).handlePick({ ctrlKey: additive, shiftKey: false, metaKey: false } as PointerEvent);
  };
  return { adapter, highlight, pick, manualGuids };
}

// ---------------------------------------------------------------------------
// Picking without query roles: existing behavior preserved (task15 §3)
// ---------------------------------------------------------------------------

describe("picking with NO active query highlighting", () => {
  it("any entity with a GlobalId may be selected", async () => {
    const { pick, manualGuids } = makeAdapter();
    await pick(KNOWN["G-Z"]!);
    expect(manualGuids()).toEqual(["G-Z"]);
  });

  it("additive selection still works up to the cap of five", async () => {
    const { adapter, pick, manualGuids } = makeAdapter();
    const limit = vi.fn();
    adapter.setCallbacks({ onSelectionLimitReached: limit });
    for (const id of [1, 2, 3, 8, 9]) await pick(id, true);
    expect(manualGuids()).toHaveLength(5);
    await pick(4 as never, true); // unknown id -> no guid -> ignored anyway
    expect(manualGuids()).toHaveLength(5);
  });

  it("manual selection renders teal when no roles are active", async () => {
    const { highlight, pick } = makeAdapter();
    highlight.mockClear();
    await pick(KNOWN["G-Z"]!);
    expect(highlight.mock.calls.map((c) => c[1])).toContain(MANUAL_MATERIAL);
  });
});

// ---------------------------------------------------------------------------
// Picking WITH active query roles: primary-only (task15 §3)
// ---------------------------------------------------------------------------

describe("picking with active query highlighting", () => {
  async function withRoles() {
    const h = makeAdapter();
    await h.adapter.applyQueryRoles(["G-A", "G-B", "G-C"], ["G-X"]);
    return h;
  }

  it("a blue primary result can be picked and focused", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!);
    expect(manualGuids()).toEqual(["G-A"]);
  });

  it("a dimmed non-result cannot be selected and does not replace the selection", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!);
    await pick(KNOWN["G-Z"]!); // dimmed
    expect(manualGuids()).toEqual(["G-A"]); // unchanged, not cleared, not replaced
  });

  it("a context (yellow) entity cannot be selected", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-X"]!);
    expect(manualGuids()).toEqual([]);
  });

  it("a rejected entity never transiently enters the selection", async () => {
    const { adapter, pick } = await withRoles();
    const manual = (adapter as unknown as { manual: Map<string, number> }).manual;
    const setSpy = vi.spyOn(manual, "set");
    const clearSpy = vi.spyOn(manual, "clear");
    await pick(KNOWN["G-Z"]!);
    expect(setSpy).not.toHaveBeenCalled(); // membership was checked FIRST
    expect(clearSpy).not.toHaveBeenCalled();
  });

  it("additive selection is limited to primary results and the cap of five", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!, true);
    await pick(KNOWN["G-X"]!, true); // context — rejected
    await pick(KNOWN["G-B"]!, true);
    expect(manualGuids().sort()).toEqual(["G-A", "G-B"]);
  });

  it("clicking empty space clears the focused selection", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!);
    await pick(null); // raycast miss
    expect(manualGuids()).toEqual([]);
  });

  it("eligibility never calls the backend", async () => {
    // The adapter has no API client at all — eligibility is a Set lookup over
    // the already-resolved primary local ids. This asserts the set exists and
    // is what the guard uses.
    const { adapter } = await withRoles();
    const set = (adapter as unknown as { queryPrimarySet: Set<number> }).queryPrimarySet;
    expect([...set].sort()).toEqual([1, 2, 3]);
  });
});

// ---------------------------------------------------------------------------
// Focused / unfocused primary appearance (task15 §3)
// ---------------------------------------------------------------------------

describe("focused query-result appearance", () => {
  it("focused results stay opaque blue; other primaries become translucent blue", async () => {
    const { adapter, highlight, pick } = makeAdapter();
    await adapter.applyQueryRoles(["G-A", "G-B", "G-C"], ["G-X"]);
    highlight.mockClear();
    await pick(KNOWN["G-A"]!);

    const calls = highlight.mock.calls;
    const materials = calls.map((c) => c[1]);
    expect(materials).toContain(PRIMARY_UNFOCUSED_MATERIAL);
    expect(materials).toContain(PRIMARY_MATERIAL);
    // never teal while roles are active (task15 §3)
    expect(materials).not.toContain(MANUAL_MATERIAL);

    const unfocusedIds = calls.find((c) => c[1] === PRIMARY_UNFOCUSED_MATERIAL)?.[0];
    const focusedIds = calls.find((c) => c[1] === PRIMARY_MATERIAL)?.[0];
    expect((unfocusedIds as number[]).sort()).toEqual([2, 3]);
    expect(focusedIds).toEqual([1]);
  });

  it("context and dimmed roles are unchanged by focusing", async () => {
    const { adapter, highlight, pick } = makeAdapter();
    await adapter.applyQueryRoles(["G-A", "G-B"], ["G-X"]);
    highlight.mockClear();
    await pick(KNOWN["G-A"]!);
    const materials = highlight.mock.calls.map((c) => c[1]);
    expect(materials).toContain(DIM_MATERIAL);
    expect(materials.filter((m) => m === DIM_MATERIAL)).toHaveLength(1);
  });

  it("removing the final focused selection restores all primaries to opaque blue", async () => {
    const { adapter, highlight, pick } = makeAdapter();
    await adapter.applyQueryRoles(["G-A", "G-B", "G-C"], []);
    await pick(KNOWN["G-A"]!);
    highlight.mockClear();
    await pick(null); // empty space clears the focus

    const calls = highlight.mock.calls;
    const primaryCall = calls.find((c) => c[1] === PRIMARY_MATERIAL);
    expect((primaryCall?.[0] as number[]).sort()).toEqual([1, 2, 3]);
    expect(calls.map((c) => c[1])).not.toContain(PRIMARY_UNFOCUSED_MATERIAL);
  });

  it("unfocused blue is the same hue at lower opacity — not teal", () => {
    expect(VIEWER_COLORS.primaryUnfocused).toBe(VIEWER_COLORS.primary);
    expect(VIEWER_OPACITY.primaryUnfocused).toBeLessThan(VIEWER_OPACITY.primary);
    expect(PRIMARY_UNFOCUSED_MATERIAL.transparent).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Edge overlay roles + theme centralization (task15 §2)
// ---------------------------------------------------------------------------

describe("edge overlay", () => {
  it("declares every color/alpha centrally in viewerTheme", () => {
    expect(EDGES.enabled).toBe(true);
    expect(EDGES.darken).toBeGreaterThan(0);
    expect(EDGES.darken).toBeLessThanOrEqual(1);
    for (const role of [
      "roof",
      "wall",
      "other",
      "primary",
      "primaryUnfocused",
      "context",
      "manual",
      "dim",
    ] as const) {
      expect(EDGES.alpha[role]).toBeGreaterThan(0);
    }
  });

  it("edges on transparent faces are more opaque than the face", () => {
    expect(EDGES.alpha.dim).toBeGreaterThan(VIEWER_OPACITY.dim);
    expect(EDGES.alpha.primaryUnfocused).toBeGreaterThan(VIEWER_OPACITY.primaryUnfocused);
    expect(EDGES.alpha.context).toBeGreaterThanOrEqual(VIEWER_OPACITY.context);
  });

  it("edge roles follow the current face role exactly", async () => {
    const { adapter, pick } = makeAdapter();
    // base state: classification decides
    Object.assign(adapter as unknown as Record<string, unknown>, {
      classification: { roof: [9], wall: [8] },
    });
    expect(adapter.edgeRoleOf(9)).toBe("roof");
    expect(adapter.edgeRoleOf(8)).toBe("wall");
    expect(adapter.edgeRoleOf(1)).toBe("other");

    await pick(1); // manual selection, no roles active
    expect(adapter.edgeRoleOf(1)).toBe("manual");
    await pick(null); // clear it — a persisting manual pick of a primary would count as focused

    await adapter.applyQueryRoles(["G-A", "G-B"], ["G-X"]);
    expect(adapter.edgeRoleOf(KNOWN["G-B"]!)).toBe("primary");
    expect(adapter.edgeRoleOf(KNOWN["G-X"]!)).toBe("context");
    expect(adapter.edgeRoleOf(KNOWN["G-Z"]!)).toBe("dim");

    await pick(KNOWN["G-A"]!); // focus one primary
    expect(adapter.edgeRoleOf(KNOWN["G-A"]!)).toBe("primary");
    expect(adapter.edgeRoleOf(KNOWN["G-B"]!)).toBe("primaryUnfocused");

    await adapter.clearQueryRoles();
    expect(adapter.edgeRoleOf(9)).toBe("roof"); // base restored
  });

  it("builds one merged LineSegments and recolors ranges per entity", async () => {
    const overlay = new EdgeOverlay();
    const parent = new THREE.Object3D();
    // Two fake items, one triangle each (unindexed).
    const tri = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    const model = {
      getLocalIds: async () => [1, 2],
      getItemsGeometry: async (ids: number[]) =>
        ids.map(() => [{ positions: tri, indices: undefined, transform: new THREE.Matrix4() }]),
    };
    const built = await overlay.build(model as never, parent);
    expect(built).toBe(true);
    expect(overlay.isBuilt()).toBe(true);
    const lines = parent.children[0] as THREE.LineSegments;
    expect(lines).toBeInstanceOf(THREE.LineSegments);
    expect(parent.children).toHaveLength(1); // ONE merged object, not per-entity

    overlay.recolor((id) => (id === 1 ? "primary" : "dim"));
    const colors = lines.geometry.getAttribute("color") as THREE.BufferAttribute;
    expect(colors.itemSize).toBe(4); // RGBA — per-entity alpha in one draw call
    // entity 1 got the primary alpha, entity 2 the dim alpha
    const half = colors.count / 2;
    expect(colors.getW(0)).toBeCloseTo(EDGES.alpha.primary, 5);
    expect(colors.getW(half)).toBeCloseTo(EDGES.alpha.dim, 5);

    overlay.dispose();
    expect(parent.children).toHaveLength(0);
    expect(overlay.isBuilt()).toBe(false);
  });

  it("a build finishing after dispose mounts nothing (model-switch safety)", async () => {
    const overlay = new EdgeOverlay();
    const parent = new THREE.Object3D();
    const tri = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    const model = {
      getLocalIds: async () => [1],
      getItemsGeometry: async (ids: number[]) => {
        overlay.dispose(); // the model switched away mid-build
        return ids.map(() => [{ positions: tri, transform: new THREE.Matrix4() }]);
      },
    };
    const built = await overlay.build(model as never, parent);
    expect(built).toBe(false);
    expect(parent.children).toHaveLength(0);
  });

  it("a failed build leaves face rendering untouched (clean fallback)", async () => {
    const overlay = new EdgeOverlay();
    const parent = new THREE.Object3D();
    const model = {
      getLocalIds: async () => {
        throw new Error("worker exploded");
      },
      getItemsGeometry: async () => [],
    };
    const built = await overlay.build(model as never, parent);
    expect(built).toBe(false);
    expect(parent.children).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Preview height (task15 §4)
// ---------------------------------------------------------------------------

describe("entity preview height", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is approximately twice the previous 160px, responsive to viewport height", () => {
    expect(PREVIEW.viewportHeightPx).toBe(320);
    render(<ComponentPreview guid="G1" />);
    const host = screen.getByTestId("component-preview");
    expect(host.style.height).toBe("min(320px, 36vh)");
  });
});
