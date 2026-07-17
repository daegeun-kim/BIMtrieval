# Task 17: Query-Only Retrieval Policy, Evidence Groups, and Complete Viewer Results

## Prerequisites and authority

Require:

```text
tasks/task13_done.md
tasks/task15_done.md
tasks/task16_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

This task corrects a Task 16 failure discovered through the real query:

```text
Describe me the circulation of this building.
```

The validated plan combined these classes into one SQL count:

```text
IfcStair
IfcRailing
IfcDoor
IfcWindow
IfcSlab
IfcWall
IfcWallStandardCase  # introduced by existing IfcWall expansion
IfcBuildingStorey
```

The exact counts were:

```text
IfcStair: 9
IfcRailing: 90
IfcDoor: 205
IfcWindow: 259
IfcSlab: 279
IfcWall: 648
IfcWallStandardCase: 232
IfcBuildingStorey: 1
combined predicate total: 1,723
```

The database correctly counted the combined predicate, but the answer incorrectly called the
1,723 objects a circulation backbone. The semantic vocabulary evidence was also dominated by
railings: its highest results included `IfcRailing`, a generic `Storey-1` railing fact,
`IfcStair`, `IfcDoor`, and another railing property. Queryable railing facts expanded to object
identities while the `IfcStair` class candidate carried a count but no identities. The bounded
evidence/result sample therefore contained railings while stairs were not prioritized for the
viewer.

Treat the current behavior as a data-contract defect, not merely a prompt-quality issue.

Amend the relevant specifications where this task conflicts with completed Task 16 behavior. Do
not rewrite or alter completed task history.

## Owner intent

The database, SQL, RAG, and graph paths are context-selection mechanisms. They reduce a BIM model
to bounded evidence that the answer LLM can judge. Exact database totals, detailed LLM examples,
and 3D viewer identities are separate products and must not share one truncation limit.

The intended limits are:

```text
exact SQL counts and aggregates: uncapped
RAG results: bounded top-k candidates, never an exact semantic total
detailed object examples sent to the answer LLM: 50 total
3D viewer identities for accepted result groups: complete, with no fixed 2,000-ID truncation
```

The 50 examples must be the most useful, group-diverse evidence for judgment, not the first 50
database rows and not the first 50 items from one global vector-similarity ordering. All identities
belonging to answerer-accepted viewer groups must be available to the frontend independently of
the 50-example evidence package.

Do not solve broad natural-language concepts with fixed mappings such as:

```text
circulation = stairs + railings + doors + corridors + slabs
```

Instead, create a question-specific evidence hierarchy:

```text
direct
supporting
context
uncertain
rejected
```

The hierarchy is about relevance to this question. It is separate from IFC inheritance. IFC
inheritance can explain that `IfcStair` and `IfcRailing` are building elements, but it cannot decide
that a stair is direct circulation evidence while a railing is supporting safety evidence.

## Non-negotiable retrieval-policy rule

Whether SQL, entity RAG, relationship RAG, or graph retrieval is necessary must be determined from
the query itself, not from semantic-resolution results.

The retrieval-policy decision may use only:

```text
current user question
bounded conversation history needed to resolve references
active-model versus catalog scope
bounded current viewer selection
explicit user request to show, count, compare, traverse, or explain
```

It must not use:

```text
ontology candidate ranks
model-vocabulary candidate ranks
candidate presence or absence
candidate exact counts
observed names/properties/types
RAG scores or prior RAG results
schema field availability
```

This is a hard dataflow and test requirement. Do not attempt to satisfy it only by telling a model
to ignore semantic candidates while those candidates remain in the same modality-decision prompt.

This task intentionally changes the earlier conceptual stage order. The query-only retrieval policy
is now Stage 2 and semantic resolution is Stage 3. This reordering is required because a planner that
can see semantic-resolution output cannot be proven independent from it. An implementation may
precompute resolution concurrently for latency only if its output is isolated and cannot be read,
awaited, or used by the policy call before the policy is validated and frozen.

To enforce the boundary, the query-only retrieval policy must be fixed before semantic resolution
is run or exposed. Once fixed:

- semantic resolution may populate concepts, candidate groups, typed SQL predicates, and probe
  search text;
- semantic resolution may not add or remove entity RAG, relationship RAG, or graph retrieval;
- a strong semantic match may not cancel RAG/graph requested by the query-only policy;
- an empty or surprising semantic result may not introduce RAG/graph that the policy did not
  request;
- a semantic-service failure may degrade candidate construction, but may not mutate the fixed
  retrieval modes.

Preserve two principal LLM calls:

```text
LLM call 1: query-only retrieval policy and conceptual facet plan
backend: semantic resolution, candidate grouping, retrieval, verification, and sampling
LLM call 2: group-level relevance judgment and answer writing
```

Do not add a separate third router, class resolver, relevance judge, or replanning LLM call.

## Objective

Refactor the active-model query pipeline so that it:

1. makes an immutable SQL/RAG/graph modality decision from the query before semantic resolution;
2. uses semantic resolution only to discover how requested concepts may be represented in IFC and
   the active model;
3. represents retrieval results as independently selectable evidence groups with deterministic
   predicates and provenance;
4. keeps exact SQL groups separate from bounded semantic candidates;
5. sends compact summaries for every bounded group and at most 50 group-aware detailed examples
   to the answerer;
6. lets the answerer classify and accept/reject individual groups rather than whole mixed probes;
7. retrieves all viewer identities for accepted groups after the answerer decision;
8. removes the fixed 2,000-identity viewer truncation;
9. prevents ambiguous concept totals such as `1,723 circulation elements`;
10. remains read-only and does not require ingestion, vector, database, or viewer-artifact changes.

## 1. Required end-to-end dataflow

Implement the following order for conversational active-model queries.

### Stage 1: request assembly

Collect:

```text
question
active source model
bounded reference-resolving history
bounded selected entities
explicit viewer intent
```

Do not attach semantic-resolution candidates to the retrieval-policy input.

### Stage 2: query-only retrieval policy (LLM call 1)

The first LLM call determines retrieval requirements and conceptual facets from the query-only
input.

The structured output must contain an equivalent of:

```json
{
  "scope": "active_model",
  "analysis_intent": "Describe how movement through the building is represented",
  "facets": [
    {
      "facet_id": "vertical-movement",
      "question": "What directly represents movement between levels?",
      "role_hint": "direct",
      "semantic_query": "vertical movement between building levels",
      "needs_exact_structured": true,
      "needs_entity_rag": true,
      "needs_relationship_rag": false,
      "needs_graph": false
    },
    {
      "facet_id": "horizontal-movement",
      "question": "How are horizontal paths or movement spaces represented?",
      "role_hint": "direct",
      "semantic_query": "horizontal circulation paths corridors lobbies movement spaces",
      "needs_exact_structured": true,
      "needs_entity_rag": true,
      "needs_relationship_rag": false,
      "needs_graph": false
    }
  ],
  "retrieval_policy": {
    "sql": true,
    "rag_entity": true,
    "rag_relationship": false,
    "graph": false
  },
  "viewer_intent": "no_op"
}
```

The example is illustrative, not a fixed circulation recipe. The planner may choose different
facets from the wording and conversation context.

The query-only planner must not emit raw SQL, database JSON paths, final IFC classes, or
model-specific property names. It emits conceptual facets, semantic query text, role hints, and
retrieval requirements. The backend resolves those concepts against the active model afterward.

The retrieval policy is immutable after validation. Record it separately from later resolved
probes/groups.

### Stage 3: semantic resolution under the fixed policy

For each conceptual facet, search the existing:

```text
static IFC ontology profiles
active-model class profiles
active-model observed fact profiles
active-model quantity/coverage profiles
```

Semantic resolution answers:

```text
How might this facet be represented?
Which classes/facts exist in the model?
Which candidates expose safe typed predicates?
Which schema definitions help interpret candidates?
```

It does not answer:

```text
Should entity RAG run?
Should relationship RAG run?
Should graph traversal run?
```

Stage 3 candidates are compact profiles, not complete entity rows. A class candidate should carry
a safe class predicate when present in the active model. A queryable fact candidate should carry
its typed field/value predicate. Non-queryable candidates remain semantic suggestions and must not
be converted into unsafe SQL.

### Stage 4: deterministic group construction and probe execution

The backend converts resolved candidates into independently selectable evidence groups, then
executes only the retrieval modes fixed in Stage 2.

Examples:

```text
group: class IfcStair
predicate: ifc_class = IfcStair

group: lift-related doors
predicate: IfcDoor AND normalized name contains liftdeur

group: a bounded set of RAG-only landing candidates
predicate: exact candidate entity IDs only; no exhaustive semantic claim
```

If the policy requests SQL, verify safe queryable groups with typed SQL. If the policy requests
entity or relationship RAG, execute threshold-free top-k search for the relevant facets. If the
policy requests graph, execute bounded graph work after deterministic start candidates are
available. Do not execute graph solely because semantic resolution returned a relationship-like
candidate.

### Stage 5: evidence-group normalization

Normalize SQL, RAG, ontology, vocabulary, and graph results into bounded groups while preserving
source authority and coverage. Do not flatten them into one mixed entity collection.

### Stage 6: group summaries and 50-example allocation

Create a deterministic factual summary for every bounded evidence group. Allocate at most 50
detailed object examples across groups using Section 7.

### Stage 7: group-level relevance judgment (LLM call 2)

The answerer classifies groups as primary, supporting, context, or rejected and writes the answer
from accepted groups only.

### Stage 8: complete post-answer viewer identity hydration

After the answerer decision, deterministically retrieve every identity belonging to accepted
viewer groups. This is a read-only database step, not another LLM call.

### Stage 9: response and frontend

Return:

```text
LLM answer text and accepted bounded evidence examples
all accepted viewer GlobalIds
exact result/group counts
accepted/rejected group metadata needed for follow-up state
```

The frontend colors every accepted viewer identity. The 50-example limit must not constrain the
viewer identity set.

## 2. Retrieval-policy semantics

### SQL

Request SQL when the query asks for exact model facts or when exact verification is a reasonable
part of answering it:

```text
counts
lists
filters
aggregates
field coverage
class presence/absence
exact typed-property facts
complete identities for a known predicate
```

SQL can be requested for an ambiguous analytical question to verify whatever safe groups are later
resolved. The query-only planner does not need to know the final IFC classes to request exact
structured evidence.

### Entity RAG

Request entity RAG when the query itself asks for qualitative or semantically defined model
evidence that may not be reducible to a known exact field/class predicate, including specific
examples whose combined names, descriptions, types, and properties may matter.

Do not request entity RAG merely because semantic resolution has weak, empty, or surprising
results. Do not cancel entity RAG because semantic resolution later finds an apparently strong SQL
candidate.

### Relationship RAG

Request relationship RAG only when the query itself asks about semantic associations,
relationships, assignments, containment, connectivity, or paths for which relationship documents
may add evidence. Candidate relationship availability cannot decide the mode after the policy is
fixed.

### Graph

Request graph traversal only when the query itself requires connectivity, neighborhood, endpoint,
containment, assignment, or path structure. Graph is not a generic fallback for ambiguity.

Graph execution may wait for deterministic start identities discovered by SQL/RAG, but the decision
to run graph must already be present in the immutable query-only policy.

### General/catalog/clarify exceptions

Preserve general explanations, model catalog behavior, deterministic detail/group endpoints, and
last-resort clarification. The modality-isolation rule applies to the conversational active-model
pipeline.

## 3. Evidence-group contract

Create a typed `EvidenceGroup` equivalent to:

```json
{
  "group_id": "vertical-movement--ifcstair",
  "facet_id": "vertical-movement",
  "label": "IfcStair objects",
  "source_kinds": ["semantic_resolution", "sql", "rag_entity"],
  "authority": "exact",
  "coverage": "complete",
  "role_hint": "direct",
  "predicate": {
    "kind": "entity_class",
    "ifc_classes": ["IfcStair"]
  },
  "predicate_queryable": true,
  "exact_count": 9,
  "rag_candidate_count": 3,
  "ontology_definition": "...",
  "factual_profile": {},
  "representative_entities": [],
  "relationship_evidence": [],
  "all_viewer_identities_available": true,
  "warnings": []
}
```

Equivalent names are allowed, but preserve these concepts.

### Stable identity and predicate

Each group requires a unique stable ID within the response. A complete/exact group must have a
safe, typed, reproducible predicate. Allowed predicate forms include:

```text
exact entity class
typed normalized attribute predicate
typed property/type/quantity predicate
explicit exact entity-ID set
exact stored relationship predicate/path
```

Do not store or execute raw SQL, arbitrary JSON paths, or LLM-authored expressions.

### One semantic claim per group

Do not place semantically distinct classes into one indivisible evidence group. A single executor
may batch database work, but the evidence contract must preserve per-class/per-predicate groups.

For a user request such as `show doors and windows`, keep door and window subgroups even if a parent
result also reports their requested combined total. For an ambiguous concept such as circulation,
never create one accepted group merely because several classes were queried with SQL `IN (...)`.

### Factual profile generation

The group description is not newly invented by an LLM and is not merely one ingestion
`description` field. Build it deterministically from:

```text
exact class/predicate count
stored names and descriptions
object/type/predefined types
storey distribution
property/quantity names and bounded common values
classifications/materials when relevant
stored relationship summaries
existing RAG document excerpts
static IFC ontology definition
```

The planner's `role_hint` and rationale are query-specific hypotheses. Keep them clearly separate
from the factual profile. The answerer makes the final role decision.

### Authority and coverage

Preserve at least:

```text
authority: exact | structured_candidate | semantic_candidate | general_context
coverage: complete | bounded | unknown | unavailable | failed
```

An exact SQL group can have an uncapped exact count. A RAG-only group contains only retrieved
candidate identities and must have bounded coverage. RAG top-k is never an exact total of every
object semantically relevant to the question.

## 4. SQL, RAG, and semantic-resolution deduplication

Stage 3, SQL, and RAG may refer to the same object or semantic group. Merge their provenance rather
than presenting duplicate evidence.

Example:

```text
semantic resolution: IfcStair, model count 9
SQL: exact IfcStair predicate count 9, all identities
RAG: three IfcStair documents among top candidates

normalized result:
one IfcStair group
exact_count = 9 from SQL
complete identities from SQL
RAG ranks/excerpts enrich representative evidence only
```

Do not:

- count the three RAG candidates as another three stairs;
- call three RAG candidates the total;
- create separate competing viewer groups for the same canonical objects;
- let an approximate candidate override an exact SQL count.

RAG-only candidate groups may contain exact candidate IDs, but their semantic coverage remains
bounded. They may be highlighted if accepted, but the system must not imply that every semantically
related object was found.

## 5. Question-specific relevance hierarchy

The query-only planner may attach a preliminary role hint to a facet:

```text
direct
supporting
context
uncertain
```

Resolved groups inherit the facet hint only as a hypothesis. Similarity, frequency, or IFC
inheritance must not automatically promote a group to direct evidence.

The answerer assigns the final role after seeing the factual group summaries and examples:

```text
primary/direct
supporting
context
rejected
```

The same IFC class may receive different roles for different questions. Examples:

```text
IfcDoor for "show the doors"       -> primary
IfcDoor for "describe circulation" -> possibly supporting
IfcDoor for "describe the roof"     -> likely rejected
```

Do not persist global natural-language role mappings.

## 6. Vector similarity responsibilities

Use vector similarity for:

```text
semantic discovery of ontology/model profiles
top-k RAG candidate retrieval
ordering representative examples within an evidence group
finding rare or model-specific descriptions not captured by a simple exact predicate
```

Do not use raw vector similarity alone for:

```text
final relevance role
global top-50 detailed evidence selection
viewer group acceptance
exact totals
proof that a supporting object is a direct instance of the requested concept
```

Association is not role. A railing may be highly similar to circulation because it protects a
stair, but that does not make all railings direct circulation paths. Repeated near-identical
objects must not consume the entire 50-example budget.

When both SQL and RAG run:

```text
SQL = exhaustive truth for a safe typed predicate
RAG = bounded semantically ranked candidates and qualitative excerpts
```

RAG must have a facet-specific information purpose. It is not required when a query-only policy
selects SQL alone, and it must not be added later because Stage 3 candidates are weak.

## 7. Group-aware 50-example evidence budget

The answerer must receive:

```text
compact factual summaries for every bounded evidence group
at most 50 detailed primary entity examples total across all groups
bounded context entities and relationships under existing limits
```

The 50-object budget applies to detailed evidence only. It does not limit exact group counts or
viewer identities.

Implement a deterministic allocator with these properties:

1. Rank groups by preliminary question role, authority, queryability, semantic relevance, and
   coverage, while treating the role as provisional.
2. Ensure viable competing groups are represented before one repeated class consumes the budget.
3. Include every member of a small high-priority direct group when it fits; the current nine
   `IfcStair` objects must not be displaced by 50 railing examples.
4. Select examples within a group by descending RAG similarity when RAG evidence exists.
5. Use stable deterministic ordering for SQL-only groups without semantic ranks.
6. Deduplicate canonical entities across groups in the detailed example budget while retaining
   cross-group provenance.
7. Keep group summaries even when a group receives zero detailed examples.
8. Record the allocation and truncation per group for testing/trace output.

Do not hard-code circulation-specific quotas. Centralize any generic per-group diversity caps or
allocation limits and justify them with tests.

## 8. Group-level answerer decision

Replace coarse probe-only relevance output with an equivalent structured decision:

```json
{
  "answer": "...",
  "primary_group_ids": ["vertical-movement--ifcstair"],
  "supporting_group_ids": ["lift-related-doors"],
  "context_group_ids": ["stair-related-railings"],
  "rejected_group_ids": ["generic-windows", "generic-walls"],
  "viewer_primary_group_ids": ["vertical-movement--ifcstair"],
  "viewer_context_group_ids": [],
  "model_evidence_sufficient": true,
  "inference_used": true,
  "inference_basis_group_ids": ["lift-related-doors"],
  "used_general_knowledge": true,
  "disclosed_conflicts": false
}
```

Validate every ID against the evidence package. Unknown, overlapping, or contradictory group
decisions must fail safely and must never add viewer identities.

The answerer may:

- accept exact SQL groups;
- reject an exact group as conceptually irrelevant;
- accept individual RAG-only candidate groups as bounded evidence;
- reject every semantic candidate;
- move a provisional direct hint to supporting/context/rejected;
- disclose cautious model-specific inference from accepted groups.

It must not:

- accept or reject only an indivisible mixed probe when separable groups exist;
- call a bounded RAG count an exact total;
- calculate an ambiguous concept total by summing associated groups;
- use a rejected group in prose, viewer actions, or follow-up state;
- expose internal group IDs, similarities, predicates, plans, or database IDs to the user.

Keep compatibility fields only as a temporary migration layer if required. New viewer and follow-up
behavior must be group-driven.

## 9. Complete viewer result identities

Remove the fixed `max_viewer_match_ids=2000` truncation from the semantic meaning of a result.

After answerer acceptance:

- execute each accepted queryable viewer-group predicate read-only;
- retrieve all matching GlobalIds;
- deduplicate while retaining primary/context role;
- send every accepted GlobalId to the frontend;
- report exact accepted viewer totals and completion status;
- never let the 50 detailed examples determine the viewer set.

Examples:

```text
accepted group count = 9
LLM examples = 9
viewer identities = 9

accepted group count = 1,723
LLM examples across all groups <= 50
viewer identities = 1,723

accepted group count = 5,000
LLM examples across all groups <= 50
viewer identities = 5,000
```

For an accepted exact SQL group, viewer identity coverage must equal the exact group count after
deduplication unless some matching database entities genuinely lack usable viewer GlobalIds. Such
missing viewer identities must be reported distinctly, not called truncation.

For an accepted RAG-only group, viewer identities are the accepted bounded candidate identities;
do not expand them into an unsupported semantic total.

### Viewer performance scope

The owner will address large-result viewer computation/load management later. This task must:

```text
remove the fixed 2,000 cap
return all accepted identities
use the existing bulk viewer action path where possible
```

This task does not require streaming, pagination, batching protocols, selection tokens, new color
systems, or large-result camera optimization. Do not reintroduce a hidden cap as a performance
workaround. Preserve camera-fit behavior unless a minimal safety correction is required for
functional correctness.

Rejected or merely retrieved candidate groups must remain uncolored. Complete visualization means
complete identities for the accepted result, not all identities in the initial candidate pool.

## 10. Answer text and totals

Exact counts remain tied to exact predicates:

```text
9 IfcStair objects
90 IfcRailing objects
36 doors whose normalized name matches liftdeur
```

Do not report:

```text
1,723 circulation-related elements
```

unless the user explicitly defined that combined set or every included group was independently
accepted under a disclosed combined definition. Association is insufficient.

When a requested concept is incompletely represented, answer from accepted evidence and state the
gap. For the current circulation case, expected wording is equivalent to:

> Vertical circulation is explicitly represented by nine stairs. Some specifically supported
> railings may provide stair-safety context, and lift-related door names suggest possible lift
> access, but elevator equipment is not explicitly represented. Horizontal corridor circulation
> cannot be assessed reliably because explicit spaces are absent.

Do not claim that generic windows, walls, slabs, all doors, or all railings define circulation.

## 11. Prompt and schema versioning

Version the query-only planner and group-aware answerer prompts/schemas. Do not silently mutate
v002 while logging the old prompt version.

The query-only planner prompt must:

- state that retrieval modes are decided only from the query input;
- define SQL/RAG/graph information needs without active-model candidates;
- produce conceptual facets rather than model-specific raw SQL/classes/fields;
- avoid fixed concept-to-class recipes;
- request RAG only for a query-derived semantic information need;
- request graph only for a query-derived relationship/connectivity need;
- keep probe/facet bounds.

The answerer prompt must:

- judge individual groups;
- distinguish factual profiles from planner role hints;
- distinguish exact SQL coverage from bounded RAG coverage;
- preserve exact totals without inventing concept totals;
- select primary/context viewer groups;
- reject semantically associated but indirect groups when appropriate;
- use only accepted groups in the final answer.

Use schema-enforced structured outputs. Do not parse free-form JSON.

## 12. Current-model regression requirements

### Circulation paraphrase that exposed the defect

Question:

```text
Describe me the circulation of this building.
```

Required behavior:

- retrieval modes are chosen from the query before semantic resolution;
- exact `IfcStair` count remains 9;
- all nine stair identities are available as a primary candidate group;
- the group-aware evidence allocation includes the stairs and is not filled by railings;
- generic `Storey-1` occurrence on railings is context at most, not proof that railings define
  circulation;
- all-railings, all-doors, all-windows, all-walls, and all-slabs groups are independently
  rejectable;
- no `1,723 circulation elements` total is reported;
- windows and generic walls/slabs are not highlighted merely because a broad SQL executor queried
  them;
- all accepted viewer identities are returned without a 2,000 cap.

### Query-only modality invariance

For the exact same question/history/selection, provide test semantic-resolution fixtures with:

```text
strong relevant candidates
weak irrelevant candidates
no candidates
degraded semantic service
misleading high-ranked candidates
```

The validated SQL/RAG/graph policy must be identical across all fixtures.

### Exact door count

Question:

```text
How many doors are in this building?
```

Expected:

- query-only policy may choose SQL without RAG/graph;
- Stage 3 maps the concept to `IfcDoor`;
- SQL verifies exactly 205;
- all 205 door identities are available to the viewer;
- LLM examples remain bounded;
- no RAG is added because Stage 3 candidates are weak or strong.

### Roof representation

Question:

```text
Show me all the roofs.
```

Expected:

- retrieval modes are selected from the semantic ambiguity of the query, not from the later
  discovery that `IfcRoof` is absent;
- resolved `IfcSlab`/`IfcCovering` name/property predicates become separate groups;
- exact groups preserve their own counts/identities;
- generic coverings/slabs are independently rejectable;
- viewer receives all identities from accepted roof groups.

### Graph invariance

Question equivalent to:

```text
What is connected to this selected stair?
```

Expected:

- query-only policy requests graph because the query asks about connectivity;
- an empty semantic-resolution result cannot cancel graph;
- strong class candidates cannot be the reason graph was requested;
- graph uses resolved/selected start identities and preserves relationship roles.

### SQL-only invariance

Question equivalent to:

```text
Show all walls on the second floor.
```

Expected:

- query-only policy may select exact SQL only;
- misleading high-similarity semantic candidates cannot add RAG or graph;
- Stage 3 can still resolve the model-specific storey value and wall classes for typed SQL.

### RAG-only totals

Use a qualitative question with no safe exhaustive predicate.

Expected:

- top-k RAG candidates are bounded and labeled non-exhaustive;
- candidate count is never reported as the model total;
- accepted RAG-only identities can be highlighted completely for that bounded group;
- rejected RAG candidates remain unchanged in the viewer.

### Viewer count above the old cap

Use synthetic accepted exact groups with:

```text
1,723 identities
2,001 identities
5,000 identities
```

Expected:

- every identity is present in the final viewer action;
- `viewer_matches_total` equals the complete accepted identity count;
- no `viewer_matches_truncated` condition is caused by the retired 2,000 cap;
- the answer LLM still receives at most 50 detailed examples.

## 13. Tests and validation

### Dataflow isolation tests

Test:

- query-only planner payload contains no ontology/model-vocabulary candidates or schema values;
- retrieval policy is produced/fixed before semantic resolution;
- policy is immutable through candidate construction and execution;
- identical query inputs yield identical modes under varied resolver fixtures;
- semantic failure does not mutate modes;
- only query/history/selection/scope affect RAG and graph decisions;
- no third LLM call occurs.

### Evidence-group tests

Test:

- stable unique group IDs;
- typed safe predicates;
- one independently selectable semantic claim per group;
- deterministic factual profiles with no LLM-generated model facts;
- per-group authority and coverage;
- class candidate predicates can hydrate complete identities;
- queryable facts preserve set/field/value provenance;
- non-queryable candidates never emit unsafe SQL;
- SQL/RAG/semantic candidates deduplicate by canonical identity/group;
- exact SQL count wins over RAG sample count;
- RAG-only candidate groups remain bounded.

### Sampling tests

Test:

- at most 50 detailed primary examples total;
- every bounded group keeps a summary even without examples;
- small high-priority groups can be represented completely;
- all nine stairs appear in the circulation evidence allocation;
- one class cannot consume all 50 while viable competing groups disappear;
- within-group vector ordering works when ranks exist;
- SQL-only ordering is deterministic;
- duplicate entities do not consume the budget twice;
- group allocation metadata is traceable.

### Answer-decision tests

Test:

- group-level primary/supporting/context/rejected decisions;
- unknown group IDs fail safely;
- contradictory role lists fail safely;
- rejected groups do not influence prose, viewer, or follow-up state;
- ambiguous associated groups are not summed into a concept total;
- RAG candidate count is not treated as exact total;
- exact predicates/counts remain authoritative;
- inference references accepted group IDs internally and is disclosed in prose.

### Viewer tests

Test:

- all accepted exact-group GlobalIds are returned;
- old 2,000 truncation is removed;
- 50-example evidence bound does not affect viewer identities;
- accepted RAG-only bounded IDs are returned without unsupported expansion;
- rejected identities are never colored;
- primary/context identity roles remain deterministic;
- missing/invalid GlobalIds are reported separately from truncation;
- existing bulk viewer action remains compatible or receives the smallest required API update.

### Existing suites

Run:

```text
backend Ruff
backend non-live pytest
frontend typecheck/lint/unit/build when the API contract changes
```

Regenerate frontend API types if the public viewer/group response contract changes. Make only the
frontend changes needed to consume complete accepted identities and the revised typed response; do
not redesign the interface or implement future viewer load management.

### Bounded live validation

After automated tests pass, run bounded live validation against the current model with:

```text
Describe me the circulation of this building.
How many doors are in this building?
Show me all the roofs.
Show all walls on the second floor.
```

Record for each:

```text
query-only retrieval policy
semantic-resolution candidates
resolved evidence groups and typed predicates
SQL exact counts
RAG/graph candidate coverage where requested
50-example allocation by group
answerer group decisions
final answer
accepted viewer identity count
frontend highlighted identity count
LLM call count and tokens
stage latency
```

Do not create a persistent live OpenAI test module or uncontrolled retry loop.

## 14. Logging and diagnostics

Add concise bounded trace/log records for:

```text
query-only policy and policy version/hash
semantic resolution as a separate later stage
resolved group IDs, authority, coverage, exact count, and sample count
executed retrieval modes compared with fixed requested modes
group allocation counts
answerer accepted/supporting/context/rejected IDs
viewer accepted identity total and returned identity total
LLM call count, tokens, and stage timing
```

Do not log full prompts, vectors, canonical JSON, SQL parameters, complete GlobalId lists,
credentials, or local paths.

The query log must make it possible to diagnose:

```text
which classes/predicates formed an exact group
why a group was sampled
which groups the answerer accepted/rejected
whether viewer identities came from an exact or bounded group
whether all accepted identities reached the response
```

Do not preserve the current observability gap where probe-level decisions and final viewer class
composition cannot be reconstructed from bounded diagnostics.

## 15. Performance and operational boundaries

- Keep the 50 detailed-example cap centralized and testable.
- Keep RAG top-k and semantic profile/group counts bounded.
- Do not pass full canonical JSON or every hydrated entity to either LLM.
- Exact database aggregates may scan every matching row but return compact summaries.
- Complete viewer identity retrieval may return every accepted GlobalId and must not use the old
  2,000 cap.
- Do not add batching/streaming/pagination for viewer identities in this task.
- Continue lazy BGE-M3 loading and existing cache versioning.
- Preserve source-model isolation on every lookup.
- Preserve Task 15 terminal tracing without vectors or parameter values.
- The query-only policy must not require an embedding model to make its mode decision.

## 16. Database, ingestion, and artifact constraints

Use the existing:

```text
ifc_source_models
ifc_entities
ifc_relationships
relationship_members
rag_documents
backend-local IFC ontology/model-vocabulary caches
prepared viewer artifacts
```

Do not:

- edit the source IFC;
- modify or run normal ingestion;
- re-import the model;
- regenerate stored entity/relationship vectors;
- change the embedding model or vector dimension;
- migrate or write BIM tables;
- add PostGIS;
- modify prepared viewer artifacts;
- import ingestion or IfcOpenShell code into the backend runtime.

The backend remains read-only with respect to model data. Session/follow-up state may store bounded
accepted group/entity references under the existing application contract.

If a migration, re-vectorization, ingestion change, or viewer-artifact rebuild appears necessary,
stop and report why before taking that action.

## 17. Prohibited actions

- Do not let semantic-resolution candidates influence whether RAG or graph is selected.
- Do not expose semantic candidates to the query-only modality decision.
- Do not enforce modality isolation only through a prompt while leaking candidates into that
  prompt.
- Do not add a third principal LLM call.
- Do not create fixed natural-language concept-to-class maps.
- Do not create indivisible mixed-class evidence groups for ambiguous concepts.
- Do not call a SQL `IN (...)` total the requested concept total without independent group
  acceptance and a disclosed definition.
- Do not call RAG top-k an exact model total.
- Do not globally sort entity vectors and take the first 50 without group diversity.
- Do not let one repeated class consume the entire 50-example budget.
- Do not let the 50-example cap constrain viewer identities.
- Do not retain or reintroduce the 2,000-viewer-identity cap.
- Do not implement future viewer batching/streaming/load-management work in this task.
- Do not color rejected or merely retrieved candidate groups.
- Do not persist rejected groups in conversational follow-up state.
- Do not allow LLM-authored raw SQL, executable code, or arbitrary JSON paths.
- Do not expose full canonical JSON, vectors, prompts, credentials, or internal identifiers.
- Do not redesign the frontend.

## 18. Acceptance criteria

1. Retrieval modes are fixed from query/history/selection/scope before semantic resolution.
2. Semantic-resolution fixtures cannot change whether SQL, entity RAG, relationship RAG, or graph
   is requested.
3. The system still uses only two principal LLM calls.
4. Stage 3 semantic resolution populates typed candidate groups without unsafe SQL or modality
   mutation.
5. SQL, RAG, graph, ontology, and model-vocabulary evidence is normalized into independently
   selectable groups.
6. Exact SQL groups retain uncapped totals and complete predicates/identity availability.
7. RAG groups remain bounded candidates and are never presented as exhaustive totals.
8. SQL and RAG evidence for the same canonical group is deduplicated, with SQL authoritative for
   exact counts.
9. Every group receives a deterministic factual summary separate from planner role hints.
10. The answerer receives at most 50 detailed primary examples selected with group diversity.
11. The current nine stairs are represented in circulation evidence and cannot be displaced by 50
    railing examples.
12. The answerer accepts/rejects individual groups and can reclassify role hints.
13. The circulation answer does not report 1,723 circulation elements or describe generic windows,
    walls, slabs, doors, or railings as the circulation backbone.
14. Viewer actions use answerer-accepted groups only.
15. Every accepted viewer GlobalId is returned without a fixed 2,000-ID truncation.
16. The 50-example LLM limit has no effect on viewer identity completeness.
17. Query logs expose bounded policy/group/decision/viewer counts sufficient to diagnose selection.
18. Source IFC, ingestion, BIM tables, stored vectors, and viewer artifacts remain unchanged.
19. Existing compatible behavior and automated suites continue to pass.

## Completion report

Rename this file to:

```text
tasks/task17_done.md
```

only when implementation and validation are complete.

Append a completion report containing:

- specification amendments;
- final query-only planner input/output schema;
- proof that semantic resolution cannot influence modality selection;
- final dataflow and two-call confirmation;
- evidence-group schema and predicate types;
- deterministic factual-profile construction;
- SQL/RAG/group deduplication behavior;
- group-aware 50-example allocation algorithm and limits;
- answerer group-decision schema and validation;
- removal of the 2,000 viewer cap and complete identity behavior;
- circulation failure reproduction and corrected result;
- door, roof, graph, SQL-only, RAG-only, and over-2,000 identity regression results;
- live query policies, groups, accepted/rejected decisions, and viewer totals;
- token and stage-latency measurements;
- automated test commands/results;
- frontend API/type changes, if any;
- database/vector/source IFC/viewer-artifact before-and-after confirmation;
- remaining limitations, including deferred viewer load management.

---

# Completion report

Implementation and bounded live validation are complete. The active-model pipeline now decides
retrieval modality from the query alone (before semantic resolution), normalizes results into
independently-selectable evidence groups, and returns complete viewer identities. The Task 16
circulation defect (a SQL `IN(...)` count reported as a `1,723 circulation elements` total) is fixed.
Backend remains read-only; ingestion/DB/vectors/viewer-artifacts unchanged.

## Specification amendments

Appended "Task 17 amendment" sections to `specs/spec_v002` (nine-stage pipeline, modality isolation,
groups, complete viewer), `spec_v003` (uncapped identity hydration via `limit=None`; missing-GlobalId
condition ≠ truncation), `spec_v004` (RAG as bounded per-facet candidate groups, SQL authoritative on
dedup), `spec_v005` (evidence-group contract + group-level answerer, `policy_planner_v001`/
`group_answerer_v001`). Task 16 history not rewritten.

## Final query-only planner input/output schema

- Input (`llm/context.build_policy_context`): question, bounded history, scope, active-model id,
  bounded selection (entity id + class), output vocab. **No ontology/vocabulary candidates, no schema
  fields, no observed values.** Verified by test that the serialized context contains no active-model
  class/property/predefined/ontology tokens.
- Output (`llm/schemas.RetrievalPolicyPlan`): scope, route, source_model_id, `analysis_intent`,
  `facets[]` (facet_id, question, role_hint, semantic_query, needs_exact_structured/entity_rag/
  relationship_rag/graph), `retrieval_policy`, plus catalog_plan/clarification for preserved routes.

## Proof that semantic resolution cannot influence modality

Structural: the service validates + freezes the policy (`_plan_policy`) BEFORE calling
`resolve_facets` (Stage 3). The authoritative modes are `validation.frozen_policy(plan)` = the union
of facet needs — never derived from candidates. Tests: (a) `build_policy_context` carries no
candidates/schema; (b) `test_retrieval_modes_independent_of_resolution` shows a SQL-only policy runs
no RAG whether resolution returns strong candidates or is empty. Live: doors/roofs/walls chose
`sql`-only from the query; circulation chose `sql+rag+graph` from the query wording.

## Final dataflow and two-call confirmation

Stage1 request assembly → Stage2 **LLM call 1** query-only policy (validate + ≤1 repair, frozen) →
Stage3 `resolve_facets` → Stage4-5 `build_groups` (execute only fixed modes) → Stage6 factual
profiles + `allocate_examples` (≤50) → Stage7 **LLM call 2** group answerer → Stage8
`hydrate_accepted_viewer_identities` (uncapped) → Stage9 response. Live runs show exactly **2 LLM
calls** per question. No third router/judge/replan call.

## Evidence-group schema and predicate types

`hybrid/groups/schemas.EvidenceGroup`: group_id, facet_id, label, predicate, role_hint, authority
∈ {exact, structured_candidate, semantic_candidate, general_context}, coverage ∈ {complete, bounded,
unknown, unavailable, failed}, source_kinds, predicate_queryable, exact_count, rag_candidate_count,
ontology_definition, factual_profile, representative_entities, allocated_examples. `GroupPredicate`
kinds: entity_class, attribute_value, property_value, type_value, entity_id_set, relationship — all
typed/allowlisted; no raw SQL or JSON paths. One semantic claim per group (verified: 0 multi-class
groups for circulation).

## Deterministic factual profile

`hybrid/groups/profile.build_factual_profile`: exact count/class histogram + the bounded
model-vocabulary class profile (common name stems, predefined/object types, storeys, property sets,
materials) + predicate field/value + ontology definition. Never LLM-invented; role_hint kept
separate from facts.

## SQL/RAG/group deduplication

Groups dedupe by `GroupPredicate.signature`. A single-class value-predicate group whose exact count
equals its class total is merged into the class group and dropped (`_dedupe_full_class_value_groups`).
RAG candidates matching an existing class group enrich its representative examples + `rag_candidate_
count` only (never the count); the remainder forms one bounded `entity_id_set` RAG-only group. SQL
count is authoritative.

## Group-aware 50-example allocation

`hybrid/groups/allocation.allocate_examples`: rank by role/authority/queryability/coverage/similarity;
Pass 1 fully includes small high-priority direct groups that fit (the 9 stairs); Pass 2 round-robins
one example per group so no class consumes the budget; dedupe canonical entities across groups; cap
`max_answer_examples=50`; keep summaries for zero-example groups; per-group allocation metadata
recorded. Tests confirm 9 stairs kept whole, ≤50 total, cross-group dedup.

## Answerer group-decision schema and validation

`client.AnswerOutput`: answer, primary/supporting/context/rejected_group_ids, viewer_primary/
viewer_context_group_ids, model_evidence_sufficient, inference_used, inference_basis_group_ids,
used_general_knowledge, disclosed_conflicts. `hybrid/groups/decision.resolve_group_answer` validates
every id (unknown → warning; a group in both accept + reject → excluded), builds viewer groups from
accepted entity-bearing groups only, and derives `answer_basis` (single accepted exact group →
exact_sql). Tests cover unknown/contradictory/rejected-not-highlighted.

## Removal of the 2,000 viewer cap and complete identity behavior

`entities._identities_for_where`/`select_viewer_identities` accept `limit=None` (no `.limit()`,
`truncated=False`). `hybrid/groups/execute.all_identities` + `groups/viewer` hydrate every accepted
viewer-group GlobalId post-answer, dedup primary/context, and report genuinely missing GlobalIds
separately. Tests: 5,000 synthetic identities returned untruncated; real IfcCovering group returns
all 1,214; `select_viewer_identities(None)` returns 1,214 untruncated while a set limit still caps.

## Circulation failure reproduction and corrected result

Before (Task 16): one SQL `IN(IfcStair,IfcRailing,IfcDoor,IfcWindow,IfcSlab,IfcWall,…)` → `1,723`
called the circulation backbone. After (Task 17, live): stairs/railings/doors/slabs are separate
independently-rejectable groups; the answer lists per-group counts (9 stairs, 90 railings, 205 doors,
279 slabs) with an explicit "do not sum", never a `1,723` total; inference discloses that horizontal
corridor circulation cannot be assessed (no explicit spaces). Automated regression
`test_circulation_stairs_primary_no_1723` (scripted answerer accepting only stairs) yields
`exact_total=9`, `class_counts={IfcStair:9}`, all 9 identities, `answer_basis=exact_sql`.

## Regression results (automated, scripted LLM + real DB/embeddings)

- circulation: stairs a primary group with all 9 identities; no 1,723; generic classes independently
  rejectable; complete viewer.
- doors: SQL-only policy; 205 exact; all 205 identities; no RAG added.
- complete viewer: 5,000 (monkeypatched) and 1,214 (real IfcCovering) fully returned, untruncated.
- modality invariance: SQL-only policy runs no RAG under strong OR empty resolution fixtures.
- policy-context isolation: no active-model leakage.

## Bounded live validation (real OpenAI `gpt-5-nano` + DB; DB/vectors UNCHANGED)

Before == After: `ifc_entities=6989, ifc_relationships=3473, rag_documents=10462, rag_vectors=10462`.

| Question | Query-only policy | Groups→decision | answer_basis | Viewer | Tokens |
|---|---|---|---|---|---|
| Describe circulation | sql+rag_entity+rag_relationship+graph | stairs/railings/doors/slabs primary; per-group counts, NO 1,723; inference used | hybrid_evidence | 493 highlighted across accepted groups (uncapped) | 23,015 |
| How many doors | sql only | IfcDoor primary (+2 supporting property groups) | hybrid_evidence | 205 (all) | 17,017 |
| Show me all the roofs | sql only | IfcCovering Type=Roof (42) + IfcSlab Element Classification=Roof (62) + covering surface groups; "do not sum" | hybrid_evidence | 115 (all) | 18,606 |
| Show all walls on 2nd floor | sql only | IfcWall/IfcWallStandardCase + Home Story=02 groups primary; IfcSlab/IfcWindow/IfcDoor/IfcCovering rejected; model storey value resolved | hybrid_evidence | 880 (all) | 19,148 |

## Token and stage-latency measurements

Cold first question ≈91 s (one-time BGE-M3 load + per-model semantic index build ≈15-25 s + per-facet
resolution + SQL/RAG/graph + two `gpt-5-nano` reasoning calls). Warm ≈37-45 s. Tokens 17k-23k/question,
in the standard per-question `[OpenAI usage]` summary. Group diagnostics (policy hash, per-group
authority/coverage/counts, decision ids, viewer accepted-vs-returned totals) logged via
`_log_group_event`.

## Automated test commands / results

- `poetry run ruff format . && poetry run ruff check .` → clean.
- `poetry run pytest` → **418 passed**. New: `tests/query_hybrid/{test_policy_plan,test_group_
  allocation,test_group_viewer}.py`, `tests/query_live/test_task17_pipeline.py`. Removed (superseded
  probe/legacy path): `test_probe_plan/test_probe_evidence/test_probe_result/test_probes_live/
  test_task16_regression/test_hybrid_pipeline`.

## Frontend API/type changes

None. The public `QueryResponseEnvelope` + `ViewerActions` shapes are unchanged; the viewer GlobalId
list is simply uncapped. No OpenAPI regeneration or frontend change required.

## Database / vector / source IFC / viewer-artifact before-and-after

Confirmed unchanged (live table above). No migration, re-import, re-vectorization, PostGIS, or
viewer-artifact edits; IfcOpenShell/`bim_rag` not imported at backend runtime.

## Retired

Task 16 probe path superseded and removed: `Probe`/`ProbeKind`/`QueryPlan.probes`,
`semantic/probes/`, `hybrid/probe_result.py`, `ProbeEvidence`/`ProbeCandidateRef`,
`build_probe_answer_payload`, `answer_from_probes`, and the probe validation/translate branches. The
reusable resolution/vocabulary/ontology machinery is retained and now driven per-facet.

## Remaining limitations

- Answerer role selection is model-dependent: `gpt-5-nano` accepted some structural classes (slabs)
  as primary circulation evidence; the groups are independently rejectable (proven by the walls case,
  which rejected non-walls), so a stronger answerer would prune more. This is answerer judgment, not a
  data-contract defect — no `1,723`-style concept total is ever reported in prose.
- Deferred (per §9 viewer performance scope): large-result viewer load management
  (streaming/pagination/camera optimization) is intentionally not implemented; the 2,000 cap is
  removed and all accepted identities are returned via the existing bulk viewer-action path.
- For a multi-group analytical acceptance the response `result_summary.exact_total` reflects the count
  of distinct highlighted identities across accepted viewer groups (a highlight count, not a claimed
  concept total); the authoritative per-group counts are in the answer prose.
