# Task 29: Deterministic Explanation Panel Presentations

## Goal

Revise the existing **Query Explanation** panel so it appears only when a structured
visualization materially supplements the current 3D viewer result.

Visualization selection must remain deterministic:

```text
accepted backend operation + already-computed structured result
    -> table, horizontal bar chart, relationship graph, or no panel
```

Do not infer a separate visualization intention, parse the prose answer, or make another
LLM call.

The initial supported presentation families are:

- bounded result/group tables;
- compact horizontal bar charts;
- bounded, grouped node-link diagrams for sufficiently complex relationship results.

Counts and lists use tables. Scalar facts, measurements, qualitative text, and other
answers that do not benefit from a supporting visualization remain in the original chat
layout with no explanation panel.

Floor plans remain a mode of the existing main viewer. They are never rendered in the
explanation panel.

This task supersedes the Task 26 visualization-selection rules and panel-opening gate. It
does not replace Task 26's established layout, lifecycle synchronization, information
region, subgroup restoration, or clearing behavior except where this task explicitly
changes whether a result qualifies for the panel.

---

## 1. Non-negotiable backend and LLM boundary

The existing natural-language and query pipeline is fixed and behaviorally frozen.

Do not change:

- semantic-manifest generation, loading, vocabulary, recommendations, or candidate
  ranking;
- relationship-token detection or relationship-candidate availability;
- the constraint ledger;
- binder, correction, or grounded-answer prompts;
- any LLM request or response schema;
- model assignments, reasoning settings, retries, token handling, or LLM call count;
- answer-part splitting, operation selection, binding, validation, closure, or retrieval
  mode derivation;
- compiled predicates, SQL/RAG/graph routing, or query interpretation;
- graph seeds, selected relationship class, traversal direction, maximum depth, endpoint
  filtering, traversal bounds, or source-model isolation;
- graph statement count, joins, predicates, ordering, or which objects traversal reaches;
- exact/zero/partial/unavailable/ambiguous classification;
- answer-packet content sent to the final LLM;
- final answer wording, grounding validation, deterministic fallback, or evidence;
- exact totals, examples, graph endpoints, viewer identities, highlights, or existing
  result truncation.

In particular:

- do not add multi-relationship-class planning;
- do not add multi-hop planning;
- do not expose depth or direction choices to the binder;
- do not add a second interpretation pass;
- do not ask the LLM whether a visualization would be useful;
- do not rerun or repair a query merely to obtain a richer diagram.

The only permitted backend work is an **additive presentation transport** that copies
authoritative relationship topology already returned by the existing accepted traversal.
It may retain additional columns already available from the same joined relationship
member rows, such as endpoint GlobalIds and endpoint roles, but it must not add another
database statement, join, predicate, traversal, or endpoint.

Any presentation builder must remain unable to query the database or call the LLM. If a
label, identity, subgroup, role, or edge cannot be obtained from the completed result,
existing viewer hydration, existing traversal hops, or fields already projected by the
same traversal statement, omit that optional detail or fall back to a table. Never perform
an additional lookup to improve the presentation.

Existing query answers must produce the same interpretation, execution, facts, status,
prose, endpoints, viewer roles, and LLM usage before and after this task.

---

## 2. One deterministic panel-opening decision

The backend remains the single owner of presentation selection. The frontend renders the
declared bounded presentation and must not independently infer a visualization from prose,
operation names, row counts, or entity names.

Evaluate only the already-designated primary visual answer part. Never union unrelated
answer parts to cross a visualization threshold.

A completed result opens the explanation panel only when all of the following are true:

1. its operation/data maps to one of the supported presentations below;
2. its status is `exact` or `partial`;
3. the required structured presentation data is authoritative and nonempty;
4. it has a nonempty current query-result highlight compatible with the established
   Task 26 synchronization contract.

Results with status `zero`, `unavailable`, or `ambiguous` never open the panel.

`partial` is a modifier, not a visualization type. Apply the base operation rule and show
the existing limitation/known-versus-unknown information in the persistent information
region. If the base operation does not qualify, partial status does not open a panel by
itself.

When a newer completed result does not qualify, retire the previous explanation and its
query-result highlight exactly as Task 26 already requires, and restore the original
full-height chat layout.

### 2.1 Fixed operation/data mapping

| Accepted operation/data | Presentation |
| --- | --- |
| `count` with authoritative displayed object identities | result table |
| `list` with authoritative rows/identities | result table |
| `group_distribution` with two or more existing buckets | horizontal bar chart |
| `group_distribution` with exactly one existing bucket | group table |
| `relationship` with a complete eligible grouped topology | node-link diagram |
| `relationship` below/above graph bounds or without complete topology | relationship endpoint table |
| `comparison` with an already-existing homogeneous numeric series and compatible unit | horizontal bar chart |
| `comparison` with already-existing structured heterogeneous values | comparison table |
| `comparison` without an existing structured comparison payload | no panel |
| `existence` | no panel |
| `sample_detail` | no explanation panel; preserve the existing component/detail behavior |
| `aggregate` | no panel |
| `extremum` | no panel |
| `description` | no panel |

Do not create new comparison values, extremum winner rows, distributions, class
breakdowns, or identity sets to make an operation qualify.

A count is the deliberate exception to the general scalar rule: when it counts an
authoritative identifiable object set, the table helps the user inspect membership. A
count with no authoritative displayed identities remains in chat.

Do not emit the former standalone metric, aggregate, relationship-metric, or partial-split
visuals. Existing public enum values may remain accepted for backward compatibility if
needed, but the new selector must not choose them.

---

## 3. Table presentation

Use one bounded, scrollable table family for result tables, group tables, comparison
tables, and relationship fallback tables.

### 3.1 Count and list

Both count and list tables must show:

- the exact/true result total;
- the number of identities currently represented;
- a bounded object table, with an explicit `showing N of total` disclosure when capped;
- GlobalId as the final identity fallback;
- IFC class and any name/storey fields already available;
- existing limitation or partial-coverage information in the persistent information
  region.

Keep the current 50-row presentation ceiling.

For count results, construct the bounded rows from the authoritative identities already
hydrated for the viewer. Merge existing example metadata by GlobalId where it is already
available; otherwise GlobalId plus IFC class is sufficient. Do not issue a query to fetch
names or storeys.

For list results, use the existing bounded result rows and viewer identities. Never imply
that a capped table is exhaustive.

When an existing class breakdown or authoritative hydration partition is meaningful, it
may appear as a compact group-summary table associated with the result table. Do not
calculate a new breakdown and do not render class bars merely to fill space.

### 3.2 Other table cases

- A one-bucket group distribution uses a group table because a one-bar chart adds no
  comparative value.
- A relationship result that does not qualify for a graph uses the existing bounded
  endpoint table.
- A structured comparison with heterogeneous fields or units uses a table only when those
  values already exist in the accepted result.
- If the rows required for a truthful table do not exist, omit the panel rather than
  falling back to a metric card.

Existing table/group viewer interaction remains valid only for authoritative GlobalId
subsets of the original highlighted result.

---

## 4. Horizontal bar chart

Use a compact horizontal bar chart only for:

- an existing group distribution with at least two buckets;
- an existing structured comparison consisting of at least two homogeneous numeric values
  with a compatible unit.

Each bar must show its exact label and value. The bar length is a visual comparison, not a
replacement for the number.

Distribution buckets remain display-only when the backend has no authoritative identity
set for bucket membership. Do not make a bucket appear selectable when selecting it cannot
truthfully reproduce that subset in the viewer.

Do not add pie/donut charts, line charts, scatter plots, dashboards, chart recommendations,
or a general charting system in this task.

---

## 5. Relationship node-link diagram

The node-link diagram explains the topology of the relationship traversal already accepted
by the current fixed query pipeline. It does not perform graph analysis or request a new
path.

### 5.1 Additive topology transport

Retain a bounded, presentation-only copy of the traversal hops already returned by the
existing traversal call.

The additive internal/public topology may contain only what is needed to reproduce the
recorded relationships, such as:

- stable presentation node IDs;
- authoritative endpoint GlobalIds where already available;
- IFC entity class where already available;
- relationship class and existing semantic role;
- actual `from` and `to` endpoint roles;
- schema direction;
- grouped entity/relationship counts;
- bounded GlobalIds needed for supported node selection.

Where the current relationship-member statement already joins the required rows, selecting
the existing `from`/`to` endpoint role or endpoint GlobalId columns is allowed. Do not
change its joins, filters, traversal frontier, depth, direction, allowed relationship
class, number of statements, or reached endpoint set.

The existing `graph_endpoints`, `graph_path_count`, answer facts, and viewer behavior
remain unchanged. The new topology is ignored by the final LLM and exists only in the
optional explanation payload.

Do not expose internal numeric database IDs, raw relationship-member rows, canonical JSON,
SQL, predicates, or unbounded paths in the public response.

### 5.2 Presentation-node grouping

Build presentation nodes deterministically after traversal is complete.

The query seed/subject remains its own node and is never merged into an endpoint group.

Group endpoint occurrences by this exact structural key:

```text
IFC entity class
+ relationship class
+ schema direction / endpoint role
```

Therefore:

- entities of the same IFC class participating through the same relationship structure
  collapse into one presentation node;
- the node displays the number of distinct underlying entities it represents;
- the same physical entity may appear in multiple presentation nodes when it participates
  through different relationship classes, directions, or endpoint roles;
- repeated occurrences of the same entity under the same structural key count once;
- graph-node identity sets may overlap and must not be treated as a partition.

Group raw hops into one presentation edge when they connect the same presentation-node
pair through the same relationship class, semantic role, direction, and endpoint-role
pair. Show the number of distinct underlying connections represented by a grouped edge.

Deduplicate the same stored connection encountered from opposite traversal directions.
Do not double-count a reverse discovery as a second semantic edge. Arrow direction must
follow the recorded IFC relationship roles, not the order in which traversal discovered
the hop.

Do not infer an edge from geometric proximity, shared storey, similar naming, viewer
selection, or class membership. If authoritative roles/direction are insufficient to
construct the grouped topology, use the relationship table.

### 5.3 Exact graph threshold and bounds

Count nodes only after the grouping rules above have been applied. Count the seed/subject
node in the total.

Render the node-link diagram only when:

```text
grouped node count >= 4
and grouped node count <= 24
and grouped edge count <= 40
and every displayed edge is authoritative
```

Use the relationship table when:

- the grouped graph has three or fewer nodes;
- it has more than 24 grouped nodes;
- it has more than 40 grouped edges;
- topology is missing or incomplete;
- truthful node/edge grouping cannot be produced.

When the upper bound causes table fallback, state compactly in the information region that
the relationship result is too large for the bounded graph. Do not silently truncate a
graph, hide edges until it passes the threshold, or sample a topology that changes its
meaning.

### 5.4 Graph rendering and interaction

Render a compact, deterministic node-link diagram within the existing visualization region.
Ordinary React/CSS/SVG is sufficient; do not add a large graph or dashboard dependency.

The diagram must:

- use a stable layout with no continuous force simulation or post-load jitter;
- clearly distinguish the seed/subject node from grouped endpoint nodes;
- label each node with its entity label/class and represented entity count;
- label or otherwise accessibly identify each edge's relationship meaning and grouped
  connection count;
- preserve recorded direction where the relationship is directional;
- remain readable within the existing explanation-card scroll area;
- provide a textual accessible description of nodes and edges;
- support keyboard focus for selectable nodes;
- respect reduced-motion preferences.

A grouped node is selectable only when its bounded GlobalIds are an authoritative subset of
the original query-result highlight. Selecting it applies that subgroup using the existing
Task 26 highlight mechanism and updates the information region. Because graph-node groups
may overlap, selecting one never implies that other groups form a disjoint remainder.

The existing **All results** action restores the exact original primary and
relationship-context roles. Nodes without selectable identities remain informative but
disabled/noninteractive.

Do not draw relationship lines in the 3D viewer, add a second viewer canvas, move the model
camera, or treat the node-link diagram as model geometry.

---

## 6. Presentation contract and frontend responsibility

Keep `answer_explanation` optional, typed, allowlisted, bounded, and backward-compatible
for clients that ignore it.

Extend it only as needed for:

- the revised table/chart presentation choice;
- the bounded grouped relationship nodes and edges;
- graph/table fallback reason;
- authoritative identity subsets required for supported interaction.

Regenerate the frontend OpenAPI types.

The frontend must not recalculate graph grouping, graph eligibility, or operation-to-visual
selection differently from the backend. It may perform only deterministic layout of the
already-declared grouped nodes and edges.

The persistent Task 26 information region remains mandatory whenever the panel is open. It
must continue to state:

- the represented answer part and backend interpretation;
- what is currently shown/highlighted;
- shown versus true count where capped;
- result status and answer basis;
- active limitation, partial information, or graph fallback reason.

Do not use the information region to introduce a new interpretation or graph claim.

---

## 7. Existing UI behavior to preserve

Keep the Task 26 desktop behavior unchanged for qualifying presentations:

- fixed right-side column;
- explanation above chat at the established 60/40 split;
- 40vw shared column, reduced to 32vw with the existing component panel;
- existing outer margins, card styling, spacing, collapse behavior, and obstruction
  calculation;
- synchronized replacement, close, Clear Chat, Reset App, model switch/unload, and stale
  request protection;
- existing component-panel behavior and deterministic object selection;
- existing subgroup highlight and **All results** restoration.

When no presentation qualifies, keep the original full-height, resizable chat panel and do
not reserve blank explanation space.

Task 28 floor-plan mode remains independent:

- floor buttons and plan rendering stay in the main viewer;
- changing 3D/plan mode neither opens nor closes the explanation;
- the explanation never renders a plan, section, elevation, or model image;
- query-primary, relationship-context, and manual selection roles keep their established
  behavior.

Do not add saved visualizations, report export, collaboration, persistence, a visualization
picker, user-authored graph controls, arbitrary graph expansion, or an “ask AI for a
visualization” action.

---

## 8. Documentation alignment

Update the delivered Task 26 amendment in `specs/spec_v006_frontend_application.md` so the
current specification records:

- the new panel-opening gate;
- the deterministic operation/data mapping;
- table and horizontal-bar behavior;
- partial as a modifier rather than a presentation;
- the grouped relationship graph rule and exact 4–24 node / 40-edge bounds;
- the fixed backend/LLM pipeline boundary;
- plans remaining exclusively in the main viewer.

Do not rewrite historical completed task files or unrelated specification sections.

---

## 9. Validation

Add focused backend and frontend tests without live OpenAI calls.

### 9.1 Backend contract and regression tests

Verify:

- count and list select table presentation;
- count rows come from already-hydrated authoritative viewer identities and remain capped
  at 50 without another statement;
- a two-or-more-bucket distribution selects horizontal bars;
- a one-bucket distribution selects a table;
- existence, sample detail, aggregate, extremum, description, and unsupported comparison
  omit the explanation payload;
- zero, unavailable, and ambiguous results omit the payload;
- partial status preserves the base operation's presentation and limitation rather than
  selecting a partial visualization;
- relationship topology is copied only from already-returned traversal hops;
- no presentation code can access a database session or LLM;
- query/LLM schema and prompt snapshots remain unchanged;
- graph statement count, plan, depth, direction, selected relationship class, endpoint set,
  and ordering remain unchanged;
- final answer text, facts, status, evidence, endpoints, viewer identities, and viewer roles
  remain byte-for-byte/equivalently unchanged where applicable.

Use focused graph fixtures to verify:

- two nodes and one edge use a table;
- three grouped nodes use a table;
- four grouped nodes use a graph;
- the seed node is included in the threshold;
- same IFC class plus same relationship structure collapses to one counted node;
- the same GlobalId under different relationship classes/directions/roles may appear in
  multiple presentation nodes;
- repeated identity occurrences in one group count once;
- duplicate reverse discovery of one stored relationship does not create a second edge;
- grouped edge counts represent distinct authoritative connections;
- schema direction is preserved independently of traversal discovery order;
- exactly 24 nodes and 40 edges remain eligible;
- 25 nodes or 41 edges use the relationship table with an explicit size limitation;
- missing roles, missing topology, or incomplete authoritative edges use the table;
- public graph payloads are typed, bounded, allowlisted, and contain no internal numeric IDs
  or raw rows.

Regenerate and verify the OpenAPI contract without changing unrelated response fields.

### 9.2 Frontend tests

Verify:

- count and list render bounded scrollable tables with exact and shown totals;
- one-bucket distributions render a table;
- multi-bucket distributions render exact-labelled horizontal bars;
- scalar/text operations leave the original full-height chat and do not open an empty card;
- a newer nonqualifying result retires the prior card/highlight;
- qualifying relationship payloads render a stable node-link diagram;
- relationship fallback payloads render the endpoint table and limitation where applicable;
- node and edge labels/counts/directions are visible and accessibly described;
- selectable graph nodes update viewer highlight and the information region;
- overlapping graph-node identity sets behave truthfully;
- nonselectable nodes do not pretend to update the viewer;
- **All results** restores the exact original primary/context roles;
- keyboard navigation, focus visibility, scrolling, and reduced-motion behavior remain
  usable;
- the existing 60/40, 40vw/32vw, component-panel, obstruction, clearing, stale-response,
  and chat-collapse behavior remains intact;
- 3D/plan mode changes do not create, replace, or close explanation content.

Run the existing frontend build, typecheck, lint, unit/component suite, and critical
Playwright path, plus focused backend offline contract/binding/graph tests. Do not run the
costly live LLM benchmark for this deterministic presentation task.

---

## Acceptance outcome

After Task 29:

```text
count or list with inspectable objects
    -> bounded table + persistent information region

existing multi-bucket distribution
    -> horizontal bars + persistent information region

relationship with 4–24 grouped nodes and <=40 grouped edges
    -> grouped node-link diagram + persistent information region

small, oversized, or incomplete relationship topology
    -> relationship table

scalar, measurement, qualitative, unsupported, zero, or unavailable answer
    -> original chat only
```

Relationship nodes group entities by IFC class plus relationship structure. The same
entity may appear in more than one node when it plays different relationship roles, and
grouped edges preserve authoritative IFC direction without double-counting reverse
traversal discovery.

The existing backend/LLM pipeline remains fixed: no new interpretation, plan, relationship
class, path depth, traversal, query, LLM call, answer fact, prose change, or viewer result
is introduced. The panel only presents bounded structured information already established
by the accepted result.
