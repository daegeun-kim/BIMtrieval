# Task 14: Viewer Interaction, Semantic Colors, and Component Detail Panel

## Prerequisites and execution order

Require:

```text
tasks/task13_done.md
tasks/task11_done.md
specs/spec_v006_frontend_application.md
```

Do not begin until Task 13 is complete and its OpenAPI contract has been validated. Regenerate the
frontend API types from that contract before using the new fields/endpoints.

## Mandatory Claude design plugin

Invoke the installed Claude **`frontend-design`** plugin before changing the UI. Give it the owner
intent and constraints in this task and v006. It may choose precise color values, panel widths,
spacing, corners, typography refinements, and transitions, but it must not change product scope,
API semantics, viewer controls, limits, or truthful data rules.

If the plugin is unavailable, stop and report that instead of silently designing without it.

## Objective

Refine the existing lightweight desktop BIM application so that:

- default model colors communicate roof/wall/other classes;
- camera and mouse controls feel like a precise desktop BIM viewer;
- every entity-returning query, including counts, highlights its database matches;
- chat displays concise summaries rather than component dumps;
- clicking an object opens a floating component panel immediately left of chat;
- the component panel provides an isolated interactive preview, truthful details, and deterministic
  instance/type/family highlight actions;
- Clear Chat and Reset App remain visibly and behaviorally distinct.

Do not turn this into a property dashboard or full BIM authoring tool. Keep it bright, fast, and
minimal.

## 1. Centralized viewer colors

Create one clearly named frontend theme module, recommended:

```text
frontend/src/viewer/viewerTheme.ts
```

Put all editable viewer material/color/opacity definitions together near the top of that module.
No roof/wall/default/highlight colors may be scattered through adapters or React components.

The `frontend-design` plugin should choose accessible exact values following these owner roles:

```text
Roof: dark gray
Wall: light gray
All other model geometry: very light gray
Primary query match: strong distinct highlight
Relationship/context match: distinct muted highlight
Manual selection: distinct from both query roles
Non-result geometry during query highlighting: highly transparent gray
Base plane/grid: quiet neutral tone
```

Class mapping:

- wall includes every `IfcWall` subtype represented in the artifact, including
  `IfcWallStandardCase`;
- roof includes `IfcRoof` and `IfcSlab` only when its explicit predefined type is `ROOF`;
- everything else uses the very-light-gray default.

Preserve semantic base colors after highlight reset. Query highlighting temporarily dims
non-results; clearing query highlights restores roof/wall/other colors rather than one uniform
material. Keep manual selection visibly distinct and layered predictably.

## 2. Camera and navigation behavior

Encapsulate all changes in the existing viewer adapter/service. Do not scatter Three.js/That Open
imperative mutations through components.

Implement and test this exact desktop control mapping:

- plain left click without meaningful movement: select object;
- left-button drag: pan;
- middle/wheel-button drag: rotate/orbit;
- mouse wheel: zoom;
- Ctrl/Shift additive selection and the five-manual-selection cap remain unchanged.

Use a small movement threshold to distinguish click selection from left-drag pan. Show a hand/grab
cursor for pan and an appropriate grabbing state while dragging. Preserve accessible focus and
keyboard behavior already present.

### Rotation pivot

At the start of a middle-button rotation:

1. raycast beneath the cursor against visible model geometry;
2. if no geometry is hit, intersect the elevation-zero base plane;
3. if neither is valid, retain the current orbit target.

Use that point as the orbit center without a disorienting camera jump. Do not permanently alter
selection merely to establish a pivot.

### 50 mm full-frame perspective

Use a perspective equivalent to a 50 mm lens on a 36 × 24 mm full-frame camera. Prefer the camera
API’s focal-length/film-gauge support; otherwise derive the correct field of view for the active
aspect ratio. Do not merely hard-code an arbitrary narrow FOV. Preserve guarded fit behavior so
small selected objects are only enlarged slightly after centering, not zoomed to fill the screen.

### Zoom-out bound

After model load, calculate a finite zoom-out bound from the model bounding box. Maximum
camera-target distance should be approximately three times the full model bounding-box diagonal,
with a safe minimum for tiny/test models. Clamp smoothly and recompute on model switch. Do not
restrict normal zooming into the model.

### Elevation-zero base plane

Place the visual base plane/grid at IFC/world elevation exactly `0`, transformed correctly into the
viewer scene coordinate system. Do not place it at bounding-box center or model minimum elevation.
Below-zero/underground geometry must remain possible and must not be clipped or repositioned.

If the artifact transform makes elevation mapping nontrivial, derive it from the loaded model’s
coordinate/transform information and document the result. Do not infer ground from the bounding
box. Keep the plane visually light enough not to obscure underground geometry.

## 3. Apply backend viewer matches consistently

Consume Task 13’s viewer match/actions for list, count, aggregate, RAG, graph, and hybrid results.
For a query such as “How many doors are there in total?” the frontend must:

- show the exact total in chat;
- highlight returned door identities;
- dim non-results with transparent gray;
- disclose if the viewer set was truncated above 2,000;
- keep the exact count distinct from the displayed/highlighted count.

“Show me all the walls” must use both `IfcWall` and `IfcWallStandardCase`. Below the 2,000 viewer
cap, highlight all matching rendered walls rather than the former 50-evidence subset. Above the cap,
apply the deterministic 2,000 identities and display a concise truncation notice.

Do not render relationship records as geometry. Missing/unrenderable GlobalIds remain a bounded
warning, not an application failure.

## 4. Simplify chat result presentation

For ordinary SQL, RAG, graph, and hybrid results, show:

- the concise natural-language answer/description;
- exact total when applicable;
- a compact class summary such as “5 doors, 3 windows”;
- a short viewer-truncation/unrenderable warning only when applicable.

Do not list every retrieved component or show all component property details in the chat. Keep the
existing bounded evidence/debug information available only through a compact collapsed disclosure
if still useful; it must not dominate the response.

Only show one component’s details in chat when the backend explicitly identifies sample-detail
intent, for example “pick a sample and show me its details.” Do not reinterpret ordinary show/count
queries as requests for component details.

## 5. Component detail panel

Clicking a rendered component in the main viewer must still select it and must also open a floating,
rounded component-detail panel immediately to the **left of** the existing floating chat panel.
When both panels are visible, automatically use narrower default widths for both so the model stays
usable. Keep reasonable resizing/collapse behavior and prevent panels from overlapping or leaving
the viewport. Let `frontend-design` choose exact desktop dimensions.

The panel must be lightweight and contain:

1. selected instance name/class and compact identity;
2. a small lazy-loaded isolated interactive 3D preview of that instance;
3. a small-font read-only nested/list presentation of available instance, type, family, dimensions,
   quantities, materials, and allowlisted properties below the preview;
4. deterministic buttons for `Instance`, `Same type`, and `Same family` highlighting.

Fetch details through Task 13’s narrow backend endpoint. Do not access PostgreSQL from the browser,
return canonical JSON, call an LLM, or request raw IFC parsing.

### Truthful optional layers

- Instance information is shown for a valid selected entity.
- Type appears only if the endpoint reports explicit IFC type data.
- Family appears only if the endpoint reports an explicit allowlisted family property; show its
  source property-set/property label where helpful.
- Omit absent fields instead of displaying empty placeholders.
- Disable `Same type` or `Same family` with a concise reason when unavailable.
- Never infer type/family from the object name or ask an LLM to guess it.

The current Schependomlaan model is expected to have no useful explicit type relationship. Its
missing type/family actions must therefore degrade cleanly. Other future IFC models can show these
fields automatically from the already-stored canonical data; no schema change or re-ingestion is
required by this task.

### Isolated preview behavior

The preview must:

- render only the selected instance, with a transparent/quiet background;
- lazy-initialize only when the panel is open;
- reuse the already loaded/cached artifact and geometry resources where safely supported rather
  than downloading or parsing the full artifact again;
- remain centered with a guarded, slightly enlarged fit;
- allow orbit/pan/zoom interaction;
- rotate slowly when untouched;
- pause auto-rotation while hovered/dragged/recently interacted with, then resume after a short idle
  interval;
- disable auto-rotation under reduced-motion preference;
- dispose listeners, render loops, and GPU resources on selection change, panel close, model switch,
  and Reset App.

Choose the safest resource-sharing/subset approach supported by the installed That Open/Fragments
version. Do not duplicate the entire model in memory merely for implementation convenience if a
lightweight subset/view is available. Document the chosen approach and measured impact.

### Highlight action behavior

The three buttons call Task 13’s deterministic group endpoint and do not submit chat queries:

- `Instance`: selected GlobalId only;
- `Same type`: all explicit same-type matches in the active model;
- `Same family`: all explicit same-family matches in the active model.

Apply the returned identities with the strong primary query-match role, dim other geometry, center
the group, and zoom only slightly. Keep the selected entity as the component-panel subject. Show
the exact group total and truncation warning. These actions must not add messages/history, consume
OpenAI tokens, or alter the backend conversation session.

Guard against stale detail/group responses after rapid selection, panel close, model switch, Clear
Chat, or Reset App.

## 6. Clear Chat and Reset App placement/behavior

Keep **Clear Chat** in its current chat-panel location. Its established semantics remain:

- clear chat/history supplied to the LLM and query result roles;
- start a fresh backend session;
- retain the loaded model, cache, and current manual selection.

Move **Reset App** to the top-left of the main viewer panel. It must remain clearly distinct from
viewer Home/Fit controls and retain its established semantics:

- clear conversation, component panel, selection, highlights, and active model;
- dispose the main and preview viewer state;
- return to the initial model-selection state;
- retain IndexedDB model cache and harmless UI preferences.

Use a lightweight confirmation only where the existing design requires it. Neither control may
delete database rows, vectors, artifacts, or cached model data.

## 7. State, API types, and performance

- Regenerate frontend TypeScript API types from Task 13 OpenAPI; do not hand-copy contracts.
- Keep one API client and the existing viewer adapter boundary.
- Store only harmless current-session UI state as already established; do not persist component
  details or backend trace data.
- Cancel or ignore stale requests with existing AbortSignal/token patterns.
- Avoid React state updates on every render frame.
- Avoid a second network model download and avoid unnecessary geometry cloning.
- Keep normal orbit/pan/zoom/selection/detail/group operations LLM-free.
- Preserve local-only, bright, desktop-oriented scope and existing security rules.

## 8. Tests and validation

Update/add tests for at least:

- centralized viewer theme roles and restoration after highlight clear;
- roof/wall/other class mapping, including roof slabs and `IfcWallStandardCase`;
- count/aggregate results highlighting all returned viewer identities;
- 2,000 viewer truncation versus exact total;
- concise chat summary with no ordinary component dump;
- explicit sample-detail exception;
- left-click selection versus left-drag pan threshold;
- middle-drag orbit and cursor-derived pivot fallbacks;
- 50 mm full-frame camera configuration;
- zoom-out bound based on approximately 3× model diagonal;
- elevation-zero plane with below-zero geometry unaffected;
- panel open/close/layout and narrower dual-panel defaults;
- detail endpoint loading/error/stale response behavior;
- absent versus explicit type/family rendering and disabled actions;
- deterministic action buttons making no chat or LLM call;
- isolated preview center/fit, interaction pause/resume, reduced motion, and disposal;
- Clear Chat versus Reset App placement and semantics;
- existing frontend regression tests.

Run:

```powershell
cd frontend
npm run gen:api
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

Then test the full application locally with the existing launcher or separate backend/frontend
commands. Validate representative count, show-all-walls, explicit sample, click-detail, and each
available group action against the current model. Use browser performance/memory tooling to compare
before/after viewer load, main interaction, panel open, preview creation, and disposal. Report
measured seconds/memory where available; do not claim unmeasured improvements.

Confirm no normal frontend operation exposes secrets, SQL, vectors, filesystem paths, canonical
JSON, or backend trace records. Confirm database and vector metadata remain unchanged.

## Prohibited actions

- Do not start before `task13_done.md` exists.
- Do not proceed without the Claude `frontend-design` plugin.
- Do not modify ingestion, parse IFC, regenerate vectors, or add PostGIS.
- Do not access PostgreSQL or OpenAI directly from the frontend.
- Do not infer type/family or add an LLM call to details/group actions.
- Do not remove all result limits or send 2,000 detailed records to the LLM/chat.
- Do not add upload, editing, measurement, sectioning, trees, dashboards, dark mode, auth, or mobile
  scope.
- Do not add automatic live OpenAI tests.
- Do not make the base plane follow the model minimum or bounding-box center.
- Do not allow underground geometry to be clipped by the plane.
- Do not leave duplicate preview render loops or GPU resources alive.

## Acceptance criteria

1. Viewer colors are centralized and restore correctly after selection/highlighting.
2. Mouse controls, cursor pivot, 50 mm perspective, zoom bound, and elevation-zero plane behave as
   specified.
3. Count/aggregate results highlight the same objects represented by SQL results.
4. All walls below 2,000 are highlighted while LLM evidence remains bounded independently.
5. Normal chat responses show summaries, not component dumps.
6. Clicking geometry opens a usable, truthful, efficient component panel left of chat.
7. Instance/type/family actions are deterministic, model-scoped, and LLM-free.
8. Clear Chat remains in chat; Reset App is at viewer top-left with correct distinct semantics.
9. Existing model loading, caching, query, selection, and reset behavior regressions pass.
10. Database, vectors, ingestion, and prepared model artifact remain unchanged.

## Completion report

Rename this file to `tasks/task14_done.md` only when complete. Append:

- confirmation and output of `frontend-design` usage;
- files/components/services changed;
- final centralized color roles and class mapping;
- camera/control/pivot/zoom/base-plane implementation;
- aggregate/all-wall highlighting behavior and limits;
- concise chat and sample-detail behavior;
- component panel, truthful field availability, and group-action behavior;
- isolated preview resource strategy and measured performance/memory impact;
- Clear Chat/Reset App validation;
- type/lint/unit/build/e2e/full-local results;
- database/vector before/after confirmation;
- explicit statuses:

```text
Frontend design plugin: USED
Centralized semantic viewer colors: VALIDATED
Camera and navigation controls: VALIDATED
Elevation-zero base plane: VALIDATED
Aggregate/all-match highlighting: VALIDATED
Concise chat presentation: VALIDATED
Component detail panel: VALIDATED
Instance/type/family actions: VALIDATED
Clear Chat and Reset App: VALIDATED
Frontend regression and local integration: VALIDATED
Database/vector/ingestion state: UNCHANGED
```

---

# Completion Report (2026-07-15)

Implemented against the validated Task 13 contract. Frontend types were regenerated from that
contract first. No ingestion, IFC parse, vector, PostGIS, database, or model-artifact change.

## Frontend design plugin: USED

The `frontend-design` skill was invoked before any UI change, with the owner intent and the fixed
constraints from this task and v006. Its guidance is explicit that a brief which pins a visual
direction wins — this one pins the whole language ("measured drawing": bright sheet `#EDF1F5`,
blueprint blue `#1F6FEB`, ochre `#E0912A`, teal, Space Grotesk / IBM Plex Sans / IBM Plex Mono), so
the design latitude was deliberately narrow: exact viewer material values, panel geometry, and the
disabled-action treatment. Product scope, API semantics, viewer controls, limits, and the truthful
data rules were not touched.

**The one structural design decision** (documented at the top of `viewerTheme.ts`):

> Base model geometry is **achromatic**; every semantic role is **chromatic**.

Roof/wall/other are pure cool grays; primary/context/manual stay saturated blue/ochre/teal. So "is
this object a query result?" is answered by the *presence of color* rather than by discriminating
one hue from another — which holds up under any color-vision deficiency and over the varied
grey/beige materials typical of BIM models. The gray ladder then separates the base classes on
lightness alone. Roof reads darkest because that is the poché convention of the drawing this
interface imitates. This is asserted by tests, not just asserted in prose.

## Files changed

**New**

```text
src/viewer/viewerTheme.ts        centralized theme: colors, opacity, camera, class mapping
src/viewer/PreviewScene.ts       isolated single-instance preview (lifecycle + disposal)
src/components/ComponentPanel.tsx    floating detail panel, left of chat
src/components/ComponentPreview.tsx  lazy preview host
src/components/ViewerControls.tsx    Reset App at the viewer's top-left
src/chat/ResultSummaryView.tsx   compact totals/class summary + sample detail
src/chat/resultSummary.ts        IFC class -> readable label/merge/pluralize
tests/viewer-theme.test.ts            17 tests
tests/viewer-controls.test.ts         17 tests
tests/viewer-pointer.test.ts           9 tests
tests/component-panel.test.tsx        22 tests
tests/component-controller.test.ts    13 tests
```

**Changed**

```text
src/types/api.ts            regenerated from the Task 13 OpenAPI (npm run gen:api)
src/api/types.ts            + ResultSummary/SampleDetail/EntityDetails*/HighlightGroup* aliases
src/api/client.ts           + entityDetails(), highlightGroup()
src/viewer/ViewerAdapter.ts controls mapping, 50 mm lens, zoom bound, cursor pivot,
                            elevation-0 plane, semantic base colors, geometry extraction
src/state/store.ts          + component panel state, dual-panel width helper
src/state/controller.ts     + detail/group flows with separate stale tokens, truncation notice
src/chat/ChatPanel.tsx      Reset App removed (moved to viewer); narrows when paired
src/chat/Message.tsx        + ResultSummaryView
src/App.tsx / src/App.css   dual-panel layout, --chat-w var, panel + control styling
src/viewer/highlightRoles.ts  DELETED — superseded by viewerTheme.ts
```

## Final centralized color roles and class mapping

All editable values sit in one block at the top of `src/viewer/viewerTheme.ts`; no roof/wall/
default/highlight color exists anywhere else (the old inline `#e9edf1` background and `#c4cdd6`
grid in `ViewerAdapter` are gone).

```text
roof              #67737f            dark gray        (sRGB chroma 0.09)
wall              #bcc6d0            light gray       (chroma 0.08)
other             #dce2e8            very light gray  (chroma 0.05)
primary match     #1f6feb  opaque    blueprint blue   (chroma 0.80)
relationship ctx  #e8a94f  a=0.92    ochre            (chroma 0.60)
manual selection  #0fb5c9  opaque    teal             (chroma 0.73)
dimmed non-result #c7ced6  a=0.16    highly transparent gray
base plane/grid   #c4cdd6  a=0.30    quiet neutral, depthWrite=false
scene background  #e9edf1            the sheet
```

Class mapping: wall = `IfcWall` + `IfcWallStandardCase` (+ `IfcWallElementedCase`); roof =
`IfcRoof`, plus `IfcSlab` **only** when its explicit predefined type is `ROOF`; everything else
`other`. Base colors are re-applied on load and restored after every highlight clear — not one
uniform material.

### Measured finding: this model has no roof data (expected, not a defect)

Verified against **both** the database and the artifact:

- the model contains **no `IfcRoof` at all**;
- **all 279 `IfcSlab` have no `PredefinedType`** (absent in the DB; absent in the Fragments
  artifact too — histogram `{"(absent)": 279}`);
- their names are `dekvloer` / `vloerveld` — Dutch for screed floor / floor field. They are floors.

So the roof role correctly matches **zero** entities here, and no geometry renders dark gray. That
is the truthful outcome: coloring them as roof would require inferring roof from name or IFC class,
which §1 forbids. Wall coloring works and is visible (880 walls in mid-gray against very-light
"other"). A future model carrying `IfcRoof`/`IfcSlab(ROOF)` gets roof coloring automatically with no
code change.

## Camera / controls / pivot / zoom / base plane

- **Controls**: `left = TRUCK` (pan), `middle = ROTATE` (orbit), `wheel = DOLLY` (zoom), set
  explicitly because camera-controls defaults left to rotate. A plain left click within a 4 px
  movement threshold selects; beyond it, the gesture was a pan and never selects. Middle-button
  release never selects. Cursor is `grab`, `grabbing` while dragging.
- **Pivot**: on middle-button down — raycast under the cursor → else intersect the elevation-zero
  plane → else retain the current target. Selection is never altered to establish a pivot.
- **50 mm full-frame**: `camera.filmGauge = 36; camera.setFocalLength(50)` — three.js's own
  focal-length/film-gauge support, not a hard-coded FOV. Yields ~26.99° vertical, re-applied on
  resize. `verticalFovDeg(aspect)` derives the same value independently and is unit-tested.
- **Zoom-out bound**: `maxDistance = max(3 x bbox diagonal, 25 m)`, recomputed per model load,
  finite, and never restricting zoom *into* the model.
- **Base plane**: placed at **IFC/world elevation exactly 0**, derived from the model's own
  `getCoordinationMatrix()` — not the bbox centre or minimum. Tested with a model whose geometry
  starts at y=20: the plane stays at 0. `depthWrite = false` and 0.30 opacity, so below-zero
  geometry is never clipped or occluded.

## Aggregate / all-wall highlighting and limits (live)

| query | exact total | viewer highlighted | LLM evidence |
|---|---|---|---|
| "How many doors are there in total?" | **205** | **205** ids + `select_and_fit` | 0 |
| "Show me all the walls" | **880** (648 `IfcWall` + 232 `IfcWallStandardCase`) | **880** ids | **50** |

Before Task 13 the door count highlighted **nothing** and the wall query highlighted at most the
50-entity evidence subset while missing 232 standard-case walls entirely. The three limits are now
independently observable in one response. Above 2,000 the frontend applies the deterministic 2,000
identities and shows a concise truncation notice; the exact count stays distinct from the
highlighted count. Relationship records are never rendered as geometry, and unrenderable GlobalIds
remain a bounded warning.

## Concise chat and sample-detail behavior

Ordinary results render the concise answer, the exact total, and a compact class summary
("5 doors, 3 windows"), plus a truncation/unrenderable warning only when applicable. `IfcWall` and
`IfcWallStandardCase` merge under one "wall" label, so 648 + 232 reads as **"880 walls"** rather
than a distinction without a difference. No component list and no per-component properties appear;
the pre-existing bounded evidence stays behind its collapsed disclosure.

Live sample-detail check:

```text
"Pick a sample door and show me its details"  -> sample_detail = 04PDIFJZXAA8R34kAXRvCn
                                                 (IfcDoor, stelkozijn_(#143009), Storey-1)
"Show me all the walls"                       -> sample_detail = None
```

The sample is chosen by the backend from the database; the panel/chat never invents one.

## Component panel, availability, and group actions

Measured live at 1440x900: component panel **x=728, w=320**; chat **x=1060, w=360** (narrowed from
the stored 380 while paired, restored to 380 on close); the panel sits immediately left of chat and
the viewer keeps **728 px** (51%). Click(hit) → panel visible in **0.69 s**.

Truthful availability on the current model: `Instance` enabled; `Same type` and `Same family`
**disabled** with the reason "This model has no explicit IFC type data for this object. This model
has no explicit family property for this object." Absent fields are omitted, not shown empty. The
`Instance` action returned "1 matching object." and **added no chat message** and consumed no
OpenAI tokens. Stale detail/group responses are rejected after rapid selection, panel close, model
switch, Clear Chat, and Reset App — detail and group carry separate tokens so a group action cannot
invalidate an in-flight detail fetch.

## Isolated preview: resource strategy and measured impact

**Strategy**: the preview renders only the selected instance, built from geometry buffers extracted
from the model the main viewer **already has loaded** (`ViewerAdapter.extractItemGeometry` →
`model.getItemsGeometry([localId])` → `THREE.BufferGeometry`). No second network request, no
re-parse of the artifact, no clone of the model. The instance keeps the same semantic base color it
has in the main viewer, so the preview reads as a detail of the same drawing. It lazily initializes
on open and disposes renderer, geometries, materials, listeners, and the render loop on selection
change, close, model switch, and Reset App. Auto-rotation is slow, pauses on hover/drag and for 2 s
after any interaction, and is disabled under `prefers-reduced-motion`.

**Measured** (Chromium with `--enable-precise-memory-info`; without it `performance.memory` is
bucketed and reports a constant, so the first run's numbers were discarded as meaningless):

| stage | JS heap |
|---|---|
| app shell | 134.8 MB |
| + model loaded | 155.3 MB (+20.5) |
| + panel & preview open | 153.2 MB (**no measurable cost** — within GC noise) |
| after panel close (forced GC) | 137.1 MB |
| after Reset App | 135.2 MB (≈ the 134.8 shell baseline) |

The preview adding no measurable heap is the evidence for the subset strategy: cloning the model
would have cost roughly the +20.5 MB the model itself takes. Returning to the shell baseline after
Reset App shows disposal works and nothing leaks. Model load → ready measured **2.6 s**, matching
the Task 11 baseline (2.6–2.8 s) — no regression.

## Clear Chat / Reset App validation

Measured live: **Reset App at (20, 20)** — the viewer's top-left; **Clear Chat at x=1341** in the
chat panel, **1321 px** apart, and distinct from the bottom-left Fit control. Semantics unchanged
and verified by tests: Clear Chat keeps the model, selection, chips, cache, and the component panel
(which follows selection) while clearing messages, query highlights, and the group highlight, and it
retires the in-flight group token so a late response cannot re-highlight after the clear. Reset App
clears conversation, panel, selection, highlights, and active model, disposes viewer + preview
state, returns to model selection, and keeps the IndexedDB cache. Neither deletes database rows,
vectors, artifacts, or cached model data.

## Type / lint / unit / build / e2e / full-local results

```text
npm run gen:api      regenerated src/types/api.ts from the Task 13 contract
npm run typecheck    clean
npm run lint         clean
npm run test         117 passed (12 files) — was 39
npm run build        built in 9.8 s
npm run test:e2e     2 passed
```

Full local integration ran against the real backend (`:8000`), the real frontend (`:5173`), and the
real Schependomlaan artifact: model load, click-detail, panel layout, preview, availability,
`Instance` group action, panel close, and Reset App — all validated with the measurements above.
No secrets, SQL, vectors, filesystem paths, canonical JSON, or backend trace records appear in any
normal frontend operation.

## Database / vector before/after

Identical before and after all validation (read-only throughout):

```text
ifc_source_models 1 · ifc_entities 6989 · ifc_relationships 3473 · relationship_members 17668
rag_documents 10462 · model_families 1 · source_model_catalog_entries 1
vectors: 10462 rows / 10462 embeddings / 1 model / dim 1024
```

## Statuses

```text
Frontend design plugin: USED
Centralized semantic viewer colors: VALIDATED
Camera and navigation controls: VALIDATED
Elevation-zero base plane: VALIDATED
Aggregate/all-match highlighting: VALIDATED
Concise chat presentation: VALIDATED
Component detail panel: VALIDATED
Instance/type/family actions: VALIDATED
Clear Chat and Reset App: VALIDATED
Frontend regression and local integration: VALIDATED
Database/vector/ingestion state: UNCHANGED
```
