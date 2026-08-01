# Specification v010: Query Explanation Panel

## 1. Purpose and authority

One frontend panel that explains the latest highlighted query result with an appropriate structured
visualization. The natural-language query pipeline remains the product; this card is a visual
explanation of the backend's already-computed authoritative result — not a second analysis system, a
report builder, a dashboard, or a replacement for the chat.

This specification is authoritative for the panel's presentation contract, its opening gate,
presentation selection, tables, bar chart, grouped relationship diagram, viewer synchronization, and
panel lifecycle.

It is governed by `spec_v006_frontend_application.md`, which owns the shared layout and panel geometry,
state and clearing semantics, security, testing policy, and acceptance criteria. Query interpretation,
routing, execution, classification, and answer wording are owned by `spec_v002` through `spec_v005` and
are never restated or reinterpreted here.

Related frontend specs: `spec_v008_3d_viewer.md` (the highlight this panel explains and manipulates),
`spec_v009_chat_panel.md` (the answer itself), `spec_v011_component_panel.md` (per-object details).

## 2. Hard boundary

The query and LLM pipeline is behaviorally frozen with respect to this panel:

- **no additional LLM call** is made for the panel;
- the prose answer is **never parsed** to build a visualization;
- nothing may be recomputed to make a result qualify — no new comparison values, extremum winner rows,
  distributions, class breakdowns, or identity sets;
- the panel never drops or broadens the identities the pipeline returned.

**The no-extra-computation guarantee is structural, not promised.** The presentation builder
(`app/query/binding/presentation.py`) and the topology reducer (`app/query/binding/topology.py`) take
no `Session` and import nothing from sqlalchemy, the execution layer, the compiler, the LLM layer, the
traversal module, or `graph_exec`. They read finished objects and copy bounded fields out of them.
Tests assert both modules' import lists.

## 3. Presentation contract

### 3.1 Envelope field

`QueryResponseEnvelope` carries ONE optional, typed, allowlisted (`extra="forbid"`), backward-compatible
field:

```text
answer_explanation: AnswerExplanation | None
```

It describes the **primary visual** answer part — the part that produced the highlight, which is not
necessarily `results[0]`. The long-standing `result_summary` behavior (first answer part) is
deliberately untouched. A client ignoring the field keeps working, and a non-qualifying result's
envelope differs from a qualifying one **only** by this field.

Schemas: `AnswerExplanation`, `ExplanationPresentation` (enum), `ExplanationGroup`, `ExplanationRow`,
`ExplanationBucket`, `ExplanationAggregate`, `ExplanationGraph`, `ExplanationGraphNode`,
`ExplanationGraphEdge`. All are OpenAPI-generated into `frontend/src/types/api.ts`
(`spec_v006` §9.6).

Exposed fields: part id, request label, operation, result status, presentation kind,
`presentation_fallback_reason`, answer basis, interpretation, retrieval modes, exact total, class
breakdown, distribution buckets, `chart_unit`, aggregate value/unit/matched/coverage/completeness,
relationship endpoint total, limitation, known/unknown parts, shown identity count, true result count,
truncation state, bounded groups (with GlobalIds), rows, and the graph payload.

Never exposed: SQL, prompts, predicates, canonical JSON, manifests, credentials, database diagnostics,
internal numeric database ids, raw relationship-member rows, or unbounded paths — asserted against the
generated OpenAPI schema.

### 3.2 Identity hydration adds no query

Displayed groups are a literal partition of the identities the viewer already received:
`hydrate_viewer_identities` has always selected `ifc_class` beside `global_id`, and
`ViewerHydration.primary_identities` keeps the pair. Where no authoritative identity subset exists —
notably distribution buckets, which are grouped counts — the value is displayed but **not** offered as
a selectable group; `ExplanationBucket` has no `global_ids` field at all.

Counts stay truthful under the viewer identity cap: `true_result_count` and a group's `exact_count`
keep their real values, and `identities_truncated` / `truncated` disclose the gap.

### 3.3 Additive topology transport

The relationship diagram is fed by an additive projection, not by new work:

- `TraversalHop` carries `from_role`, `to_role`, `from_entity_global_id`, `from_entity_ifc_class`,
  `to_entity_ifc_class`, and `traversal_direction`. Every one is projected off the two
  `relationship_members` rows (`m_from`, `m_to`) the traversal statement **already joins** — the SELECT
  list grew and nothing else. Tests compile that statement and assert the join count, source-model
  isolation, the frontier/role/self-exclusion predicates, the absence of any ORDER BY / LIMIT /
  GROUP BY / DISTINCT / UNION, and one statement per class per direction.
- `GraphExecution` / `AnswerPartResult` carry `graph_seed_entity_ids`, `graph_topology_hops`, and
  `graph_topology_truncated`. The hop copy is an **in-memory filter** of rows traversal already
  returned, restricted to the seeds and the ACCEPTED endpoints, so a diagram can never draw a
  connection the answer did not claim. Above 2,000 hops the copy is dropped and reported as too large
  — never sampled.

## 4. Opening gate

The panel appears **only** when a structured visualization materially supplements the 3D viewer
result. A completed result opens it only when all four hold:

1. its operation/data maps to a supported presentation (§5);
2. its status is `exact` or `partial`;
3. the required structured data is authoritative and non-empty;
4. it has a non-empty current query-result highlight.

`zero`, `unavailable`, and `ambiguous` never open it. `partial` is a **modifier**: it keeps the base
operation's presentation and shows its limitation and known/unknown split in the information region; a
partial aggregate still opens nothing.

Selection stays deterministic — no separate visualization intention is inferred:

```text
accepted backend operation + already-computed structured result
    -> table, horizontal bar chart, relationship graph, or no panel
```

Scalar answers open no panel. When a newer completed result does not qualify, the previous explanation
and its highlight retire together and the original full-height chat layout returns; no blank
explanation space is reserved.

## 5. Fixed operation/data mapping

| Accepted operation/data | Presentation |
| --- | --- |
| `count` with authoritative hydrated identities | `result_table` |
| `list` with authoritative rows/identities | `result_table` |
| `group_distribution`, >= 2 existing buckets | `bar_chart` |
| `group_distribution`, exactly 1 bucket | `group_table` |
| `relationship` with a complete in-bounds grouped topology | `relationship_graph` |
| `relationship` otherwise | `relationship_table` + fallback reason |
| `comparison` with >= 2 existing homogeneous numeric values | `bar_chart` |
| `comparison` with existing heterogeneous structured values | `comparison_table` |
| `comparison` with no existing structured payload | no panel |
| `existence`, `aggregate`, `extremum`, `description` | no panel |
| `sample_detail` | no panel; existing component/detail behavior preserved |

A count is the deliberate exception to the general scalar rule: counting an identifiable object set
makes membership worth inspecting. A count with no authoritative displayed identities stays in chat.

`ExplanationPresentation` emits `result_table`, `group_table`, `comparison_table`,
`relationship_table`, `bar_chart`, and `relationship_graph`. The earlier values (`metric`, `table`,
`distribution`, `aggregate`, `relationship`, `partial`) remain **accepted** so an older client keeps
parsing the contract, but the selector never emits them and no standalone metric, aggregate,
relationship-metric, or partial-split visual exists in the frontend.

Presentation is chosen in the backend from the authoritative operation and status, so the frontend
never guesses. Only the primary visual part is shown; answer parts are never unioned.

**Known contract reality.** The frozen pipeline never produces a structured comparison payload —
`comparison` executes as a scoped-RAG-ranked structured count and leaves `distribution` empty — so in
practice comparison answers take the "no existing structured comparison payload → no panel" row. The
two comparison rows above are implemented and tested against the only structured series a result can
carry, and activate the moment a future pipeline change populates one. Nothing is computed to make a
comparison qualify.

## 6. Panel content

Two regions, always: the visualization at the left and a persistent plain-language information region
at the right. A chart or table never appears alone.

The information region states what question part the card represents, what the backend interpreted,
what is currently highlighted, shown-versus-true counts where truncation exists (independently of, and
in addition to, the table caption of §7.1), operation/result
status and answer basis, and any limitation, coverage note, known/unknown split, or graph fallback
reason. Selecting a group changes it to distinguish the subgroup from the full answer
(`Showing: IfcDoor` / `5 of 9 query-result objects` / `Full result: 9 · external doors on floor 3`).

It is descriptive only: every line restates a backend field, and it introduces no interpretation, no
factual claim, and no graph claim of its own.

The frontend recalculates no grouping, eligibility, or presentation choice. Visualizations are ordinary
React/CSS/SVG — no charting dependency.

## 7. Tables

One bounded scrollable table family serves result, group, comparison, and relationship-fallback
tables.

**Row-based OBJECT tables** — result tables and the relationship endpoint fallback table — have no
terminal row ceiling. The payload carries every authoritative row already represented by the response's
hydrated identities, and §7.1 displays them progressively. The naturally bounded contents of one-bucket
group tables and comparison tables are unchanged: those are not object tables and neither paginate nor
sort.

Count and list tables show the exact/true total, the number of identities represented, IFC class, any
already-available name/storey, and GlobalId as the final identity fallback. **Count rows are built from
the identities the viewer was already hydrated with**, merged with existing example metadata by
GlobalId; both lists are ordered by entity id, and no query is issued to fill a missing name.

### 7.1 Bounded availability and progressive display

The row list is bounded by **viewer hydration**, not by a display quantum: `MAX_EXPLANATION_ROWS`
mirrors `Settings.max_viewer_match_ids` (**2,000**), a second explicit ceiling so the payload can never
become an unbounded result transport even if that setting were raised. The 2,000-identity viewer cap
itself is unchanged: it bounds a single response and the viewer highlight, and it never changes the
exact result total.

The presentation builder keeps its structural isolation from the database, execution, and LLM layers.
Filling the larger list issues no additional database query and no LLM call — a row with no name is a
GlobalId plus IFC class, which is a sufficient row.

The frontend renders the first **50** rows and appends the next **50** each time the user reaches the
end of the table's own bounded scroll area, until every available row is displayed. There is no
`Load more` button, the explanation panel itself never grows, and scrolling is pure in-memory work: no
pagination endpoint and no network request on scroll or sort.

The caption distinguishes all three quantities whenever they differ — **rows currently displayed**,
**rows available under the viewer-identity cap**, and the **true result total**. It may never let an
available count read as the complete result:

```text
Showing 50 of 2,000 listed objects; 5,000 results in total
Showing all 2,000 listed objects; 5,000 results in total
Showing 50 of 120 results
120 results
```

### 7.2 Three-state column sorting

Every object-table column header — `Object`, `Class`, `Storey` — is an accessible sort button with this
exact cycle:

```text
first click  -> descending
second click -> ascending
third click  -> cancel sorting and restore the original backend order
```

Only one column is active at a time; activating another column starts that column at descending and
clears the prior column's state. Sorting covers the **complete available row set**, not only the rows
currently mounted. Any sort-state change returns the display to the first 50 rows and scrolls the table
to the top. Missing values stay last in both directions (they are absent, not extreme), ties keep the
original relative order via an explicit index tiebreaker, and cancelling restores the deterministic
backend/entity order exactly. The `Object` column sorts on what it displays — the name, else the
GlobalId fallback.

The active direction is exposed visually and through `aria-sort`, and the headers are operable from the
keyboard. No spreadsheet component or table dependency is added.

A one-bucket distribution uses a table because one bar carries no comparison. A structured comparison
uses a table only when its values already exist. If the rows a truthful table needs do not exist, the
panel is omitted rather than falling back to a metric card.

The class group summary appears beside a result or relationship table only when the breakdown means
something: the backend withholds `groups` entirely for a single-class result, so no bars fill space.

## 8. Horizontal bar chart

Used for an existing distribution with >= 2 buckets, or an existing comparison of >= 2 homogeneous
numeric values with a compatible unit (`chart_unit`, taken only from a unit the result already
recorded).

Every bar states its exact label and exact value — the length is a comparison, never a replacement for
the number. Buckets stay display-only: grouped counts have no identity set, so no bucket is ever a
button.

No pie, donut, line, or scatter chart; no dashboard; no chart recommendation; no general charting
system.

## 9. Grouped relationship diagram

`app/query/binding/topology.py` reduces the retained hops to grouped nodes and edges after traversal is
complete. It performs no graph analysis and requests no path.

**Direction is the IFC schema's, not traversal's.** Each hop is normalized with the registry's role
names so `source` is always the *relating* side and `target` the *related* side. The same stored
connection discovered from the opposite direction normalizes to the identical
`(relationship, relating entity, related entity)` triple and collapses into one edge with the correct
arrow — a reverse discovery is never a second semantic edge. Because every registered relationship is
directional relating→related, `schema_direction` is a constant on the public edge; the informative
direction data is the recorded `source_role`/`target_role` pair, which both the normalization and the
arrow derive from. `traversal_direction` is retained on the internal hop for diagnostics only and never
orients an edge.

**Grouping.** The seed/subject is its own node and is never merged into an endpoint group. Endpoint
occurrences group by `IFC entity class + relationship class + endpoint role`, so entities of the same
class participating through the same relationship structure collapse into one node carrying its
distinct-entity count. Node identity sets **overlap and are not a partition**: the same entity appears
in several nodes when it participates through a different relationship class, direction, or role, and
repeated occurrences under one key count once. Edges group by node pair + relationship class + semantic
role + endpoint-role pair and carry a distinct-connection count.

No edge is ever inferred from proximity, shared storey, naming, viewer selection, or class membership.

**Exact bounds, counted after grouping with the seed included:** the diagram renders only when
`4 <= nodes <= 24`, `edges <= 40`, and every displayed edge is authoritative. The endpoint table is used
instead when there are <= 3 nodes, > 24 nodes, > 40 edges, a missing role, a missing endpoint class, an
unresolved endpoint, an unregistered relationship class, an over-ceiling hop copy, or an accepted
endpoint no retained hop covers. The information region then states the backend's own compact reason.
Nothing is silently truncated, hidden, or sampled to pass a threshold.

**Rendering** (`frontend/src/explain/RelationshipGraph.tsx`): an SVG edge layer with real focusable node
controls positioned above it. Fixed geometry (seed at the left, endpoint groups in columns of 8),
deterministic layout from the backend's own node order, no force simulation, no animation, no post-load
jitter — rendering the same payload twice yields identical markup. Each node shows its label and
represented entity count and is visually distinguished as seed or endpoint; each edge is drawn with a
directional arrowhead and also listed textually with its relationship meaning and grouped connection
count. The backend supplies the graph's plain-language `description` for assistive technology, so the
accessible reading can never describe a different topology. Reduced motion is respected; the diagram
scrolls inside its own area.

No relationship lines are drawn in the 3D viewer, no second canvas is added, and the model camera never
moves.

## 10. Viewer synchronization and group selection

Displayed groups are backed by authoritative GlobalIds that are a subset of the original query-result
highlight. Clicking a bar, a table group, or a selectable diagram node applies that subgroup as the
viewer's primary highlight and marks it `aria-pressed`.

- **All results** appears whenever a subgroup is active and restores the original primary *and*
  relationship-context roles exactly from stored frontend state.
- Neither path issues a query, an LLM call, a backend request, or a chat turn.
- A group with no identities renders disabled rather than pretending to select a set nobody hydrated.
  The seed node and any node without selectable identities render as informative, non-interactive
  elements.
- A capped node selection discloses `N of M objects in this group`; truncation is disclosed rather than
  implied away.
- When diagram groups can share objects, the information region says so, so the other groups are not
  mistaken for the remainder.
- Clicking an individual object still uses the existing deterministic object-detail flow and the
  unmodified component panel (`spec_v011`).

## 11. Panel lifecycle

The card represents the current query-result highlight, not chat history.

- It opens only when the latest completed query satisfies the §4 gate. The highlight and the
  explanation are applied in one step in `applyViewerActions`, so they cannot diverge.
- A newer qualifying result replaces the card outright, active subgroup included.
- A newer completed query with no qualifying explanation retires the previous explanation **and** the
  previous query highlight together.
- It is cleared on Clear Chat, Reset App, model switch/unload, and its own close control — which also
  clears its query-result highlight.
- Stale, canceled, or superseded responses can neither reopen nor overwrite it: the existing
  `queryToken` guard returns before any explanation state is touched.
- Opening the component panel by clicking an object does not replace the explanation or its highlight.
  A deterministic **Same type** / **Same family** action does replace the highlight, so it retires the
  explanation at the same moment.
- Clicking empty viewer space clears only the *manual* selection and has never cleared query roles, so
  the query highlight and the card both persist through it. The explicit clear is the card's own close
  control.
- Floor-plan mode is independent: entering or leaving it neither opens nor closes the card, and the
  panel never renders a plan, section, elevation, or model image (`spec_v008` §8.7).

## 12. State

Store state is serializable and current-session only: the bounded payload, the original
primary/context GlobalIds (so **All results** needs no new query), the active subgroup, and lifecycle
state. Nothing is persisted to local storage; there are no saved reports, exports, backend write
tables, collaboration features, visualization pickers, user-authored graph controls, graph expansion,
or "ask AI for a visualization" actions.

Manual object selection and the selected-object query chips are unaffected by this panel
(`spec_v009` §6).

Layout — the fixed right-side column, its split with the chat panel, its width beside the component
panel, margins, card styling, collapse behavior, and the single obstruction calculation — is owned by
`spec_v006` §7.2 and §7.3.
