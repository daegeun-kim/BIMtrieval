// Component detail panel + compact chat summary (tasks/task14.md §4, §5, §8).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EntityDetailsResponse, ResultSummary } from "../src/api/types";
import ResultSummaryView from "../src/chat/ResultSummaryView";
import { formatClassSummary, summarizeClassCounts } from "../src/chat/resultSummary";
import ComponentPanel from "../src/components/ComponentPanel";
import { useStore } from "../src/state/store";

// The preview owns a WebGL context; stub it out for the DOM-level panel tests.
vi.mock("../src/components/ComponentPreview", () => ({
  default: ({ guid }: { guid: string }) => <div data-testid="component-preview">{guid}</div>,
}));

const applyGroupScope = vi.fn(async () => {});
const closeComponent = vi.fn();
vi.mock("../src/state/controller", () => ({
  controller: {
    applyGroupScope: (...a: unknown[]) => applyGroupScope(...(a as [])),
    closeComponent: () => closeComponent(),
  },
}));

const WITH_TYPE_AND_FAMILY: EntityDetailsResponse = {
  source_model_id: 1,
  instance: {
    global_id: "G1",
    ifc_class: "IfcDoor",
    name: "Deur_binnen_88x231",
    predefined_type: "DOOR",
    tag: "331621",
    storey_name: "01 begane grond",
    materials: ["Hout"],
    quantities: [{ name: "Width", value: "880", source_set: "Qto", unit: "mm" }],
    properties: [{ name: "FireRating", value: "30", source_set: "Pset_DoorCommon" }],
  },
  type: { name: "DoorType_88x231", global_id: "T1", ifc_class: "IfcDoorType", predefined_type: "DOOR" },
  family: { value: "88x231", property_set: "Pset_DoorCommon", property_name: "Reference" },
  availability: {
    instance: true,
    same_type: true,
    same_family: true,
    type_unavailable_reason: null,
    family_unavailable_reason: null,
  },
};

// The current Schependomlaan model: no explicit type, no family.
const NO_TYPE_NO_FAMILY: EntityDetailsResponse = {
  source_model_id: 1,
  instance: {
    global_id: "G2",
    ifc_class: "IfcWallStandardCase",
    name: "Basiswand:Wand_Bui_Spouw:305150",
    materials: [],
    quantities: [],
    properties: [],
  },
  type: null,
  family: null,
  availability: {
    instance: true,
    same_type: false,
    same_family: false,
    type_unavailable_reason: "This model has no explicit IFC type data for this object.",
    family_unavailable_reason: "This model has no explicit family property for this object.",
  },
};

function openPanel(details: EntityDetailsResponse | null, guid = "G1") {
  useStore.setState({
    componentGuid: guid,
    componentDetails: details,
    componentLoading: details === null,
    componentError: null,
    componentScope: null,
    componentGroupNotice: null,
  });
}

beforeEach(() => {
  applyGroupScope.mockClear();
  closeComponent.mockClear();
  useStore.setState({ componentGuid: null, componentDetails: null, panelCollapsed: false });
});

describe("component panel visibility", () => {
  it("renders nothing until a component is selected", () => {
    const { container } = render(<ComponentPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a loading state while details are in flight", () => {
    openPanel(null);
    render(<ComponentPanel />);
    expect(screen.getByText(/loading details/i)).toBeInTheDocument();
  });

  it("shows a bounded error without exposing internals", () => {
    openPanel(null);
    useStore.setState({ componentLoading: false, componentError: "Couldn't load this component's details." });
    render(<ComponentPanel />);
    expect(screen.getByText(/couldn't load this component/i)).toBeInTheDocument();
  });
});

describe("truthful optional layers (task14 §5)", () => {
  it("renders explicit type and family with their source property", () => {
    openPanel(WITH_TYPE_AND_FAMILY);
    render(<ComponentPanel />);
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("DoorType_88x231")).toBeInTheDocument();
    expect(screen.getByText("Family")).toBeInTheDocument();
    expect(screen.getByText("88x231")).toBeInTheDocument();
    // provenance of the family value is visible
    expect(screen.getByText(/Pset_DoorCommon · Reference/)).toBeInTheDocument();
  });

  it("omits absent type/family entirely instead of empty placeholders", () => {
    openPanel(NO_TYPE_NO_FAMILY, "G2");
    render(<ComponentPanel />);
    expect(screen.queryByText("Type")).not.toBeInTheDocument();
    expect(screen.queryByText("Family")).not.toBeInTheDocument();
    // instance information is still shown
    expect(screen.getByText("IfcWallStandardCase")).toBeInTheDocument();
  });

  it("disables Same type / Same family with a concise reason when unavailable", () => {
    openPanel(NO_TYPE_NO_FAMILY, "G2");
    render(<ComponentPanel />);
    expect(screen.getByRole("button", { name: "Same type" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Same family" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Instance" })).toBeEnabled();
    expect(screen.getByText(/no explicit IFC type data/i)).toBeInTheDocument();
    expect(screen.getByText(/no explicit family property/i)).toBeInTheDocument();
  });

  it("never renders a name-derived family for a family-looking object name", () => {
    // "Basiswand:Wand_Bui_Spouw:305150" looks like a Revit family:type string.
    openPanel(NO_TYPE_NO_FAMILY, "G2");
    render(<ComponentPanel />);
    expect(screen.queryByText("Family")).not.toBeInTheDocument();
    expect(screen.queryByText(/Wand_Bui_Spouw$/)).not.toBeInTheDocument();
  });

  it("enables all three actions when the model has type and family", () => {
    openPanel(WITH_TYPE_AND_FAMILY);
    render(<ComponentPanel />);
    expect(screen.getByRole("button", { name: "Instance" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Same type" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Same family" })).toBeEnabled();
  });
});

describe("deterministic actions (task14 §5)", () => {
  it("calls the group endpoint and never submits a chat query", async () => {
    const user = userEvent.setup();
    openPanel(WITH_TYPE_AND_FAMILY);
    render(<ComponentPanel />);

    await user.click(screen.getByRole("button", { name: "Same type" }));
    expect(applyGroupScope).toHaveBeenCalledWith("type");
    // No chat message was created by the action.
    expect(useStore.getState().messages).toHaveLength(0);
  });

  it("reports the exact group total and truncation", () => {
    openPanel(WITH_TYPE_AND_FAMILY);
    useStore.setState({
      componentScope: "type",
      componentGroupNotice: "Highlighted the first 2000 of 5000 matching objects.",
    });
    render(<ComponentPanel />);
    expect(screen.getByText(/first 2000 of 5000/)).toBeInTheDocument();
  });

  it("closes the panel via the controller", async () => {
    const user = userEvent.setup();
    openPanel(WITH_TYPE_AND_FAMILY);
    render(<ComponentPanel />);
    await user.click(screen.getByRole("button", { name: /close component details/i }));
    expect(closeComponent).toHaveBeenCalled();
  });

  it("renders allowlisted quantities and properties, not raw canonical JSON", () => {
    openPanel(WITH_TYPE_AND_FAMILY);
    render(<ComponentPanel />);
    expect(screen.getByText("Width")).toBeInTheDocument();
    expect(screen.getByText("FireRating")).toBeInTheDocument();
    expect(screen.queryByText(/canonical_json/)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Compact chat summary (task14 §4)
// ---------------------------------------------------------------------------

describe("class summary formatting", () => {
  it('renders "5 doors, 3 windows"', () => {
    expect(formatClassSummary({ IfcDoor: 5, IfcWindow: 3 })).toBe("5 doors, 3 windows");
  });

  it("merges wall subtypes under one label", () => {
    // The backend counts 648 IfcWall + 232 IfcWallStandardCase for "all walls".
    expect(formatClassSummary({ IfcWall: 648, IfcWallStandardCase: 232 })).toBe("880 walls");
  });

  it("uses the singular for a count of one", () => {
    expect(formatClassSummary({ IfcDoor: 1 })).toBe("1 door");
  });

  it("orders by count descending", () => {
    expect(summarizeClassCounts({ IfcWindow: 3, IfcDoor: 5 }).map((i) => i.label)).toEqual([
      "door",
      "window",
    ]);
  });

  it("humanizes unmapped classes rather than dropping them", () => {
    expect(formatClassSummary({ IfcFlowSegment: 2 })).toBe("2 flow segments");
  });

  it("handles an empty/absent summary", () => {
    expect(formatClassSummary({})).toBe("");
    expect(formatClassSummary(null)).toBe("");
  });
});

describe("chat result summary (task14 §4)", () => {
  const base: ResultSummary = {
    exact_total: 205,
    viewer_match_count: 205,
    viewer_matches_total: 205,
    truncated: false,
    class_counts: { IfcDoor: 205 },
    sample_detail: null,
  };

  it("shows the exact total and a compact class summary, not a component list", () => {
    render(<ResultSummaryView summary={base} />);
    expect(screen.getByText("205")).toBeInTheDocument();
    expect(screen.getByText("205 doors")).toBeInTheDocument();
  });

  it("discloses viewer truncation while keeping the exact total distinct", () => {
    render(
      <ResultSummaryView
        summary={{ ...base, exact_total: 5000, viewer_match_count: 2000, viewer_matches_total: 5000, truncated: true }}
      />,
    );
    expect(screen.getByText("5,000")).toBeInTheDocument();
    expect(screen.getByText(/highlighting 2,000 of 5,000/)).toBeInTheDocument();
  });

  it("shows no component details for an ordinary query", () => {
    render(<ResultSummaryView summary={base} />);
    expect(screen.queryByText(/storey/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/materials/i)).not.toBeInTheDocument();
  });

  it("shows one component's details only on explicit sample-detail intent", () => {
    render(
      <ResultSummaryView
        summary={{
          ...base,
          sample_detail: {
            global_id: "G1",
            ifc_class: "IfcDoor",
            name: "Deur_binnen",
            storey_name: "01 begane grond",
            materials: ["Hout"],
            quantities: [{ name: "Width", value: "880", unit: "mm", source_set: "Qto" }],
            properties: [],
          },
        }}
      />,
    );
    expect(screen.getByText("Deur_binnen")).toBeInTheDocument();
    expect(screen.getByText("01 begane grond")).toBeInTheDocument();
    expect(screen.getByText("Hout")).toBeInTheDocument();
  });
});
