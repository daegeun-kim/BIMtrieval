// Floor-plan control rendering + accessibility (tasks/task28.md §1.1, §8.2).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FloorControls from "../src/components/FloorControls";
import { controller } from "../src/state/controller";
import { useStore, type FloorOption } from "../src/state/store";

function option(bandIndex: number, label: string, extra?: Partial<FloorOption>): FloorOption {
  return {
    bandIndex,
    label,
    enabled: true,
    reason: null,
    storeyNames: [`storey ${bandIndex}`],
    ...extra,
  };
}

const THREE_FLOORS = [option(0, "Floor 1"), option(1, "Floor 2"), option(2, "Floor 3")];

function ready(options: FloorOption[], available = true): void {
  const s = useStore.getState();
  s.setLoadPhase("ready");
  s.setFloorOptions(1, options, available);
}

beforeEach(() => {
  const s = useStore.getState();
  s.clearFloors();
  s.setLoadPhase("idle");
  vi.restoreAllMocks();
});

describe("when the control appears (task28 §1.1)", () => {
  it("is absent before a model is ready", () => {
    ready(THREE_FLOORS);
    useStore.getState().setLoadPhase("downloading");
    render(<FloorControls />);
    expect(screen.queryByTestId("floor-controls")).toBeNull();
  });

  it("is absent when the model has no usable logical floors", () => {
    ready([], false);
    render(<FloorControls />);
    expect(screen.queryByTestId("floor-controls")).toBeNull();
  });

  it("appears once a model with available floors is ready", () => {
    ready(THREE_FLOORS);
    render(<FloorControls />);
    expect(screen.getByTestId("floor-controls")).toBeInTheDocument();
  });

  it("appears for a single-floor model", () => {
    ready([option(0, "Floor 1")]);
    render(<FloorControls />);
    const group = screen.getByRole("group", { name: /viewer floor plan/i });
    expect(within(group).getAllByRole("button")).toHaveLength(2); // 3D + Floor 1
  });
});

describe("what the control renders (task28 §1.1)", () => {
  it("renders 3D plus every returned logical floor, in order", () => {
    ready(THREE_FLOORS);
    render(<FloorControls />);
    const labels = screen
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(labels).toEqual(["3D", "Floor 1", "Floor 2", "Floor 3"]);
  });

  it("renders every floor of a tall model rather than omitting any", () => {
    const many = Array.from({ length: 24 }, (_, i) => option(i, `Floor ${i + 1}`));
    ready(many);
    render(<FloorControls />);
    expect(screen.getAllByRole("button")).toHaveLength(25);
    expect(screen.getByRole("button", { name: "Floor 24" })).toBeInTheDocument();
  });

  it("puts the floor list in its own scrollable container", () => {
    ready(THREE_FLOORS);
    render(<FloorControls />);
    // The scroll behavior lives on .floor-buttons in App.css (overflow-y: auto);
    // the contract asserted here is that the buttons share ONE bounded container
    // rather than being laid out directly in the page flow.
    const group = screen.getByRole("group", { name: /viewer floor plan/i });
    expect(group.className).toContain("floor-buttons");
    expect(group.querySelectorAll("button")).toHaveLength(4);
  });

  it("shows a plan limitation as a non-blocking status", () => {
    ready(THREE_FLOORS);
    useStore.getState().setFloorNotice("Cut outlines aren't available for this floor.");
    render(<FloorControls />);
    expect(screen.getByRole("status")).toHaveTextContent(/cut outlines aren't available/i);
  });
});

describe("active state and accessibility (task28 §1.1)", () => {
  it("marks 3D as the selected state by default", () => {
    ready(THREE_FLOORS);
    render(<FloorControls />);
    expect(screen.getByRole("button", { name: "3D" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Floor 2" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("moves the selected state to the active floor in plan mode", () => {
    ready(THREE_FLOORS);
    useStore.getState().setFloorMode("plan", 1);
    render(<FloorControls />);
    expect(screen.getByRole("button", { name: "Floor 2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "3D" })).toHaveAttribute("aria-pressed", "false");
    // Exactly one control is marked active at a time.
    const pressed = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);
  });

  it("also marks the active floor visually, not only via aria", () => {
    ready(THREE_FLOORS);
    useStore.getState().setFloorMode("plan", 2);
    render(<FloorControls />);
    expect(screen.getByRole("button", { name: "Floor 3" }).className).toContain(
      "floor-btn-active",
    );
    expect(screen.getByRole("button", { name: "Floor 1" }).className).not.toContain(
      "floor-btn-active",
    );
  });

  it("uses source storey names only in the tooltip / accessible description", () => {
    ready([option(0, "Floor 1", { storeyNames: ["01 begane grond", "01 vloer"] })]);
    render(<FloorControls />);
    const button = screen.getByRole("button", { name: "Floor 1" });
    // The visible label is derived from the reference band, never from a name.
    expect(button.textContent).toBe("Floor 1");
    expect(button.getAttribute("title")).toContain("01 begane grond");
    expect(button.getAttribute("title")).toContain("01 vloer");
  });

  it("omits the storey list from the tooltip when the model supplies no names", () => {
    ready([option(0, "Floor 1", { storeyNames: [] })]);
    render(<FloorControls />);
    expect(screen.getByRole("button", { name: "Floor 1" })).toHaveAttribute("title", "Floor 1");
  });

  it("is reachable by keyboard with a focusable, native button per floor", async () => {
    ready(THREE_FLOORS);
    const spy = vi.spyOn(controller, "selectFloor").mockResolvedValue();
    render(<FloorControls />);

    await userEvent.tab();
    expect(screen.getByRole("button", { name: "3D" })).toHaveFocus();
    await userEvent.tab();
    const floor1 = screen.getByRole("button", { name: "Floor 1" });
    expect(floor1).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(spy).toHaveBeenCalledWith(0);
  });
});

describe("disabled floors (task28 §6)", () => {
  it("keeps an unmappable floor visible but disabled, with its reason", () => {
    ready([
      option(0, "Floor 1"),
      option(1, "Floor 2", { enabled: false, reason: "This floor's elevation could not be located." }),
      option(2, "Floor 3"),
    ]);
    render(<FloorControls />);

    const disabled = screen.getByRole("button", { name: "Floor 2" });
    expect(disabled).toBeInTheDocument();
    expect(disabled).toBeDisabled();
    expect(disabled.getAttribute("title")).toContain("could not be located");
    // Every other floor and the 3D button stay available.
    expect(screen.getByRole("button", { name: "Floor 1" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Floor 3" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "3D" })).toBeEnabled();
  });

  it("does not act on a disabled floor", async () => {
    ready([option(0, "Floor 1", { enabled: false, reason: "unavailable" })]);
    const spy = vi.spyOn(controller, "selectFloor").mockResolvedValue();
    render(<FloorControls />);
    await userEvent.click(screen.getByRole("button", { name: "Floor 1" }));
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("what the buttons ask for (task28 §1.2, §1.3)", () => {
  it("requests the selected band, and null for 3D", async () => {
    ready(THREE_FLOORS);
    const spy = vi.spyOn(controller, "selectFloor").mockResolvedValue();
    render(<FloorControls />);

    await userEvent.click(screen.getByRole("button", { name: "Floor 3" }));
    expect(spy).toHaveBeenLastCalledWith(2);
    await userEvent.click(screen.getByRole("button", { name: "3D" }));
    expect(spy).toHaveBeenLastCalledWith(null);
  });

  it("adds no tree, storey browser, visibility checklist, or plane editor", () => {
    ready(THREE_FLOORS);
    render(<FloorControls />);
    expect(screen.queryAllByRole("tree")).toHaveLength(0);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.queryAllByRole("slider")).toHaveLength(0);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
  });
});
