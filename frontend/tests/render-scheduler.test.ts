// Manual-mode invalidation scheduler (tasks/task18.md §2). No real WebGL —
// a fake renderer/components pair shaped like the installed
// @thatopen/components API, matching the Object.assign-fake convention used
// throughout viewer-adapter.test.ts.
import * as OBC from "@thatopen/components";
import { describe, expect, it } from "vitest";

import { RenderScheduler } from "../src/viewer/RenderScheduler";

function makeFakeRenderer() {
  const listeners = new Set<() => void>();
  const renderer = {
    mode: OBC.RendererMode.AUTO,
    needsUpdate: false,
    onAfterUpdate: {
      add: (fn: () => void) => listeners.add(fn),
      remove: (fn: () => void) => listeners.delete(fn),
    },
  };
  return { renderer, tick: () => listeners.forEach((fn) => fn()) };
}

function makeFakeComponents() {
  return { enabled: true, init: () => {} };
}

describe("RenderScheduler", () => {
  it("switches the renderer to MANUAL mode on construction", () => {
    const { renderer } = makeFakeRenderer();
    const components = makeFakeComponents();
    new RenderScheduler(components as never, renderer as never);
    expect(renderer.mode).toBe(OBC.RendererMode.MANUAL);
  });

  it("requestFrame sets needsUpdate once; a tick with no holds does not re-arm it", () => {
    const { renderer, tick } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.requestFrame("manual");
    expect(renderer.needsUpdate).toBe(true);

    // Simulate the library consuming the flag when it renders.
    renderer.needsUpdate = false;
    tick();
    expect(renderer.needsUpdate).toBe(false); // no hold active — nothing re-arms it
  });

  it("multiple same-tick invalidations collapse into one pending frame", () => {
    const { renderer } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.requestFrame("highlight");
    scheduler.requestFrame("edges");
    scheduler.requestFrame("fit");
    expect(renderer.needsUpdate).toBe(true); // still just one pending frame, not stacked
  });

  it("hold keeps re-arming needsUpdate every tick until released", () => {
    const { renderer, tick } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.hold("camera-motion");
    expect(scheduler.isHeld()).toBe(true);

    for (let i = 0; i < 5; i++) {
      renderer.needsUpdate = false; // simulate the library rendering and clearing it
      tick();
      expect(renderer.needsUpdate).toBe(true); // re-armed every tick while held
    }
  });

  it("releasing the last hold renders one final frame, then stops", () => {
    const { renderer, tick } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.hold("camera-motion");
    renderer.needsUpdate = false;
    tick();
    expect(renderer.needsUpdate).toBe(true); // frame requested by the tick while held

    scheduler.release("camera-motion");
    expect(scheduler.isHeld()).toBe(false);
    // The frame already armed above still renders once (simulated by the caller
    // consuming it) — the next tick after release must NOT re-arm it again.
    renderer.needsUpdate = false;
    tick();
    expect(renderer.needsUpdate).toBe(false);
  });

  it("two independent hold reasons both keep the frame armed until both release", () => {
    const { renderer, tick } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.hold("camera-motion");
    scheduler.hold("pointer-drag");
    scheduler.release("camera-motion");
    renderer.needsUpdate = false;
    tick();
    expect(renderer.needsUpdate).toBe(true); // pointer-drag still held

    scheduler.release("pointer-drag");
    renderer.needsUpdate = false;
    tick();
    expect(renderer.needsUpdate).toBe(false);
  });

  it("suspend halts the entire Components loop, not just the draw call", () => {
    const { renderer } = makeFakeRenderer();
    const components = makeFakeComponents();
    const scheduler = new RenderScheduler(components as never, renderer as never);
    scheduler.suspend();
    expect(components.enabled).toBe(false);
    expect(scheduler.isSuspended()).toBe(true);
  });

  it("suspend blocks further requestFrame calls until resume", () => {
    const { renderer } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.suspend();
    renderer.needsUpdate = false;
    scheduler.requestFrame("manual");
    expect(renderer.needsUpdate).toBe(false);
  });

  it("resume re-enables Components and renders exactly one bounded frame", () => {
    const { renderer } = makeFakeRenderer();
    let initCalls = 0;
    const components = { enabled: true, init: () => { initCalls += 1; } };
    const scheduler = new RenderScheduler(components as never, renderer as never);
    scheduler.suspend();
    renderer.needsUpdate = false;
    scheduler.resume();
    expect(initCalls).toBe(1);
    expect(renderer.needsUpdate).toBe(true);
    expect(scheduler.isSuspended()).toBe(false);
  });

  it("resume without a prior suspend is a no-op", () => {
    const { renderer } = makeFakeRenderer();
    let initCalls = 0;
    const components = { enabled: true, init: () => { initCalls += 1; } };
    const scheduler = new RenderScheduler(components as never, renderer as never);
    scheduler.resume();
    expect(initCalls).toBe(0);
  });

  it("dispose removes the tick listener so holds no longer re-arm frames", () => {
    const { renderer, tick } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.hold("camera-motion");
    scheduler.dispose();
    renderer.needsUpdate = false;
    tick();
    expect(renderer.needsUpdate).toBe(false);
  });

  it("dispose prevents further requestFrame calls", () => {
    const { renderer } = makeFakeRenderer();
    const scheduler = new RenderScheduler(makeFakeComponents() as never, renderer as never);
    scheduler.dispose();
    renderer.needsUpdate = false;
    scheduler.requestFrame("manual");
    expect(renderer.needsUpdate).toBe(false);
  });
});
