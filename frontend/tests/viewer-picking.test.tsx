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

/** One simulated ray intersection: a local ID at a given distance along the ray. */
interface Hit {
  localId: number;
  distance: number;
}

function makeAdapter() {
  const adapter = new ViewerAdapter(5);
  const highlight = vi.fn(async (_ids: number[] | undefined, _mat: unknown) => {});
  let nextHits: Hit[] | null = null;

  const model = {
    box: new THREE.Box3(new THREE.Vector3(), new THREE.Vector3(10, 10, 10)),
    getLocalIdsByGuids: async (guids: string[]) => guids.map((g) => KNOWN[g] ?? null),
    getGuidsByLocalIds: async (ids: number[]) =>
      ids.map((id) => Object.keys(KNOWN).find((k) => KNOWN[k] === id) ?? null),
    getMergedBox: async () => new THREE.Box3(new THREE.Vector3(), new THREE.Vector3(1, 1, 1)),
    resetHighlight: vi.fn(async () => {}),
    highlight,
    // Single-nearest-hit raycast, used when no query roles are active.
    raycast: async () =>
      nextHits && nextHits.length
        ? { localId: nextHits[0]!.localId, distance: nextHits[0]!.distance, point: new THREE.Vector3() }
        : null,
    // Every ordered ray intersection, used to pick through transparent
    // non-results while blue query-primary results are active (task19 §1).
    raycastAll: async () =>
      nextHits && nextHits.length
        ? nextHits.map((h) => ({ localId: h.localId, distance: h.distance, point: new THREE.Vector3() }))
        : null,
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
  // Accepts a single local ID (one hit), an ordered list of hits (nearest
  // first unless distances say otherwise), or null (a total miss).
  const pick = async (spec: number | Hit[] | null, additive = false) => {
    nextHits =
      spec === null
        ? null
        : typeof spec === "number"
          ? [{ localId: spec, distance: 1 }]
          : spec;
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

  it("manual selection renders blue when no roles are active", async () => {
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

  // task19 §1: dimmed/transparent geometry no longer blocks or "rejects" a
  // click — it is transparent to picking. A ray that meets only non-result
  // geometry behaves exactly like a total miss (clears on a plain click),
  // not like a no-op that preserves the current selection.
  it("a ray meeting only a dimmed non-result clears the selection like an empty-space click", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!);
    await pick(KNOWN["G-Z"]!); // dimmed, nothing blue behind it
    expect(manualGuids()).toEqual([]);
  });

  it("an ignored context entity remains dim and cannot be selected", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-X"]!);
    expect(manualGuids()).toEqual([]);
  });

  it("a transparent non-result in front of a blue primary does not block selection", async () => {
    const { pick, manualGuids } = await withRoles();
    // G-Z (dimmed) is nearer the camera; the blue primary G-A sits behind it
    // on the same ray. The dimmed hit must not occlude the pick.
    await pick([
      { localId: KNOWN["G-Z"]!, distance: 1 },
      { localId: KNOWN["G-A"]!, distance: 5 },
    ]);
    expect(manualGuids()).toEqual(["G-A"]);
  });

  it("selects the nearest of several blue primaries intersected by the ray", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick([
      { localId: KNOWN["G-C"]!, distance: 8 },
      { localId: KNOWN["G-A"]!, distance: 2 }, // nearest
      { localId: KNOWN["G-B"]!, distance: 5 },
    ]);
    expect(manualGuids()).toEqual(["G-A"]);
  });

  it("a ray with no blue hit at all preserves the empty-space-click behavior", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!);
    await pick([
      { localId: KNOWN["G-Z"]!, distance: 1 },
      { localId: KNOWN["G-X"]!, distance: 3 },
    ]); // dimmed + context only — no blue result anywhere on the ray
    expect(manualGuids()).toEqual([]);
  });

  it("both a focused and an unfocused blue primary remain eligible for picking", async () => {
    const { pick, manualGuids } = await withRoles();
    await pick(KNOWN["G-A"]!); // focus A
    await pick(KNOWN["G-B"]!, true); // additively pick unfocused B — still eligible
    expect(manualGuids().sort()).toEqual(["G-A", "G-B"]);
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
    // dim is the one deliberate exception (task18 §9 candidate 3 — non-result
    // edges disabled to reduce visual line density); every other role keeps a
    // positive edge alpha.
    for (const role of [
      "roof",
      "wall",
      "other",
      "primary",
      "primaryUnfocused",
      "context",
      "manual",
    ] as const) {
      expect(EDGES.alpha[role]).toBeGreaterThan(0);
    }
    expect(EDGES.alpha.dim).toBe(0);
  });

  it("edges on transparent faces are more opaque than the face (except dim, disabled by task18 §9)", () => {
    expect(EDGES.alpha.dim).toBe(0);
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
    expect(adapter.edgeRoleOf(KNOWN["G-X"]!)).toBe("dim");
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

  it("spatially separates distant entities into different frustum-culled chunks (task18 §7)", async () => {
    const overlay = new EdgeOverlay();
    const parent = new THREE.Object3D();
    const near = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    const far = new Float32Array([100, 100, 100, 101, 100, 100, 100, 101, 100]);
    const model = {
      box: new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(100, 100, 100)),
      getLocalIds: async () => [1, 2],
      getItemsGeometry: async (ids: number[]) =>
        ids.map((id) => [
          { positions: id === 1 ? near : far, indices: undefined, transform: new THREE.Matrix4() },
        ]),
    };
    const built = await overlay.build(model as never, parent);
    expect(built).toBe(true);
    expect(overlay.getChunkCount()).toBeGreaterThan(1); // never one whole-model object
    expect(overlay.getChunkCount()).toBeLessThanOrEqual(160); // within the accepted bound
    expect(parent.children).toHaveLength(overlay.getChunkCount());
    for (const child of parent.children) {
      const lines = child as THREE.LineSegments;
      expect(lines.frustumCulled).toBe(true); // opposite of the old whole-model object
      expect(lines.geometry.boundingSphere).not.toBeNull();
      expect(lines.geometry.boundingBox).not.toBeNull();
    }

    // Recoloring one entity only touches its own chunk's color buffer.
    overlay.recolor((id) => (id === 1 ? "primary" : "dim"));
    const nearChunk = parent.children.find(
      (c) => (c as THREE.LineSegments).geometry.getAttribute("color").getW(0) > 0,
    ) as THREE.LineSegments;
    expect(nearChunk).toBeDefined();
    const colors = nearChunk.geometry.getAttribute("color") as THREE.BufferAttribute;
    expect(colors.getW(0)).toBeCloseTo(EDGES.alpha.primary, 5);

    overlay.dispose();
    expect(parent.children).toHaveLength(0);
    expect(overlay.getChunkCount()).toBe(0);
  });

  it("updateLod culls a far/small chunk while a highlighted chunk of the same size stays visible (task18 §8)", async () => {
    const tri = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]); // bounding-sphere radius ≈0.707, center (0.5,0.5,0)
    const buildOne = async (role: "primary" | "dim") => {
      const overlay = new EdgeOverlay();
      const parent = new THREE.Object3D();
      const model = {
        getLocalIds: async () => [1],
        getItemsGeometry: async () => [[{ positions: tri, indices: undefined, transform: new THREE.Matrix4() }]],
      };
      await overlay.build(model as never, parent);
      overlay.recolor(() => role);
      return overlay;
    };

    const baseOverlay = await buildOne("dim");
    const highlightedOverlay = await buildOne("primary");

    // At distance=400 with a 50° / 900px viewport, projectedPx ≈1.7px: below
    // the base farEnterPx (2px, so it culls) but above the highlighted
    // highlightFarEnterPx (0.75px, so it stays visible) — a real, computed
    // behavioral difference driven by highlightCount, not a mocked threshold.
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 10000);
    camera.position.set(0.5, 0.5, -400);
    camera.lookAt(0.5, 0.5, 0);
    camera.updateMatrixWorld(true);

    baseOverlay.updateLod(camera, 900);
    highlightedOverlay.updateLod(camera, 900);

    expect((baseOverlay as unknown as { chunks: { lines: THREE.LineSegments }[] }).chunks[0]!.lines.visible).toBe(
      false,
    );
    expect(
      (highlightedOverlay as unknown as { chunks: { lines: THREE.LineSegments }[] }).chunks[0]!.lines.visible,
    ).toBe(true);

    // Far enough away, even the highlighted chunk culls.
    camera.position.set(0.5, 0.5, -5000);
    camera.updateMatrixWorld(true);
    highlightedOverlay.updateLod(camera, 900);
    expect(
      (highlightedOverlay as unknown as { chunks: { lines: THREE.LineSegments }[] }).chunks[0]!.lines.visible,
    ).toBe(false);

    // Hysteresis: moving back closer to distance=700 (projectedPx≈0.975) is
    // ABOVE the highlighted enter threshold (0.75px, so a never-culled chunk
    // would stay visible there) but still BELOW its exit threshold (1.5px),
    // so an ALREADY-culled chunk must not restore yet — it needs to cross the
    // farther exit threshold, not just clear the enter one again.
    camera.position.set(0.5, 0.5, -700);
    camera.updateMatrixWorld(true);
    highlightedOverlay.updateLod(camera, 900);
    expect(
      (highlightedOverlay as unknown as { chunks: { lines: THREE.LineSegments }[] }).chunks[0]!.lines.visible,
    ).toBe(false); // still culled — hysteresis band, not restored yet

    // Close enough to clear the exit threshold: restored.
    camera.position.set(0.5, 0.5, -100);
    camera.updateMatrixWorld(true);
    highlightedOverlay.updateLod(camera, 900);
    expect(
      (highlightedOverlay as unknown as { chunks: { lines: THREE.LineSegments }[] }).chunks[0]!.lines.visible,
    ).toBe(true);

    baseOverlay.dispose();
    highlightedOverlay.dispose();
  });

  it("accepts precomputed localIds (task18 §6/§11) without calling getLocalIds again", async () => {
    const overlay = new EdgeOverlay();
    const parent = new THREE.Object3D();
    const tri = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    const getLocalIds = vi.fn(async () => [99]); // would be wrong on purpose if called
    const model = {
      getLocalIds,
      getItemsGeometry: async (ids: number[]) =>
        ids.map(() => [{ positions: tri, indices: undefined, transform: new THREE.Matrix4() }]),
    };
    const built = await overlay.build(model as never, parent, { localIds: [1, 2, 3] });
    expect(built).toBe(true);
    expect(getLocalIds).not.toHaveBeenCalled();
    expect(overlay.getItemCount()).toBe(3);
  });

  it("uses the profile-specific angle threshold passed via options (task18 §6)", async () => {
    // Two triangles sharing the edge (0,0,0)-(1,0,0), folded at an exact 90°
    // dihedral angle (one lies in the XY plane, the other in the XZ plane).
    // A threshold at or below 90° keeps that shared edge (5 total edges: the
    // shared one plus 2 boundary edges per triangle); a threshold above 90°
    // drops it (4 boundary edges only) — a real, deterministic behavioral
    // difference driven purely by the `thresholdDeg` option.
    // prettier-ignore
    const folded = new Float32Array([
      0, 0, 0,  1, 0, 0,  0, 1, 0, // triangle A — XY plane
      1, 0, 0,  0, 0, 0,  0, 0, 1, // triangle B — XZ plane, shared edge reversed for consistent winding
    ]);
    const buildWith = async (thresholdDeg: number) => {
      const overlay = new EdgeOverlay();
      const parent = new THREE.Object3D();
      const model = {
        getLocalIds: async () => [1],
        getItemsGeometry: async () => [[{ positions: folded, indices: undefined, transform: new THREE.Matrix4() }]],
      };
      await overlay.build(model as never, parent, { thresholdDeg });
      return overlay.getVertexCount();
    };
    expect(await buildWith(45)).toBe(10); // shared 90° edge included: 5 edges x 2 verts
    expect(await buildWith(135)).toBe(8); // shared 90° edge excluded: 4 boundary edges x 2 verts
  });

  it("hides base edges on motion start, keeps primary/manual visible, restores after the delay (task18 §5)", async () => {
    vi.useFakeTimers();
    try {
      const overlay = new EdgeOverlay();
      const parent = new THREE.Object3D();
      const tri = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
      const model = {
        getLocalIds: async () => [1, 2],
        getItemsGeometry: async (ids: number[]) =>
          ids.map(() => [{ positions: tri, indices: undefined, transform: new THREE.Matrix4() }]),
      };
      await overlay.build(model as never, parent);
      // entity 1 is the query-primary, entity 2 is a dim base entity
      overlay.recolor((id) => (id === 1 ? "primary" : "dim"));
      const colors = (parent.children[0] as THREE.LineSegments).geometry.getAttribute(
        "color",
      ) as THREE.BufferAttribute;
      const half = colors.count / 2;
      expect(colors.getW(0)).toBeCloseTo(EDGES.alpha.primary, 5);
      expect(colors.getW(half)).toBeCloseTo(EDGES.alpha.dim, 5);

      const dirty = vi.fn();
      const roleOf = (id: number): "primary" | "dim" => (id === 1 ? "primary" : "dim");

      overlay.setMotion(true, roleOf, dirty);
      expect(dirty).toHaveBeenCalledTimes(1);
      expect(colors.getW(0)).toBeCloseTo(EDGES.alpha.primary, 5); // primary stays visible
      expect(colors.getW(half)).toBe(0); // base edge hidden

      // A second "moving" call while already hidden is a no-op — no redundant dirty.
      overlay.setMotion(true, roleOf, dirty);
      expect(dirty).toHaveBeenCalledTimes(1);

      overlay.setMotion(false, roleOf, dirty);
      vi.advanceTimersByTime(100); // still within the 100-200ms window
      expect(colors.getW(half)).toBe(0); // not restored yet

      // Movement resumes before the delay elapses — cancels the pending restore.
      overlay.setMotion(true, roleOf, dirty);
      vi.advanceTimersByTime(300);
      expect(colors.getW(half)).toBe(0); // restore was cancelled, still hidden

      overlay.setMotion(false, roleOf, dirty);
      vi.advanceTimersByTime(300); // past EDGE_RESTORE_DELAY_MS
      expect(colors.getW(half)).toBeCloseTo(EDGES.alpha.dim, 5); // restored
      expect(colors.getW(0)).toBeCloseTo(EDGES.alpha.primary, 5); // primary untouched throughout

      overlay.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it("disposing while a restore is pending cancels the timer cleanly", async () => {
    vi.useFakeTimers();
    try {
      const overlay = new EdgeOverlay();
      const parent = new THREE.Object3D();
      const tri = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
      const model = {
        getLocalIds: async () => [1],
        getItemsGeometry: async (ids: number[]) =>
          ids.map(() => [{ positions: tri, transform: new THREE.Matrix4() }]),
      };
      await overlay.build(model as never, parent);
      const dirty = vi.fn();
      overlay.setMotion(true, () => "dim", dirty);
      overlay.setMotion(false, () => "dim", dirty);
      overlay.dispose();
      // Should not throw when the (cancelled) timer would otherwise have fired.
      expect(() => vi.advanceTimersByTime(1000)).not.toThrow();
    } finally {
      vi.useRealTimers();
    }
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
