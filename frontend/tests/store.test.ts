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
