# Task 23: Query-Constraint Preservation and Projected-Size Rendering

Task 23 contains exactly two independent issues:

1. the backend loses user constraints, causing filtered questions to return unfiltered results;
2. the 3D viewer renders unnecessary detail when individual objects become too small on screen.

Keep these as two separate implementation groups. Do not reinterpret either issue as part of the
other, and do not add unrelated work.

---

# Main issue 1: Preserve all query constraints through the LLM and retrieval pipeline

## Reported failure and confirmed cause

For model 2:

```text
show me all the doors in the second floor
```

returned and highlighted all 551 `IfcDoor` objects, the same result as asking for every door in the
building.

This is not an IFC or ingestion-data defect. A read-only database check confirmed that model 2's
551 doors retain 23 distinct non-null `storey.name` values. Storey information is extracted,
persisted, exposed by the field registry, and queryable by the existing typed SQL path.

The information is lost in the Task 17 orchestration pipeline. It resolves the target class and
conditions into independent evidence groups, such as:

```text
IfcDoor objects              -> all doors
storey = resolved value      -> separate group
another property/value       -> separate group
```

It does not preserve the required compound result:

```text
IfcDoor AND containing storey = resolved second floor
```

The unfiltered class group is therefore executed and later accepted as exact evidence. The answer
LLM cannot recover a condition that retrieval has already discarded.

Treat this as a generic constraint-preservation defect, not a floor-specific patch. The same
failure can affect class plus property, quantity, material, classification, missing value, spatial
scope, relationship scope, nested Boolean logic, and other compound requests.

## Required architecture and behavior

Preserve every material condition expressed by the user from the first planner output through
semantic resolution, execution, answer evidence, and viewer identities:

```text
user question
    -> LLM call 1: query-only retrieval policy and conceptual intent tree
    -> deterministic model-aware resolution of the tree's leaves
    -> deterministic composition into the existing typed executable plans
    -> scoped SQL, RAG, and/or graph execution
    -> LLM call 2: grounded answer
    -> viewer identities from the same accepted scoped result
```

The query-only planner must emit a typed conceptual intent tree containing the result concept,
operation, Boolean structure, condition identity and scope, field/property/quantity/spatial or
relationship concept, operator, value or value concept, unit when applicable, and graph seed or
endpoint intent when applicable. Conditions must not exist only in prose fields such as
`question`, `semantic_query`, or `analysis_intent`.

The first LLM call must remain query-only. It must not see active-model semantic candidates,
observed values, counts, RAG scores, database fields, JSON paths, or final IFC-class bindings. It
must not emit raw SQL. Retrieval modality is decided before semantic resolution and cannot be
changed afterward.

Resolve each intent-tree leaf deterministically against the existing ontology and active-model
vocabulary while preserving its identity, Boolean position, and subject scope. Resolution must be
contextual to the already resolved result or subject concept. For example, resolve a requested
width for the target door concept rather than searching for any width-like field in the model.

Floor/storey language is one model-aware value-resolution case within this generic system. Do not
hard-code a universal floor-name or ordinal convention. If one conceptual storey legitimately maps
to corresponding storeys in multiple buildings, preserve that as an `OR` inside the surrounding
predicate. If materially different interpretations cannot be resolved safely, use the existing
clarification behavior.

Compose resolved structured leaves into the existing recursive, allowlisted typed SQL filters.
Reuse the current SQL compiler; do not build a parallel compiler or allow an LLM to generate SQL.
All conditions assigned to the result must apply to the same authoritative result set. A required
condition that cannot be resolved or compiled must never be silently dropped so that a broader
query can run.

For exact structured questions, execute one authoritative compound result. Its exact count,
bounded answer examples, and viewer identities must all derive from that result. An unfiltered
class group must not be accepted as the exact answer to a filtered question.

When RAG is also required, run it within the applicable structured scope. For example:

```text
doors on the second floor that appear suitable for emergency egress
```

must first resolve the door-and-storey scope, then rank/search only those entities for semantic
relevance. RAG remains bounded semantic evidence and never becomes an exact count. An empty scoped
RAG result must remain empty rather than broadening to whole-model RAG.

When graph retrieval is required, preserve which subtree constrains the seed, relationship,
endpoint, and final result. For example, `spaces connected to doors on the second floor` must start
from doors satisfying the resolved floor condition, not every door in the model.

The answer and the 3D viewer must use the same accepted scoped identities. Preserve the existing
separation between exact totals, bounded answer examples, and complete accepted viewer identities.
Follow-up questions must intentionally extend or replace prior constraints rather than losing the
established scope.

## Constraints

Preserve these existing decisions:

- exactly two principal LLM calls for an answered active-model question;
- query-only modality policy remains isolated from active-model semantic data;
- SQL facts remain exact, while RAG candidates remain bounded semantic evidence;
- existing SQL allowlists, source-model isolation, graph limits, and read-only behavior remain;
- existing vocabulary/index caches and typed SQL machinery are reused;
- no late answerer-side reconstruction of discarded intersections;
- no additional router, resolver, verifier, judge, or replanning LLM call;
- no floor-specific hard-coded fix;
- no source-IFC, ingestion-data, database, or vector regeneration merely to solve data already
  present in canonical JSON.

Update the relevant query specifications during implementation so they describe the final
constraint-preserving architecture without deleting completed task history:

```text
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

## Validation for issue 1

Run the automated and live read-only testing necessary to demonstrate that the complete user
intent above is met. Testing must cover the generic constraint-preservation behavior across SQL,
SQL-scoped RAG, scoped graph traversal, unresolved required conditions, answer/viewer identity
consistency, and unchanged simple queries—not only one floor example.

Validate model 2 with both the reported second-floor-door request and the total-door request. The
filtered request must no longer return 551 merely because the model contains 551 doors. Record the
resolved storey interpretation and resulting count without hard-coding that interpretation or
count into general application logic. Continue correcting and retesting until the intended scope,
answer, and highlighted identities agree.

---

# Main issue 2: Reduce 3D rendering by persistent projected object size

## User intent

Reduce visualization load whenever an individual object becomes too small on screen to justify
rendering non-fundamental detail. This policy depends only on that object's projected screen size,
not its absolute distance from the camera and not whether the camera is moving.

The policy remains active throughout all visualization. Do not create separate navigation,
camera-motion, wake, or stationary rendering modes.

## Projected-size rule

Measure each renderable IFC object's projected screen size in CSS pixels using its scene-correct
bounding volume and the active perspective camera. Use the projected bounding-sphere diameter, or
an equivalently conservative maximum projected dimension.

Use hysteresis:

```text
enter reduced state: projected object size < 20 px
leave reduced state: projected object size > 24 px
```

An object between 20 px and 24 px keeps its previous state. An object below 20 px enters the
reduced policy regardless of camera distance; an object that remains sufficiently large on screen
stays in the current base rendering path regardless of camera distance.

Re-evaluate through suitable existing events such as model load, camera rest, viewport resize, and
projection/view-offset changes. Do not introduce a per-frame whole-model scan or periodic
Fragments updates during camera motion.

## Elements retained below 20 px

For a non-highlighted object below 20 px, retain only:

- walls, including the wall subtypes already recognized by the viewer;
- roofs;
- slabs explicitly identified as roof slabs;
- other slabs/floors;
- doors and windows with explicit IFC `IsExternal = true`;
- columns with explicit IFC `LoadBearing = true`.

Hide other non-highlighted objects until they cross the 24 px exit threshold. Restore them through
the existing rendering and material path without reloading the model.

Do not guess exterior or load-bearing status from names, geometry, position, material, proximity,
or an LLM. If the applicable property is missing, null, unsupported, or ambiguous, the object does
not qualify for the retained set.

Use deterministic IFC metadata already available in the prepared artifact. If the artifact does
not expose a required property, add only the minimum preparation-time metadata needed by the
viewer. Do not call the backend, database, embedding service, or LLM during camera interaction.

This filtering policy changes eligibility/visibility only. Retained objects must continue to meet
all current rendering standards, including existing class mapping, colors, opacity, semantic
roles, picking identity, and selection behavior.

## Preserve current rendering reductions and LOD

Do not remove, disable, duplicate, retune, or replace any current mesh simplification, Fragments
LOD/visibility, frustum culling, edge reduction, or other rendering-load reduction attempt.
Preserve its existing configuration, update timing, and relationship to the completed Task 22
rollback.

Fundamental objects retained below 20 px should continue through whatever simplified
representation the current supported Fragments/mesh LOD path selects. Do not create custom
bounding-box proxies, generic replacement solids, a parallel low-poly artifact, or a second model
download.

The new filter must compose with the current mechanisms without competing visibility writers,
repeated geometry extraction, per-event mesh rebuilding, whole-model worker transfers, or private
dependency modification.

## Highlighted and manually selected objects

Highlighted and manually selected objects always bypass the fundamental-element filter. They must
remain shown even if they are interior, MEP, furnishing, otherwise non-fundamental, or below 20 px.
The rendering optimization must not drop or broaden the identities returned by the corrected query
pipeline.

Always shown does not mean always rendered at full detail. Highlighted/selected objects remain
subject to the viewer's current supported Fragments/mesh LOD and detail reductions while keeping
their semantic highlight color and interaction behavior.

If implementation inspection proves there is no applicable existing detail-level control for
highlighted objects, use the same 20 px entry and 24 px exit decision to control their detail level,
but do not apply the fundamental-class filter to them and do not hide them. Use supported mechanisms
in the current rendering stack; do not create navigation-specific behavior or another prepared
artifact. Detail overlays such as custom edges may be reduced below the threshold only while the
highlighted object remains visibly identifiable.

## Interaction and performance requirements

- Filtered objects remain loaded and restore deterministically above 24 px.
- Highlighting an otherwise filtered object makes it visible; clearing the highlight immediately
  reapplies its current size/category state.
- An invisible filtered object cannot be picked.
- Existing query-primary, relationship-context, manual-selection, dimming, fit, clear-selection,
  preview, load/unload, and disposal behavior remains consistent.
- The isolated component preview is not hidden by the main camera's projected-size policy.
- Cache object classification and projected-size state; do not repeat IFC classification on every
  camera update.
- Do not regenerate artifacts at runtime, scan canonical JSON during interaction, or rebuild object
  geometry for camera events.
- Do not change current renderer scheduling, pixel ratio, camera controls, styling, or LOD
  thresholds except where strictly necessary to implement the accepted behavior.
- Use maintained public Fragments/rendering APIs only. Do not patch private dependency internals.

Update `specs/spec_v006_frontend_application.md` during implementation so it becomes the current
source of truth for the final rendering behavior while preserving completed task history.

## Validation for issue 2

Run the automated, visual, and performance testing necessary on model 1 and model 2 until the full
rendering intent above is met. Demonstrate that the projected-size threshold and hysteresis work,
only the accepted architectural elements remain for non-highlighted small objects, highlighted
objects remain visible with controlled detail, hidden objects restore and cannot be picked, and all
current rendering reductions and viewer semantics remain intact.

Use comparable before/after views and measurements sufficient to show that rendering load is
reduced without reintroducing the Task 18/20 interaction regressions that Task 22 removed. Continue
correcting and retesting until the behavior is stable and the user intent is satisfied.

---

# Completion

Complete both main issues before renaming this file to:

```text
tasks/task23_done.md
```

Append a concise completion report that records:

- the final implementation for each of the two issues;
- specification updates and any intentionally superseded behavior;
- the model 2 filtered-door result versus the total-door result;
- proof that answer identities and viewer identities share the same resolved scope;
- final projected-size, architectural eligibility, LOD, and highlight behavior;
- tests and live validations performed, their results, and relevant before/after performance
  evidence;
- confirmation that no unrelated IFC, ingestion, database, vector, artifact, query, or rendering
  behavior was changed;
- any genuine remaining limitations.
