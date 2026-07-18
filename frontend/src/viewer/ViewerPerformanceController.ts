// Single source of truth for viewer motion/profile state (tasks/task18.md
// §2/§3/§4/§5). Pure state + pub/sub — no THREE/DOM dependency — so pixel
// ratio, Fragments throttling, and edge motion-hiding all read the same
// decision instead of each polling camera-controls/frame-time independently.
import type { Profile } from "./profileDetection";

export type { Profile };
export type MotionState = "resting" | "moving";

const FRAME_RING_SIZE = 30;
/** ~30fps frame budget — the interaction target this task protects (task18 §3). */
const SLOW_FRAME_MS = 1000 / 30;
/** Minimum time between sustained-slow verdict flips — avoids oscillating on one slow frame. */
const VERDICT_COOLDOWN_MS = 1500;

type Unsubscribe = () => void;

function nowMs(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

export class ViewerPerformanceController {
  private motion: MotionState = "resting";
  private profile: Profile = "balanced";
  private readonly motionListeners = new Set<(state: MotionState) => void>();
  private readonly profileListeners = new Set<(profile: Profile) => void>();
  private readonly sustainedSlowListeners = new Set<(slow: boolean) => void>();

  private frameRing = new Float32Array(FRAME_RING_SIZE);
  private frameCursor = 0;
  private frameFilled = 0;
  private sustainedSlow = false;
  private lastVerdictAt = 0;

  onMotionChange(fn: (state: MotionState) => void): Unsubscribe {
    this.motionListeners.add(fn);
    return () => this.motionListeners.delete(fn);
  }

  onProfileChange(fn: (profile: Profile) => void): Unsubscribe {
    this.profileListeners.add(fn);
    return () => this.profileListeners.delete(fn);
  }

  /** Fires only on a real sustained-slow flip (task18 §3's frame-time-driven pixel-ratio step). */
  onSustainedSlowChange(fn: (slow: boolean) => void): Unsubscribe {
    this.sustainedSlowListeners.add(fn);
    return () => this.sustainedSlowListeners.delete(fn);
  }

  getMotion(): MotionState {
    return this.motion;
  }

  /** One notification per real transition — repeated calls with the same state are free. */
  setMotion(state: MotionState): void {
    if (state === this.motion) return;
    this.motion = state;
    this.motionListeners.forEach((fn) => fn(state));
  }

  getProfile(): Profile {
    return this.profile;
  }

  setProfile(profile: Profile): void {
    if (profile === this.profile) return;
    this.profile = profile;
    this.profileListeners.forEach((fn) => fn(profile));
  }

  /**
   * Feed one frame's duration. Only evaluated once the ring buffer is full
   * (a stable window, not a single-sample reaction), and only allowed to flip
   * the `sustainedSlow` verdict once per `VERDICT_COOLDOWN_MS` — this is the
   * hysteresis/cooldown the pixel-ratio policy requires so resolution never
   * changes on one individual slow frame (task18 §3).
   */
  recordFrameTime(ms: number): void {
    this.frameRing[this.frameCursor] = ms;
    this.frameCursor = (this.frameCursor + 1) % FRAME_RING_SIZE;
    if (this.frameFilled < FRAME_RING_SIZE) this.frameFilled += 1;
    this.evaluateFrameTime();
  }

  private evaluateFrameTime(): void {
    if (this.frameFilled < FRAME_RING_SIZE) return;
    const now = nowMs();
    if (now - this.lastVerdictAt < VERDICT_COOLDOWN_MS) return;
    let sum = 0;
    for (let i = 0; i < FRAME_RING_SIZE; i++) sum += this.frameRing[i]!;
    const avg = sum / FRAME_RING_SIZE;
    const nextSlow = avg > SLOW_FRAME_MS;
    if (nextSlow !== this.sustainedSlow) {
      this.sustainedSlow = nextSlow;
      this.lastVerdictAt = now;
      this.sustainedSlowListeners.forEach((fn) => fn(nextSlow));
    }
  }

  /** True when recent frame times sustain below the 30fps target (task18 §3). */
  isSustainedSlow(): boolean {
    return this.sustainedSlow;
  }

  /** Clear per-model runtime state on unload — profile is re-detected per load, not carried over. */
  reset(): void {
    this.motion = "resting";
    this.frameRing = new Float32Array(FRAME_RING_SIZE);
    this.frameCursor = 0;
    this.frameFilled = 0;
    this.sustainedSlow = false;
    this.lastVerdictAt = 0;
  }
}
