# Task 19: Highlight Picking, Visible Viewport Center, and Model-Lowest Base Plane

This task contains three small, independent frontend viewer corrections. Implement only the
specified behavior. Do not redesign the viewer, query pipeline, panels, controls, ingestion, or
model data.

Where the current frontend specification conflicts with this task, update
`specs/spec_v006_frontend_application.md` so it remains the current source of truth.

## Non-negotiable model-data rule

The application explains existing IFC content to the user. It must never modify the original IFC
data.

For this task, do not:

- edit or rewrite any source IFC file;
- translate or rebase model geometry;
- change IFC coordinates, elevations, placements, or properties;
- change stored database coordinates or ingestion output;
- modify the prepared Fragments artifact to move the model;
- add an ingestion migration for the base plane.

The base-plane correction is a viewer-only presentation calculation performed from each loaded
model. It must work automatically for already ingested models and future models without changing
their source data.

## Objective

Correct these three behaviors:

1. while query-result objects are blue, transparent non-result objects must not block picking a
   blue object behind them;
2. camera fitting and visual centering must use the center of the unobstructed viewer area to the
   left of the visible right-side panels, not the center of the full browser window beneath those
   panels;
3. place the viewer's visual level/base plane at the loaded model's lowest geometric point rather
   than the IFC coordinate origin/elevation zero.

## 1. Pick through transparent non-results to blue results

### Current defect

When query results are active, primary result objects render blue and non-result geometry renders
transparent gray. The current raycast can hit a transparent non-result first. The existing
query-result eligibility check then rejects that hit, so a blue result behind the transparent
geometry cannot be selected.

Example:

```text
transparent outer wall
    blocks raycast
blue inner wall behind it
    cannot be clicked
```

### Required behavior

When query-result roles are active and at least one blue primary result exists:

- picking must consider only the blue query-primary result set;
- transparent/dimmed non-result geometry must not block the picking ray;
- the nearest blue result intersected by the ray must be selected;
- if the ray intersects no blue result, preserve the existing no-result click behavior;
- the existing additive-selection keys and maximum selection count remain unchanged;
- manually focused blue results and unfocused blue primary results are both eligible;
- no backend request or LLM call may be required to decide eligibility.

Do not solve this by hiding transparent geometry. It must remain visible and provide spatial
context; it is ignored only as an occluder for picking while query-primary results are active.

When query-result roles are not active, preserve the current normal picking behavior against
visible model geometry.

Use the already resolved local-ID primary set as the source of truth. Prefer the supported
Fragments raycast/filter mechanism if it can restrict candidates directly. Otherwise, inspect the
ordered ray intersections or temporarily apply a safe pick filter so the first eligible blue hit
is chosen. Do not permanently mutate visibility or create one picking mesh per entity.

The same eligible-result rule must apply when establishing a selection click. Do not broaden this
task into changing middle-button orbit-pivot behavior unless the implementation shares the same
filtered helper and doing so is necessary to prevent inconsistent or broken interaction.

## 2. Center the 3D view within the unobstructed left area

### Current defect

The WebGL viewer occupies the full application area while the chat panel floats over its right
side. Camera fitting therefore places the model at the center of the full canvas, which appears too
far to the right because part of the canvas is covered.

When the component panel opens immediately left of the chat panel, more of the right side is
covered and the apparent center becomes even less correct.

### Required behavior

Define the effective visible viewer region as:

```text
full viewer bounds
minus the horizontal area occupied by visible right-side panels
```

The apparent center of fitted/focused model content must be the centroid of that remaining visible
left region.

Required panel states:

- expanded chat panel only: center within the area left of the chat panel;
- expanded chat panel plus component panel: center within the area left of both panels;
- collapsed chat restore tab: account only for its actual collapsed width;
- component panel closed: remove its contribution immediately;
- panel resize: update the effective center from the live width;
- responsive/narrow layout changes: use actual rendered bounds rather than duplicated assumed
  widths where practical.

Apply the corrected visible center to:

```text
initial model fit
Fit All
fit/focus to query results
fit/focus to citations
fit/focus to selected component(s)
```

Do not translate the model to achieve this. Use a supported camera-controls viewport, fit padding,
camera view offset, or equivalent camera-framing mechanism. Preserve:

- the 50 mm camera/lens requirement;
- the existing orbit/pan/zoom mapping;
- the existing moderate fit expansion and minimum fit size;
- the maximum zoom-out bound;
- pointer/raycast coordinate correctness;
- the full-size renderer and existing overlay panel design.

Opening, closing, collapsing, or resizing a panel must update the camera's effective viewport
calculation. Do not unexpectedly reset the user's camera on every panel change. Recenter/refit only
when consistent with an active fit operation; otherwise update the offset/viewport so the current
view remains visually stable.

Keep one source of truth for panel geometry. Reuse the existing live panel width and component-open
state rather than creating unrelated hard-coded copies in the viewer.

## 3. Place the visual base plane at the model's lowest point

### Current defect

The viewer currently derives its base-plane height from the model coordination matrix's IFC/world
elevation zero. That can place the plane above or below the lowest actual model geometry.

### Required behavior

For every loaded model, set the visual base-plane Y position to the lowest point of the loaded
model's geometric bounding box:

```text
basePlaneY = modelBoundingBox.min.y
```

Use the bounding box after the Fragments model's coordination transform has been applied, in the
same scene coordinate system used to render the model and plane.

Requirements:

- compute the value on every successful model load;
- use it for already ingested models and future models automatically;
- preserve negative/below-origin geometry;
- do not clip, move, or hide geometry at or below the plane;
- preserve the existing plane material, opacity, size intent, and non-occluding behavior;
- use a safe fallback only when the model bounding box is missing, empty, or non-finite;
- reset the stored plane height correctly on unload/model switch;
- expose the resulting value through the existing `getGroundY()` test seam or its renamed
  equivalent.

The plane is a visual reference at the model's geometric minimum. It does not redefine IFC level
semantics and must not be reported as an actual `IfcBuildingStorey` elevation or IFC coordinate
origin.

## 4. Tests

Add or update focused automated tests for the three changes.

### Picking

- a transparent non-result in front of a blue primary does not block selection;
- when multiple blue primaries lie on the ray, the nearest eligible blue object is selected;
- a ray with no blue hit does not select the transparent non-result;
- focused and unfocused blue primaries remain eligible;
- normal non-query picking remains unchanged;
- additive selection and the existing selection limit remain unchanged;
- filtering uses local frontend IDs and makes no backend call.

### Visible viewport center

- chat-only fit centers within the remaining left region;
- chat plus component panel shifts the effective center farther left;
- closing the component panel restores the chat-only center;
- collapsing and resizing the chat use the live occupied width;
- zero/right-panel-free state uses the full viewer center;
- fit-all, result fit, citation fit, and component fit share the same effective viewport logic;
- camera lens, fit expansion, zoom bound, and pointer mapping remain correct;
- panel changes do not unnecessarily reset the user's camera.

### Base plane

- the plane uses `model.box.min.y` in scene coordinates;
- a model whose minimum is below IFC zero places the plane at that negative minimum;
- a model whose entire geometry is above IFC zero places the plane at its positive minimum;
- switching models recomputes the value;
- an invalid/empty box uses the documented safe fallback;
- no geometry or source-model coordinate is translated or modified;
- plane depth/material behavior continues to allow all model geometry to remain visible.

Run the existing frontend unit/component tests, TypeScript check, lint, production build, and
relevant Playwright critical-path checks. Tests must not call OpenAI, mutate IFC files, or require a
live database.

## 5. Manual validation

Validate with a real loaded model:

1. Produce blue query results including an inner object behind a transparent outer wall.
2. Click through the transparent wall and confirm the nearest blue object is selected.
3. Clear query roles and confirm ordinary picking still works.
4. Fit the full model with chat expanded and confirm it centers in the visible left region.
5. Open the component panel and confirm subsequent fits use the smaller remaining left region.
6. Collapse/resize/close panels and confirm centering follows their actual occupied width.
7. Confirm Fit All, query-result fit, citation focus, and selected-component focus behave
   consistently.
8. Load models whose geometric minima differ from IFC elevation zero and confirm the plane touches
   the lowest model point without moving the model.
9. Switch between models and confirm the plane is recomputed without stale state.

## Definition of done

This task is complete only when:

- blue query-primary objects can be selected through transparent non-results;
- non-result transparency remains visually present;
- all viewer fit/focus operations center within the actual unobstructed left region;
- chat/component panel state and live width are reflected without duplicating layout truth;
- the visual base plane is located at each model's geometric minimum;
- original IFC data, database values, model transforms, and prepared geometry remain unchanged;
- the three changes have focused regression tests and the frontend validation suite passes;
- the current frontend specification is reconciled with the implemented behavior.
