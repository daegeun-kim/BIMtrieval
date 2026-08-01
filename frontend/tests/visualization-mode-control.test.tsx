// The Fine | Standard | Fast control in the bottom-left readout
// (tasks/task31.md §2.1, §8.1). The viewer adapter is mocked — this suite is
// about the control, the store, and the controller boundary.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewerStub = vi.hoisted(() => ({
  setCallbacks: vi.fn(),
  init: vi.fn(async () => {}),
  hasModel: vi.fn(() => true),
  fitAll: vi.fn(async () => {}),
  unloadModel: vi.fn(async () => {}),
  clearManualSelection: vi.fn(),
  clearQueryRoles: vi.fn(async () => {}),
  exitPlanMode: vi.fn(async () => {}),
  setVisualizationMode: vi.fn(async () => {}),
  dispose: vi.fn(),
}));
vi.mock("../src/viewer/ViewerAdapter", () => ({ ViewerAdapter: vi.fn(() => viewerStub) }));
vi.mock("../src/api/client", () => ({
  api: { query: vi.fn(async () => ({})) },
}));

import StatusReadout from "../src/components/StatusReadout";
import { controller } from "../src/state/controller";
import { useStore } from "../src/state/store";

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    visualizationMode: "standard",
    loadPhase: "ready",
    backendReachable: true,
    activeModel: {
      source_model_id: 1,
      display_name: "House A",
      source_fingerprint: "fp1",
      viewer_asset_status: "ready",
    },
    messages: [],
  });
});

function group() {
  return screen.getByRole("radiogroup", { name: /visualization quality/i });
}

describe("the control itself (task31 §2.1)", () => {
  it("sits in the readout beside Fit, offering exactly three options", () => {
    render(<StatusReadout />);
    const options = within(group()).getAllByRole("radio");
    expect(options.map((o) => o.textContent)).toEqual(["Fine", "Standard", "Fast"]);
    expect(screen.getByRole("button", { name: "Fit" })).toBeInTheDocument();
  });

  it("shows Standard selected by default", () => {
    render(<StatusReadout />);
    expect(within(group()).getByRole("radio", { name: "Standard" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(group()).getByRole("radio", { name: "Fine" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("is not the removed automatic/manual performance-profile control", () => {
    render(<StatusReadout />);
    expect(within(group()).queryByRole("radio", { name: /auto/i })).toBeNull();
    expect(screen.queryByText(/performance|profile|fps|frame/i)).toBeNull();
  });

  it("applies the chosen mode through the controller, not by touching the scene", async () => {
    const user = userEvent.setup();
    render(<StatusReadout />);
    await user.click(within(group()).getByRole("radio", { name: "Fast" }));
    expect(useStore.getState().visualizationMode).toBe("fast");
    expect(viewerStub.setVisualizationMode).toHaveBeenCalledWith("fast");
  });

  it("reflects the newly selected mode in aria-checked", async () => {
    const user = userEvent.setup();
    render(<StatusReadout />);
    await user.click(within(group()).getByRole("radio", { name: "Fine" }));
    expect(within(group()).getByRole("radio", { name: "Fine" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(group()).getByRole("radio", { name: "Standard" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("keeps only the selected option in the tab order and moves with arrow keys", async () => {
    const user = userEvent.setup();
    render(<StatusReadout />);
    const standard = within(group()).getByRole("radio", { name: "Standard" });
    expect(standard).toHaveAttribute("tabindex", "0");
    expect(within(group()).getByRole("radio", { name: "Fine" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    standard.focus();
    await user.keyboard("{ArrowRight}");
    expect(useStore.getState().visualizationMode).toBe("fast");
    await user.keyboard("{ArrowLeft}");
    expect(useStore.getState().visualizationMode).toBe("standard");
  });
});

describe("mode lifecycle through the controller (task31 §2.1)", () => {
  it("ignores a re-selection of the current mode", async () => {
    await controller.setVisualizationMode("standard");
    expect(viewerStub.setVisualizationMode).not.toHaveBeenCalled();
  });

  it("keeps the selection across a model switch", async () => {
    await controller.setVisualizationMode("fine");
    // A model switch never touches the mode: the adapter owns it, and the
    // controller's load path does not reset it.
    useStore.setState({ activeModelId: 2 });
    expect(useStore.getState().visualizationMode).toBe("fine");
  });

  it("Reset App returns the mode to Standard", async () => {
    await controller.setVisualizationMode("fast");
    viewerStub.setVisualizationMode.mockClear();
    await controller.resetApp();
    expect(useStore.getState().visualizationMode).toBe("standard");
    expect(viewerStub.setVisualizationMode).toHaveBeenCalledWith("standard");
  });

  it("Clear Chat does NOT reset the mode", async () => {
    await controller.setVisualizationMode("fast");
    await controller.clearChat();
    expect(useStore.getState().visualizationMode).toBe("fast");
  });
});
