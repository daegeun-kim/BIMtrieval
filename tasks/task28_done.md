# Task 28: Floor Plan Mode in the Main Viewer

## Goal

Add a floor-plan viewing mode to the existing main BIM viewer.

For every loaded BIM model whose IFC spatial data establishes one or more identifiable logical
floors:

- show one button for every logical floor;
- let the user switch the existing viewer from its normal perspective 3D view to a top-down,
  parallel-projection plan of the selected floor;
- apply a horizontal cut approximately 1.2 m above that floor;
- restrict the visible vertical range so lower floors do not appear through openings;
- preserve the current model, selection, query highlights, panels, and chat;
- provide a **3D** button that removes the plan cut and restores the exact perspective camera view
  that was active before plan mode.

This is a mode of the original viewer. It is not a new explanation-panel visualization, a second
canvas, a generated image, a saved drawing, or a replacement for the 3D model.

---

## 1. Fixed product behavior

### 1.1 Floor controls

When the loaded model has at least one identifiable logical floor, render a compact vertical control
below the existing **Reset app** control:

```text
3D
Floor 1
Floor 2
...
```

The control must:

- contain one button for every logical floor, including a single-floor model;
- remain vertically scrollable when the model has more floors than fit in the viewport;
- clearly mark the active floor or **3D** state;
- support keyboard navigation, visible focus, and `aria-pressed` or equivalent selected-state
  semantics;
- use source IFC storey names only in a tooltip or compact accessible description;
- not use storey names to discover, group, or order floors.

Use the existing floor-reference semantics for labels so the UI and natural-language floor
interpretation cannot disagree:

- the reference band is **Floor 1**;
- bands above it are **Floor 2**, **Floor 3**, and so on;
- bands below it use neutral labels such as **Lower level 1**, **Lower level 2**, rather than
  inventing a basement designation;
- when the existing floor model falls back to the lowest band as its reference, every band is
  labelled **Floor 1** upward.

Do not add a tree, storey browser panel, visibility checklist, arbitrary clipping-plane editor, or
saved-view manager.

### 1.2 Switching modes

Selecting a floor button must:

1. keep the same loaded Fragments model and the same viewer canvas;
2. save the normal 3D camera state only when first leaving 3D mode;
3. change to a true orthographic/parallel projection;
4. orient the camera vertically downward;
5. enable plan-style pan and zoom without free 3D orbit;
6. apply the selected floor's upper cut plane and lower range boundary;
7. fit the model footprint within the currently unobstructed viewer region;
8. mark that floor button active.

Switching directly from one floor to another must not overwrite the saved 3D camera state.

Selecting **3D** must:

- remove both plan clipping boundaries and every plan-only section overlay;
- restore the normal perspective projection, 50 mm lens behavior, orbit/pan/zoom mapping,
  projected-size policy, base plane, and other established 3D behavior;
- restore the exact camera pose and target that existed before entering plan mode;
- leave selection and query-result roles unchanged.

Model unload, model switch, and Reset App must dispose plan resources, clear the active floor, and
return the viewer state to its normal unloaded/default mode. Do not persist plan mode or the selected
floor to local storage.

### 1.3 Independence from query presentation

Floor plan mode is a user-controlled viewer state, not an answer presentation.

- Entering or leaving plan mode must not create a chat turn, issue a natural-language query, call an
  LLM, open the Query Explanation panel, or close it.
- It must not clear or replace query-primary, relationship-context, or manual-selection roles.
- A later query must not automatically choose or change a floor.
- Existing viewer actions may update highlights while plan mode is active, but they must use the
  active camera/projection safely and must not silently return to perspective mode.

---

## 2. One authoritative floor definition

Reuse `backend/app/query/semantic/spatial.py::build_storey_model()` and its existing logical
`FloorBand` clustering.

That model already:

- reads `IfcBuildingStorey` elevations from the active source model;
- groups nearby structural sublevels into one physical/logical floor band;
- orders bands by elevation;
- selects the elevation-zero band as the reference when present and otherwise uses the lowest band;
- remains independent of model filename, exporter, storey name, and absolute project unit.

Do not create a second floor detector in the frontend, infer floors from geometry bounding boxes,
make one button per raw `IfcBuildingStorey`, or use storey-name patterns such as `Level`, `Plan`,
`Ground`, or `Storey`.

### 2.1 Additive read-only floor contract

Add one narrow, typed, read-only model endpoint, for example:

```text
GET /api/models/{source_model_id}/floors
```

The exact schema names are implementation details, but the response must expose:

- active `source_model_id`;
- whether floor plan controls are available and a bounded reason when not;
- the existing reference band and reference basis;
- every logical floor band in deterministic elevation order;
- each band's zero-based band index;
- the display label derived from the reference semantics above;
- the band's constituent storey GlobalIds;
- bounded source storey names for tooltip/accessibility use;
- the stored minimum and maximum band elevation for diagnostics, without presenting them as viewer
  scene coordinates.

The endpoint must be source-model scoped, allowlisted, deterministic, and read-only. It must not
open the IFC, parse the viewer artifact, write the database, call an LLM, create embeddings, or
duplicate the floor-clustering implementation.

Return an honest unavailable/empty result when the model has no usable `IfcBuildingStorey`
elevations. The frontend then omits the floor control and leaves the normal viewer unchanged.

Regenerate the frontend OpenAPI types. Existing clients that do not call the endpoint must continue
to work.

---

## 3. Scene-space plan range

Database elevations and viewer scene coordinates are not interchangeable.

Use the logical band membership from the backend, then resolve those storey GlobalIds against the
already loaded Fragments artifact. Read their artifact-native elevations and the model's public
coordinate information to establish the corresponding scene-space heights. Follow the same public
coordinate/elevation behavior used by the installed `Views.createFromIfcStoreys` implementation.

Do not:

- assume a raw database elevation is already a Three.js Y value;
- use `model.box.min.y` as a floor elevation;
- infer a floor plane from the geometry centroid;
- introduce a model-specific offset;
- rewrite stored measurements or change Task 27's IFC-native unit contract.

The installed Fragments/viewer coordinate path uses metre-scale scene distances. Apply the nominal
cut offset as a presentation-only scene distance:

```text
nominal cut = highest scene elevation in the logical band + 1.2 m
```

If the artifact cannot resolve a finite scene elevation for any constituent storey, keep that
floor's button visible but disabled with a concise reason. Never place a guessed plane.

### 3.1 Upper cut plane

For a selected band:

```text
base = highest resolved scene elevation in the selected band
cut  = base + 1.2 m
```

When another logical band exists above it, constrain the cut below that next band:

```text
cut = min(base + 1.2 m, next_band_lowest_scene_elevation - numeric_tolerance)
```

The tolerance exists only to prevent coincident clipping planes and must be derived from safe
floating-point/model-scale handling, not from a model name or manually tuned per-file value.

If the resulting range is non-finite or does not extend above the selected band, disable that floor
plan rather than showing the wrong level.

For the uppermost floor, use the nominal 1.2 m cut without inventing a nonexistent next level.

### 3.2 Lower range boundary

Do not leave every floor below the cut visible.

- When a lower logical band exists, place the lower boundary halfway between that lower band's
  highest scene elevation and the selected band's lowest scene elevation.
- For the lowest logical band, use the loaded model's finite geometric minimum as the lower
  boundary.
- The active view range is the volume between this lower boundary and the upper cut.

This boundary is presentation-only. It must not change containment, floor membership, model
coordinates, or query scope.

---

## 4. Plan visual quality

The plan must remain a live rendering of the original model, not a raster screenshot or separately
generated drawing.

### 4.1 Projection and navigation

Use the installed viewer library's public supported APIs where compatible:

- `OBC.Views` / `View` for the two-plane clipped view and reversible camera ownership;
- `OBC.OrthoPerspectiveCamera` with orthographic projection;
- its plan navigation mode for top-down pan/zoom behavior;
- the loaded Fragments model's public coordinate, item-data, and section APIs.

Do not patch installed packages, rely on private/minified fields, create a second Three.js world, or
replace the current `ViewerAdapter` boundary. React components continue to request typed viewer
actions; imperative scene mutation remains in the adapter.

### 4.2 Cut and projected graphics

Use the loaded model's public `getSection` capability, or an equally authoritative supported public
API, to render the actual intersection at the upper cut plane.

The visual hierarchy must be:

- geometry intersected by the cut: strong, opaque dark cut contour and restrained cut fill;
- geometry below the cut but above the lower boundary: lighter projected surfaces and edges;
- query-primary cut/result geometry: existing blueprint blue;
- relationship-context geometry: existing ochre role;
- manual selection: existing teal role;
- non-result geometry under an active query: retain the established subdued context treatment.

Cut contours must remain visually stronger than projected edges at ordinary plan zoom levels.
Highlighted cut geometry must remain legible over the base cut contour.

The current bright measured-drawing theme, panel-aware viewport centering, and accessible contrast
remain authoritative. Hide the decorative geometric-minimum base grid while plan mode is active and
restore it unchanged on return to 3D.

Do not fabricate:

- door swing arcs;
- window, furniture, fixture, or stair symbols;
- room tags, dimensions, annotations, north arrows, or scale bars;
- Revit family-specific plan graphics;
- geometry that is absent from the prepared artifact.

Source-provided geometry remains the only model graphic authority. This task produces a clean
model-derived plan slice, not a claim of Revit documentation equivalence.

### 4.3 Performance and lifecycle

Do not precompute section geometry for every floor during model load.

- Create or request section geometry only for the active floor.
- Keep expensive section work in the existing worker/public Fragments path.
- Guard asynchronous floor changes so an older floor result cannot overwrite a newer selection.
- Dispose the previous floor's cut fills, contours, materials, cameras/views, and listeners when
  switching floors, leaving plan mode, unloading, or resetting.
- Reuse bounded resources; do not retain one complete section mesh per floor indefinitely.
- Refresh Fragments only through the existing controlled update path.

The perspective-only projected-size and edge-LOD calculations must not run against an orthographic
camera as though it were perspective. Either provide their correct orthographic equivalent or
suspend only those policies during plan mode and restore their exact prior state in 3D.

---

## 5. Existing application behavior to preserve

Do not change:

- natural-language query interpretation, prompts, schemas, model assignments, reasoning effort, or
  LLM call count;
- semantic manifest generation, floor-band clustering, query execution, answer facts, or viewer
  identity derivation;
- the Query Explanation panel's current decision or visualization rules in this task;
- component-detail behavior, Same type/Same family actions, chat history, or selected-object chips;
- the one-loaded-model rule;
- existing colors and semantic roles;
- manual selection limits and picking semantics;
- right-side panel obstruction calculations;
- normal 3D camera lens, controls, fit expansion, zoom bound, base-plane behavior, or viewport
  centering after returning to 3D;
- offline operation and local viewer-asset streaming.

The floor controls are the only new main-viewer controls. Do not add general hide/isolate,
measurement, arbitrary sections, reflected ceiling plans, elevations, saved viewpoints, exports,
editing, or annotations.

---

## 6. State and failure behavior

Keep plan state current-session only:

- `3d` or `plan`;
- active source-model ID;
- active logical band;
- floor-contract loading/availability state.

The saved perspective camera pose and live clipping/section objects belong inside the imperative
viewer layer, not the serializable application store.

Failure to load the floor contract or construct one floor plan must not unload the model or break
the normal 3D viewer.

- No usable floor data: omit the floor control.
- One floor cannot map safely into scene coordinates: show its disabled button and reason.
- A stale response from a previous model: ignore it.
- Section-contour generation failure after entering a valid floor: retain a truthful clipped
  orthographic view if safe, show a concise non-blocking limitation, and never show contours from a
  different floor.
- Returning to **3D** must remain available even after a plan-rendering failure.

---

## 7. Documentation alignment

Update `specs/spec_v006_frontend_application.md` with the implemented floor-plan contract.

This task narrowly supersedes the earlier exclusions on section planes and storey controls only for:

- the fixed automatic horizontal cut associated with a selected logical floor;
- the lower boundary required to isolate that floor;
- the compact fixed floor-button control described here.

The exclusions remain in force for arbitrary user-authored clipping planes, a general storey
browser, hide/isolate tools, measurements, annotations, saved views, and other drawing modes.

Do not rewrite unrelated historical task files.

---

## 8. Validation

### 8.1 Backend tests

Add focused offline tests verifying:

- the new endpoint is typed, allowlisted, OpenAPI-generated, read-only, and source-model scoped;
- it returns exactly one record per existing logical `FloorBand`, not per raw storey;
- multi-wing/sublevel storeys at nearby elevations remain one button;
- bands are ordered by elevation without using their names;
- labels use the same reference band and basis as current query floor interpretation;
- lower bands receive neutral lower-level labels rather than an invented basement name;
- a single logical floor remains available;
- missing/non-finite storey elevations return an honest unavailable/empty state;
- source storey names are descriptive only;
- no IFC parse, viewer-asset read, LLM call, embedding call, or database write occurs.

### 8.2 Frontend and viewer tests

Add focused tests verifying:

- the control appears only after a model with available logical floors is ready;
- **3D** plus every returned logical floor is rendered, with scrolling rather than omission;
- active, focus, keyboard, tooltip, and accessible selected states are correct;
- selecting a floor keeps the same canvas/model and activates orthographic top-down plan navigation;
- the cut uses the highest constituent storey elevation plus 1.2 scene metres;
- the next floor constrains the cut and the uppermost floor uses the nominal cut;
- the lower boundary is the approved midpoint or geometric minimum for the lowest band;
- raw database elevations are never treated directly as scene Y coordinates;
- unresolved/invalid mappings disable only the affected floor;
- switching floors does not overwrite the saved 3D camera;
- **3D** removes clipping and plan overlays and restores the exact prior perspective camera;
- base grid, perspective lens, controls, projected-size policy, and edge behavior restore correctly;
- query-primary, relationship-context, and manual-selection roles survive mode changes;
- cut contours use the correct semantic colors and outrank projected edges visually;
- stale asynchronous section results cannot replace the active floor;
- floor/model switching and Reset App dispose every plan-only resource and listener;
- panel obstruction, resizing, fit, and picking remain correct in both projections;
- no additional canvas, world, backend query, chat turn, or LLM call is created.

### 8.3 Real-model verification

Verify the behavior on each currently ingested model that exposes usable floor bands:

- record raw `IfcBuildingStorey` count versus logical floor-button count;
- confirm every logical floor is reachable;
- inspect a lower, middle, and upper floor where available;
- confirm walls/columns cut strongly and projected geometry remains lighter;
- confirm lower floors do not bleed through the selected floor;
- confirm query and manual highlights retain their established colors;
- confirm repeated floor switching does not accumulate section meshes, cameras, or listeners;
- confirm **3D** restores the exact pre-plan camera and uncut model.

Do not add model-name or expected-count behavior to production code.

Run the frontend build, typecheck, lint, unit/component tests, and critical Playwright viewer path,
plus the focused backend API/spatial/OpenAPI tests. Do not run the costly live LLM benchmark for this
deterministic viewer feature.

---

## Acceptance outcome

After Task 28, a model with identifiable logical floors shows a compact control such as:

```text
[3D]
[Floor 1]
[Floor 2]
[Floor 3]
```

Choosing **Floor 2** changes the existing viewer itself into a top-down orthographic plan:

- a horizontal cut is placed approximately 1.2 m above Floor 2;
- the view is bounded below so Floor 1 does not appear through it;
- true cut contours are stronger than projected geometry;
- existing query and selection colors remain synchronized;
- pan and zoom work without perspective distortion or accidental orbit.

Choosing **3D** removes the plan range and restores the exact perspective view that existed before
the user entered plan mode.

No separate visualization panel, image, canvas, IFC rewrite, LLM behavior change, fabricated plan
symbol, or general-purpose sectioning system is introduced.
