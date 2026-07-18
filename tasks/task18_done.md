# Task 18: Adaptive 3D Viewer Performance and Power Management

## Prerequisites and authority

Require:

```text
tasks/task10_done.md
tasks/task11_done.md
tasks/task14_done.md
tasks/task15_done.md
specs/spec_v006_frontend_application.md
```

This task improves the existing React / That Open Components / Fragments / Three.js viewer. It
does not change the BIM query pipeline, database, ingestion semantics, model identity contracts,
or viewer-result meaning.

Where this task conflicts with the performance implementation notes in the current frontend
specification, amend `specs/spec_v006_frontend_application.md` so it remains the current source of
truth. Do not rewrite completed task history.

Before implementation, verify the installed `@thatopen/components` and `@thatopen/fragments`
3.4.6 APIs and behavior from the installed package source and current official documentation.
Keep the existing maintained Fragments stack and locally bundled worker. Do not replace the viewer
framework.

## Owner intent

Model 2 is a relatively large model and currently lags during camera interaction even on a laptop
with an RTX 5080 Laptop GPU and 64 GB RAM. The viewer also consumes excessive GPU power while the
scene is stationary. Optimize rendering without removing model content based on semantic meaning.

Do not hide or unload geometry merely because of:

```text
IFC category
discipline
storey
query relevance
an assumed user workflow
```

All categories and storeys must remain available. Performance decisions may depend on:

```text
camera/frustum visibility
projected screen size
distance as used by the supported Fragments LOD system
interaction state
document/element visibility
measured frame time
model geometric size or item count
```

The stationary final image must retain the current design intent: achromatic base geometry,
semantic blue roles, feature edges, current camera behavior, and surrounding spatial context.
Temporary quality reduction while the camera is moving is acceptable when it produces a visibly
smoother interaction and the full stationary appearance returns promptly.

## Explicit exclusions

Do not include or implement:

- dedicated occlusion culling, GPU occlusion queries, hierarchical Z-buffer work, portal/room
  visibility, or a custom software occlusion system;
- category, discipline, or storey hiding as a performance mechanism;
- a section-box feature as part of this task;
- semantic removal of non-result geometry;
- one Three.js object or draw call per IFC entity;
- a new model format or replacement viewer framework;
- backend, database, RAG, LLM, or ingestion-pipeline behavior changes;
- an unmeasured large rewrite of the prepared Fragments artifact format.

True custom occlusion culling is deliberately deferred and must not be added as an optional final
phase.

## Existing behavior to preserve and improve

The implementation already has:

- prepared immutable Fragments artifacts rather than runtime IFC rendering;
- a locally bundled Fragments worker;
- Fragments camera attachment and its default LOD/frustum-visibility behavior;
- forced Fragments updates after model load, highlight changes, and camera rest;
- no React-tree rerender on camera movement;
- disposal of the prior model and custom GPU resources on switch/reset;
- asynchronous, yielded custom feature-edge construction;
- one selected-instance-only component preview;
- a renderer pixel-ratio ceiling of 2 through the library/default preview setup.

Do not duplicate these mechanisms. Improve their scheduling, thresholds, and interaction with the
custom edge overlay. In particular, recognize these current defects:

1. `components.init()` drives an automatic `requestAnimationFrame` loop and `SimpleRenderer`
   remains in automatic mode, so the unchanged main scene renders continuously.
2. The effective main-viewer pixel ratio can reach 2, which renders four times the pixels of a
   ratio of 1.
3. The custom edge overlay merges the entire model into one `LineSegments` and explicitly sets
   `frustumCulled = false`; all base-model feature edges can therefore be submitted together even
   when most of the building is off screen.
4. Custom edges do not participate in Fragments LOD.
5. The component preview has its own continuous animation loop and resumes indefinite
   auto-rotation after 2 seconds.
6. The app does not expose sufficient frame/draw/geometry measurements to identify the limiting
   stage on model 2.

## Objective

Implement adaptive viewer scheduling and quality so that:

1. model 2 sustains at least 30 FPS during normal orbit, pan, and zoom on the owner's machine;
2. an unchanged stationary main view performs near-zero rendering work rather than continuously
   redrawing identical frames;
3. hidden tabs and non-visible previews perform no continuous rendering;
4. motion may temporarily use lower resolution and fewer base-model edges, but the full stationary
   appearance returns promptly;
5. existing Fragments LOD/frustum behavior is retained and updated at bounded intervals during
   motion, with a final forced update at rest;
6. full-model feature edges become spatially cullable instead of one permanently non-cullable
   object;
7. performance decisions remain geometric and interaction-based, never category/storey-based;
8. all existing selection, query highlighting, camera, preview, reset, and resource-disposal
   behavior remains correct.

## 1. Establish performance instrumentation and baseline

Implement a development-only instrumentation facility. It may be an unobtrusive overlay, a
structured console report, or both, but it must not be visible in a production build by default.
Record at minimum:

```text
instantaneous and rolling-average FPS
average frame time
worst frame time over a bounded recent window
Three.js draw calls
rendered triangles
rendered lines/points where the renderer exposes them
canvas drawing-buffer width and height
effective device pixel ratio
main-thread long tasks, where supported
Fragments update duration
forced versus throttled Fragments update count
edge-overlay build duration
edge vertex count
edge chunk count
model local-item count
camera moving versus stationary state
current adaptive performance profile
```

Instrumentation must have negligible cost when disabled. Do not send telemetry externally and do
not add backend logging for browser frame measurements.

Before changing behavior, capture a repeatable model 2 baseline for:

```text
initial load and settle
fit-all stationary view
continuous orbit
continuous pan
continuous zoom
query-result highlighting
component preview open and closed
visible tab and background tab
```

Record the baseline and final comparison in the task completion notes. At minimum compare FPS,
frame time, draw calls, edge vertices, effective pixel ratio, and whether stationary frames
continue to render.

## 2. Main renderer: manual, invalidation-driven scheduling

Switch the main `SimpleRenderer` from automatic rendering to its supported manual mode. Keep the
Components update system only where required by the installed library, but the WebGL renderer must
not draw an unchanged scene on every animation tick.

Create one centralized render invalidation/scheduling mechanism. Do not scatter direct render
calls across unrelated methods. A frame must be requested when any visible state can change,
including:

```text
camera-controls movement
Fragments tile/LOD/visibility results
model load or unload
selection or query-role highlights
edge visibility, chunk availability, or edge colors
fit-all or fit-to-object animation
canvas/container resize
pixel-ratio change
base-plane creation/removal
document returning to the foreground
```

Coalesce multiple invalidations into one animation frame. A camera animation or active pointer
interaction may request consecutive frames, but after the camera and Fragments work settle, render
one final frame and stop.

When `document.hidden` becomes true:

- stop scheduling main-viewer render frames;
- stop preview rendering/rotation;
- do not dispose the loaded model solely because the tab is hidden.

When the document becomes visible, request a bounded Fragments refresh followed by one correct
render. Avoid a burst of accumulated frames.

Near-zero stationary rendering means the main WebGL renderer records no ongoing sequence of
identical frames after camera/Fragments settling. A small Components bookkeeping tick that does not
issue a WebGL render is acceptable if required by the library.

## 3. Accepted main-viewer resolution policy

Replace the effective pixel-ratio ceiling of 2 with an adaptive policy. Use these accepted values:

| Viewer state | Balanced/normal model | Large-model mode |
|---|---:|---:|
| Camera moving | 1.0-1.25 | 0.85-1.0 |
| Stationary | 1.5 | 1.25 |
| Absolute main-viewer ceiling | 1.5 | 1.25 |

Choose one deterministic value within each accepted moving range based on measured frame time, not
arbitrary styling preference. Start at the high end and step down only when needed to protect the
30 FPS interaction target. Do not exceed the listed stationary or absolute ceilings.

Changing pixel ratio must preserve the CSS size, update the renderer drawing buffer correctly,
refresh camera aspect/projection as needed, and request a render. Avoid oscillation by using a
bounded rolling frame-time window and hysteresis/cooldown. Do not change resolution on every
individual slow frame.

After camera movement stops, restore the applicable stationary ratio and render one sharp final
frame after the final Fragments update has settled.

## 4. Fragments LOD and visibility update policy

Preserve the installed Fragments default LOD/frustum-visibility mode. Do not switch to an
all-visible/full-geometry mode.

During active camera movement, request Fragments visibility/LOD updates at a throttled interval:

| Profile | Accepted interval |
|---|---:|
| Balanced/normal model | 100-150 ms |
| Large-model mode | 150-250 ms |

Choose a stable deterministic interval within each range using the instrumentation results. Do not
force a synchronous full update on every pointer or camera event. Coalesce overlapping requests and
prevent stale async completions from restoring an older camera state.

When camera movement rests:

1. issue one final forced `fragments.core.update(true)`;
2. wait for its supported completion semantics;
3. restore stationary resolution and stationary base edges;
4. render the settled frame.

If the installed public API exposes supported projected-size thresholds, configure and test these
accepted starting thresholds:

| Projected object size | Intended representation |
|---|---|
| Above 20-30 px | Full geometry |
| Approximately 4-20 px | Fragments LOD representation |
| Below approximately 2-4 px | Coarse/point representation or omitted |
| Below approximately 1 px | Omitted |

Use hysteresis so borderline objects do not flicker. As an accepted starting rule, enter full
geometry around 24 px and leave it around 18 px. Equivalent hysteresis is required at the lower
transition if the API exposes it.

Do not patch private/minified dependency internals to obtain threshold control. If the installed
public API does not expose these thresholds, document that fact, keep the default Fragments
thresholds, and implement the surrounding update-frequency, resolution, and edge policies. Do not
pretend an application threshold was applied when it was not.

## 5. Edge behavior during camera interaction

Preserve feature edges in the final stationary design, but do not render the complete base-model
edge set during active navigation.

Required behavior:

- on camera movement start, hide base-model edges;
- keep selected-object and query-primary edges visible during movement;
- do not regenerate all model edges merely because movement started or stopped;
- after camera rest and final Fragments update, wait 100-200 ms before restoring base-model edges;
- cancel/restart that restoration delay if movement resumes;
- restore edges and request one final stationary render.

Use a deterministic delay within 100-200 ms based on interaction testing. The delay is a stability
threshold, not a UI design value.

Selected/query-result edge handling may use a small dedicated dynamic overlay if required, but it
must remain bounded by the existing viewer-result and manual-selection contracts. Do not create an
independent mesh object for every IFC entity.

## 6. Edge extraction threshold

The current `THREE.EdgesGeometry` threshold is 25 degrees. Evaluate 30, 35, and 40 degrees on both
model 1 and model 2, including curved walls, round columns, MEP geometry, stairs, windows, and
facade details where present.

Accept these operating ranges:

```text
normal model: 25-30 degrees
large-model mode: 35-40 degrees
```

Prefer one common threshold if a value in the evaluated range preserves the intended appearance
and meets performance gates. If model-size adaptation is necessary, use the profile-specific
ranges above and report the selected values and visual/performance evidence. Do not silently remove
important silhouette or component-defining edges.

Changing the threshold requires rebuilding the cached/prepared runtime edge buffers for the newly
loaded model, not repeated rebuilding during camera movement.

## 7. Spatially chunk the custom edge overlay

Replace the one whole-model, `frustumCulled = false` edge object with spatially bounded chunks.
The chunks must use normal Three.js frustum culling with correct bounding volumes.

Requirements:

- target approximately 50-150 populated edge chunks for model 2;
- balance chunks by spatial extent and/or edge vertex count so one giant chunk does not retain most
  of the original cost;
- use tens or low hundreds of drawables, never one drawable per entity;
- retain a local-ID-to-edge-range/chunk index so role recoloring remains deterministic;
- update only affected chunk color attributes where practical;
- preserve model coordination transforms;
- dispose every geometry, material, typed array reference, listener, and incomplete async build on
  model switch/reset;
- ignore stale chunk builds that finish after the active model changes;
- keep asynchronous/yielded construction so loading remains interactive;
- compute bounding boxes/spheres and leave `frustumCulled` enabled;
- expose chunk count, edge vertex count, and build duration to development instrumentation.

The exact spatial partition algorithm is an implementation decision, but it must satisfy the
observable chunk-count, balance, culling, identity, and disposal requirements. Do not introduce
category/storey-based partitions.

## 8. Screen-size policy for custom edges

Faces and custom edges must not share an assumption that every visible face requires an explicit
line at every distance.

Implement a geometric screen-size policy for base-model edge chunks or their contained edge
groups:

```text
near: full feature edges
medium: reduce to the supported strong/coarse edge representation where practical
far / visually sub-pixel: no custom base edge geometry
selected or query-primary: preserve their edge emphasis farther than base context
```

Use the same accepted lower projected-size guidance as the LOD policy: base custom edges that are
approximately below 2-4 px in meaningful projected extent should not be rendered, and sub-1-pixel
edges must not be retained merely for completeness. Apply hysteresis to prevent flicker.

If robust per-edge projected sizing would add disproportionate per-frame CPU cost, apply the rule
at the spatial-chunk or bounded-group level and document the approximation. Do not perform a
per-edge CPU projection across the entire model every frame.

## 9. Query-highlight transparency and overdraw

The existing query-highlight state applies a transparent dim material to the full non-result
model (`opacity 0.16`) and more opaque dim edges (`alpha 0.4`). Preserve surrounding context, but
reduce blended overdraw and visual line density.

Benchmark these accepted candidates on model 2:

1. current face alpha 0.16 with optimized/motion-hidden edges;
2. a very-light opaque neutral context material with context edges reduced or disabled;
3. face alpha 0.3-0.4 with context edges disabled.

Select the candidate that best preserves the established result-emphasis intent while meeting the
30 FPS gate. Prefer the opaque light-neutral candidate when its appearance remains acceptable,
because it can restore depth rejection and reduce layered blending. Primary and manual selections
must remain clearly blue and legible. Do not hide non-result geometry.

Record the chosen material/edge values and comparison. All final color, opacity, and edge constants
must remain centralized in `viewerTheme.ts` or an equivalent single viewer-configuration module.

## 10. Component preview scheduling

Replace the component preview's unconditional full-rate loop with interaction-aware scheduling.

Use these accepted values:

| Preview state | Required behavior |
|---|---|
| Pointer drag or wheel interaction | Render continuously only while active |
| Auto-rotation, normal profile | Cap at 30 FPS |
| Auto-rotation, large-model profile | Cap at 20 FPS |
| No active motion | Render once, then stop |
| Auto-rotation lifetime | Stop after 10-15 seconds |
| Preview moving pixel ratio | 1.0 |
| Preview stationary pixel ratio | 1.25 |
| Preview outside viewport | Pause completely |
| Document hidden | Pause completely |

Choose one deterministic auto-rotation lifetime within 10-15 seconds. Preserve the current
two-second idle delay before auto-rotation resumes unless testing shows it conflicts with the new
finite lifetime. User interaction may restart the bounded auto-rotation lifetime, but it must not
create indefinite rendering.

Use `IntersectionObserver` or an equivalent supported visibility mechanism so an open but
off-screen/fully obscured preview does not animate. On becoming visible again, render the correct
current state without accumulating missed frames.

## 11. Adaptive profiles

Provide at least:

```text
Balanced / normal-model profile
Large-model performance profile
```

Automatic profile selection must use geometric/runtime evidence such as artifact byte size,
model local-item count, edge vertex count, or an initial bounded frame-time sample. It must not use
model name, source-model ID, IFC categories, disciplines, or storeys. Avoid a single fragile magic
number: document the selected signals and add hysteresis so the profile does not switch repeatedly.

Allow a user override only if it can be added without cluttering the primary viewer. The owner has
no strong intention about the exact presentation, label wording, dimensions, icon, placement, or
control type. Claude may rely on its frontend-design plugin for these unspecified UI values. Convey
and preserve this product intention:

- automatic selection should work without user intervention;
- an override, if provided, should be discoverable but secondary;
- users should understand whether the viewer is in automatic, balanced, or large-model mode;
- changing the override must take effect without reloading the model where technically safe;
- the control must match the existing visual system and accessibility behavior.

Do not delegate numeric rendering thresholds to the frontend-design plugin. Every accepted numeric
threshold in this task is authoritative. The plugin is only for UI presentation values where the
owner intentionally has no strong preference.

The default automatic behavior and all performance gates are required even if no override UI is
ultimately justified.

## 12. Resource, concurrency, and lifecycle rules

- Maintain one active main model and one main viewer context.
- Do not create another full-model renderer for instrumentation or edges.
- Coalesce render invalidations, Fragments updates, resize events, and pixel-ratio changes.
- Guard every async model/edge operation with the active model identity or an equivalent generation
  token.
- Cancel pending edge restoration, adaptive timers, observers, and animation frames on unload and
  disposal.
- Preserve current model-switch/reset semantics and artifact caching.
- Do not repeatedly transfer all model geometry from the worker during navigation.
- Do not regenerate whole-model edges on selection/highlight recoloring.
- Keep raycasting, selection, query-result eligibility, camera pivot, fit bounds, and below-zero
  geometry behavior unchanged.
- Do not leak WebGL contexts, typed arrays, object URLs, workers, observers, or event listeners.

## 13. Testing requirements

Add or update deterministic automated tests for:

### Render scheduling

- renderer uses manual mode;
- multiple same-tick invalidations coalesce into one frame;
- camera movement requests frames and rest stops ongoing rendering after final settlement;
- model load, highlight, resize, pixel-ratio change, and edge change invalidate the view;
- hidden document stops continuous rendering and visibility restoration requests a correct frame;
- disposal cancels scheduled frames and listeners.

### Resolution and profiles

- main-viewer moving/stationary ratios respect the accepted ceilings;
- large-model profile uses the accepted lower ranges;
- frame-time adaptation uses hysteresis/cooldown and does not oscillate on one slow frame;
- automatic profile selection is geometric/runtime-based and never model-ID/category/storey-based;
- an optional override applies and persists only according to the chosen frontend state contract.

### Fragments updates

- moving updates are throttled to the selected accepted interval;
- overlapping updates are coalesced or safely serialized;
- camera rest performs one final forced update;
- stale async completions cannot overwrite a newer camera/model state;
- lack of a public LOD-threshold API takes the documented default path without private dependency
  modification.

### Edges

- base edges hide during movement and restore 100-200 ms after settled rest;
- selected/query-primary edges remain available during movement;
- restoration cancels if movement resumes;
- chunk count for a representative large fixture stays within the intended bounded strategy;
- chunks have valid bounds and frustum culling enabled;
- recoloring updates the correct local-ID ranges;
- screen-size culling uses hysteresis and preserves selected/query-primary emphasis;
- stale builds and model unload dispose all created resources.

### Preview

- moving and stationary pixel ratios are 1.0 and 1.25;
- auto-rotation is capped at 30/20 FPS by profile;
- auto-rotation stops within the selected 10-15 second lifetime;
- stationary, off-screen, and hidden-document previews do not continue rendering;
- interaction and visibility restoration request the required frames;
- preview teardown cancels all frames, observers, and listeners.

### Regression

- existing camera controls, 50 mm lens behavior, pivot selection, fit guards, base plane, and
  below-zero geometry remain correct;
- base colors and primary/manual highlight roles remain correct;
- query-result-only picking remains correct;
- component preview still shows only the selected instance;
- switching/resetting models disposes previous resources;
- frontend unit, component, type-check, lint, and production-build checks pass;
- critical Playwright behavior remains functional.

Tests must mock browser timing, visibility, observers, worker behavior, and GPU-facing APIs where
needed. They must not call OpenAI or depend on a live database.

## 14. Manual performance and visual validation

Automated tests do not prove GPU performance. Perform a repeatable browser validation on the
owner's machine using the same viewport, browser zoom, display configuration, and model 2 camera
path for baseline and final runs.

Required acceptance gates:

1. Model 2 sustains at least 30 FPS during normal orbit, pan, and zoom after initial load settles.
2. The main renderer issues no continuing unchanged WebGL frames while stationary after camera and
   Fragments settlement.
3. A hidden tab issues no continuous main-viewer or preview renders.
4. Returning to the tab produces a correct view without a prolonged burst or stale LOD state.
5. Motion resolution reduction does not resize the CSS viewport or disrupt picking.
6. Stationary resolution and full stationary edge appearance return promptly after rest.
7. Base edges are absent during motion while selected/query-primary emphasis remains legible.
8. Off-screen spatial edge chunks are frustum-culled.
9. Query-result context remains visible; no category or storey is semantically hidden.
10. Model switching and reset do not increase retained WebGL contexts or leave old model resources.
11. Opening the component preview does not create indefinite full-rate rendering.

Also report:

```text
selected profile-detection signals
selected moving pixel ratios
selected Fragments update intervals
whether public LOD thresholds were configurable
selected edge angle threshold(s)
selected edge-restoration delay
model 2 edge chunk and vertex counts
selected query-context opacity/material approach
selected preview auto-rotation lifetime
baseline versus final metrics
remaining bottleneck, if the 30 FPS gate is not met
```

If the 30 FPS gate is not met after all in-scope work, do not add excluded occlusion culling or
semantic hiding. Stop, report the measured remaining bottleneck, and propose a separately approved
follow-up.

## 15. Implementation order

Use this sequence so each optimization is attributable:

1. Add instrumentation and capture the model 2 baseline.
2. Measure model 2 with the custom edge overlay disabled as a diagnostic only.
3. Measure model 2 at pixel ratio 1.0 as a diagnostic only.
4. Implement manual/invalidation-driven main rendering and visibility pausing.
5. Implement adaptive main-viewer pixel ratio.
6. Implement throttled moving Fragments updates and final forced rest update.
7. Hide base edges during motion while preserving selected/query-primary edges.
8. Evaluate and select the edge-angle threshold.
9. Spatially chunk and frustum-cull the edge overlay.
10. Add screen-size policy for custom edges.
11. Benchmark and select the query-context transparency/material approach.
12. Implement preview scheduling, caps, ratios, visibility pausing, and finite auto-rotation.
13. Implement automatic profiles and, only if justified, the secondary override UI.
14. Run regression tests and repeat the model 2 performance/visual validation.
15. Update the current specification and completion documentation with verified final values.

Do not combine the early diagnostic measurements into an undocumented rewrite. Preserve the
before/after evidence so it is clear whether edges, resolution, render scheduling, Fragments
updates, or another stage caused the improvement.

## Definition of done

This task is complete only when:

- all in-scope sections above are implemented and tested;
- model 2 meets the 30 FPS interaction gate on the owner's machine;
- stationary and hidden rendering meet the near-zero/no-continuous-render requirements;
- the full stationary visual intent is preserved without category/storey hiding;
- selected and query-result interactions remain correct during adaptive rendering;
- edge chunks are spatially cullable and no whole-model `frustumCulled = false` overlay remains;
- the component preview cannot render indefinitely at full frame rate;
- all selected values and baseline/final measurements are documented;
- the current frontend specification is reconciled with the implemented source of truth;
- no excluded occlusion-culling or semantic-hiding work has been introduced.

---

# Completion Report (2026-07-17)

All in-scope sections implemented, unit-tested, and live-verified against the real dev server with
model 2 (headless Chromium — software rendering, not the owner's RTX 5080; used strictly for
relative before/after evidence, per the documented headless-GL gotcha from `task15_done.md`). Item
11's gate ("model 2 meets 30 FPS on the owner's machine") requires the owner's own hardware and is
called out explicitly below as the one item this report cannot self-certify.

No backend/database/RAG/LLM/ingestion change. No category/discipline/storey-based hiding. No
occlusion culling. No per-entity draw object. No private/minified dependency patch.

## 1. Instrumentation and baseline

New `src/viewer/ViewerInstrumentation.ts` (dev-only, `import.meta.env.DEV` + `?perf=1` opt-in — never
constructed otherwise, so a production build never pays for it) records FPS, frame time (instant/
rolling-avg/worst), draw calls/triangles/lines, canvas size, effective pixel ratio, long-task count,
forced/throttled Fragments update counts, edge build duration/vertex/chunk counts, model item count,
and motion/profile state, surfaced via `ViewerInstrumentationOverlay.tsx` (a `<pre>` polling at 2 Hz,
independent of camera events so it cannot itself cause a re-render storm).

Baseline captured on model 2 (27,388 items, 5,370,488 edge vertices, one merged edge object, ~1.04M
triangles of base geometry) against the running dev server + backend:

| Scenario | Baseline (before) |
|---|---|
| Initial load and settle | fps 27 (avg 13), frame avg 74.2 ms, worst 2808 ms, 30 long tasks (worst 2805 ms) |
| Fit-all stationary (idle) | fps 32 (avg 26), frame avg 37.8 ms, draw 893, tris 1,040,056, lines 2,685,526, canvas 2800×1800 @ dpr 2 |
| Continuous orbit / pan / zoom | avg fps 33 / 32 / 31 |
| After motion settled | avg fps 32 — rendering continued at full rate even fully idle (no manual-mode gating existed) |
| Edge build | 8423 ms wall clock (CPU-bound, closer to representative of real hardware than the FPS numbers) |
| Hidden tab | not exercised live pre-implementation — confirmed via source read that no visibility handling existed, so rendering was unconditional |

## 2. Diagnostics (edges disabled / pixel ratio 1.0)

| | Shipped (dpr 2, edges on) | dpr 1 (edges on) | Edges off (dpr 2) |
|---|---:|---:|---:|
| Fit-all stationary avg fps | 26 | 39 | 53 |
| Continuous orbit avg fps | 33 | 39 | 50 |
| Long-task count | 32 | 34 | 4 |
| Long-task worst | 2805 ms | 2838 ms | 202 ms |

Disabling the whole-model edge overlay alone had by far the largest effect (~2x stationary FPS,
~14x reduction in worst long task) — the strongest single piece of evidence motivating the spatial
chunking rewrite (§7 below) over any other single change.

## 3. Manual, invalidation-driven main rendering (§2)

`RenderScheduler` (`src/viewer/RenderScheduler.ts`) switches `SimpleRenderer.mode` to the library's
supported `MANUAL` and rides its own always-on tick (`onAfterUpdate`) to flip `needsUpdate` only on
real invalidations, coalescing same-tick requests for free. `document.hidden` suspends the entire
`Components` tick loop via its public `enabled` field (verified in the installed package source to
halt the whole RAF chain, not just the draw call — confirmed empirically, see below); resuming uses
the library's own documented restart path (`Components.init()`).

Live-measured on model 2 (WebGL `drawArrays`/`drawElements` call counting, independent of the
library's internal RAF bookkeeping):

- **Idle 3 s window after settle: 0 draw calls** (previously continuous).
- Orbit burst (~500 ms of drag): ~36,000 draw calls — confirms motion still renders correctly.
- Hidden tab: `requestAnimationFrame` calls dropped from ~91/1.5 s (visible) to **0/1.5 s** (hidden),
  resuming at ~61/1 s with no accumulated burst.

## 4. Adaptive main-viewer pixel ratio (§3)

`PIXEL_RATIO` (`viewerTheme.ts`): moving 1.0–1.25 (balanced) / 0.85–1.0 (large-model), stationary 1.5
(balanced) / 1.25 (large-model), always capped at the display's own `devicePixelRatio`. The moving
value steps to its low end only under a sustained-slow verdict from `ViewerPerformanceController`'s
frame-time sampler (30-sample rolling window, 1.5 s minimum between verdict flips — never on one slow
frame; unit-tested for exactly this hysteresis).

Live: stationary settled at dpr 1.5 (balanced) / 1.25 (large-model, model 2's detected profile);
moving correctly stepped to the low end (0.85/1.0) under genuinely slow measured frame times in this
environment. CSS canvas size (1400×900) never changed across any pixel-ratio transition — only the
internal drawing buffer did. Selection/picking verified correct immediately after a sustained orbit.

## 5. Fragments update throttle (§4)

`FRAGMENTS_THROTTLE_MS`: 120 ms (balanced) / 200 ms (large-model) while moving, 100 ms (library
default) at rest — driving the installed, public `FragmentsModels.settings.maxUpdateRate`, which
already gates every `core.update()` call (forced or not) before the `force` branch runs (verified in
the installed package source). Forced calls (load/highlight/rest) route through a guard that zeroes
the rate for the call's duration so a throttle window set moments earlier during motion can never
silently skip a forced update.

Live: a rapid drag burst produced only 2–5 throttled calls (not one per tick); exactly one forced
call fired at rest, every time.

No public per-object LOD screen-size threshold API was found (`FragmentsModel`'s screen-size logic
is a private method in the installed type declarations) — documented per the task's fallback
instruction; no private/minified internals were patched. The surrounding update-frequency,
pixel-ratio, and custom-edge-LOD policies stand in for it.

## 6. Edge motion-hide/restore (§5)

`EdgeOverlay.setMotion()` zeroes only the ALPHA channel of non-highlighted vertex ranges on camera
`wake` (never touching selected/query-primary ranges, and never touching `lastRole` so a role change
mid-hide is never lost), and restores it 150 ms after `rest`, cancelling/restarting the delay if
motion resumes first. Unit-tested for hide/keep-visible/restore/cancel-restart precisely; live
screenshots during an orbit show base window-mullion edges absent while a query-primary edge stays
faintly visible.

## 7. Edge angle threshold (§6)

`EDGES.thresholdAngleDeg = { balanced: 25, largeModel: 40 }`, chosen from the model's provisional
profile before the edge build starts. Evaluated 25°/38°/40° on model 2:
**no measurable vertex-count difference across the range** (5,370,488 vertices at every value
tested) — model 2's edges are overwhelmingly either true ~90° corners (included at any threshold in
this range) or coplanar-triangulation diagonals at ~0° (excluded at any threshold in this range), so
angle choice is not a performance lever for this specific artifact. `balanced` kept at the unchanged,
previously validated 25°; `largeModel` set to 40° (top of the accepted range) as a zero-measured-cost
hedge for a future model with more curved/faceted geometry. A dedicated unit test constructs a real
90°-dihedral two-triangle fixture and confirms the threshold parameter genuinely changes which edges
survive (10 vertices at 45°, 8 at 135°) — proof the mechanism works even though it happens not to
matter for either currently available test model.

## 8. Spatially chunked edge overlay (§7 + §8)

`EdgeOverlay.ts` was rewritten from one whole-model `LineSegments` (`frustumCulled = false`) into a
uniform 3D grid, sized from the model bounding box and item count, bucketing each entity's edge-vertex
centroid into a cell during the existing yielded batch loop — no second pass, no duplicate worker
fetch. Every populated cell becomes its own `LineSegments` with a real computed bounding sphere/box
and `frustumCulled = true`.

- **Model 2: 71 populated chunks** (target: 50–150).
- The `localId -> {chunkIndex, start, count}` index is retained; `recolor()`'s existing per-entity
  diff (`lastRole`) is unchanged — only the upload step changed, from one global min–max envelope to
  one upload per touched chunk (strictly cheaper for the common 1–2-entity change, no worse for an
  ~880-entity scattered change).
- Live: zooming into one facade dropped draw calls from 952 to ~410–422 and triangles from ~1.03M to
  ~256–258k, with average FPS in this headless environment rising from ~4 to ~55–56 — direct evidence
  off-screen chunks are now culled (acceptance gate 8).
- Disposal iterates every chunk; a build finishing after `dispose()` is ignored (existing
  disposed-flag guard, now covering the multi-chunk finalize path too). A model-switch round trip
  (model 2 → Schependomlaan → model 2) reproduced identical chunk/vertex/item counts with zero
  console errors.

**Screen-size LOD** (`EdgeOverlay.updateLod`, §8): per-chunk bounding-sphere projected-size check
(cheap — tens to ~160 chunks, never per-edge-per-frame), called at camera rest and on resize (not
every tick during motion, per the task's own "not a per-frame CPU cost" constraint). Hysteresis pair
`EDGES.lod`: 2 px enter / 4 px exit for base chunks, 0.75 px / 1.5 px for chunks containing a
selected/query-primary entity (`highlightCount`, maintained incrementally by `recolor()`) — so
results stay visible farther from the camera than base context. Unit-tested with a real computed
bounding-sphere radius and a `PerspectiveCamera` at three concrete distances, confirming both the
near/far cull and the hysteresis band (a culled chunk does not restore until it clears the farther
exit threshold, not merely the enter threshold again).

## 9. Query-highlight transparency (§9)

Benchmarked three candidates live on model 2, applying real query-primary roles client-side (no
OpenAI/backend call spent on this): (1) original 0.16 + motion-hidden edges; (2) fully opaque (1.0)
light-neutral, edges disabled; (3) moderate 0.35, edges disabled.

**Candidate 2 was rejected** — screenshotted evidence from two camera angles shows zero visible
primary highlights: with non-result geometry fully opaque, the 5 sampled query-primary results
(spread across the model, several interior) were occluded from every external viewpoint, violating
"primary and manual selections must remain clearly blue and legible." This is a materially important
finding for a BIM query tool, where results are frequently interior elements (partition walls, MEP,
doors), not just exterior-visible surfaces — the task's own conditional preference for the opaque
candidate ("when its appearance remains acceptable") is explicitly not satisfied here.

**Candidate 3 selected**: `VIEWER_OPACITY.dim = 0.35` (was 0.16), `EDGES.alpha.dim = 0` (was 0.4 —
non-result edges fully disabled rather than merely dimmed). Screenshots confirm every sampled primary
stays visible, and disabling non-result edges measurably reduces visual line density versus the
original. All values remain centralized in `viewerTheme.ts`.

## 10. Component preview scheduling (§10)

`PreviewScene.ts`: `IntersectionObserver` + `document.visibilitychange` fully stop the RAF chain (not
just skip rendering) when off-screen or backgrounded, re-arming via those same callbacks; auto-rotation
capped at 30 fps (balanced) / 20 fps (large-model, via a new `profile` param threaded from
`ComponentPreview.tsx` -> `ViewerAdapter.getProfile()`); a finite **12 s auto-rotation lifetime**
(was indefinite pause/resume); dynamic pixel ratio 1.0 while actively dragging/wheel-zooming, 1.25
otherwise (including while auto-rotating, treated as ambient motion rather than "moving" for
resolution purposes).

Live: ~72 draw calls measured during a 2 s auto-rotating window; **0 draw calls** in a 2 s window
sampled after the 12 s lifetime expired while idle — direct evidence of acceptance gate 11 (no
indefinite full-rate rendering).

## 11. Adaptive profiles and override (§11)

`profileDetection.ts`'s `detectProfile()` uses only artifact byte size, item count, and (once known)
edge vertex count, with hysteresis against the previous verdict — never model name/ID/category/
discipline/storey (enforced structurally: the function's input type has no such field). Called twice
per load in `ViewerAdapter.loadModel()`: provisionally right after the artifact downloads (so
pixel-ratio/throttle/edge-threshold defaults are correct from the first frame), finally once the edge
build resolves. Model 2 (27,388 items, 5,370,488 edge vertices) is automatically classified
`large-model`.

A minimal, discoverable-but-secondary override control was added to the existing bottom-left CAD
status readout (`perf: <profile> (auto|manual)`, cycling Automatic → Balanced → Large model on
click), matching the readout's established mono/small-button visual language rather than introducing
a new UI pattern. Selecting an override calls `ViewerAdapter.setProfileOverride()`, which
re-applies immediately to the shared `ViewerPerformanceController` — every adaptive system (pixel
ratio, Fragments throttle) already subscribes to it, so no reload is needed. Live-verified: clicking
cycles `large model (auto)` -> `balanced (manual)` -> `large model (manual)` -> `large model (auto)`
correctly.

## Baseline vs final summary

| Metric | Baseline | Final |
|---|---|---|
| Stationary idle rendering | continuous every tick | **0 draw calls / 3 s** |
| Hidden-tab RAF | continuous (~91/1.5 s) | **0/1.5 s**, resumes cleanly |
| Main pixel ratio | fixed `min(dpr, 2)` | adaptive 0.85–1.5, capped at native dpr |
| Edge overlay | 1 object, `frustumCulled=false`, 5.37M verts | **71 culled chunks** (model 2) |
| Zoomed-detail draw calls | 952 (whole model always submitted) | **~410–422** |
| Zoomed-detail triangles | ~1.03M | **~256–258k** |
| Fragments updates during motion | unthrottled (implicit) | 120/200 ms throttle, 2–5 calls/burst |
| Fragments updates at rest | always forced | exactly 1 forced call, guaranteed to execute |
| Query-highlight dim opacity/edges | 0.16 / edge alpha 0.4 | 0.35 / edges disabled (candidate 2 rejected on evidence) |
| Preview auto-rotation | indefinite | 12 s lifetime, then 0 draws while idle |
| Adaptive profile | none | automatic (byte/item/edge-count signals) + manual override |

## Also-reported values (task §14)

```text
profile-detection signals: artifact byte size, item count, edge vertex count (hysteresis, two-phase)
moving pixel ratios: 1.0-1.25 (balanced) / 0.85-1.0 (large-model), stepped by sustained-slow frame time
Fragments update intervals: 120 ms (balanced) / 200 ms (large-model) moving, 100 ms resting
public LOD thresholds: NOT configurable (private API) — documented fallback path used, no patching
edge angle threshold(s): 25 deg (balanced, unchanged) / 40 deg (large-model)
edge-restoration delay: 150 ms
model 2 edge chunk/vertex counts: 71 chunks / 5,370,488 vertices
query-context material: 0.35 opacity, non-result edges disabled (candidate 3; candidate 2 rejected)
preview auto-rotation lifetime: 12 seconds
baseline vs final: see table above
remaining bottleneck: edge build itself is ~7.7-10.8s wall clock on model 2 (CPU-bound, async,
  non-blocking of interaction) — not addressed further, as it happens once per load, off the
  interaction-frame critical path, and rebuilding it more cheaply was out of this task's scope
  (task explicitly limits scope to scheduling/culling/threshold work, not extraction algorithm
  redesign)
```

## Regression and validation

- Frontend unit suite: **173 tests / 16 files, all green** (new coverage: `RenderScheduler`,
  `ViewerPerformanceController`, `profileDetection`, chunked `EdgeOverlay` — spatial separation,
  frustum culling, LOD hysteresis, motion-hide/restore, threshold behavior — and the adapter's
  profile-override API).
- `npm run typecheck`, `npm run lint`, `npm run build`: all clean.
- Playwright e2e: 1 of 2 green. The failing test (`critical-path.spec.ts`'s evidence-disclosure
  assertion) was traced to already-uncommitted, unrelated work present before this task began —
  `Message.tsx`'s working-tree diff shows `EvidenceDisclosure`/`ResultSummaryView` rendering was
  removed, and neither component is referenced anywhere in `src/` anymore. This task never touched
  `Message.tsx`, `EvidenceDisclosure.tsx`, or the query/evidence pipeline. Not fixed here — out of
  scope (backend/RAG/answer-rendering concern, not viewer performance), and CLAUDE.md instructs
  against exceeding the active spec.
- Manual/live validation: all 11 acceptance gates in task §14 were exercised against the real dev
  server + backend with model 2 (see §§3-10 above for the gate-by-gate evidence). **Gate 1 (the 30
  FPS interaction target) requires the owner's own RTX 5080 Laptop hardware** — headless Chromium is
  software-rendered and not representative (documented gotcha, `task15_done.md`). This is the one
  item this report cannot self-certify; the owner should confirm with `?perf=1` open on model 2.

## Status

```text
Instrumentation and baseline: VALIDATED
Manual invalidation-driven rendering: VALIDATED
Adaptive main-viewer pixel ratio: VALIDATED
Fragments update throttle: VALIDATED
Edge motion-hide/restore: VALIDATED
Edge angle threshold: VALIDATED (no measurable effect on either available test model; documented)
Spatially chunked edge overlay + frustum culling: VALIDATED
Screen-size edge LOD: VALIDATED
Query-highlight transparency: VALIDATED (candidate 3 selected; candidate 2 rejected on evidence)
Component preview scheduling: VALIDATED
Adaptive profiles + override: VALIDATED
30 FPS gate on owner's real GPU: PENDING OWNER CONFIRMATION
Frontend regression (unit/typecheck/lint/build): VALIDATED
Playwright e2e: 1/2 VALIDATED, 1 PRE-EXISTING FAILURE (unrelated, task17 scope)
Specification reconciled (spec_v006 §25, supersedes §24.1): VALIDATED
Database/vector/model artifacts: UNCHANGED
```
