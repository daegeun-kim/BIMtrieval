// Viewer adapter identity + camera-guard behavior (spec_v006 §11, §18.1).
// A fake FragmentsModel/world is injected — no WebGL, no worker.
import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import { ViewerAdapter } from "../src/viewer/ViewerAdapter";

interface FakeModel {
  getLocalIdsByGuids: (guids: string[]) => Promise<(number | null)[]>;
  getGuidsByLocalIds: (ids: number[]) => Promise<(string | null)[]>;
  getMergedBox: (ids: number[]) => Promise<THREE.Box3>;
  resetHighlight: () => Promise<void>;
  highlight: (ids: number[] | undefined, mat: unknown) => Promise<void>;
}

function makeAdapter(box: THREE.Box3) {
  const adapter = new ViewerAdapter(5);
  const known: Record<string, number> = { "G-A": 101, "G-B": 102 };
  const model: FakeModel = {
    getLocalIdsByGuids: async (guids) => guids.map((g) => known[g] ?? null),
    getGuidsByLocalIds: async (ids) =>
      ids.map((id) => Object.keys(known).find((k) => known[k] === id) ?? null),
    getMergedBox: async () => box,
    resetHighlight: vi.fn(async () => {}),
    highlight: vi.fn(async () => {}),
  };
  const fitToBox = vi.fn(async (_box: THREE.Box3, _transition?: boolean) => {});
  // inject the imperative internals the adapter normally builds in init()
  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world: { camera: { controls: { fitToBox } } },
    fragments: { core: { update: async () => {} } },
  });
  return { adapter, fitToBox, model };
}

describe("ViewerAdapter identity + roles", () => {
  it("reports GlobalIds missing from the artifact without crashing", async () => {
    const { adapter } = makeAdapter(new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(1, 1, 1)));
    const res = await adapter.applyQueryRoles(["G-A", "G-MISSING"], ["G-B", "G-GONE"]);
    expect(res.missing).toEqual(["G-MISSING"]);
  });

  it("returns everything missing when no model is loaded", async () => {
    const adapter = new ViewerAdapter(5);
    const res = await adapter.applyQueryRoles(["G-A"], []);
    expect(res.missing).toEqual(["G-A"]);
  });
});

describe("adaptive profile override (tasks/task18.md §11)", () => {
  it("defaults to no override, and overriding takes effect immediately", () => {
    const adapter = new ViewerAdapter(5);
    expect(adapter.getProfileOverride()).toBeNull();
    expect(adapter.getProfile()).toBe("balanced");

    adapter.setProfileOverride("large-model");
    expect(adapter.getProfileOverride()).toBe("large-model");
    expect(adapter.getProfile()).toBe("large-model"); // no reload needed
  });

  it("reverts to the last automatically detected profile when cleared", () => {
    const adapter = new ViewerAdapter(5);
    adapter.setProfileOverride("large-model");
    expect(adapter.getProfile()).toBe("large-model");

    adapter.setProfileOverride(null);
    expect(adapter.getProfileOverride()).toBeNull();
    expect(adapter.getProfile()).toBe("balanced"); // the pre-load default, no model ever loaded
  });
});

describe("camera fit guard", () => {
  it("enforces a minimum framed size so tiny objects never fill the viewport", async () => {
    const tiny = new THREE.Box3(
      new THREE.Vector3(10, 10, 10),
      new THREE.Vector3(10.1, 10.1, 10.1),
    );
    const { adapter, fitToBox } = makeAdapter(tiny);
    await adapter.fitToGuids(["G-A"]);
    expect(fitToBox).toHaveBeenCalledTimes(1);
    const framed = fitToBox.mock.calls[0]![0];
    const size = new THREE.Vector3();
    framed.getSize(size);
    // MIN_FIT_SIZE half-extent of 2.5 -> at least 5m on every axis
    expect(size.x).toBeGreaterThanOrEqual(5);
    expect(size.y).toBeGreaterThanOrEqual(5);
    expect(size.z).toBeGreaterThanOrEqual(5);
  });

  it("expands a normal box moderately to keep surroundings visible", async () => {
    const room = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(10, 10, 10));
    const { adapter, fitToBox } = makeAdapter(room);
    await adapter.fitToGuids(["G-A"]);
    const framed = fitToBox.mock.calls[0]![0];
    const size = new THREE.Vector3();
    framed.getSize(size);
    expect(size.x).toBeCloseTo(19, 0); // 10m * 1.9 expansion
  });
});
