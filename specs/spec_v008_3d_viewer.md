# Specification v008: 3D Viewer

## 1. Purpose and authority

This specification is authoritative for the frontend 3D viewer: the prepared viewer artifact and its
delivery, the coordinate model, camera and navigation, manual selection and picking, highlighting and
viewer appearance, rendering/resource policy, and floor-plan mode.

It is governed by `spec_v006_frontend_application.md`, which owns the shared layout, application
lifecycle, state/clearing semantics, shared backend contracts, accessibility, security, testing
policy, and acceptance criteria. Backend query semantics remain owned by `spec_v002` through
`spec_v005`; nothing here reinterprets a query or changes what the pipeline returns.

Related frontend specs: `spec_v009_chat_panel.md` (chat and citations), `spec_v010_explanation_panel.md`
(explanation panel and its subgroup highlighting), `spec_v011_component_panel.md` (component details
and the isolated preview).

The viewer is a deterministic renderer. No viewer action — loading, selection, picking, fitting,
highlighting, floor-plan entry, or disposal — may invoke an LLM, write the database, parse IFC at
runtime, or contact any service other than the approved backend routes.

## 2. Rendering representation and viewer assets

### 2.1 Prepared Fragments artifact

Normal visualization uses a prepared That Open Fragments artifact. Do not reconstruct the scene from
PostGIS and do not parse raw IFC on load.

The repository-level artifact convention is:

```text
model_assets/
└── {source_model_id}/
    └── {source_fingerprint}.frag
```

The backend derives the expected path from allowlisted configuration plus database model identity. No
user-supplied filesystem path may be joined or opened. Only one model is loaded into the scene at a
time.

### 2.2 One-time preparation tool

A manual TypeScript/npm preparation command under the frontend project converts a local IFC to the
artifact convention, using the same maintained That Open Fragments importer/version family the viewer
uses (`npm run prepare:model`). It:

- is not imported or invoked by FastAPI and is not part of `npm run dev`;
- does not import `bim_rag`, write PostgreSQL, or replace/edit the source IFC;
- preserves the identity information needed to map rendered items to IFC GlobalIds;
- records format/library version and source fingerprint metadata;
- writes atomically, so a failed conversion cannot leave a valid-looking partial artifact;
- validates the completed artifact by loading it and sampling identity mappings.

No Python/IfcOpenShell converter may be added to the backend. If current That Open APIs require a
minor change of file extension or sidecar metadata, the supported format may be chosen provided this
architecture is preserved and the choice documented.

Prepared artifacts are not committed. A small tracked fixture artifact exists for browser tests.

### 2.3 Asset delivery contract

```text
GET /api/models/{source_model_id}/viewer-asset
```

Read-only, LLM-free, no conversion, no database write. It verifies model existence, derives
`{root}/{source_model_id}/{source_fingerprint}.frag` from database identity only, enforces containment
under the configured asset root, streams the binary with the correct content type and a
fingerprint-derived `ETag` (`If-None-Match` → 304), and returns bounded `404 missing` / `409 stale` /
`503 unavailable`. No arbitrary path query parameter is accepted and no server path is ever returned.
Range support is optional and only if it stays simple.

`viewer_actions.viewer_source_location` carries this HTTP reference, never a filesystem path.

The asset root defaults to `<repo>/model_assets` (overridable via `VIEWER_ASSET_ROOT`) and is a
backend-owned setting.

### 2.4 IndexedDB artifact cache

Cache the downloaded artifact in IndexedDB under a key containing at least:

```text
source_model_id
source_fingerprint
artifact_format_version
```

Validate the key before reuse; never reuse a stale artifact after the fingerprint or format changes.
Use a small configurable LRU limit appropriate to a local prototype (default: two artifacts) and
handle quota denial by falling back to a non-persistent load.

The cache is a performance optimization, not application state: it survives both Clear Chat and Reset
App (`spec_v006` §10). No cache-management UI is required.

## 3. Coordinate model (load-bearing)

Two distinct coordinate facts must be kept apart:

- a stored `IfcBuildingStorey.Elevation` is expressed in the model's own project length unit and is
  **never** a Three.js Y value;
- `model.box` is already world-space (Fragments applies `object.matrixWorld` in its getter), while
  `Elevation + (await model.getCoordinates())[1]` is in the model object's **local** space, and
  `model.getSection(plane)` both consumes and produces geometry in that same local space.

Mapping a logical floor band into the scene therefore means: read the artifact-native `Elevation`, add
the model's own coordinate height, then push the result through the model object's own world matrix.
No model-specific offset, no `model.box.min.y` used as a floor elevation, no geometry centroid.

## 4. Camera and navigation

### 4.1 Controls

Provide only:

- orbit, pan, and zoom;
- fit/home model;
- click selection and Ctrl/Shift additive selection;
- response-driven highlight and fit;
- citation-driven center and fit (invoked by chat, `spec_v009` §5);
- the floor-plan control stack (§8).

Do not add hide/isolate, measurements, user-authored clipping planes, a storey browser, a class tree,
or editing controls. The floor button stack is the only additional main-viewer control and is not a
storey browser.

Desktop control mapping is set explicitly rather than left to camera-controls defaults: left-drag
pans, middle-drag orbits, the wheel zooms. A plain left click within a 4 px threshold selects; beyond
it the gesture was a pan. The orbit pivot resolves cursor raycast → visual base plane → current
target, and never alters selection.

### 4.2 Projection and bounds

Perspective uses three.js's focal-length/film-gauge support (`filmGauge = 36`,
`setFocalLength(50)` ≈ 26.99° vertical), re-applied on resize. The zoom-out bound is
`max(3 x bbox diagonal, 25 m)` — finite and recomputed per load.

### 4.3 Fit policy

Fitting an object or result must center and enlarge it only **moderately**: surrounding geometry stays
visible and a maximum approach/zoom prevents one small element from filling the viewport. Fit
expansion and the minimum fit size are part of this guarantee.

One method (`fitBox`) backs every fit — fit-all, query-result fit, citation fit, and component-panel
group fit — so all of them share identical viewport logic.

### 4.4 Centering within the unobstructed region

Right-side panels obscure part of the canvas. The adapter stores the current obstruction width and
applies `camera.setViewOffset(leftWidth, canvasHeight, 0, 0, canvasWidth, canvasHeight)` with
`leftWidth = canvasWidth - obstructionPx`, floored at a minimum effective-width fraction of the
canvas. Passing the narrower `leftWidth` as the offset's `fullWidth` makes `fitToBox` size content to
the visible region, while the rendered width/height keep the image undistorted and land the fitted
content at pixel `leftWidth / 2` — the visible-region centroid — with no extra shift term.

Because this edits only the projection matrix and never the camera position, Fragments' own
camera+mouse+dom picking and the orbit-pivot raycast stay pixel-correct with no special casing.
Resizing re-applies it from the fresh canvas size. Setting the obstruction alone (a panel opening,
closing, collapsing, or resizing) re-centers the already-framed view without moving the camera or
re-fitting — no unexpected reset.

The obstruction value has exactly one source, shared with the layout CSS variable
(`spec_v006` §7.3). No second set of hard-coded panel measurements may exist.

Orthographic cameras use the same method: `OrthographicCamera.updateProjectionMatrix` widens the
horizontal frustum by exactly `width / fullWidth`, so a box fitted against the full canvas fills the
unobstructed region precisely, centered, never clipped and never stretched.

### 4.5 Base plane

The decorative base plane sits at the loaded model's own geometric minimum (`model.box.min.y`,
scene-space, after the Fragments coordination transform) — **not** IFC/world elevation 0, which can
sit above or below a model's actual geometry. A missing, empty, or non-finite box falls back to scene
`0`. The value resets on unload/model switch and is recomputed on every successful load; it also backs
the orbit-pivot fallback plane.

`depthWrite = false`: below-plane geometry is never clipped, hidden, moved, or occluded. This is a
presentation-only reference value, never reported as an `IfcBuildingStorey` elevation or the IFC
coordinate origin, and no IFC file, database row, or artifact is read or rewritten to compute it.

The grid is hidden in floor-plan mode and restored on return (§8).

## 5. Selection and picking

### 5.1 Manual selection

- Maximum five selected objects.
- Clicking an object obtains its IFC GlobalId locally and resolves it through the deterministic
  resolution endpoint (`spec_v006` §9.2).
- Selection chips are rendered by the chat surface (`spec_v009` §6).
- At five, explain the limit rather than silently replacing one.
- Clicking empty viewer space clears manual selection; no separate Clear Selection control is
  required.
- Debounce/deduplicate resolution requests and ignore stale responses after model or session changes.

Selecting geometry never calls the LLM. Selected objects are supplied with the next question
(`spec_v006` §9.3).

### 5.2 Picking under active query highlighting

While query-primary results are present, only they can be picked:

- the ray is checked against the already-resolved primary local-id set **before** any selection state
  changes, so there is no flicker, replacement, or backend/LLM call;
- transparent/dimmed non-results and relationship-context geometry do not block a primary behind them:
  picking uses the Fragments-supported `model.raycastAll(...)` (one local worker round trip), filters
  the ordered intersections to the resolved primary set, and returns the nearest eligible hit by
  distance;
- non-result geometry is never hidden and never given a per-entity picking mesh — it is simply
  excluded as an occluder for this filtered query;
- a ray with no primary hit is treated exactly like an empty-space click: it clears the current
  non-additive focus rather than silently no-oping, because dimmed geometry is transparent to picking
  rather than a rejecting wall;
- an object hidden by the projected-size policy (§7.3) cannot be picked — a hit on a size-hidden id is
  rejected, so selection identity never depends on whether Fragments raycasts invisible geometry.

Ctrl/Shift additive selection stays primary-only and capped at five. Without active query roles,
picking is unchanged: anything pickable, single nearest-hit `model.raycast`, manual-selection
appearance.

### 5.3 Roles remain distinct

Manual selection and query-result roles remain internally distinct even when they overlap.

## 6. Highlighting and appearance

### 6.1 Semantic roles

Apply the complete semantic roles returned in `viewer_actions`:

- primary matches: strong accessible highlight;
- relationship context: distinct secondary, more muted treatment;
- non-results: visibly reduced while retaining spatial context;
- relationship records themselves: evidence only, never rendered as meshes.

Implement `select_and_fit`, `select_only`, `clear`, and `none` defensively. Missing or unrenderable
GlobalIds produce a bounded warning without breaking the answer or the viewer.

A focused primary stays fully opaque; unfocused primaries drop to the same hue at reduced opacity
(`primaryUnfocused`) — never the manual-selection treatment. Removing the last focus restores all
primaries to opaque.

Count, aggregate, list, RAG, graph, and hybrid results all highlight their full viewer match set, up
to the 2,000-identity viewer cap; above it the deterministic set is applied with a truncation notice
and the exact total stays distinct from the highlighted count (`spec_v006` §9.4).

### 6.2 Centralized theme

`frontend/src/viewer/viewerTheme.ts` is the single place any viewer color, opacity, or camera constant
may live. No inline colors elsewhere in the viewer.

Organizing rule: **base model geometry is achromatic; every semantic role is chromatic.** Role
membership reads as *presence of color* rather than hue discrimination, which survives color-vision
deficiency and the varied grey/beige materials typical of BIM models.

```text
roof #67737f · wall #bcc6d0 · other #dce2e8
primary #1f6feb · manual #0fb5c9 · context (muted, uncolored gray)
dim #c7ced6 (0.35) · plane #c4cdd6 (0.30) · background #e9edf1
```

Wall = `IfcWall` + `IfcWallStandardCase` (+ `IfcWallElementedCase`); roof = `IfcRoof`, plus `IfcSlab`
**only** on an explicit `ROOF` predefined type; everything else `other`. Semantic base colors are
restored after every highlight clear, never one uniform material.

Roof/exterior status is never inferred from name, geometry, position, or an LLM. A model containing no
`IfcRoof` and no explicit slab `PredefinedType` therefore renders nothing in the roof role — the
truthful result, not a defect. A future model carrying explicit roof data colors automatically.

### 6.3 Non-result transparency (accepted decision)

Non-result geometry uses `VIEWER_OPACITY.dim = 0.35` with non-result edges fully disabled
(`EDGES.alpha.dim = 0`).

Fully opaque non-result geometry is **rejected** and must not be reintroduced: with it, interior
query-primary results (partition walls, MEP, doors) are occluded from every external camera angle,
which breaks the guarantee that primary and manual selections remain clearly legible. Primaries must
stay visible *through* non-results.

### 6.4 Entity edges

Every rendered entity carries ~1 px feature edges, built asynchronously after scene-ready from the
already-loaded model's geometry (`src/viewer/EdgeOverlay.ts`), with an RGBA vertex-color attribute and
a `localId -> {chunkIndex, start, count}` index.

- **Spatially chunked and frustum-culled.** Each entity's edge-vertex centroid is bucketed into a
  uniform 3D grid cell (sized from the model bounding box and item count) during the same yielded
  batch-extraction loop, and one `LineSegments` is mounted per populated cell with a real computed
  bounding sphere/box and `frustumCulled = true` (target: roughly 50–150 populated chunks). A single
  whole-model non-culled object is not acceptable.
- **Color follows role.** Edge color always follows the entity's current face role (base roof/wall/
  other and every highlight role), darkened ×0.72; transparent faces get more-opaque edges. All values
  live in `viewerTheme.ts` (`EDGES`).
- **Threshold angle** `EDGES.thresholdAngleDeg = { balanced: 25, largeModel: 40 }`, chosen from the
  model's provisional profile before the build starts so a large model builds at the coarser angle on
  its first pass, never a rebuild.
- **Bounded recoloring.** `recolor()` rewrites only changed entities and uploads only the touched span
  of each touched chunk, never a global envelope.
- **Hidden faces leave no floating wireframe:** a `hidden` edge role with alpha 0 exists for
  size-hidden objects (§7.3).
- **Disposal** iterates every chunk's geometry/material on unload/switch/reset; a build finishing after
  `dispose()` is ignored via the disposed-flag guard, so a mid-build model switch abandons cleanly.
- Yield with `MessageChannel`, not `setTimeout(0)` — background-tab timer clamping turns a ~1 s build
  into ~30 s.

The class also contains motion-hide, screen-size LOD, and a separate highlight-edge overlay. These are
**not wired** to the adapter (§7.2) and must not be re-wired without the evidence §7.4 requires.

## 7. Rendering and resource policy

### 7.1 Priorities

- load only one active model into the scene;
- use prepared Fragments, workers, and the culling/LOD facilities the maintained stack supports;
- never fetch full canonical JSON for selection or display;
- avoid rerendering the React tree on camera movement, and keep mutable Three.js/That Open objects
  outside serializable React state;
- debounce resize and identity-resolution work;
- dispose models, materials, workers, event listeners, object URLs, and GPU resources on switch/reset;
- measure first-load, cached-load, scene-ready, query, highlight, and reset timing, and report actual
  results rather than inventing unsupported performance claims.

If the current IFC cannot meet usable local interaction with supported Fragments settings, report the
measured bottleneck before raising limits, adding large dependencies, or reducing identity
correctness.

Headless-Chromium GL numbers are software rendering, not the real GPU: they are usable only as
*relative* before/after evidence. Interaction smoothness is confirmed on the owner's real hardware.

### 7.2 Continuous rendering (accepted decision)

`SimpleRenderer` runs in its default **automatic continuous** rendering mode. There is no manual
`needsUpdate` flow, render scheduler, render hold, or hidden-tab suspension.

Fragments LOD/visibility refreshes through one plain `fragments.core.update(true)` on **model load,
camera rest, and an actual highlight/material change** only. No per-motion or per-tick update, and no
unforced `core.update()` call site anywhere in the viewer.

### 7.3 Projected-size visibility policy

A screen-size-driven visibility filter composes with — and never replaces — Fragments LOD/visibility,
frustum culling, the chunked edge overlay, and mesh simplification.

**The rule.** An object's projected size is its bounding-sphere diameter in CSS px under the active
perspective camera:

```text
px = (2 * radius * viewportHeightPx) / (2 * distance * tan(fov / 2))
```

An object enters the reduced state below **20 px** and leaves it only above **24 px**; between the two
it keeps its previous state. The decision depends ONLY on projected size — never on absolute camera
distance and never on whether the camera is moving. A camera inside an object's bounding sphere yields
`Infinity`, so an enclosing object is never hidden. The horizontal view offset (§4.4) passes
`fullHeight === height`, so the vertical mapping stays correct with or without an offset.

**When it is evaluated.** Model load, camera `rest`, viewport resize, view-offset/projection change,
and highlight changes. There is no per-frame whole-model scan and no periodic Fragments update during
camera motion; this policy introduces no navigation, motion, wake, or stationary rendering mode. Each
evaluation is a numeric pass over cached centres/radii and applies only the ids whose visibility
actually changed, via one bounded `setVisible` call per direction, followed by the single Fragments
refresh the caller already performs.

**Retained at any projected size:**

- walls, including every wall subtype the viewer recognises;
- roofs;
- slabs — both explicit roof slabs and ordinary floor slabs;
- doors and windows with explicit IFC `IsExternal = true`;
- columns with explicit IFC `LoadBearing = true`.

Everything else non-highlighted is hidden below 20 px and restored above 24 px through the existing
rendering and material path, without reloading the model.

Exterior/load-bearing status is NEVER guessed from names, geometry, position, material, proximity, or
an LLM. Only an explicit IFC boolean qualifies; a missing, null, string, or otherwise ambiguous value
does not. A model that stores these in a non-standard flattened pset therefore has no qualifying
doors/windows/columns — the correct outcome under this rule.

**Implementation trap:** the property read requires `getItemsData(ids, { attributesDefault: true,
relations: { IsDefinedBy: … } })`. With a pruned attribute list the Fragments API returns the relation
array EMPTY, which silently reads as "property absent" for every object.

**Highlighted and selected objects bypass the filter entirely** and are never hidden, however small.
Highlighting an otherwise filtered object makes it visible immediately; clearing the highlight
reapplies its current size/category state. The policy never drops or broadens the identities the query
pipeline returned. Detail level for highlighted objects is handled by Fragments' own mesh LOD and the
edge overlay's dedicated highlight thresholds; no new per-object detail control exists for them.

**Guarantees.** Filtered objects remain loaded and restore deterministically above 24 px; they cannot
be picked (§5.2); the isolated component preview is unaffected because the policy is driven by the main
camera only; classification and bounding volumes are cached once at load, and camera updates never
re-read IFC data, rebuild geometry, regenerate artifacts, or call the backend/database/embedding
service/LLM. Failure is safe: if required Fragments APIs are missing or classification throws, the
policy stays inactive and every object remains visible. It is an optimization, never a correctness
requirement.

`getItemsWithGeometry()` must NOT be used to pre-restrict the candidate set (it has been measured
stalling for minutes on a 283k-item model). Candidates self-restrict, because `getBoxes` returns an
empty box for a geometry-less item and those are skipped. The one-time classification pass runs
asynchronously after the scene is usable — the same pattern as the edge overlay — so it never blocks
load or input; on a pathological model the policy simply becomes active a few seconds after the model
appears.

The policy is **suspended** in floor-plan mode rather than misapplied (§8.5).

### 7.4 Rejected approaches — do not reintroduce

The following were built, measured, and removed after the owner confirmed on real RTX 5080 Laptop
hardware that a large model (≈27k items, ≈5.4M edge vertices) lagged *more* during pan/orbit/zoom
than the continuous-rendering viewer, even though stationary GPU usage improved. The diagnosis is
load-bearing: on this GPU raw per-frame render cost was never the bottleneck; the per-gesture
**transition** work was. Natural navigation is many small start/stop nudges, so that machinery ran
constantly.

Do not reintroduce without new real-hardware evidence:

- manual `RendererMode.MANUAL` rendering with an invalidation scheduler and hidden-tab suspension;
- adaptive main-viewer pixel ratio driven by a frame-time sampler / sustained-slow verdict;
- Fragments `maxUpdateRate` throttling and forced-update race guards;
- camera-motion base-edge hiding and rest-triggered edge LOD;
- a user-facing adaptive-profile override control;
- any other per-gesture transition work on wake/rest.

The accepted trade-off is higher idle GPU usage in exchange for zero interaction-time scheduling
overhead.

`detectProfile()` (`src/viewer/profileDetection.ts`) is retained **solely** to size the component
preview's frame-rate cap and pixel ratio (`spec_v011` §5). It classifies from artifact byte size, item
count, and edge vertex count only — never model name, id, category, discipline, or storey — and it
influences no main-viewer rendering decision.

## 8. Floor-plan mode

A mode of the **existing** viewer: same components, same world, same canvas, same Fragments model.
Only the camera in use and two clipping planes change. It is not a second canvas, a second Three.js
world, a generated image, a saved drawing, an explanation-panel visualization, an IFC rewrite, or a
general-purpose sectioning system.

A compact vertical control appears under **Reset app**: `3D`, then one button per logical floor.
Choosing a floor turns the viewer into a top-down orthographic plan of that floor, cut ~1.2 m above it
and bounded below so lower floors do not appear through openings. Choosing **3D** removes the cut and
restores the exact perspective view that was active before plan mode.

No tree, storey browser, visibility checklist, arbitrary clipping-plane editor, saved-view manager,
hide/isolate, measurement, reflected ceiling plan, elevation, export, editing, or annotation is added.

### 8.1 One authoritative floor definition

```text
GET /api/models/{source_model_id}/floors -> ModelFloorsResponse
```

One narrow, typed, allowlisted (`extra="forbid"`), read-only, source-model-scoped endpoint. It reuses
`app/query/semantic/spatial.py::build_storey_model()` — the same elevation-gap `FloorBand` clustering
the natural-language floor interpretation resolves against — so the buttons and "the second floor" can
never disagree. **There is no second floor detector.** A model's raw storeys therefore resolve to its
real floors, and multi-wing storeys at the same elevation stay one button.

Response: `source_model_id`, `available`, `unavailable_reason`, `reference_band_index`,
`reference_basis` (`elevation_zero | lowest_band | none`), `total_storeys` (raw storeys, so the
storey-versus-floor difference stays observable), and `floors` — one `FloorBandInfo` per **logical
band**, never per raw `IfcBuildingStorey`: `band_index` (0-based, ascending by elevation), `label`,
`is_reference`, `storey_global_ids`, bounded `storey_names`, `min_elevation`, `max_elevation`.

Labels come from `spatial.band_label(band_index, reference_index)`, a pure helper shared by the
endpoint and the existing floor interpretation: the reference band is **Floor 1**, bands above
continue upward, and bands below get neutral **Lower level N** names rather than an invented basement
designation. Storey names are carried for tooltip/accessible use only and never discover, group,
order, or label a floor.

`min_elevation`/`max_elevation` are stored project-unit diagnostics for exactly one purpose —
diagnostics. **They are not viewer scene coordinates** and must never be used as Three.js Y values
(§3). The frontend's `FloorContractBand` type deliberately omits them so the adapter cannot.

Deterministic and LLM-free: no IFC parse, viewer-asset read, OpenAI call, embedding, or database
write. A model with no usable storey elevations returns an honest `available: false` with a bounded
reason, and the frontend then omits the control entirely.

### 8.2 Scene-space plan range

`frontend/src/viewer/floorPlan.ts` owns the arithmetic as pure functions with no scene access, so the
numbers are exactly testable. Given bands already mapped into scene space (§3):

```text
base  = highest resolved scene elevation in the selected band
cut   = min(base + 1.2 m, next_band_lowest_scene_elevation - tolerance)
lower = (band_below.highest + selected.lowest) / 2, else model.box.min.y for the lowest band
```

The uppermost floor uses the nominal 1.2 m cut without inventing a next level. An **unresolved** band
above cannot constrain the cut. The tolerance is `planeTolerance()`: a few Float32 ULPs scaled by the
magnitudes actually being compared, so a metre model and a far-from-origin model each get a
proportional separation — never a per-file tuned value.

A band whose constituent storeys do not all resolve to a finite scene elevation, or whose range is
non-finite or does not extend above the band, keeps its button **visible but disabled with a concise
reason**. No guessed plane is ever placed.

The lower boundary is presentation-only: it changes no containment, membership, coordinate, or query
scope.

### 8.3 Projection, navigation, and camera ownership

`OBC.Views` + `View` provide the two-plane clipped view and reversible camera ownership, using the
View's own `OrthoPerspectiveCamera` in `Orthographic` + `Plan` mode. The View's `farPlane` sits `range`
below the cut, which is exactly the required lower boundary, so no second clipping mechanism exists.
Every drag pans and the wheel zooms; nothing orbits. `model.useCamera()` repoints Fragments' own
LOD/culling at whichever camera is rendering.

No installed package is patched, no private field read, no second world created; the `ViewerAdapter`
boundary is intact — React only requests typed viewer actions.

**Camera save/restore:** the adapter saves the pose itself (`views.restoreCameraOnClose = false`) and
captures it **only on the first departure from 3D**, so floor-to-floor switching cannot overwrite it.
Returning to 3D re-asserts the 50 mm lens, desktop control mapping, and panel-aware centering before
restoring the exact position and target.

### 8.4 Cut graphics

`model.getSection(localPlane)` runs in the existing worker for the **active floor only**, never
precomputed per floor at load. The world plane is transformed into model-local space before the call
and the results mounted under `model.object`, because `getSection` both consumes and produces geometry
in that space. Output is copied out of the worker's fixed scratch buffer so only the used vertices are
retained.

With a query highlight active, a second layer is requested for exactly the primary local ids and drawn
over the base cut in the primary highlight color, so established roles survive into the plan and
highlighted cut geometry stays legible over the base contour. Layers are nudged `PLAN.cutInsetM`
(2 mm) off the plane that produced them, because exactly-coplanar geometry makes the GPU clip test a
coin flip.

**Visual hierarchy.** `VIEWER_COLORS.planCut` is the darkest ink in the viewer (asserted against every
base gray and against the darkened edge colors), fully opaque, with a restrained translucent
`planFill`. All cut layers render above the base edge chunks and the highlight overlay. The decorative
base grid is hidden in plan mode and restored on return.

**Nothing is fabricated:** no door swings, symbols, room tags, dimensions, annotations, north arrows,
or scale bars. Source geometry remains the only graphic authority. This is a clean model-derived plan
slice, not a claim of documentation-drawing equivalence.

### 8.5 Interaction with other viewer policies

- `applyViewOffset` is generalized to orthographic (§4.4), so a plan fits the unobstructed region.
- The projected-size policy (§7.3) is **suspended**: entering plan mode restores everything it had
  hidden, so the plan is never missing geometry, and leaving re-evaluates against the restored
  perspective camera.
- Edge LOD and motion hiding remain unwired (§7.4).

### 8.6 Lifecycle and state

A monotonic `planToken` guarantees an older floor's asynchronous section can never replace a newer
selection. Switching floors, leaving plan mode, unloading, and disposing all dispose the previous view,
camera, cut fills, contours, and materials; repeated switching leaves exactly one live view and one
live overlay.

Store state — `3d`/`plan`, active source-model id, active band, contract availability — is serializable
and current-session only. The saved pose and the live clipping/section objects stay inside the
imperative viewer layer. Nothing is persisted to local storage.

### 8.7 Independence from query presentation

Entering or leaving plan mode creates no chat turn, issues no query, calls no LLM, and neither opens
nor closes the explanation panel (`spec_v010` §11). Query-primary, relationship-context, and
manual-selection roles are untouched. A later query never chooses or changes a floor. A highlight
arriving while a plan is active rebuilds the cut layers for the new roles and never silently returns
to perspective.

### 8.8 Failure behavior

A floor-contract failure or a failed plan construction never unloads the model or breaks the 3D
viewer. No usable floor data omits the control; one unmappable floor disables only that button; a
response for a superseded model or load is ignored; a section-generation failure keeps the truthful
clipped orthographic view and reports a concise non-blocking limitation; **3D** stays available after
any plan-rendering failure.

## 9. Viewer failure behavior

Provide explicit, recoverable states for: asset missing/stale, artifact download failure, IndexedDB
unavailable or quota denied, worker/WASM initialization failure, unsupported or corrupt Fragments
artifact, a GlobalId that is not renderable or not resolvable, and a stale response after a model or
reset change.

Do not crash the UI because one entity cannot be highlighted, and do not expose credentials, local
paths, stack traces, or provider internals (`spec_v006` §11, §13).

## 10. Known verification gaps

Live in-browser visual verification of the projected-size policy and of floor-plan mode against the
ingested models has not been performed; the standing evidence is automated tests plus artifact-level
measurement and a Playwright run against the tracked fixture artifact. Real-model checks —
raw-storey-versus-logical-floor counts, per-floor inspection, cut-versus-projected legibility,
bleed-through, highlight colors in plan, and repeated-switch resource growth — remain owner-run on
real hardware, consistent with §7.1.
