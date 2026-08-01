# Task 31: Viewer quality modes, plan corrections, and progressive result tables

## Goal

Apply the accepted frontend refinements to the existing 3D viewer, floor-plan mode, and Query
Explanation table without changing query meaning, result identities, or the established rendering
architecture.

This task has four implementation groups:

1. add user-selectable **Fine / Standard / Fast** visualization modes by changing only existing
   rendering thresholds;
2. centralize the most relevant user-editable viewer appearance and interaction values in one
   logic-free TypeScript file, and apply the accepted transparency changes;
3. correct floor-plan wall graphics, wheel-zoom speed, and orthographic scale distortion;
4. replace the explanation table's 50-row terminal ceiling with 50-row progressive display and
   three-state sorting over all identities already available to the response.

Do not add unrelated viewer tools, query features, or presentation types.

---

## 1. Central viewer customization values

Create:

```text
frontend/src/viewer/viewerCustomization.ts
```

This file contains **constants only**. It is the easy-to-edit source for the most relevant
user-facing viewer values. Do not put functions, derived materials, class-mapping logic, state,
event handling, API behavior, or rendering algorithms in it.

Organize the file in this order, with concise comments stating units and visual effect:

1. **colors** — base geometry, semantic highlights, background/plane, plan graphics, and plan-wall
   black;
2. **opacity/transparency** — face and edge alpha values;
3. **line appearance/thickness** — the existing entity-edge and plan-contour appearance values
   that the installed renderer actually honors;
4. **visualization-mode thresholds** — the complete Fine / Standard / Fast matrix and the default;
5. **navigation values** — including the plan wheel-zoom speed;
6. any other directly user-visible viewer values retained in this file, grouped by their purpose.

Use `#000000` for the new plan-wall cut color.

Move the relevant existing editable constants out of `viewerTheme.ts`,
`ProjectedSizePolicy.ts`, and other viewer files into this file. Those original modules must import
the values rather than keep duplicate numeric or color literals. `viewerTheme.ts` may continue to
own derived Three.js/Fragments materials, `geometryRole`, `verticalFovDeg`, and other logic.

Keep operational/internal values out of the customization file: batching sizes, worker timing,
cache limits, API/result limits, render-order safety, disposal tokens, and similar implementation
details are not UI customization.

Do not add a wide-line library or patch Three.js merely to make a thickness constant effective.
Expose only line values supported by the current rendering path, and comment any installed-renderer
limitation beside the applicable constant.

---

## 2. Fine, Standard, and Fast visualization modes

### 2.1 Mode control and lifecycle

Add one compact, accessible three-option control to the existing bottom-left viewer readout beside
the Fit control:

```text
Fine | Standard | Fast
```

- **Standard is the default.**
- The selected mode takes effect on the currently loaded model without a model download or page
  reload.
- The selection remains active across model switches in the current app session.
- **Reset App returns the mode to Standard.**
- Do not persist the selection in local storage or IndexedDB.
- The control is a visualization-quality choice, not the removed Task 18 automatic/manual
  performance-profile control. Do not restore that old control or its behavior.

Keep the selected mode in the existing typed frontend state/controller boundary. React requests the
mode change; imperative scene work remains inside `ViewerAdapter`.

### 2.2 Exact accepted thresholds

`Fine` reproduces the current visualization thresholds. `Standard` and `Fast` retain the same
algorithms but enter their reduced states earlier and retain fewer feature edges.

| Mode | Projected-size hide | Projected-size restore | Edge angle, balanced model | Edge angle, large model |
| --- | ---: | ---: | ---: | ---: |
| Fine | 20 px | 24 px | 25 deg | 40 deg |
| Standard | 32 px | 38 px | 40 deg | 55 deg |
| Fast | 48 px | 58 px | 55 deg | 70 deg |

The projected-size pair keeps the existing hysteresis meaning: a hide candidate enters the reduced
state below the first value, restores only above the second, and keeps its prior state between them.

Retain the existing deterministic balanced/large-model signal when choosing the applicable edge
angle inside the selected mode. It must not automatically choose Fine, Standard, or Fast for the
user.

### 2.3 Immediate application and edge rebuild

Changing mode must re-evaluate the current model's projected-size state and refresh Fragments through
the established bounded update path. Because the feature-edge angle is applied when the edge
geometry is extracted, regenerate the active edge overlay asynchronously when that angle changes.

- Do not reload or reconvert the model.
- Cancel or ignore a stale rebuild after another mode change, model switch, unload, or Reset App.
- Never leave duplicate overlays or undisposed geometry/materials.
- Keep interaction usable during the yielded rebuild.
- A mode change must not alter query/manual identities, camera pose, active floor, or panel state.

### 2.4 Rendering mechanisms that must remain unchanged

The modes change only the threshold values in Section 2.2. Preserve all existing behavior around
them:

- Fragments' supported mesh LOD/visibility and current update cadence;
- continuous renderer mode;
- projected-size category eligibility and its cached bounding volumes;
- walls, roofs, slabs, explicitly external doors/windows, and explicitly load-bearing columns being
  retained at every projected size;
- highlighted/manual objects bypassing object hiding;
- plan-mode suspension of the projected-size policy;
- spatially chunked and frustum-culled edge overlays;
- base-model frustum culling and current mesh simplification;
- selection, pick-through-transparency, fit, highlight, clear, load/unload, and disposal behavior;
- the isolated component preview's existing independent profile behavior.

Do not reintroduce manual render scheduling, adaptive main-viewer pixel ratio, motion/wake/rest
quality switching, edge hiding during motion, Fragments motion throttling, or any other Task 22
rollback behavior.

---

## 3. Transparent-object appearance

Set these values in `viewerCustomization.ts`:

```text
dim non-result face opacity        0.20   (was 0.35)
relationship-context face opacity 0.10   (was 0.16)
unfocused-primary edge opacity     0      (was 0.75)
```

The edge change applies only to the translucent `primaryUnfocused` 3D role. Its blue face remains
visible at the established face opacity, but it has no entity-edge overlay.

Preserve:

- opaque focused-primary and manual-selection blue edges;
- the already-disabled dim non-result edges;
- the base grey geometry edges;
- plan-mode blue cut contours, which remain necessary to override black wall cuts;
- all semantic role identities and picking behavior.

Do not make the grey roles more opaque and do not change the base model's opaque grey materials.

---

## 4. Query Explanation result-table behavior

### 4.1 Scope and fixed boundaries

The current count/list grouping and presentation selection are already implemented. **Do not change
their operation mapping, grouping, panel-opening gate, subgroup highlighting, or All results
behavior in this task.**

Keep the existing **2,000 viewer-identity cap**. It bounds a single response and viewer highlight;
it does not change the exact result total. Do not raise or remove it.

Replace only the explanation object's 50-row terminal ceiling:

- make every authoritative row already represented by the response's hydrated identities available
  to the frontend, up to the existing 2,000-identity cap;
- keep `true_result_count` distinct and disclose when the real result exceeds the available identity
  set;
- continue merging only name/storey metadata already available in the accepted result;
- use GlobalId plus IFC class as the truthful fallback when optional metadata is absent;
- do not issue another database query or LLM call merely to fill missing names/storeys;
- do not add a pagination endpoint or make a network request when the user scrolls or sorts.

The presentation builder must retain its existing structural isolation from the database, execution,
and LLM layers. The larger row list remains bounded by viewer hydration rather than becoming an
unbounded result transport.

Apply the progressive behavior to row-based object tables that currently use the 50-row ceiling,
including result tables and relationship endpoint fallback tables. Do not change the natural bounded
contents of one-bucket group tables or comparison tables.

### 4.2 Progressive display

- Render the first **50** rows initially.
- When the user reaches the end of the table's scroll area, automatically append the next **50**.
- Continue until every available row has been displayed.
- Do not require a Load more button.
- Keep the table inside its existing bounded scroll area; do not grow the explanation panel itself.
- Scrolling performs only in-memory frontend work.

The caption/information must distinguish all three quantities whenever they differ:

```text
rows currently displayed
rows available under the viewer-identity cap
true result total
```

It must never imply that 2,000 available rows are the complete result when the true total is higher.

### 4.3 Three-state column sorting

Turn every existing object-table column header into an accessible sort button:

```text
Object | Class | Storey
```

Each column independently follows this exact click cycle:

```text
first click  -> descending
second click -> ascending
third click  -> cancel sorting and restore original backend order
```

Only one column is active at a time. Activating another column starts that column at descending.

- Sort the **complete available row set**, not only the 50 rows currently mounted.
- After any sort-state change, return the table to the first 50 rows and scroll it to the top.
- Canceling restores the original deterministic backend/entity order.
- Missing values stay last in both directions.
- Ties retain deterministic original order.
- Expose the active direction visually and through `aria-sort`; sorting must work by keyboard.

Do not add a spreadsheet component or table dependency for this behavior.

---

## 5. Floor-plan corrections

### 5.1 Black wall cuts only

In floor-plan mode, wall cut geometry uses `#000000` for both:

- the wall cut fill;
- the wall cut contour/edge.

This applies only to wall cut graphics produced at the active section plane, using the viewer's
existing wall-class definition (`IfcWall`, `IfcWallStandardCase`, and
`IfcWallElementedCase`). It must not turn normal 3D wall faces or normal 3D wall edges black.

Keep non-wall plan cut graphics at their existing colors and opacity. Keep the established plan-fill
opacity unless changed later through the customization file; this task changes the wall cut color,
not its alpha.

**Blue semantic graphics always override black.** A query-primary wall must use the established blue
primary plan fill/contour and render above the black wall layer. Black wall graphics must never cover
or recolor a blue primary result.

Do not change IFC data, query classes, wall membership, section range, clipping planes, or the plan
cut height to achieve the styling.

### 5.2 Plan wheel-zoom speed

Set the orthographic plan camera's wheel zoom speed to exactly:

```text
2
```

The installed View/Plan mode currently assigns a much more abrupt value of 6. Reassert the accepted
value after the plan camera/mode is created so the library default cannot overwrite it. Store the
value in `viewerCustomization.ts`.

Do not change perspective 3D zoom speed, pan speed, fit framing, zoom bounds, or mouse-button mapping.

### 5.3 Preserve equal scale on both plan axes

Correct the horizontal compression in every model's floor-plan view. In the final orthographic
projection:

```text
one scene unit horizontally == one scene unit vertically in CSS pixels
```

Therefore equal-length horizontal and vertical elements display at equal lengths, and perpendicular
geometry displays as perpendicular.

This guarantee must hold:

- with no right-side panel;
- with the explanation/chat obstruction active;
- after the obstruction width changes;
- after canvas/window resize;
- after switching floors;
- after returning to 3D and entering a plan again.

Preserve the existing requirement that fitted content centers inside the unobstructed viewer region
and is not clipped. Fix the orthographic frustum/view-offset/aspect calculation; do not scale or
transform the model, alter section geometry, patch an installed package, or compensate with a
model-specific factor.

Perspective projection and pixel-correct picking must remain unchanged.

---

## 6. State and behavior preservation

Preserve the existing boundaries and lifecycle:

- no IFC parsing or artifact regeneration at runtime;
- no database write and no additional LLM call;
- no query interpretation, exact total, result membership, answer wording, or viewer-identity change;
- one active model and the existing artifact/cache behavior;
- current floor selection, camera save/restore, section disposal, and stale-token guards;
- query-primary, context, manual-selection, explanation subgroup, and component-panel synchronization;
- Clear Chat behavior; only Reset App resets visualization mode to Standard;
- existing accessibility, failure handling, and stale-response protection.

---

## 7. Documentation alignment

Update the current authoritative specifications during implementation:

- `specs/spec_v008_3d_viewer.md` — customization-file ownership, Standard default and exact mode
  thresholds, accepted opacities/edge behavior, plan-wall styling, plan zoom speed, and equal-axis
  orthographic scale;
- `specs/spec_v010_explanation_panel.md` — remove the terminal 50-row ceiling for object tables,
  document the 2,000 available-identity boundary, 50-row progressive display, truthful three-count
  disclosure, and the descending/ascending/original sort cycle;
- `specs/spec_v006_frontend_application.md` only where its shared Reset App semantics must state that
  visualization mode returns to Standard.

Do not edit completed task history or unrelated specification sections. Remove or supersede any
active-spec statement that conflicts with this task so the specifications remain one current source
of truth.

---

## 8. Validation

Add focused automated tests for the accepted behavior.

### 8.1 Visualization modes and customization

Verify:

- Standard is the initial and Reset App mode;
- Fine/Standard/Fast use exactly the Section 2.2 thresholds;
- the selected mode survives model switches;
- changing mode re-evaluates current visibility without changing model/camera/query/floor state;
- edge-overlay rebuilds are stale-safe, do not duplicate resources, and use the selected angle;
- projected-size hysteresis and retained/exempt category behavior remain correct in every mode;
- the relevant appearance/navigation values have one constant source in
  `viewerCustomization.ts`, with no duplicate inline definitions;
- dim/context opacity is 0.20/0.10;
- only translucent unfocused-primary 3D entity edges are removed;
- opaque blue and plan-primary contours remain.

### 8.2 Explanation tables

Verify:

- 50 rows render initially;
- each end-of-scroll event appends exactly the next 50 and stops at the available count;
- the caption distinguishes displayed, available, and true totals;
- the existing 2,000 identity cap and exact total remain unchanged;
- each column cycles descending, ascending, original in that order;
- sorting covers rows not yet displayed, resets display to 50, and scrolls to the top;
- switching columns starts descending and clears the prior column state;
- missing values remain last and ties restore deterministically;
- header buttons expose correct keyboard and `aria-sort` behavior;
- scrolling/sorting causes no backend or LLM request;
- existing count/list grouping, subgroup selection, All results, panel lifecycle, and relationship
  fallback behavior remain unchanged.

### 8.3 Floor plans

Verify:

- wall cut fills and contours are black while non-wall cuts keep current styling;
- query-primary blue walls render above and override black;
- normal 3D walls are unchanged;
- plan wheel zoom speed is 2 and perspective zoom is unchanged;
- a square or equal orthogonal reference in plan has equal horizontal and vertical pixel length;
- the equal-scale result survives panel obstruction, resize, floor switching, and repeated 3D/plan
  transitions;
- plan fitting remains centered in the unobstructed region without clipping;
- camera save/restore, clipping, highlights, projected-size suspension, and disposal still pass.

Run the frontend typecheck, lint, build, unit/component suite, and critical Playwright path, plus the
focused offline backend presentation/contract tests affected by the larger bounded explanation row
payload. Do not run a live LLM benchmark for these deterministic UI/rendering changes.

Perform a bounded real-browser check on the available real models for mode switching, transparent
roles, long-table scrolling/sorting, wall cuts, plan zoom feel, and plan proportions. Report measured
or observed results without claiming unperformed GPU validation.

---

## Completion

After implementation and validation:

1. reconcile the specifications listed in Section 7;
2. append a concise completion report recording the final constants, tests, and any genuine visual
   limitation of the installed renderer;
3. rename this file to `tasks/task31_done.md`.

---

## Completion report

Implemented and validated 2026-07-31. Specifications reconciled: `spec_v008_3d_viewer.md`
(§6.2 customization ownership, §6.3 opacities/edges, §6.4 line-width limitation and mode-driven
angle, §7.3 mode-driven thresholds, **new §7.5** Fine/Standard/Fast, §8.3 plan zoom speed, §8.4
black wall cuts, **new §8.9** equal-axis scale, §10 verification gap), `spec_v010_explanation_panel.md`
(§7 rewritten; **new §7.1** bounded availability + progressive display, **new §7.2** three-state
sorting), `spec_v006_frontend_application.md` (§7.3 control placement, §10.2 Reset App semantics).

### Final constants

New file `frontend/src/viewer/viewerCustomization.ts` — constants only, no logic. `viewerTheme.ts`
and `ProjectedSizePolicy.ts` now import from it and hold no colour or threshold literal of their own
(asserted by a source-scanning test).

| Mode | Projected-size hide | Projected-size restore | Edge angle, balanced | Edge angle, large |
| --- | ---: | ---: | ---: | ---: |
| Fine | 20 px | 24 px | 25 deg | 40 deg |
| Standard **(default)** | 32 px | 38 px | 40 deg | 55 deg |
| Fast | 48 px | 58 px | 55 deg | 70 deg |

```text
VIEWER_OPACITY.dim               0.20   (was 0.35)
VIEWER_OPACITY.context           0.10   (was 0.16)
EDGES.alpha.primaryUnfocused     0      (was 0.75)   3D entity edges only
VIEWER_COLORS.planWallCut        #000000              plan wall cut fill + contour
VIEWER_NAVIGATION.planWheelZoomSpeed  2  (library assigns 6)
```

### Implementation notes

- **Wall cuts are a disjoint layer, not an over-paint.** Walls are withheld from the non-wall
  `getSection` call and query-primaries from both earlier layers, so a 0.55-alpha black fill is never
  blended over the grey poché and blue can never be tinted by black. Render orders renumbered
  3/4 (base) · 5/6 (wall) · 7/8 (primary). With no wall classification the split degrades to the
  previous single layer.
- **Equal-axis scale** is a frustum correction, not a transform. `OrthoPerspectiveCamera` builds its
  orthographic frustum from `window.innerWidth / window.innerHeight` and its resize handler never
  reaches a `View`'s own camera, so every plan was compressed. `applyOrthoScale` rewrites only the
  horizontal half-extent so `(right-left)/(top-bottom) === effectiveWidth/canvasHeight`, before the
  view offset is written (`fitToBox` reads `right-left` synchronously).
- **Edge rebuilds dispose-then-build** under a monotonic `edgeToken`. `EdgeOverlay.build` now releases
  chunks it had already mounted when aborted mid-finalize — a pre-existing leak that only became
  routine once mode changes could supersede a build.
- **Backend**: `MAX_EXPLANATION_ROWS` 50 → 2000, mirroring `Settings.max_viewer_match_ids`.
  `presentation.py` still imports nothing from the database, execution, or LLM layers.

### Tests

- Frontend: **478 pass / 27 files**, typecheck and lint clean, production build succeeds. New:
  `visualization-modes.test.ts` (21), `visualization-mode-control.test.tsx` (10),
  `explanation-table.test.tsx` (30), plus 11 new plan-mode cases and 9 new equal-scale cases.
- Backend: **1031 pass / 27 fail** — the same 27 pre-existing failures as the recorded baseline
  (`test_validate` ×3, `test_llm_retry` ×5, `query_live/test_binding_pipeline_live` ×16,
  `test_rag_search` ×1, `test_openai_usage_output` ×1, `test_settings` ×1). None in presentation.
- Playwright: 2/3 pass; the failing case is the pre-existing `.ev-toggle` critical-path failure
  recorded since Task 26. No live LLM benchmark was run.

### Bounded real-browser check (Chromium + SwiftShader, real backend, model 1 Schependomlaan)

| Check | Observed |
| --- | --- |
| Mode control | `Fine \| Standard \| Fast` present beside Fit; **Standard** checked by default |
| Mode application | each switch settled on the live model in 7.6–8.3 s (edge re-extraction), no reload, no page error; wheel-zoom still responsive afterwards |
| Wall cuts | darkest plan pixel exactly `#000000`, 5,739 pixels below luminance 40; non-wall fills stayed grey |
| Plan proportions | drawing aspect 1.0814 @1600×950, 1.0811 @1100×950, 1.0765 @1600×700, 1.0516 with the chat collapsed — **drift ≤ 0.46 %** across canvas sizes and ≤ 2.8 % including the obstruction change |
| Long table | one live query ("list all the walls") → 880 results; caption `Showing 50 of 880 results`; 50 → 100 → 150 → 200 rows on successive end-of-scroll events, caption tracking each; sort cycle descending → ascending → none, each resetting to 50 rows with `scrollTop` 0 |

### Genuine limitations

- **Line thickness is not exposable.** Every line is `LineBasicMaterial` + `LineSegments`, and the
  WebGL renderer ignores `linewidth` — the core profile only guarantees 1-px lines. No thickness
  constant exists in the customization file, because it would be a knob that silently does nothing;
  a wide-line library or a patched Three.js is out of scope per §1. Line presence, colour and alpha
  are honoured exactly, and the limitation is commented beside the block.
- **The black wall fill keeps the established 0.55 plan-fill alpha** (§5.1 changes colour, not alpha),
  so the rendered pixel is a very dark blend against the sheet rather than pure `#000000`. The
  material colour is exactly `#000000`, and the measured darkest plan pixel was `#000000`.
- **No real-GPU perceptual judgement.** The measurements above come from a SwiftShader-headless
  Chromium session: they establish correctness (thresholds applied, black cuts drawn, proportions
  invariant, rows/sorting behaving), not how any of it *feels*. Whether Standard reads better than
  Fine on the owner's RTX 5080, and whether a plan wheel speed of 2 feels right at real zoom levels,
  remain owner-run judgements. The ~8 s mode-switch settle time is dominated by the edge
  re-extraction under software rendering and is not a real-hardware figure.
