// Motion/profile state machine + frame-time hysteresis (tasks/task18.md §2/§3).
import { afterEach, describe, expect, it, vi } from "vitest";

import { ViewerPerformanceController } from "../src/viewer/ViewerPerformanceController";

describe("ViewerPerformanceController", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("dedupes motion notifications: only fires on a real transition", () => {
    const perf = new ViewerPerformanceController();
    const calls: string[] = [];
    perf.onMotionChange((s) => calls.push(s));
    perf.setMotion("moving");
    perf.setMotion("moving"); // duplicate — no notification
    perf.setMotion("resting");
    expect(calls).toEqual(["moving", "resting"]);
  });

  it("unsubscribe stops further motion notifications", () => {
    const perf = new ViewerPerformanceController();
    const calls: string[] = [];
    const off = perf.onMotionChange((s) => calls.push(s));
    perf.setMotion("moving");
    off();
    perf.setMotion("resting");
    expect(calls).toEqual(["moving"]);
  });

  it("dedupes profile notifications the same way", () => {
    const perf = new ViewerPerformanceController();
    const calls: string[] = [];
    perf.onProfileChange((p) => calls.push(p));
    perf.setProfile("large-model");
    perf.setProfile("large-model");
    perf.setProfile("balanced");
    expect(calls).toEqual(["large-model", "balanced"]);
  });

  it("starts not sustained-slow and waits for a full frame-time window before judging", () => {
    const perf = new ViewerPerformanceController();
    expect(perf.isSustainedSlow()).toBe(false);
    for (let i = 0; i < 29; i++) perf.recordFrameTime(100); // slow, but window not full yet
    expect(perf.isSustainedSlow()).toBe(false);
  });

  it("flips sustained-slow once a full window of slow frames is recorded, past cooldown", () => {
    const perf = new ViewerPerformanceController();
    vi.spyOn(performance, "now").mockReturnValue(10_000);
    for (let i = 0; i < 30; i++) perf.recordFrameTime(50); // 50ms/frame ~20fps, below the 30fps target
    expect(perf.isSustainedSlow()).toBe(true);
  });

  it("does not flip back on fast frames within the cooldown window", () => {
    const perf = new ViewerPerformanceController();
    vi.spyOn(performance, "now").mockReturnValue(10_000);
    for (let i = 0; i < 30; i++) perf.recordFrameTime(50);
    expect(perf.isSustainedSlow()).toBe(true);

    vi.spyOn(performance, "now").mockReturnValue(10_500); // 500ms later — inside the 1500ms cooldown
    for (let i = 0; i < 30; i++) perf.recordFrameTime(5);
    expect(perf.isSustainedSlow()).toBe(true); // cooldown holds the prior verdict
  });

  it("flips back to fast once the cooldown elapses and the window is fully fast", () => {
    const perf = new ViewerPerformanceController();
    vi.spyOn(performance, "now").mockReturnValue(10_000);
    for (let i = 0; i < 30; i++) perf.recordFrameTime(50);
    expect(perf.isSustainedSlow()).toBe(true);

    vi.spyOn(performance, "now").mockReturnValue(12_000); // past the 1500ms cooldown
    for (let i = 0; i < 30; i++) perf.recordFrameTime(5);
    expect(perf.isSustainedSlow()).toBe(false);
  });

  it("notifies onSustainedSlowChange only on real flips, not every recordFrameTime call", () => {
    const perf = new ViewerPerformanceController();
    const calls: boolean[] = [];
    perf.onSustainedSlowChange((slow) => calls.push(slow));
    vi.spyOn(performance, "now").mockReturnValue(10_000);
    for (let i = 0; i < 30; i++) perf.recordFrameTime(50); // flips true once, at sample 30
    expect(calls).toEqual([true]);

    vi.spyOn(performance, "now").mockReturnValue(12_000);
    for (let i = 0; i < 30; i++) perf.recordFrameTime(5); // flips back to false once
    expect(calls).toEqual([true, false]);
  });

  it("reset clears motion and frame-time state; profile is left for the caller to re-set", () => {
    const perf = new ViewerPerformanceController();
    perf.setMotion("moving");
    perf.setProfile("large-model");
    vi.spyOn(performance, "now").mockReturnValue(10_000);
    for (let i = 0; i < 30; i++) perf.recordFrameTime(50);
    expect(perf.isSustainedSlow()).toBe(true);

    perf.reset();
    expect(perf.getMotion()).toBe("resting");
    expect(perf.isSustainedSlow()).toBe(false);
    expect(perf.getProfile()).toBe("large-model"); // profile is re-detected per load, not reset here
  });
});
