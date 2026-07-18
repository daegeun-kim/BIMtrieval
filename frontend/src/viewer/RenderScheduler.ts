// Centralized, invalidation-driven render scheduling (tasks/task18.md §2).
//
// Rides `@thatopen/components`'s always-on internal tick rather than owning a
// second RAF chain: `Components.update()` (verified in
// node_modules/@thatopen/components/dist/index.mjs) reschedules itself via
// `requestAnimationFrame` every tick regardless of camera motion, and
// `SimpleRenderer.update()` only calls `three.render(...)` when `mode` is
// MANUAL and `needsUpdate` is true. This class's only job is setting
// `needsUpdate` at the right moments, so it never draws an unchanged scene on
// an otherwise-idle tick.
import * as OBC from "@thatopen/components";

export type InvalidationReason =
  | "camera-motion"
  | "pointer-drag"
  | "resize"
  | "load"
  | "unload"
  | "highlight"
  | "edges"
  | "fit"
  | "pixel-ratio"
  | "base-plane"
  | "viewport-offset"
  | "visibility-resume"
  | "manual";

/** Reasons that keep requesting a frame every tick until explicitly released. */
type HoldReason = "camera-motion" | "pointer-drag";

export class RenderScheduler {
  private readonly holds = new Set<HoldReason>();
  private suspended = false;
  private disposed = false;

  private readonly rearm = (): void => {
    // While any hold is active, keep re-arming needsUpdate every tick so
    // continuous camera motion/dragging keeps rendering. Once the last hold
    // is released, this stops firing and the already-in-flight frame (set by
    // the release-time requestFrame call below) renders once more and stops
    // naturally — no special-cased "final frame" branch needed.
    if (this.holds.size > 0) this.renderer.needsUpdate = true;
  };

  constructor(
    private readonly components: OBC.Components,
    private readonly renderer: OBC.SimpleRenderer,
  ) {
    this.renderer.mode = OBC.RendererMode.MANUAL;
    this.renderer.onAfterUpdate.add(this.rearm);
  }

  /** One-shot: render the next tick. Multiple calls before that tick collapse for free. */
  requestFrame(_reason: InvalidationReason): void {
    if (this.suspended || this.disposed) return;
    this.renderer.needsUpdate = true;
  }

  /** Keep requesting a frame every tick until released (camera motion, pointer drag). */
  hold(reason: HoldReason): void {
    this.holds.add(reason);
    this.requestFrame(reason);
  }

  /** Release a hold. If none remain, the frame already in flight renders once more and stops. */
  release(reason: HoldReason): void {
    this.holds.delete(reason);
  }

  isHeld(): boolean {
    return this.holds.size > 0;
  }

  /**
   * Halt the ENTIRE Components tick loop, not just the WebGL render call
   * (`Components.enabled = false` — a documented public field: "If disabled,
   * the animation loop will be stopped"). Used for `document.hidden`, where
   * camera-controls damping and Fragments culling should stop too, not only
   * the draw call.
   */
  suspend(): void {
    if (this.suspended) return;
    this.suspended = true;
    this.components.enabled = false;
  }

  /**
   * Resume the loop and render exactly one correct frame — no accumulated
   * burst of stale frames. `Components.init()` is the library's own
   * documented restart path ("starts the animation loop, sets the enabled
   * flag to true, and calls the update method"); it only flips flags and
   * kicks the tick loop, it does not recreate the scene/camera/renderer.
   */
  resume(): void {
    if (!this.suspended) return;
    this.suspended = false;
    this.components.init();
    this.requestFrame("visibility-resume");
  }

  isSuspended(): boolean {
    return this.suspended;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.renderer.onAfterUpdate.remove(this.rearm);
    this.holds.clear();
  }
}
