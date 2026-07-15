// Component behavior: composer keys, chips, evidence disclosure, selector
// confirmation gating (spec_v006 §18.1). Viewer + API are mocked.
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewerStub = vi.hoisted(() => ({
  setCallbacks: vi.fn(),
  init: vi.fn(async () => {}),
  hasModel: vi.fn(() => true),
  removeManualSelection: vi.fn(),
  clearManualSelection: vi.fn(),
  clearQueryRoles: vi.fn(async () => {}),
  unloadModel: vi.fn(async () => {}),
  fitToGuids: vi.fn(async (): Promise<{ missing: string[] }> => ({ missing: [] })),
  applyQueryRoles: vi.fn(async (): Promise<{ missing: string[] }> => ({ missing: [] })),
  fitAll: vi.fn(async () => {}),
  resize: vi.fn(),
  setSelectionEnabled: vi.fn(),
  dispose: vi.fn(),
}));
vi.mock("../src/viewer/ViewerAdapter", () => ({ ViewerAdapter: vi.fn(() => viewerStub) }));

import { api } from "../src/api/client";
import Composer from "../src/chat/Composer";
import EvidenceDisclosure from "../src/chat/EvidenceDisclosure";
import SelectionChips from "../src/chat/SelectionChips";
import ModelSelector from "../src/components/ModelSelector";
import { controller } from "../src/state/controller";
import { useStore } from "../src/state/store";

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    messages: [],
    pending: false,
    retryQuestion: null,
    manualGuids: [],
    resolvedChips: {},
    selectionNotice: null,
    models: [
      { source_model_id: 1, display_name: "House A", source_fingerprint: "fp1", viewer_asset_status: "ready" },
      { source_model_id: 2, display_name: "House B", source_fingerprint: "fp2", viewer_asset_status: "missing" },
    ],
    activeModel: null,
    activeModelId: null,
    pendingConfirmModelId: null,
  });
});

describe("Composer", () => {
  it("Enter submits, Shift+Enter does not, blank cannot submit", async () => {
    const spy = vi.spyOn(controller, "submitQuestion").mockResolvedValue();
    render(<Composer />);
    const ta = screen.getByLabelText("Ask a question about the model");

    fireEvent.keyDown(ta, { key: "Enter" }); // blank — rejected
    expect(spy).not.toHaveBeenCalled();

    await userEvent.type(ta, "How many doors?");
    fireEvent.keyDown(ta, { key: "Enter", shiftKey: true }); // newline, no submit
    expect(spy).not.toHaveBeenCalled();

    fireEvent.keyDown(ta, { key: "Enter" });
    expect(spy).toHaveBeenCalledWith("How many doors?");
  });

  it("shows Cancel while pending and Retry after a retryable failure", () => {
    useStore.setState({ pending: true });
    const { rerender } = render(<Composer />);
    expect(screen.getByLabelText("Cancel request")).toBeInTheDocument();

    useStore.setState({ pending: false, retryQuestion: "q" });
    rerender(<Composer />);
    const retry = screen.getByRole("button", { name: "Retry" });
    const spy = vi.spyOn(controller, "retry").mockImplementation(() => {});
    fireEvent.click(retry);
    expect(spy).toHaveBeenCalled();
  });
});

describe("SelectionChips", () => {
  it("renders resolved names, allows removal, shows the five-object notice", () => {
    useStore.setState({
      manualGuids: ["G1", "G2"],
      resolvedChips: {
        G1: { entity_id: 11, global_id: "G1", ifc_class: "IfcDoor", name: "Front door" },
      },
      selectionNotice: "Selection is limited to five objects. Remove one to add another.",
    });
    render(<SelectionChips />);
    expect(screen.getByText("Front door")).toBeInTheDocument();
    expect(screen.getByText("G2")).toBeInTheDocument(); // unresolved falls back to id
    expect(screen.getByText(/limited to five/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Remove Front door from selection"));
    expect(viewerStub.removeManualSelection).toHaveBeenCalledWith("G1");
  });
});

describe("EvidenceDisclosure", () => {
  const evidence = {
    route: "hybrid",
    answerBasis: "hybrid_evidence",
    scope: "active_model",
    sqlCount: 12,
    ragCount: 5,
    relCount: null,
    primaries: [{ entityId: 1, globalId: "GP", ifcClass: "IfcDoor", name: "D1", role: "primary" as const }],
    contexts: [],
    relationships: [],
    notes: ["bounded"],
    warnings: [],
  };

  it("is collapsed by default and expands on toggle", () => {
    render(<EvidenceDisclosure evidence={evidence} />);
    expect(screen.queryByText("D1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("D1")).toBeInTheDocument();
    expect(screen.getByText("bounded")).toBeInTheDocument();
  });

  it("citation click centers the entity without calling the LLM", () => {
    const qspy = vi.spyOn(api, "query");
    render(<EvidenceDisclosure evidence={evidence} />);
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    fireEvent.click(screen.getByText("D1"));
    expect(viewerStub.fitToGuids).toHaveBeenCalledWith(["GP"]);
    expect(qspy).not.toHaveBeenCalled();
  });
});

describe("ModelSelector", () => {
  it("choosing a model only proposes it — nothing loads without confirmation", () => {
    const loadSpy = vi.spyOn(controller, "confirmAndLoadModel").mockResolvedValue();
    render(<ModelSelector />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2" } });
    expect(useStore.getState().pendingConfirmModelId).toBe(2);
    expect(loadSpy).not.toHaveBeenCalled();
  });
});
