# Task 22: Roll back the Task 18 adaptive main-viewer machinery

## Origin

Owner-reported, direct instruction (not a pre-written task): after Task 20, model 2 still lagged
during pan/orbit/zoom on the real RTX 5080 Laptop GPU — worse than the pre-Task-18 viewer. This is
the exact owner decision point reserved by `tasks/task20_done.md` §9 ("If the real-hardware result is
still worse than the pre-Task-18 viewer … the next decision may be to revert the remaining Task 18
main-viewer changes … that rollback requires a separate explicit owner decision"). The owner chose
the full Task 18 main-viewer rollback.

## Diagnosis

On the owner's GPU the raw per-frame render cost was never the bottleneck (edges hidden or not, at
dpr 0.85, model 2's ~1M triangles are trivial for a 5080). The regression was the per-*gesture*
transition work Task 18/20 added, which fires on every start and stop of movement:

- a forced `fragments.core.update(true)` (a worker round trip) on every camera `rest`;
- base-edge hide on every `wake` and restore 150 ms after every `rest`;
- pixel-ratio reallocation (`setPixelRatio`) on every motion transition.

Natural navigation is many small start/stop nudges, so this machinery ran constantly, each cycle a
hitch. The pre-Task-18 viewer had none of it — continuous fixed-quality rendering, heavier while idle
but smooth during interaction. Verified in the installed `@thatopen/fragments` source that
`useCamera()` does not auto-update on camera movement (it only snapshots camera state), so removing
the periodic/rest update work does not silently reintroduce a library-driven update loop.

## Change (localized, reversible)

Removed (deleted files): `RenderScheduler.ts`, `ViewerPerformanceController.ts`,
`ViewerInstrumentation.ts`, `ViewerInstrumentationOverlay.tsx`, and their two dedicated test files
(`render-scheduler.test.ts`, `viewer-performance-controller.test.ts`).

Edited `ViewerAdapter.ts`:
- renderer returns to `SimpleRenderer`'s default automatic continuous rendering (no manual mode, no
  scheduler, no render holds, no `requestFrame` call sites);
- Fragments LOD refresh is one plain `updateFragments()` → `core.update(true)` on model load, camera
  `rest`, and an actual highlight/material change — the pre-Task-18 cadence; no per-motion/per-tick
  update, no `maxUpdateRate` juggling, no forced-update race guard;
- removed adaptive pixel ratio, Fragments throttle, motion state, edge motion-hide wiring, per-tick
  frame sampling, screen-size-LOD invocation, and the instrumentation snapshot;
- `document.hidden` suspension dropped with the scheduler (accepted trade-off: higher idle GPU).

Edited `viewerTheme.ts` (removed dead `PIXEL_RATIO` / `FRAGMENTS_THROTTLE_MS`), `App.tsx` (removed the
instrumentation overlay), `StatusReadout.tsx` + `App.css` (removed the dead adaptive-profile button).

Kept unchanged, deliberately:
- `EdgeOverlay.ts` — spatially chunked, frustum-culled overlay (strictly better than pre-Task-18's
  single `frustumCulled = false` whole-model object). Its `setMotion`/`updateLod`/highlight-overlay
  methods remain but are no longer called by the adapter.
- Task 19 UX (pick-through-transparency, view-offset centering, base plane at `model.box.min.y`).
- `PreviewScene.ts` component-preview power management (separate from the main viewer, never
  implicated in the lag). `profileDetection.ts` / `Profile` retained only to size the preview.

## Validation

- Frontend unit suite: **178 tests / 15 files, all green** (25-test drop = exactly the two deleted
  machinery test files; EdgeOverlay + adapter profile-override tests unchanged and passing).
- `npm run typecheck`, `npm run lint`, `npm run build`: all clean.
- Real-hardware interaction smoothness: the owner's to confirm on the RTX 5080. This change is a
  removal that restores the pre-Task-18 rendering path the owner remembers as smooth (plus retained
  chunk culling), not a new mechanism.

Spec reconciled: `specs/spec_v006_frontend_application.md` §28 (supersedes §25.1/§25.2/§25.3/§25.8 and
§27.3–§27.5 for the main viewer). Database, vectors, and the prepared artifact format unchanged.
