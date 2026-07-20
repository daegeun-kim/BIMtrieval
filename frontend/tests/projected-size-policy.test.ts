// Projected-size rendering policy (tasks/task23.md issue 2).
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import {
  PROJECTED_SIZE,
  type PolicyModel,
  ProjectedSizePolicy,
  projectedDiameterPx,
  readExplicitBoolean,
} from "../src/viewer/ProjectedSizePolicy";

function camera(z = 0): THREE.PerspectiveCamera {
  const cam = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  cam.position.set(0, 0, z);
  cam.updateMatrixWorld();
  return cam;
}

/** Distance at which a sphere of `radius` projects to exactly `px`. */
function distanceForPx(radius: number, px: number, fovDeg: number, heightPx: number): number {
  const tanHalf = Math.tan(THREE.MathUtils.degToRad(fovDeg) / 2);
  return (2 * radius * heightPx) / (px * 2 * tanHalf);
}

// ---------------------------------------------------------------------------
// Projection math
// ---------------------------------------------------------------------------

describe("projectedDiameterPx", () => {
  it("shrinks with distance", () => {
    const near = projectedDiameterPx(new THREE.Vector3(0, 0, -10), 1, camera(), 800);
    const far = projectedDiameterPx(new THREE.Vector3(0, 0, -100), 1, camera(), 800);
    expect(near).toBeGreaterThan(far);
  });

  it("scales linearly with viewport height", () => {
    const c = new THREE.Vector3(0, 0, -50);
    const small = projectedDiameterPx(c, 1, camera(), 400);
    const large = projectedDiameterPx(c, 1, camera(), 800);
    expect(large).toBeCloseTo(small * 2, 5);
  });

  it("scales linearly with radius", () => {
    const c = new THREE.Vector3(0, 0, -50);
    const a = projectedDiameterPx(c, 1, camera(), 800);
    const b = projectedDiameterPx(c, 2, camera(), 800);
    expect(b).toBeCloseTo(a * 2, 5);
  });

  it("treats a camera inside the object as large, never small", () => {
    expect(projectedDiameterPx(new THREE.Vector3(0, 0, 0), 5, camera(), 800)).toBe(Infinity);
  });

  it("matches the analytic distance for a target pixel size", () => {
    const d = distanceForPx(1, 20, 45, 800);
    const px = projectedDiameterPx(new THREE.Vector3(0, 0, -d), 1, camera(), 800);
    expect(px).toBeCloseTo(20, 4);
  });
});

// ---------------------------------------------------------------------------
// Explicit-property reading (no guessing)
// ---------------------------------------------------------------------------

function itemWithProp(name: string, value: unknown) {
  return {
    IsDefinedBy: [
      {
        _category: { value: "IFCPROPERTYSET" },
        HasProperties: [{ Name: { value: name }, NominalValue: { value } }],
      },
    ],
  };
}

describe("readExplicitBoolean", () => {
  it("reads an explicit true", () => {
    expect(readExplicitBoolean(itemWithProp("IsExternal", true), "IsExternal")).toBe(true);
  });

  it("reads an explicit false", () => {
    expect(readExplicitBoolean(itemWithProp("IsExternal", false), "IsExternal")).toBe(false);
  });

  it("returns null for a missing property", () => {
    expect(readExplicitBoolean(itemWithProp("Other", true), "IsExternal")).toBeNull();
  });

  it("returns null for a non-boolean value rather than coercing", () => {
    expect(readExplicitBoolean(itemWithProp("IsExternal", "TRUE"), "IsExternal")).toBeNull();
    expect(readExplicitBoolean(itemWithProp("IsExternal", 1), "IsExternal")).toBeNull();
    expect(readExplicitBoolean(itemWithProp("IsExternal", null), "IsExternal")).toBeNull();
  });

  it("returns null when relations are absent entirely", () => {
    expect(readExplicitBoolean({}, "IsExternal")).toBeNull();
    expect(readExplicitBoolean(undefined, "IsExternal")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Fake model
// ---------------------------------------------------------------------------

interface FakeItem {
  id: number;
  category: string;
  center: [number, number, number];
  radius: number;
  props?: Record<string, unknown>;
}

function fakeModel(items: FakeItem[]) {
  const visible = new Map<number, boolean>(items.map((i) => [i.id, true]));
  return {
    visible,
    async getCategories() {
      return [...new Set(items.map((i) => i.category))];
    },
    async getItemsOfCategories(regexes: RegExp[]) {
      const out: Record<string, number[]> = {};
      for (const item of items) {
        if (regexes.some((r) => r.test(item.category))) {
          (out[item.category] ??= []).push(item.id);
        }
      }
      return out;
    },
    async getItemsData(ids: number[], config: unknown) {
      // Mirrors the real API trap: without attributesDefault the relations are empty.
      if (!(config as { attributesDefault?: boolean })?.attributesDefault) {
        return ids.map(() => ({}));
      }
      return ids.map((id) => {
        const item = items.find((i) => i.id === id);
        if (!item?.props) return {};
        return {
          IsDefinedBy: [
            {
              _category: { value: "IFCPROPERTYSET" },
              HasProperties: Object.entries(item.props).map(([k, v]) => ({
                Name: { value: k },
                NominalValue: { value: v },
              })),
            },
          ],
        };
      });
    },
    async getBoxes(ids: number[]) {
      return ids.map((id) => {
        const item = items.find((i) => i.id === id)!;
        const c = new THREE.Vector3(...item.center);
        const r = item.radius;
        return new THREE.Box3(
          new THREE.Vector3(c.x - r, c.y - r, c.z - r),
          new THREE.Vector3(c.x + r, c.y + r, c.z + r),
        );
      });
    },
    async setVisible(ids: number[] | undefined, v: boolean) {
      for (const id of ids ?? []) visible.set(id, v);
    },
  };
}

/** Bounding-sphere radius of a cube half-extent r (matches getBoxes above). */
const sphereRadius = (halfExtent: number) => (new THREE.Vector3(2, 2, 2).length() * halfExtent) / 2;

const HEIGHT = 800;
const FOV = 45;

/** Place an object so it projects to approximately `px`. */
function centerForPx(halfExtent: number, px: number): [number, number, number] {
  return [0, 0, -distanceForPx(sphereRadius(halfExtent), px, FOV, HEIGHT)];
}

// ---------------------------------------------------------------------------
// Category eligibility
// ---------------------------------------------------------------------------

describe("category eligibility", () => {
  const tiny = () => centerForPx(1, 5); // far below the 20 px threshold

  it("retains walls, roofs and slabs at any size", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCWALL", center: tiny(), radius: 1 },
      { id: 2, category: "IFCWALLSTANDARDCASE", center: tiny(), radius: 1 },
      { id: 3, category: "IFCROOF", center: tiny(), radius: 1 },
      { id: 4, category: "IFCSLAB", center: tiny(), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    expect(await policy.prepare(model, [1, 2, 3, 4])).toBe(true);
    expect(policy.getRetainedCount()).toBe(4);
    expect(policy.getCandidateCount()).toBe(0);

    const delta = policy.evaluate(camera(), HEIGHT, () => false);
    expect(delta.hide).toEqual([]);
  });

  it("retains a door only with explicit IsExternal=true", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCDOOR", center: tiny(), radius: 1, props: { IsExternal: true } },
      { id: 2, category: "IFCDOOR", center: tiny(), radius: 1, props: { IsExternal: false } },
      { id: 3, category: "IFCDOOR", center: tiny(), radius: 1 }, // absent
      { id: 4, category: "IFCDOOR", center: tiny(), radius: 1, props: { IsExternal: "T" } },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1, 2, 3, 4]);
    expect(policy.getRetainedCount()).toBe(1);

    const { hide } = policy.evaluate(camera(), HEIGHT, () => false);
    expect(hide.sort()).toEqual([2, 3, 4]); // ambiguous/absent do NOT qualify
  });

  it("retains a column only with explicit LoadBearing=true", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCCOLUMN", center: tiny(), radius: 1, props: { LoadBearing: true } },
      { id: 2, category: "IFCCOLUMN", center: tiny(), radius: 1, props: { LoadBearing: false } },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1, 2]);
    const { hide } = policy.evaluate(camera(), HEIGHT, () => false);
    expect(hide).toEqual([2]);
  });

  it("hides ordinary furniture and MEP when small", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: tiny(), radius: 1 },
      { id: 2, category: "IFCFLOWTERMINAL", center: tiny(), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1, 2]);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide.sort()).toEqual([1, 2]);
  });
});

// ---------------------------------------------------------------------------
// Threshold + hysteresis
// ---------------------------------------------------------------------------

describe("threshold and hysteresis", () => {
  async function policyFor(px: number) {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, px), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);
    return { policy, model };
  }

  it("hides below the 20 px entry threshold", async () => {
    const { policy } = await policyFor(15);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([1]);
    expect(policy.isHidden(1)).toBe(true);
  });

  it("does not hide a comfortably large object", async () => {
    const { policy } = await policyFor(60);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([]);
  });

  it("keeps previous state inside the 20-24 px band", async () => {
    // Starts large, moves into the band -> stays visible.
    const { policy } = await policyFor(22);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([]);
    expect(policy.isHidden(1)).toBe(false);
  });

  it("requires passing 24 px to reappear, not merely 20 px", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 10), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);

    // Hidden at 10 px.
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([1]);

    // Growing the viewport to reach ~22 px is inside the band -> still hidden.
    const bandHeight = HEIGHT * 2.2;
    expect(policy.evaluate(camera(), bandHeight, () => false).show).toEqual([]);
    expect(policy.isHidden(1)).toBe(true);

    // Past 24 px -> restored.
    const aboveExit = HEIGHT * 3.0;
    expect(policy.evaluate(camera(), aboveExit, () => false).show).toEqual([1]);
    expect(policy.isHidden(1)).toBe(false);
  });

  it("thresholds are 20/24 px as specified", () => {
    expect(PROJECTED_SIZE.enterPx).toBe(20);
    expect(PROJECTED_SIZE.exitPx).toBe(24);
  });

  it("depends on projected size, not raw distance", async () => {
    // A large object far away and a small object nearby can project the same;
    // both must be treated identically.
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(10, 15), radius: 10 },
      { id: 2, category: "IFCFURNISHINGELEMENT", center: centerForPx(0.1, 15), radius: 0.1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1, 2]);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide.sort()).toEqual([1, 2]);
  });

  it("re-evaluating without change reports no delta (idempotent)", async () => {
    const { policy } = await policyFor(10);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([1]);
    const second = policy.evaluate(camera(), HEIGHT, () => false);
    expect(second.hide).toEqual([]);
    expect(second.show).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Highlight exemption
// ---------------------------------------------------------------------------

describe("highlighted and selected objects", () => {
  it("are never hidden even when tiny and non-fundamental", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 2), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);
    expect(policy.evaluate(camera(), HEIGHT, (id) => id === 1).hide).toEqual([]);
    expect(policy.isHidden(1)).toBe(false);
  });

  it("become visible immediately when highlighted while hidden", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 5), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([1]);
    // Now highlighted -> restored.
    expect(policy.evaluate(camera(), HEIGHT, (id) => id === 1).show).toEqual([1]);
    expect(policy.isHidden(1)).toBe(false);
  });

  it("reapply their size state as soon as the highlight clears", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 5), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);
    policy.evaluate(camera(), HEIGHT, (id) => id === 1);
    expect(policy.isHidden(1)).toBe(false);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([1]);
  });
});

// ---------------------------------------------------------------------------
// Robustness
// ---------------------------------------------------------------------------

describe("robustness", () => {
  it("fails safe when the Fragments APIs are unavailable", async () => {
    const policy = new ProjectedSizePolicy();
    const ok = await policy.prepare(
      { getCategories: async () => [] } as unknown as PolicyModel,
      [1],
    );
    expect(ok).toBe(false);
    expect(policy.isReady()).toBe(false);
    expect(policy.evaluate(camera(), HEIGHT, () => false).hide).toEqual([]);
  });

  it("fails safe when classification throws", async () => {
    const broken = {
      getCategories: async () => {
        throw new Error("worker exploded");
      },
      getBoxes: async () => [],
      setVisible: async () => {},
      getItemsOfCategories: async () => ({}),
      getItemsData: async () => [],
    };
    const policy = new ProjectedSizePolicy();
    expect(await policy.prepare(broken as unknown as PolicyModel, [1])).toBe(false);
  });

  it("ignores items with no geometry", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: [0, 0, -10], radius: 0 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);
    expect(policy.getCandidateCount()).toBe(0);
  });

  it("restoreAll clears every hidden object", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 5), radius: 1 },
      { id: 2, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 5), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1, 2]);
    policy.evaluate(camera(), HEIGHT, () => false);
    expect(policy.restoreAll().sort()).toEqual([1, 2]);
    expect(policy.hiddenIds()).toEqual([]);
  });

  it("reset clears all state", async () => {
    const model = fakeModel([
      { id: 1, category: "IFCFURNISHINGELEMENT", center: centerForPx(1, 5), radius: 1 },
    ]);
    const policy = new ProjectedSizePolicy();
    await policy.prepare(model, [1]);
    policy.reset();
    expect(policy.isReady()).toBe(false);
    expect(policy.getCandidateCount()).toBe(0);
  });
});
