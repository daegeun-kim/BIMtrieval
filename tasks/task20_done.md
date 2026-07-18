# Task 20: Remove Task 18 Interaction-Time Viewer Regression

Task 18 reduced stationary GPU usage, but model 2 now lags more severely during orbit, pan, and
zoom on the owner's RTX 5080 Laptop GPU. Correct the interaction regression without adding another
broad optimization system.

Preserve the parts of Task 18 that worked:

- manual/invalidation-driven rendering while stationary;
- no continuing identical WebGL renders after the view settles;
- hidden-tab rendering suspension;
- spatial edge chunks and frustum culling when stationary;
- component-preview power management;
- current viewer appearance after the camera settles.

Keep this change isolated and reversible. Do not refactor unrelated viewer behavior. Do not add
occlusion culling, category/storey hiding, new artifact formats, or backend/ingestion changes.

## Diagnosed regression

Model 2 contains approximately:

```text
27,388 entities
5,370,488 custom edge vertices
71 spatial edge chunks
approximately 86 MB of RGBA float edge-color data
```

The Task 18 motion handler currently hides base edges by iterating entity ranges, rewriting the
alpha value of millions of edge vertices, and marking large color-buffer ranges for GPU upload.
It repeats the work when motion rests. Alpha zero also does not remove the geometry from the draw:
the line objects and vertices can still be submitted while visually transparent.

Task 18 also added Fragments updates during camera movement every 200 ms in large-model mode. The
worker/LOD/tile processing can introduce periodic frame stalls even if average GPU utilization is
lower.

Treat these as the first causes to correct. Do not assume lower GPU percentage means smoother
interaction; frame pacing and worst-frame duration are the acceptance criteria.

## Objective

1. Never rewrite or upload the full base-edge color data merely because camera motion starts or
   stops.
2. During camera movement, do not submit base-model custom edges for rendering.
3. Keep selected, manually selected, and query-primary blue edges visible during movement.
4. Restore the stationary base-edge appearance after camera rest without rebuilding geometry.
5. Stop periodic Fragments updates during motion; perform the final forced update at rest.
6. Correct frame-time measurement so an idle interval is not counted as a slow rendered frame.
7. Validate the result on the owner's real browser/GPU, not only headless software rendering.

## 1. Replace per-vertex alpha hiding

Remove the motion path that calls `setBaseEdgeAlpha()` across the entire edge range map. Camera
motion transitions must not:

- loop over all 27,000+ entity edge ranges;
- rewrite millions of per-vertex alpha values;
- mark whole-chunk color buffers dirty;
- upload the approximately 86 MB edge-color dataset;
- rebuild `EdgesGeometry` or repartition chunks.

Do not treat alpha zero as equivalent to hiding geometry.

The existing per-entity color-buffer update remains valid when an entity's semantic role actually
changes. This task only removes bulk color rewriting caused by camera movement.

## 2. Separate base-edge submission from moving highlight edges

Structure the runtime edge representation so base edges can be excluded from rendering during
motion with bounded object/material state changes.

Required behavior:

- stationary: render the spatially chunked base-edge overlay with the established colors;
- motion start: stop submitting base-edge drawables by changing chunk/object visibility or an
  equivalently cheap geometry-level draw control;
- motion: retain edges for query-primary, manually selected, and focused/unfocused blue result
  objects;
- camera rest: after the existing 150 ms restoration delay, make the applicable base chunks
  visible again and request one frame;
- motion resuming during the delay cancels restoration;
- no full edge-color upload occurs on hide or restore.

The preferred implementation is:

```text
spatial base-edge chunks
    visible = false during motion

small dynamic highlight-edge overlay
    contains only current query-primary/manual result edges
    remains visible during motion
```

Reuse already extracted geometry/index information where practical. Do not create one Three.js
object per IFC entity, perform another whole-model worker transfer on every selection, or clone the
complete edge dataset.

The highlight overlay must update only when the actual highlighted ID set changes. Camera movement
alone must not reconstruct it. Keep it bounded to the current query-primary/manual selection set
and dispose it on role clear, model switch, reset, and viewer disposal.

If an even simpler supported representation can hide base edges cheaply while retaining only
highlight edges, it is acceptable, but it must satisfy the measurable constraints above. Do not
retain hidden base geometry in active draw submission through alpha-zero blending.

## 3. Return Fragments updates to rest-only behavior

Remove the per-render-tick/moving path that calls unforced `fragments.core.update()` every 120 or
200 ms.

During ordinary orbit, pan, and zoom:

- do not request periodic Fragments LOD/tile updates;
- continue rendering the currently available Fragments state;
- do not start overlapping worker update promises.

When camera motion rests:

1. perform one guaranteed forced `fragments.core.update(true)`;
2. await its supported completion;
3. update stationary edge LOD/culling;
4. restore base edges after the 150 ms delay;
5. render the final settled view.

Keep forced updates required by model load, actual highlight/material changes, resize/visibility
restoration, and other existing non-motion state changes. Remove only the periodic camera-motion
updates.

Do not add a slower moving interval in this task. First establish whether rest-only updates restore
smooth interaction. A moving update interval may be reconsidered later only if stale geometry is
visibly unacceptable and measured evidence supports it.

## 4. Keep adaptive resolution stable during an interaction

Preserve Task 18's accepted large-model moving pixel ratio, but prevent drawing-buffer churn during
one continuous camera interaction.

For model 2 / large-model mode:

```text
moving pixel ratio: 0.85
stationary pixel ratio: 1.25
```

Apply the moving value once when motion starts and the stationary value once after motion rests.
Do not change pixel ratio again in the middle of that same continuous interaction based on a
rolling slow-frame verdict.

The adaptive profile may still select balanced versus large-model before interaction. This task
only removes mid-interaction pixel-ratio reallocations that can add hitches.

## 5. Correct frame-time sampling

The current sampler derives frame duration from successive `renderer.onAfterUpdate` timestamps.
With manual rendering, the first frame after a stationary period can therefore include the entire
idle gap and be recorded as an extremely slow frame.

Correct the measurement so:

- idle time between rendered sequences is not counted as render-frame duration;
- a new motion sequence resets or re-arms the rolling interaction sample;
- only consecutive frames belonging to active rendering are used for moving FPS/frame-time
  decisions;
- instrumentation distinguishes frame interval from actual CPU/GPU render duration where the
  available APIs allow it;
- no instrumentation work is required in production when the development overlay is disabled.

Do not add complex GPU timing-query infrastructure in this task. A correct browser-frame interval
sample is sufficient.

## 6. Focused instrumentation

Extend the existing optional `?perf=1` instrumentation only as needed to expose:

```text
moving FPS
average moving frame interval
worst moving frame interval
base-edge chunks submitted during motion
highlight-edge drawables and vertices during motion
edge color bytes uploaded because of motion transitions
Fragments updates requested during motion
pixel-ratio changes during one interaction
```

Required expected values after the fix:

```text
base-edge chunks submitted during motion: 0
edge color bytes uploaded solely because motion started/stopped: 0
Fragments updates requested during motion: 0
mid-interaction pixel-ratio changes: 0
```

Instrumentation must not poll or traverse millions of vertices per frame.

## 7. Tests

Add focused tests proving:

- motion start does not call the bulk base-edge alpha rewrite;
- motion start hides all base-edge chunk objects through bounded visibility/draw state changes;
- motion start does not dirty/upload base-edge color attributes;
- query-primary/manual highlight edges remain visible during motion;
- camera movement alone does not rebuild the highlight overlay;
- role changes update the highlight overlay without cloning the whole edge model;
- rest restoration uses the 150 ms delay and is cancelled if motion resumes;
- base-edge chunks return after settled rest;
- no unforced Fragments updates occur during camera movement;
- exactly one final forced Fragments update occurs at rest;
- model load/highlight/resize/visibility updates still occur where required;
- large-model pixel ratio changes once at motion start and once at rest, not during motion;
- an idle interval is excluded from the first moving-frame sample;
- model switch/reset/dispose releases both base and highlight edge resources;
- stationary manual rendering and hidden-tab suspension remain correct.

Run the frontend unit/component tests, type check, lint, production build, and relevant Playwright
critical-path checks. Do not alter tests merely to accept worse behavior.

## 8. Real-hardware validation

Headless Chromium software rendering is not sufficient to declare this task complete. Use it for
functional regression only. The owner must validate performance on the actual RTX 5080 Laptop GPU.

Use the same model 2, viewport size, browser zoom, camera position, and interaction path before and
after the change. Test:

```text
Fit All then continuous orbit
continuous pan
continuous zoom
close facade view
query-primary results visible during motion
repeated short start/stop camera movements
stationary view after settlement
```

Record at minimum:

```text
average moving FPS
worst moving frame interval
visible long stalls
draw calls during motion
line vertices during motion
Fragments update count during motion
edge transition upload bytes
stationary draw calls over 3 seconds
```

Acceptance requires:

1. at least 30 FPS during normal model 2 orbit, pan, and zoom on the owner's machine;
2. no obvious periodic stutter caused by worker updates;
3. no visible freeze at motion start or 150 ms edge restoration;
4. base edges absent during motion and restored correctly at rest;
5. blue query-primary/manual edges remain visible during motion;
6. zero periodic Fragments updates during motion;
7. zero bulk base-edge color upload caused by motion transitions;
8. stationary main-viewer rendering remains near zero after settlement;
9. hidden-tab and preview power-management behavior remains correct.

Do not mark the real-hardware gate validated unless the owner has actually confirmed it. If Claude
cannot run against the owner's hardware interactively, leave this gate explicitly pending rather
than claiming completion from headless measurements.

## 9. Rollback decision record

Keep the Task 20 changes localized so they can be reverted without undoing unrelated work. At
completion, report separately:

- which Task 18 features remain active;
- which interaction-time mechanisms were removed;
- before/after model 2 measurements;
- whether the 30 FPS and no-visible-stall gates passed on the owner's hardware;
- any remaining bottleneck.

If the real-hardware result is still worse than the pre-Task-18 viewer, stop and report the
evidence. Do not add another optimization layer automatically. The next decision may be to revert
the remaining Task 18 main-viewer changes while preserving only independently useful fixes, and
that rollback requires a separate explicit owner decision.

## Definition of done

This task is complete only when:

- camera motion performs no whole-model edge alpha rewrite or bulk motion-triggered color upload;
- base-edge geometry is not submitted during motion;
- blue highlighted edges remain visible during motion;
- moving Fragments updates are removed and the final rest update remains correct;
- pixel ratio is stable within one continuous interaction;
- frame-time measurement excludes idle gaps;
- Task 18's stationary and hidden-tab power savings remain intact;
- automated frontend validation passes;
- the real-hardware performance gate is either owner-confirmed or truthfully marked pending;
- the implementation remains localized and reversible.

---

# Completion Report (2026-07-18)

Implemented and unit-tested against the frontend test suite. Full detail (rationale, per-file
mechanics) is recorded in `specs/spec_v006_frontend_application.md` §27, which amends §25.2/§25.3/
§25.4. This report summarizes what changed and the required rollback-decision record (task §9).

## What was removed (the diagnosed interaction-time regression)

1. `EdgeOverlay.setBaseEdgeAlpha()` — the bulk per-vertex alpha rewrite across all populated chunks
   on every motion start/stop, plus its per-chunk `addUpdateRange`/GPU color-upload trigger. Deleted
   entirely.
2. The periodic unforced `fragments.core.update()` call in `ViewerAdapter`'s per-tick handler
   (120ms balanced / 200ms large-model, while moving). Deleted entirely; verified by grep that the
   only remaining `fragments.core.update()` call site anywhere in the viewer is
   `forceFragmentsUpdate()`, always `force = true`.
3. `ViewerPerformanceController.onSustainedSlowChange -> applyPixelRatio()` — the reactive
   subscription that re-applied pixel ratio on every mid-gesture sustained-slow verdict flip.
   Deleted; `applyPixelRatio()` is now only invoked on a real motion/profile transition.
4. The unconditional per-tick `lastTickAt`-based frame-time sampling in `ViewerAdapter`'s tick
   handler, which could record a stationary period's idle gap as one giant "frame." Replaced with
   `ViewerPerformanceController.recordTick()`, which owns the timestamp and gates on motion state.

## What was added

1. `EdgeOverlay`: motion now toggles each chunk's `THREE.LineSegments.visible` (bounded, O(chunks),
   zero color-buffer writes) instead of rewriting alpha. A new shared `applyChunkVisibility()` helper
   unifies motion-hide and screen-size LOD culling so they can't fight each other.
2. `EdgeOverlay`: a new small, separate highlight overlay carries query-primary/manual/unfocused-
   primary edges during motion, built only from `recolor()`'s existing role-diff loop (never from
   camera motion), sliced from already-extracted chunk buffers — no worker call, no whole-model
   clone, one object total.
3. `ViewerPerformanceController.recordTick(nowMs)` + `getMovingFrameStats()` — correct, motion-gated
   frame-interval sampling, re-armed on every transition.
4. `ViewerInstrumentation`/`ViewerAdapter.getInstrumentationSnapshot()`: new fields — moving FPS/
   frame-interval avg+worst, base-edge chunks visible during motion, highlight-overlay vertex/
   drawable counts, pixel-ratio changes per interaction — surfaced in the dev-only `?perf=1` overlay.

## What Task 18 features remain active (unchanged)

- Manual/invalidation-driven main rendering (`RenderScheduler`) — stationary rendering still issues
  zero ongoing draw calls after settlement.
- Hidden-tab render suspension (`document.hidden` -> `Components.enabled = false`).
- Spatially chunked, frustum-culled edge overlay (71 chunks on model 2) and its screen-size LOD.
- Component preview power management (finite auto-rotation, visibility gating, fps caps).
- Adaptive profile detection (balanced / large-model) and the manual override control.
- Stationary/moving pixel-ratio ranges and Fragments update-rate configuration values themselves
  (`viewerTheme.ts` — no numeric constants changed).

## Before/after (structural, not GPU-measured — see gate below)

| Mechanism | Before (Task 18) | After (Task 20) |
|---|---|---|
| Motion edge-hide | rewrite alpha of every non-highlighted vertex across 71 chunks; GPU color upload every hide/restore | toggle `.visible` on ~71-160 chunk objects; zero color-buffer writes (unit-tested via `addUpdateRange` spy) |
| Highlighted edges during motion | spared inside the same per-vertex alpha sweep | small separate overlay, built only from role changes |
| Fragments updates while moving | unforced call every 120-200ms | none; only the rest-time forced call remains |
| Pixel ratio | could re-apply on any sustained-slow flip mid-gesture | applied once at motion start, once at rest |
| Frame-time sampling | every tick unconditionally, including idle gaps | motion-gated, re-armed on every transition |

## Automated validation

- Frontend unit suite: **203 tests / 17 files, all green** (11 new: 5 `EdgeOverlay` motion/highlight
  cases, 4 `ViewerPerformanceController.recordTick` cases).
- `npm run typecheck`, `npm run lint`, `npm run build`: all clean.
- Playwright critical-path: 1 of 2 green; the other fails on the same pre-existing, unrelated
  `evidence-disclosure` assertion documented in `task18_done.md`/`task19_done.md` (traced to
  already-uncommitted work removing `EvidenceDisclosure` rendering before Task 18 began) — this
  task's diff touches only `EdgeOverlay.ts`, `ViewerAdapter.ts`, `ViewerPerformanceController.ts`,
  `ViewerInstrumentation(Overlay)`, and their tests, none of which touch chat/evidence rendering.

## Real-hardware gate

**PENDING OWNER CONFIRMATION.** This report does not and cannot self-certify the 30 FPS / no-visible-
stall gates from headless testing (per task §8's explicit instruction and the documented headless-GL
gotcha in `task15_done.md`). The owner should reproduce Task 18's baseline model 2 / viewport /
camera path with `?perf=1` open and confirm:

- at least 30 FPS during normal orbit, pan, and zoom;
- no obvious periodic stutter from worker updates;
- no visible freeze at motion start or the 150ms edge restoration;
- base edges absent during motion, blue query-primary/manual edges remaining legible;
- zero periodic Fragments updates during motion (visible in the `?perf=1` overlay);
- stationary rendering remains near-zero after settlement, matching Task 18's own gate.

## Remaining bottleneck

None identified beyond the four removed mechanisms above — this task's own diagnosis attributed the
regression specifically to those four, and each has a direct, isolated, reversible fix with unit-test
coverage of the corrected behavior. If the owner's real-hardware confirmation still shows worse
interaction than the pre-Task-18 viewer, per task §9 the next step is a separate, explicitly-approved
decision to roll back the remaining Task 18 main-viewer changes — not layering another optimization
automatically.

## Status

```text
Alpha-rewrite motion hide: REMOVED (replaced with chunk visibility)
Highlight-edge separation: IMPLEMENTED
Periodic Fragments updates during motion: REMOVED
Mid-interaction pixel-ratio reallocation: REMOVED
Frame-time idle-gap exclusion: IMPLEMENTED
Focused instrumentation additions: IMPLEMENTED
Task 18 stationary/hidden-tab power savings: UNCHANGED, VALIDATED (unit tests re-run, all green)
Frontend regression (unit/typecheck/lint/build): VALIDATED
Playwright e2e: 1/2 VALIDATED, 1 PRE-EXISTING UNRELATED FAILURE (task17 scope, per task18/19 reports)
Real-hardware 30 FPS / no-visible-stall gate: PENDING OWNER CONFIRMATION
Specification reconciled (spec_v006 §27, amends §25.2/§25.3/§25.4): VALIDATED
Database/vector/model artifacts: UNCHANGED
```
