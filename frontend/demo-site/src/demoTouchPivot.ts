// Touch orbit pivot (spec_v013 §6.8).
//
// The application resolves an orbit pivot from whatever is under the cursor, but
// only for the middle mouse button — that is the button it maps to ROTATE, and
// on a desktop nothing else orbits:
//
//     if (e.button === 1) { void this.setPivotFromCursor(e); ... }
//
// A touch reports `button === 0`, so that branch never runs on a phone. Meanwhile
// `configureControls` sets only `mouseButtons` and leaves `touches` at the
// camera-controls default, where one finger rotates. The result is a model that
// orbits around whatever the target happened to be — usually the centre of the
// last fit — rather than around the thing being dragged, which feels like the
// building is sliding away from your finger.
//
// This restores the application's own behaviour on touch by calling the same
// pivot resolution it already uses. It resolves nothing itself: no raycasting,
// no target maths, no second definition of what a pivot is. If that method ever
// changes, touch changes with it.
//
// Reaching a private method needs a cast, for the same reason as demoCamera:
// the alternative is editing `src/` for a device the application was not built
// for, and spec_v013 forbids it.

import { controller } from "../../src/state/controller";

interface PivotReach {
  setPivotFromCursor?: (event: PointerEvent) => Promise<void> | void;
}

/**
 * Count of touches this module has forwarded as pivot requests.
 *
 * A deliberate test seam. Whether the pivot lands in the right place is the
 * application's own logic and its own tests; what belongs to this module is
 * narrower — that a touch reaches `setPivotFromCursor` and a mouse press does
 * not. Nothing else can observe that from outside, and a browser test that
 * cannot fail is worse than none.
 */
declare global {
  interface Window {
    __demoTouchPivotCount?: number;
  }
}

/**
 * Make a touch set the orbit pivot, the way a middle-drag does with a mouse.
 * Returns a teardown function; a no-op one if the viewer container is absent.
 */
export function enableTouchPivot(): () => void {
  const container = document.querySelector<HTMLElement>(".viewer-canvas");
  if (!container) return () => {};

  const onPointerDown = (event: PointerEvent) => {
    if (event.pointerType !== "touch") return;
    // Only the finger that begins the gesture. A pinch's second finger would
    // otherwise re-pivot mid-gesture, moving the ground under a zoom.
    if (!event.isPrimary) return;

    const reach = controller.viewer as unknown as PivotReach;
    try {
      void reach.setPivotFromCursor?.(event);
      window.__demoTouchPivotCount = (window.__demoTouchPivotCount ?? 0) + 1;
    } catch {
      // A pivot is an improvement to a gesture, never a precondition for one.
      // If this fails the orbit still works, just around the previous target.
    }
  };

  // Capture on the CONTAINER, so this runs before camera-controls' own listener
  // on the canvas inside it and the pivot is being resolved before the orbit
  // starts consuming movement.
  container.addEventListener("pointerdown", onPointerDown, { capture: true });
  return () => container.removeEventListener("pointerdown", onPointerDown, { capture: true });
}
