// Store semantics: session identity, panel bounds, selection state
// (spec_v006 §13, §18.1).
import { beforeEach, describe, expect, it } from "vitest";

import { PANEL_MAX_WIDTH, PANEL_MIN_WIDTH, useStore } from "../src/state/store";

beforeEach(() => {
  sessionStorage.clear();
});

describe("store", () => {
  it("keeps one tab-scoped session id and can regenerate it", () => {
    const s = useStore.getState();
    const first = s.sessionId;
    expect(first).toBeTruthy();
    const second = s.regenerateSessionId();
    expect(second).not.toBe(first);
    expect(useStore.getState().sessionId).toBe(second);
    expect(sessionStorage.getItem("bimrag.sessionId")).toBe(second);
  });

  it("clamps panel width into safe desktop bounds", () => {
    const s = useStore.getState();
    s.setPanelWidth(10);
    expect(useStore.getState().panelWidth).toBe(PANEL_MIN_WIDTH);
    s.setPanelWidth(99999);
    expect(useStore.getState().panelWidth).toBe(PANEL_MAX_WIDTH);
    s.setPanelWidth(400);
    expect(useStore.getState().panelWidth).toBe(400);
  });

  it("clearSelection wipes chips, guids, and notices together", () => {
    const s = useStore.getState();
    s.setManualGuids(["G1"]);
    s.setResolvedChips({ G1: { entity_id: 1, global_id: "G1", ifc_class: "IfcWall", name: null } });
    s.setSelectionNotice("limit");
    s.clearSelection();
    const after = useStore.getState();
    expect(after.manualGuids).toEqual([]);
    expect(after.resolvedChips).toEqual({});
    expect(after.selectionNotice).toBeNull();
  });

  it("setActiveModel keeps id and item in sync", () => {
    const s = useStore.getState();
    s.setActiveModel({
      source_model_id: 4,
      display_name: "M",
      source_fingerprint: "fp",
      viewer_asset_status: "ready",
    });
    expect(useStore.getState().activeModelId).toBe(4);
    s.setActiveModel(null);
    expect(useStore.getState().activeModelId).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Floor-plan state (task28 §6): current-session only and serializable — no
// camera pose, clipping plane, or section object ever lands in the store.
// ---------------------------------------------------------------------------

const OPTION = {
  bandIndex: 0,
  label: "Floor 1",
  enabled: true,
  reason: null,
  storeyNames: ["01 begane grond"],
};

describe("floor-plan store state (task28 §6)", () => {
  beforeEach(() => {
    useStore.getState().clearFloors();
  });

  it("starts in 3D with no floors", () => {
    const s = useStore.getState();
    expect(s.floorMode).toBe("3d");
    expect(s.floorBandIndex).toBeNull();
    expect(s.floorOptions).toEqual([]);
    expect(s.floorsAvailable).toBe(false);
  });

  it("holds only the four documented pieces of plan state", () => {
    const s = useStore.getState();
    s.setFloorOptions(2, [OPTION], true);
    s.setFloorMode("plan", 0);
    const after = useStore.getState();
    expect(after.floorMode).toBe("plan");
    expect(after.floorModelId).toBe(2);
    expect(after.floorBandIndex).toBe(0);
    expect(after.floorsLoading).toBe(false);
    // No imperative viewer object leaked into the serializable store.
    expect(JSON.stringify(after.floorOptions)).toBe(JSON.stringify([OPTION]));
  });

  it("returning to 3D always clears the active band", () => {
    const s = useStore.getState();
    s.setFloorOptions(2, [OPTION], true);
    s.setFloorMode("plan", 0);
    s.setFloorMode("3d", 0);
    expect(useStore.getState().floorBandIndex).toBeNull();
  });

  it("a new contract replaces the previous model's floors outright", () => {
    const s = useStore.getState();
    s.setFloorOptions(2, [OPTION], true);
    s.setFloorMode("plan", 0);
    s.setFloorsLoading(5);
    const after = useStore.getState();
    expect(after.floorModelId).toBe(5);
    expect(after.floorOptions).toEqual([]);
    expect(after.floorMode).toBe("3d");
    expect(after.floorBandIndex).toBeNull();
    expect(after.floorsLoading).toBe(true);
  });

  it("disabling one floor leaves every other floor alone", () => {
    const s = useStore.getState();
    s.setFloorOptions(2, [OPTION, { ...OPTION, bandIndex: 1, label: "Floor 2" }], true);
    s.setFloorOptionDisabled(1, "not locatable");
    const options = useStore.getState().floorOptions;
    expect(options[0]!.enabled).toBe(true);
    expect(options[1]!.enabled).toBe(false);
    expect(options[1]!.reason).toBe("not locatable");
  });

  it("never writes plan state to session or local storage", () => {
    const s = useStore.getState();
    s.setFloorOptions(2, [OPTION], true);
    s.setFloorMode("plan", 0);
    const keys = [...Object.keys(sessionStorage), ...Object.keys(localStorage)];
    expect(keys.filter((k) => /floor|plan/i.test(k))).toEqual([]);
  });
});
