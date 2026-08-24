// Opening camera pose for the demo (spec_v013 §6.5).
//
// The application's `fitAll()` has already run by the time this is called, and
// its framing DISTANCE is good — it accounts for the viewport obstruction from
// the chat panel, the lens, and the model's bounds. What it cannot know is which
// direction looks like a building rather than an elevation drawing, because it
// frames from wherever the camera happens to face.
//
// So this keeps the distance the application computed and changes only the
// direction, then tightens by a small factor. Deriving a distance from the model
// bounds independently was the first attempt and it framed the corner of the
// roof: the application's own number is better than a reconstruction of it.
//
// Demo-only presentation. Nothing under `src/` changes, the real application's
// framing is untouched, and this runs exactly once — the visitor's first orbit
// takes full control back.

import * as THREE from "three";

import { controller } from "../../src/state/controller";

/** Where the camera sits relative to the target: to one side, and above. */
const DIRECTION = new THREE.Vector3(1, 0.78, 1).normalize();

/** Fraction of the application's own fit distance. Slightly closer, not close. */
const ZOOM = 0.85;

/**
 * Aims slightly BELOW the model's centre, as a fraction of the view distance.
 * The camera's target is what lands at the centre of the frame, so lowering it
 * raises the building — which is the fix for a model sitting on the bottom edge.
 */
const TARGET_DROP = 0.03;

/**
 * The viewer's camera controls are private to `ViewerAdapter`, and reaching them
 * needs a cast. The alternative was a demo-only parameter on the adapter, which
 * would mean editing `src/` for a cosmetic choice — a worse trade than one
 * narrow, guarded reach that fails silently if the internals move.
 */
interface CameraReach {
  world?: {
    camera?: {
      controls?: {
        getPosition: (out: THREE.Vector3) => THREE.Vector3;
        getTarget: (out: THREE.Vector3) => THREE.Vector3;
        setLookAt: (
          px: number,
          py: number,
          pz: number,
          tx: number,
          ty: number,
          tz: number,
          enableTransition: boolean,
        ) => Promise<void> | void;
      };
    };
  };
}

/**
 * Re-aim the camera to a three-quarter aerial view, keeping the distance the
 * application's own fit chose. Returns false when the viewer internals are not
 * shaped as expected, in which case that fit simply stands.
 */
export async function frameForDemo(): Promise<boolean> {
  const controls = (controller.viewer as unknown as CameraReach).world?.camera?.controls;
  if (!controls) return false;

  try {
    const position = controls.getPosition(new THREE.Vector3());
    const target = controls.getTarget(new THREE.Vector3());

    const distance = position.distanceTo(target) * ZOOM;
    if (!Number.isFinite(distance) || distance <= 0) return false;

    const aim = target.clone().setY(target.y - distance * TARGET_DROP);
    const next = aim.clone().addScaledVector(DIRECTION, distance);

    // No transition: this is the opening frame, not a move away from one the
    // visitor chose. Animating would show them the default view first, which is
    // the thing being avoided.
    await controls.setLookAt(next.x, next.y, next.z, aim.x, aim.y, aim.z, false);
    return true;
  } catch {
    return false;
  }
}
