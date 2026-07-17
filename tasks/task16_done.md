# Task 16: Universal Hybrid Semantic Evidence Pipeline for Ambiguous BIM Questions

## Prerequisites and authority

Require:

```text
tasks/task09_done.md
tasks/task13_done.md
tasks/task15_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

This task is a backend query-architecture change. Preserve the independent application boundary:

```text
ingestion/   # owns IFC parsing, canonical BIM import, and stored corpus vectors
backend/     # owns read-only query interpretation, retrieval, orchestration, and answers
frontend/    # consumes the existing typed API and viewer actions
```

The requirements in this task amend the older v004/v005 behavior where they conflict:

- active-model questions are no longer forced into one exclusive `sql`, `rag`, or `graph` route;
- a hard RAG similarity threshold no longer decides whether evidence is relevant;
- the backend may execute multiple bounded evidence probes for one question;
- retrieved SQL/RAG/graph results are candidate references that the answer LLM may accept or reject;
- clarification is attempted only after semantic discovery and safe model inspection cannot produce
  a useful answer.

Update the relevant specifications with a concise Task 16 architecture amendment rather than
silently leaving contradictory requirements in place. Do not rewrite completed task history.

## Owner intent

The owner’s intended mental model is:

> If the complete BIM database could fit into an LLM context, the LLM could inspect it and decide
> what matters. The database is too large, so SQL, semantic retrieval, and graph traversal exist to
> reduce it to a bounded set of potentially useful references. The final LLM then determines which
> references actually answer the question and may conclude that none of them are relevant.

The system must become more helpful with ambiguous natural-language BIM questions without requiring
users to know IFC class names, property-set names, schema conventions, or exporter-specific
representations.

Examples motivating this task:

```text
show me all the roofs
how is the circulation like in this building
what is the total corridor area
show opening-related objects
describe the building's exterior enclosure
```

The system must not solve these by a manually gated synonym dictionary such as:

```text
IfcDoor = door, gate, opening
circulation = corridor + stair + ramp + elevator
```

Such lists are incomplete, confuse related concepts with equivalent concepts, and cannot cover
different exporters, languages, schemas, or future questions.

Instead, use:

1. a versioned IFC schema ontology;
2. a model-specific semantic vocabulary derived from the actual database;
3. LLM-generated, bounded retrieval probes;
4. deterministic SQL/graph verification where possible;
5. threshold-free top-k semantic retrieval;
6. an answer LLM that explicitly judges relevance, evidence strength, limitations, and inference.

## Objective

Replace the current exclusive-route planner with a universal hybrid evidence pipeline that:

1. semantically resolves every conversational active-model question covered by this pipeline
   against IFC schema knowledge and the active model’s observed vocabulary before planning;
2. lets one planner call dynamically decompose ambiguous questions into bounded evidence probes;
3. supports zero or more SQL, model-vocabulary, entity-RAG, relationship-RAG, and graph probes;
4. treats every retrieved result as a candidate reference rather than mandatory answer evidence;
5. removes hard RAG acceptance thresholds while retaining ranks/similarities internally;
6. lets the final answer call accept or reject probe results through structured output;
7. permits cautious model-specific inference when supported by evidence and clearly disclosed;
8. distinguishes exact zero, absent representation, semantic non-relevance, missing data, and
   retrieval failure;
9. avoids asking users to supply IFC classes or property names;
10. remains read-only with respect to BIM tables, stored vectors, source IFCs, and viewer artifacts.

Keep two principal OpenAI calls:

```text
LLM call 1: planner/analyzer
Backend: execute bounded probes
LLM call 2: evidence judge and answer writer
```

Do not add a third routing or relevance-judge call in this task.

## 1. Meaning of “universal hybrid”

For conversational active-model questions covered by this pipeline, semantic resolution is always
present and the LLM-facing route is hybrid evidence analysis.

This does **not** mean every question must execute full SQL, entity RAG, relationship RAG, and graph
searches.

Examples:

```text
How many doors are there?
→ semantic resolution identifies IfcDoor
→ one exact SQL probe may be sufficient

Show me the roofs.
→ ontology/model-vocabulary discovery
→ structured verification over model-specific classes/properties
→ optional entity RAG for supporting candidates

How is circulation organized?
→ several independently purposed SQL, vocabulary, RAG, and graph probes
```

Preserve these exceptions:

- pure general IFC/BIM explanations may still use `explain_general`;
- model-catalog questions may retain the existing bounded catalog path;
- genuinely unresolved questions may use `clarify`, but only under Section 10;
- deterministic component detail/group endpoints remain unchanged and do not use this pipeline.

For API compatibility, the existing `hybrid` route value may represent the universal active-model
pipeline. Do not require a frontend redesign or introduce a new public route value unless there is
a demonstrated contract need.

The answer basis remains evidence-dependent. A hybrid-routed question whose accepted evidence is
only one exact SQL count may still report `answer_basis=exact_sql`.

## 2. Static versioned IFC ontology

Create a backend-owned, machine-readable ontology resource for IFC schema entities. The
authoritative resource must be JSON, not a Python dictionary embedded in prompt code.

Recommended location:

```text
backend/app/query/semantic/ontology/
├── IFC2X3.json
├── schema.py
├── loader.py
└── generated/
    └── IFC2X3_bge_m3_v001.*
```

Exact organization may vary, but the JSON must remain the human-inspectable source of truth and
derived embedding data must remain clearly replaceable.

### IFC2X3 scope

The current model declares `IFC2X3`. Populate the complete `IfcRoot` hierarchy for IFC2X3 TC1:

```text
IfcRoot
├── IfcObjectDefinition
├── IfcPropertyDefinition
└── IfcRelationship
```

The expected hierarchy contains:

```text
301 entity declarations including IfcRoot
300 descendants of IfcRoot
233 declarations in the IfcObjectDefinition branch, including IfcObjectDefinition
17 declarations in the IfcPropertyDefinition branch, including IfcPropertyDefinition
50 declarations in the IfcRelationship branch, including IfcRelationship
```

Include abstract parent classes and concrete leaf classes. This task does not require resource
entities outside `IfcRoot`, such as low-level geometry, profiles, points, or scalar property-value
entities.

For scope clarity, the authoritative IFC2X3 TC1 EXPRESS schema contains 653 entity declarations in
total. This task intentionally maps the 301 declarations in the `IfcRoot` hierarchy, not the other
352 resource/support declarations. The format must still avoid assumptions that prevent those
resources or other schema versions from being added later if a future task needs them.

Build the resource format so IFC4/IFC4X3 files can be added as separate versioned resources later.
Do not copy IFC2X3 inheritance or predefined-type assumptions into another schema. If an active
model uses an ontology version not yet bundled, degrade truthfully to its observed model vocabulary
and exact schema catalog; do not pretend IFC2X3 is compatible.

### Required ontology fields

Each entity profile must contain enough schema-grounded information for semantic retrieval:

```json
{
  "ifc_class": "IfcSlab",
  "label": "Slab",
  "short_definition": "A planar building element that may function as a floor, roof slab, or landing.",
  "immediate_parent": "IfcBuildingElement",
  "ancestors": [
    "IfcBuildingElement",
    "IfcElement",
    "IfcProduct",
    "IfcObject",
    "IfcObjectDefinition",
    "IfcRoot"
  ],
  "abstract": false,
  "predefined_types": ["FLOOR", "ROOF", "LANDING", "BASESLAB", "USERDEFINED", "NOTDEFINED"],
  "direct_attributes": [],
  "schema": "IFC2X3"
}
```

Use schema-accurate fields. The example is illustrative and must not override the official
IFC2X3 declaration.

The ontology may include a short definition because it improves retrieval grounding and
reproducibility. It is not intended to replace the LLM’s general BIM knowledge. When an official
short description is unavailable, build a useful semantic profile from class label, hierarchy,
attributes, children, and predefined-type literals rather than inventing synonyms.

### No manual synonym gate

Do not add an exhaustive or access-controlling alias list:

```json
{
  "IfcDoor": ["door", "gate", "opening"]
}
```

Do not require user wording to match an ontology label before the class can be considered. Class
profiles are searched semantically.

Exact normalized class-name recognition may remain as a high-confidence shortcut, but it must not
be the only resolver.

### Ontology generation and indexing

Provide a deterministic development/build utility that:

- derives inheritance, abstract/concrete status, attributes, and predefined types from an
  authoritative IFC2X3 schema source;
- records source/release/version metadata and a content hash;
- validates the expected 301-class `IfcRoot` hierarchy;
- produces deterministic semantic profile text;
- produces a local BGE-M3-compatible semantic index or cache;
- makes no OpenAI/LLM call;
- is not required to access the network during normal backend startup or queries.

The ontology JSON is authoritative. A generated embedding artifact may be committed or built by an
explicit development command, but the backend must not re-embed all ontology documents on every
question.

## 3. Dynamic active-model vocabulary

Build a bounded, read-only semantic vocabulary from the actual database for each source model.
This is how the system learns exporter-specific and multilingual representations without a manual
dictionary.

Cache it by at least:

```text
source_model_id
file_fingerprint
extraction/template version relevant to the profile
profile-builder version
embedding model/version
```

The cache may be process memory or another backend-local derived cache. It must not mutate BIM
tables or stored corpus vectors. Do not require re-ingestion or a database migration in this task.

### Model profile types

Generate deterministic, bounded profiles from existing structured data.

#### Class profiles

One profile per observed entity/relationship class, including:

- exact IFC class;
- exact instance count;
- ontology parent/ancestor information when available;
- bounded representative normalized names;
- descriptions and object types when present;
- predefined-type values and counts;
- explicit type names/predefined types;
- material names;
- classifications;
- storey names;
- property-set and quantity-set names;
- important textual field/value summaries;
- relationship endpoint role/class summaries for relationship classes.

#### Observed fact profiles

Create separately searchable facts so minority meanings are not hidden inside a large class
profile. Examples:

```text
IfcCovering | property Type | value Roof | occurrence count
IfcSlab | name stem | plat dak | occurrence count
IfcDoor | name stem | liftdeur | occurrence count
IfcDoor | property Egress Dimensions | field coverage
IfcSpace | quantity NetFloorArea | field coverage
```

Every fact must preserve exact provenance:

```text
ifc_class
fact kind
attribute/property/quantity/type/classification source
set name when applicable
field name
observed value or normalized value stem
occurrence count
queryable typed field reference when available
```

Normalize for aggregation without destroying the original evidence. For example, exporter suffixes
such as `_(#755216)` may be stripped from a separate normalized name stem while the original name
remains available.

Exclude or strongly bound low-value noise:

- GlobalIds and GUID-like values;
- STEP IDs;
- empty strings;
- long opaque identifiers;
- raw geometry data;
- full canonical JSON;
- unbounded unique numeric/property values;
- secrets or filesystem metadata.

Retain multilingual semantic values. The current IFC contains Dutch terms such as `dak`,
`plat dak`, `trap`, and `liftdeur`; do not translate or discard them before multilingual semantic
embedding.

#### Quantity/coverage profiles

Expose quantity and dimension availability as semantic profile evidence:

```text
field name
set name
applicable classes
populated count
missing count
unit/normalization availability
```

This lets the planner discover whether concepts such as area, width, height, or volume are
calculable without asking the user for IFC field names.

### Bounds

Centralize limits and keep profile generation deterministic. Initial upper bounds:

```text
maximum observed values per class/field profile: 20
maximum representative original examples per profile: 5
maximum active-model semantic profiles sent to one planner call: 30 total
maximum characters per profile excerpt: 500
```

The internal cached vocabulary may be larger, but never pass the entire vocabulary or database to
the LLM.

If better measured limits are selected, document and test them. Do not silently sample without a
stable sort and occurrence counts.

### Embeddings

Extend the backend-owned embedding service with a bounded batch document-embedding operation for
ontology/model-profile indexing. Preserve:

```text
BAAI/bge-m3
1024 dimensions
L2 normalization
cosine comparison
```

Do not import ingestion embedding code. Do not persist query vectors. Do not rebuild model-profile
embeddings per question.

## 4. Pre-planner semantic resolution

Before LLM call 1, search the following with the user’s actual question plus bounded relevant
history/selection context:

```text
IFC ontology profiles
active-model class profiles
active-model observed fact profiles
active-model quantity/coverage profiles
```

Return top-k candidates regardless of a hard similarity cutoff.

The planner context must receive bounded, structured candidates such as:

```json
{
  "semantic_resolution": {
    "ontology_candidates": [
      {
        "ifc_class": "IfcRoof",
        "schema": "IFC2X3",
        "present_in_model": false,
        "exact_model_count": 0,
        "profile_excerpt": "..."
      },
      {
        "ifc_class": "IfcSlab",
        "present_in_model": true,
        "exact_model_count": 279,
        "predefined_types": ["ROOF", "FLOOR", "..."],
        "profile_excerpt": "..."
      }
    ],
    "model_fact_candidates": [
      {
        "ifc_class": "IfcCovering",
        "source": "property",
        "set_name": "SynchroResourceProperty",
        "field_name": "[ArchiCADProperties]Type",
        "observed_value": "Roof",
        "occurrence_count": 165,
        "queryable": true
      }
    ]
  }
}
```

The example illustrates the required shape, not a hard-coded roof rule.

Similarity/rank may remain available internally and in trace/evaluation output, but normal planner
context should emphasize semantic content, exact presence/count, and provenance rather than
encouraging the LLM to treat a score as truth.

Semantic resolution is advisory:

- it does not automatically accept a class;
- it does not block classes absent from a synonym list;
- it does not assert that top-1 is relevant;
- it does not substitute approximate names for canonical identities;
- it gives the planner a bounded view of how IFC and the active model may represent the concept.

## 5. Universal hybrid probe plan

Replace the active-model planner’s single `sql_plan`/`rag_plan`/`graph_plan` choice with a bounded
array of typed probes. Existing typed SQL/RAG/graph executors should be reused behind the probe
layer where practical.

An equivalent planner shape is:

```json
{
  "scope": "active_model",
  "route": "hybrid",
  "source_model_id": 1,
  "analysis_intent": "Assess how circulation is represented in this building",
  "probes": [
    {
      "probe_id": "vertical-elements",
      "kind": "sql",
      "purpose": "Find exact counts of explicitly modeled vertical circulation elements",
      "facet": "vertical circulation",
      "sql_plan": {}
    },
    {
      "probe_id": "movement-vocabulary",
      "kind": "model_vocabulary",
      "purpose": "Find model-specific classes, names, fields, and values related to movement",
      "facet": "model representation",
      "semantic_query": "spaces and elements used for movement through the building"
    },
    {
      "probe_id": "circulation-entities",
      "kind": "rag_entity",
      "purpose": "Retrieve entity candidates that may provide qualitative circulation evidence",
      "facet": "circulation components",
      "semantic_query": "building circulation paths and vertical or horizontal movement"
    }
  ],
  "needs_clarification": false,
  "clarification_question": null,
  "viewer_intent": "select_and_fit"
}
```

### Probe kinds

Support:

```text
sql
model_vocabulary
ontology
rag_entity
rag_relationship
graph
```

Ontology and model-vocabulary probes may perform more focused searches than the pre-planner
resolution when the planner dynamically decomposes the question into facets.

Every probe must include:

- a unique bounded `probe_id`;
- a concise `purpose`;
- the question `facet` it investigates;
- one typed, allowlisted plan appropriate to its kind;
- explicit source model;
- bounded result limits;
- optional dependency metadata only when genuinely required.

Do not allow raw SQL, arbitrary JSON paths, unbounded Boolean logic, or free-form executable code.

### Probe limits

Initial maximums:

```text
maximum probes per question: 10
maximum SQL probes: 4
maximum ontology/model-vocabulary semantic probes: 4 combined
maximum entity/relationship RAG probes: 4 combined
maximum graph probes: 2
```

The total limit remains authoritative even when per-kind maxima overlap. Centralize the limits and
validate them before execution.

The planner must use the fewest probes that can reasonably answer the question. A simple exact
question must not run expensive RAG searches merely to satisfy the word “hybrid.”

### Dynamic decomposition, not fixed recipes

The planner may use its BIM knowledge to decompose:

```text
circulation
façade construction
accessibility
fire separation
structural system
roof construction
```

into likely observable facets. Do not hard-code global mappings such as:

```text
circulation = stairs + elevators + corridors + ramps
```

The LLM may propose those as context-dependent probes, but they are not mandatory vocabulary rules
and may be supplemented or rejected based on the model and question.

## 6. Probe execution and automatic structured verification

Execute independent probes concurrently within bounded timeouts. Preserve dependency ordering only
when one probe genuinely consumes another probe’s candidate identities.

One failed probe must not make successful probes appear empty. Record partial failures explicitly.

### SQL probes

Use existing typed SQL operations and exact source-model scoping. SQL provides:

- exact counts;
- exact filters;
- exact aggregates when field coverage and units permit;
- exact class absence/presence;
- deterministic identities for viewer highlighting;
- exact missing-value and coverage facts.

SQL output is still only relevant if it addresses the probe purpose. The answer LLM may reject an
exact SQL result as irrelevant to the user’s question.

### Ontology/model-vocabulary probes

Return top semantic candidates with exact provenance and active-model presence/count.

When a model fact contains a safe queryable predicate, automatically verify it against structured
data before the answer call. For example:

```text
semantic candidate:
IfcCovering / property Type / value Roof

automatic structured verification:
exact matching entity count
bounded matching identities
class histogram
field/value provenance
```

Automatic verification does not mean the candidate is accepted as relevant. It only upgrades the
candidate from an unverified phrase to a precisely described model fact that the answerer can
judge.

Support verification of:

- exact class presence/count;
- normalized name/object/type text;
- exact or case-insensitive property values;
- property/quantity field coverage;
- deterministic matching identities;
- exact aggregate only when the requested numeric field and units are valid and unambiguous.

Do not generate unsafe fuzzy SQL over arbitrary canonical JSON.

### Entity and relationship RAG probes

Search the existing stored entity and relationship documents independently. Return top-k
candidates even when every similarity is below the old threshold.

Hydrate candidates from structured tables. Preserve:

- canonical identity;
- IFC class;
- name/summary;
- source kind/document kind;
- per-kind rank;
- similarity internally;
- bounded relevant document excerpt;
- relationship endpoints where requested.

Do not claim that top-k is exhaustive or relevant merely because it was returned.

### Graph probes

Graph traversal remains deterministic and relationship-class/role aware. Preserve direct endpoint
roles and path provenance. Graph evidence is exact for the traversed stored relationships, but its
relevance to the natural-language question remains for the answerer to judge.

### No forced set combination

The current hybrid implementation emphasizes intersection/union of one SQL and one RAG entity set.
Retain those operations for questions that truly require them, but add an independent evidence
group mode:

```text
independent_evidence_groups
```

Analytical questions such as circulation must be able to preserve:

```text
stair count
space/class absence
lift-related names
egress property coverage
semantic relationship candidates
```

without forcing all evidence into one canonical-ID intersection or union.

## 7. Remove hard RAG acceptance thresholds

Amend v004 and the implementation:

- remove `minimum_similarity_profile`/`threshold_profile` as an acceptance gate from new planner
  and execution contracts;
- retrieve a bounded top-k for every enabled semantic probe;
- keep similarity and rank internal for ordering, diagnostics, and evaluation;
- do not set `sufficient_evidence=false` only because a score is below 0.50/0.55;
- do not discard all candidates before the answer LLM sees their bounded evidence;
- do not silently label top-k candidates as relevant.

Old threshold profiles may remain temporarily for backward-compatible tests or diagnostics, but
they must not control the new pipeline’s factual evidence inclusion.

Replace threshold concepts such as:

```text
passed_threshold
sufficient_evidence
no candidate passed threshold
```

with candidate/relevance concepts such as:

```text
retrieved_candidate
rank
candidate_evidence
accepted_by_answerer
rejected_by_answerer
```

The answerer may reject every top-k result and state that the model contains no useful evidence for
the question.

## 8. Probe-aware evidence package

Build one bounded evidence package with separately labeled probe outputs. Do not flatten all
results into one undifferentiated entity list before the answer call.

Each probe evidence record must contain an equivalent of:

```json
{
  "probe_id": "vertical-elements",
  "purpose": "Find vertical circulation evidence",
  "facet": "vertical circulation",
  "source": "sql",
  "authority": "exact",
  "coverage": "complete",
  "result_summary": {},
  "primary_entities": [],
  "context_entities": [],
  "relationships": [],
  "warnings": [],
  "partial_failure": null
}
```

### Authority

Use a small typed vocabulary:

```text
exact
structured_candidate
semantic_candidate
general_context
```

Examples:

- exact SQL count: `exact`;
- exact stored graph relationship/path: `exact`;
- exact verification of a semantically discovered property value:
  `structured_candidate` until the answerer judges conceptual relevance;
- entity RAG result: `semantic_candidate`;
- ontology definition: `general_context`.

### Coverage

Use:

```text
complete
bounded
unknown
unavailable
failed
```

Do not represent these conditions as equivalent:

```text
exact SQL count = 0
IFC class absent from model
field absent from model
top-k semantic candidates all judged irrelevant
semantic service failed
query returned a bounded sample
information is not explicitly represented
```

### Global bounds

Preserve separate limits for:

```text
exact database counts: uncapped
viewer match identities: 2,000
answer-LLM entity evidence: 50 primary + 50 context
answer-LLM relationships: 20
```

Also cap:

```text
semantic candidates per probe: default 10, maximum 20
probe evidence summaries sent to the answerer: maximum 10
document/profile excerpt: maximum 500 characters
```

When aggregate evidence exceeds global bounds, summarize deterministically by probe, class, field,
and count. Do not let an early probe consume the entire context budget.

## 9. Answerer as relevance judge

LLM call 2 must receive all bounded probe evidence as candidate references and return structured
relevance decisions alongside the user-facing answer.

Extend the answer output with an equivalent of:

```json
{
  "answer": "...",
  "used_probe_ids": ["vertical-elements", "movement-vocabulary"],
  "rejected_probe_ids": ["unrelated-coverings"],
  "viewer_probe_ids": ["vertical-elements"],
  "model_evidence_sufficient": true,
  "inference_used": true,
  "inference_basis_probe_ids": ["vertical-elements", "movement-vocabulary"],
  "used_general_knowledge": true,
  "disclosed_conflicts": false
}
```

Validate returned probe IDs against the executed evidence package. Unknown IDs must not affect
state or viewer actions. Fail safely with a bounded warning rather than accepting invented probe
references.

### Relevance rules

The answerer must:

- use a probe only when its result supports that probe’s purpose and the user’s question;
- be allowed to reject exact SQL that is technically correct but conceptually irrelevant;
- be allowed to reject every RAG result;
- prioritize exact structured facts for counts and measured values;
- treat ontology/model-vocabulary/RAG results as candidate interpretations unless structurally
  verified;
- never treat raw similarity as probability or truth;
- never use the number of retrieved candidates as the number of relevant objects;
- disclose incomplete coverage and representation gaps;
- distinguish “not explicitly represented” from “does not exist in the building”;
- avoid exposing probe IDs, scores, raw SQL, plan JSON, or internal database IDs to the user.

### Inference

Permit bounded model-specific inference when:

1. the inference is supported by accepted probes;
2. it does not contradict exact evidence;
3. it is phrased as an inference rather than a measured fact;
4. its limitations are stated when material.

Example style:

> Vertical circulation is explicitly represented by nine stairs. Horizontal circulation cannot be
> assessed reliably because the model has no explicit space objects for corridors or lobbies.
> Lift-related door names suggest lift access, but the model does not explicitly represent elevator
> equipment, so that conclusion is incomplete.

Do not say:

> There is no elevator.

when the evidence only shows no explicit `IfcTransportElement`.

### General knowledge

General BIM knowledge may help interpret accepted model evidence, but it must not create
model-specific objects, counts, relationships, or measurements.

### Viewer actions after relevance judgment

Build final viewer highlights from `viewer_probe_ids`/accepted entity-bearing probes after the
answerer’s structured relevance judgment. Do not highlight rejected semantic candidates merely
because vector search returned them.

Apply the existing deterministic identity limits and role semantics. Store accepted result
identities—not every raw candidate—in conversational follow-up state.

## 10. Clarification policy

Clarification becomes the last resort, not the first response to model vocabulary uncertainty.

Before asking the user, the pipeline must attempt as applicable:

1. IFC ontology resolution;
2. active-model class/fact/quantity vocabulary search;
3. safe SQL presence and coverage probes;
4. top-k entity/relationship RAG;
5. graph evidence when connectivity is relevant.

Ask one concise clarification only when:

- materially different interpretations remain plausible after inspection;
- choosing among them would materially change the result; and
- the database cannot support a truthful bounded answer or limitation statement without the
  user’s intended convention.

Never ask the user to provide:

```text
an IFC entity class
a property-set name
a quantity-set name
a database field
an IFC schema path
```

For:

```text
what is the total corridor area
```

the preferred behavior is to inspect whether corridor-like spaces/classifications and usable area
quantities exist. If the model does not explicitly represent them, answer:

> A reliable corridor-area total is not available from this model because corridor spaces and
> usable corridor area quantities are not explicitly represented.

Do not ask the user whether to use `IfcSpace` unless multiple actual model representations were
found and a user convention is genuinely required.

## 11. Planner and answer prompt changes

Version both prompts. Do not silently mutate v001 text while logging the old version.

The planner prompt must explain:

- universal active-model hybrid evidence analysis;
- semantic resolution candidates are suggestions, not facts;
- dynamically decompose ambiguous questions;
- create the fewest useful probes;
- prefer exact verification when a semantic candidate exposes a queryable class/field/value;
- do not stop after one guessed class returns zero;
- do not demand IFC vocabulary from users;
- do not hard-code concept recipes;
- do not run expensive probes that add no plausible value.

The answerer prompt must explain:

- all probe outputs are references, not mandatory evidence;
- accept/reject probes explicitly;
- exact and semantic authority differences;
- top-k does not imply relevance;
- exact zero does not necessarily prove real-world absence;
- model-specific inference rules;
- representation-gap wording;
- final viewer-probe selection.

Keep schema-enforced structured outputs. Do not parse free-form JSON from the model.

## 12. Current-model regression requirements

Add committed evaluation cases and automated/mocked regression tests for at least the following.

### Exact door count

Question:

```text
How many doors are in this building?
```

Expected:

- semantic resolution identifies `IfcDoor`;
- exact SQL remains authoritative;
- answer is 205 for the current model;
- unnecessary full entity/relationship RAG is not required;
- unrelated semantic candidates cannot change the exact count;
- matching door identities remain available to the viewer.

### Roof representation

Question:

```text
Show me all the roofs.
```

Current model facts include:

```text
IfcRoof count = 0
IfcSlab count = 279
IfcCovering count = 1,214
names such as "plat dak", "dakvloer", and "dakelement"
properties such as Type = Roof and Reference = Type Dak
```

Expected:

- do not return zero only because `IfcRoof` is absent;
- do not filter `IfcCovering.predefined_type = ROOF` when that value is not present;
- discover and verify model-specific roof representations;
- return a non-empty, defensible set of roof-relevant objects;
- explain that the model represents roof components through other IFC classes/properties;
- allow the answerer to reject roof-adjacent but irrelevant candidates such as arbitrary wall or
  task records.

### Building circulation

Question:

```text
How is the circulation like in this building?
```

Current model facts include:

```text
IfcStair count = 9
IfcSpace count = 0
IfcRamp count = 0
IfcTransportElement count = 0
doors with names normalized from "liftdeur"
properties named "Egress Dimensions"
```

Expected:

- dynamically create several useful facets/probes rather than one broad RAG query;
- report exact stair/absence/coverage facts where relevant;
- recognize lift-related door evidence as supporting, not proof of elevator equipment;
- state that horizontal circulation cannot be assessed accurately without explicit spaces or
  equivalent model evidence;
- provide a cautious, useful model-specific interpretation instead of “0 circulation-related
  elements.”

### Corridor area

Question:

```text
What is the total corridor area?
```

Expected:

- search for corridor/hall/lobby-like model vocabulary and applicable area fields;
- determine whether a defensible entity set and area quantity exist;
- do not ask the user for an IFC class/property name;
- do not calculate an area from unrelated slabs/coverings;
- answer that a reliable total is unavailable when the representation/coverage is absent.

### Opening-related wording

Question:

```text
Show opening-related objects.
```

Expected:

- distinguish an opening void from elements that fill or relate to openings;
- consider relevant classes/relationships semantically;
- do not treat `opening` as a synonym that automatically means only `IfcDoor`;
- disclose ambiguity when multiple accepted evidence groups are returned.

### Irrelevant top-k

Use a question whose semantic search necessarily returns top-k records but none support the intent.

Expected:

- candidates still reach the bounded evidence package;
- the answerer rejects them;
- final answer states that no relevant model evidence was found;
- rejected candidates are not highlighted or stored as follow-up results.

## 13. Tests and validation

### Static ontology

Test:

- exactly 301 IFC2X3 `IfcRoot` hierarchy entries;
- correct root branches;
- no duplicate class names;
- valid single-parent ancestry;
- parent chains terminate at `IfcRoot`;
- schema metadata/hash/version;
- representative known classes and predefined types;
- no required alias/synonym gate;
- deterministic generated semantic text/index.

### Model vocabulary

Test:

- source-model isolation;
- fingerprint/version cache invalidation;
- deterministic frequency ordering and sampling;
- normalized name stems preserve original examples;
- GUID/STEP/noise exclusion;
- multilingual values remain searchable;
- property/quantity provenance and typed field references;
- bounded profiles and excerpts;
- no full canonical JSON in planner/answer payloads;
- no database writes.

### Planning

Test:

- active-model questions use the universal hybrid probe schema;
- simple exact questions can use one SQL probe;
- complex questions can use multiple independent probes;
- probe count/per-kind bounds;
- unique probe IDs and required purpose/facet;
- no raw SQL or arbitrary paths;
- one repair attempt only;
- no manual concept recipe is required for regression questions;
- catalog/general/clarify exceptions remain valid.

### RAG

Test:

- top-k candidates are returned without threshold rejection;
- entity and relationship searches remain source-scoped and separate;
- rank/similarity remain internal;
- no candidate is automatically marked relevant;
- answerer may reject all candidates;
- embedding failure leaves exact SQL usable;
- query/profile vectors are never persisted.

### Evidence and answer

Test:

- independent probe evidence groups;
- authority and coverage labels;
- exact zero versus absent/unavailable/failed states;
- accepted/rejected probe-ID validation;
- viewer actions use only accepted viewer probes;
- rejected candidates do not enter session follow-up IDs;
- exact SQL facts outrank conflicting semantic guesses;
- inference is disclosed and cites accepted evidence internally;
- no probe IDs/scores/internal IDs leak into normal answers;
- result and viewer limits remain intact.

### Existing suites

Run:

```text
backend Ruff
backend non-live pytest
frontend typecheck/lint/unit/build if the OpenAPI contract changes
```

Regenerate frontend API types only if the public contract changes. Make the smallest compatible
frontend update needed; do not redesign the UI.

### Bounded live validation

After automated tests pass, run a bounded manual validation against the current active model using
the real backend and existing models:

```text
How many doors are in this building?
Show me all the roofs.
How is the circulation like in this building?
What is the total corridor area?
```

Do not create a persistent live OpenAI test module. Record:

- planner probes;
- probe execution times;
- accepted/rejected evidence groups;
- final answer behavior;
- token usage;
- viewer match behavior;
- database/vector before/after counts.

If one query exposes a defect, fix and rerun only the necessary bounded case rather than creating an
uncontrolled agent loop.

## 14. Performance and operational requirements

- Do not pass all 301 ontology entries to every planner call.
- Do not pass the complete active-model vocabulary to the LLM.
- Do not embed ontology/model profiles per question.
- Keep ontology/model-profile caches bounded and versioned.
- Continue lazy loading of BGE-M3.
- Independent probes may run concurrently but remain bounded by per-path and total timeouts.
- Print submitted SQL/RAG statements according to Task 15 without vectors or parameter values.
- Include all OpenAI calls in the existing per-question token summary.
- Add concise trace records for semantic resolution and probes without printing full profiles,
  prompts, vectors, canonical JSON, or long candidate lists.
- Measure cold first-semantic-query time and warm subsequent-query time.
- Preserve SQL-only usability when semantic embedding is degraded.

## 15. Database, ingestion, and artifact constraints

This task must use existing:

```text
ifc_source_models
ifc_entities
ifc_relationships
relationship_members
rag_documents
```

Do not:

- edit the source IFC;
- run or modify normal ingestion behavior;
- re-import the source model;
- regenerate stored entity/relationship vectors;
- migrate or write BIM tables;
- add PostGIS;
- modify prepared viewer artifacts;
- import `bim_rag` or IfcOpenShell into the backend runtime.

Backend-local ontology resources and derived in-memory/local semantic caches are allowed because
they do not alter persistent BIM corpus data.

If implementation discovers that a database migration or re-vectorization is truly unavoidable,
stop and report the exact reason before doing it. Do not silently broaden this task.

## 16. Prohibited actions

- Do not implement an alias whitelist that gates class access.
- Do not hard-code broad concepts such as circulation, accessibility, façade, or fire safety as
  fixed class lists.
- Do not assume the top semantic result is relevant.
- Do not preserve the old hard similarity threshold as the new acceptance decision.
- Do not force every simple question to run every expensive probe kind.
- Do not add a third LLM call.
- Do not add an unbounded planning/replanning/tool loop.
- Do not let the LLM emit raw SQL or arbitrary JSON paths.
- Do not expose full canonical JSON, vectors, raw prompts, SQL parameters, credentials, or local
  paths.
- Do not claim that an absent IFC class proves the real-world feature is absent.
- Do not claim an exact aggregate when field/entity coverage is insufficient.
- Do not ask users to know IFC classes or property names.
- Do not highlight or persist rejected evidence candidates.
- Do not redesign the frontend.

## 17. Acceptance criteria

1. Every conversational active-model question covered by this pipeline receives pre-planner
   semantic resolution against a versioned IFC ontology and active-model vocabulary, while the
   explicitly preserved catalog/general/clarify exceptions remain well-defined.
2. The committed IFC2X3 ontology contains exactly the 301 `IfcRoot` hierarchy declarations and no
   required synonym gate.
3. Active-model planning uses bounded probe arrays rather than one exclusive SQL/RAG/graph choice.
4. Simple exact questions can remain efficient with one SQL probe.
5. Ambiguous analytical questions can use multiple independent evidence groups.
6. RAG returns bounded top-k candidates without a hard acceptance threshold.
7. The answerer explicitly accepts/rejects probe evidence and may reject all retrieved results.
8. Viewer actions and follow-up state use accepted evidence only.
9. Model-vocabulary candidates preserve exact class/field/value provenance and receive safe
   structured verification when possible.
10. “Show me all the roofs” returns useful non-empty model evidence despite `IfcRoof` being absent.
11. The circulation question produces a cautious evidence-based assessment rather than an empty
    semantic result.
12. Corridor-area behavior reports unavailable/incomplete representation without demanding IFC
    vocabulary from the user.
13. Exact counts, semantic candidates, representation gaps, failures, and inference remain clearly
    distinguishable.
14. The backend remains read-only and ingestion/database/vector/viewer-artifact state is unchanged.
15. Existing compatible backend/frontend behavior and automated suites remain valid.

## Completion report

Rename this file to:

```text
tasks/task16_done.md
```

only when implementation and validation are complete.

Append a completion report containing:

- specification amendments made;
- ontology files, generator, source metadata, exact class count, and validation;
- semantic index/cache design;
- model-vocabulary profile design, bounds, and cache key;
- final planner probe schema and limits;
- RAG threshold removal/migration details;
- evidence authority/coverage schema;
- answerer relevance-decision schema;
- viewer/follow-up accepted-evidence behavior;
- the four required live query plans, accepted/rejected probes, and final answers;
- cold/warm timing and token-usage results;
- automated test commands/results;
- database, `rag_documents`, source IFC, and viewer-artifact before/after confirmation;
- remaining limitations, especially unsupported IFC ontology versions or missing model semantics.

---

# Completion report

Implementation and bounded live validation are complete. The universal hybrid semantic
evidence pipeline is live; the backend remains read-only and ingestion/DB/vector/viewer-artifact
state is unchanged.

## Specification amendments

Appended concise "Task 16 amendment" sections to `specs/spec_v002_query_architecture.md`
(ontology + model-vocabulary resources, two-call probe pipeline), `spec_v003_sql_query_path.md`
(structured verification reuses typed SQL), `spec_v004_rag_query_path.md` (threshold-free
candidate retrieval; `passed_threshold`/`sufficient_evidence` no longer gate inclusion), and
`spec_v005_hybrid_query_orchestration.md` (probe array replaces exclusive route; independent
evidence groups; answerer relevance judge; `planner_v002`/`answerer_v002`). Completed task history
was not rewritten.

## Ontology

- Files: `backend/app/query/semantic/ontology/{schema.py,loader.py,generate.py,IFC2X3.json}` plus
  committed index `generated/IFC2X3_bge_m3_v001.npy` and `.meta.json`.
- Source: IfcOpenShell 0.8.5 `ifcopenshell_wrapper.schema_by_name("IFC2X3")` (offline dev
  utility, run under the `bim_rag` conda env; the backend runtime never imports IfcOpenShell).
- Exact class count: **301** in the `IfcRoot` hierarchy (233 IfcObjectDefinition + 17
  IfcPropertyDefinition + 50 IfcRelationship + IfcRoot). Content hash `71fb9453ff4f…`.
- Validation: 10 committed tests — 301 count, branch counts, no duplicates, single-parent
  ancestry terminating at IfcRoot, hash/metadata, representative classes/predefined types
  (IfcSlab→FLOOR/ROOF/LANDING/BASESLAB, IfcCovering→ROOFING), **no synonym/alias gate**,
  deterministic profile text, committed-index alignment.

## Semantic index / cache design

- Ontology index is committed (301×1024 float32, L2-normalized), keyed to the JSON content hash
  plus profile version plus embedding model/dim; a stale index is refused at load.
- Model semantic index (embedded class+fact profiles) is built once per model and cached in
  process memory, keyed by (source_model_id, fingerprint, extraction_version,
  profile_builder_version, embedding_model). Query embeds via the shared BGE-M3 service; nothing
  is persisted. Batch embedding added as `EmbeddingService.embed_documents`.

## Model-vocabulary profile design, bounds, cache key

- `backend/app/query/semantic/vocabulary/{profiles,builder,cache}.py`. Deterministic, read-only
  grouped SQL. Class profiles (28 for the current model), observed-fact profiles (name stems,
  categorical property values, coverage, object/predefined/type/material/storey — 1500 capped),
  quantity/coverage profiles (0 — this model has no quantity sets). Name stems strip the exporter
  suffix `_(#…)` while keeping originals; GUID/STEP/UUID/numeric/long values excluded; multilingual
  Dutch retained. Bounds (settings): ≤20 values/profile, ≤5 examples, ≤30 profiles to planner,
  ≤500-char excerpts, ≤1500 internal facts (fair round-robin trim), min 2 occurrences for value
  facts. Cache key includes fingerprint + extraction + builder version. Cold build ≈0.9 s; warm
  cached. No BIM writes/migration.

## Planner probe schema + limits

- `route=hybrid` + `probes[]` (`app/llm/schemas.py::Probe`, kinds sql / model_vocabulary /
  ontology / rag_entity / rag_relationship / graph). Limits (centralized in settings, validated
  before execution): ≤10 total, ≤4 sql, ≤4 ontology+model_vocabulary, ≤4 rag, ≤2 graph; unique
  ids; required purpose/facet; one typed allowlisted plan per kind; no raw SQL/paths. One repair
  attempt only. Legacy exclusive-route plans and catalog/general/clarify remain valid.

## RAG threshold removal

- The probe path returns bounded top-k for every semantic/RAG probe with no acceptance gate;
  similarity + rank kept internal (trace/eval). `thresholds.py` and the legacy fields remain only
  for backward-compatible tests/diagnostics. Embedding failure degrades and leaves SQL usable;
  query/profile vectors are never persisted.

## Evidence authority / coverage schema

- `ProbeEvidence` (per probe): `authority` in {exact, structured_candidate, semantic_candidate,
  general_context}; `coverage` in {complete, bounded, unknown, unavailable, failed}; bounded
  candidate refs (rank + provenance, similarity internal); exact counts uncapped. Automatic
  structured verification upgrades a queryable model-vocabulary candidate to `structured_candidate`
  with an exact verified count + bounded identities (allowlisted FILTER_ENTITIES, never fuzzy SQL).
  Distinct states (exact zero vs absent class/field vs all-rejected vs failed vs bounded) are kept
  separate.

## Answerer relevance-decision schema

- `AnswerOutput` adds `used_probe_ids`, `rejected_probe_ids`, `viewer_probe_ids`,
  `model_evidence_sufficient`, `inference_used`, `inference_basis_probe_ids` (plus the existing
  general-knowledge/conflict flags). Unknown ids are ignored with a bounded warning.

## Viewer / follow-up accepted-evidence behavior

- `app/query/hybrid/probe_result.py`: viewer highlights are built ONLY from accepted, entity-
  bearing probes named in `viewer_probe_ids` (fallback: accepted `used_probe_ids`); rejected
  semantic candidates are never highlighted. Follow-up session state stores only accepted probe
  entity/relationship ids. `answer_basis` stays evidence-dependent (one accepted exact SQL count →
  `exact_sql`).

## Bounded live validation (real backend + DB + OpenAI, current model)

DB/vector before == after: `ifc_entities=6989, ifc_relationships=3473, rag_documents=10462,
rag_vectors=10462` (UNCHANGED). Source IFC and viewer artifacts untouched. Planner=answerer model
`gpt-5-nano`.

| Question | Probes | Accepted / rejected | Answer basis | Result | Tokens |
|---|---|---|---|---|---|
| How many doors…? | 1 sql (door-count) | door-count / — | exact_sql | 205 doors, 205 highlighted | 13,798 |
| Show me all the roofs. | 1 model_vocabulary (roof-vocab) | roof-vocab / — | hybrid_evidence | roofs via IfcCovering + IfcSlab Type=Roof (42 + 61 = 103); 536 highlighted; explains IfcRoof absent | 17,732 |
| How is the circulation…? | sql + model_vocabulary + ontology | all accepted (viewer: circulation-vocab) | hybrid_evidence | 9 stairs, 36 lift doors (liftdeur), no IfcSpace so horizontal circulation not assessable; lift access inferred not proven | 34,711 |
| What is the total corridor area? | 1 model_vocabulary (corridor-vocab) | — / corridor-vocab | insufficient_evidence | "not explicitly represented … a total corridor area cannot be reported"; no IFC-class question asked | 30,172 |

Two planner-quality defects surfaced and were fixed by prompt/context changes (not code):
initial roof and corridor plans guessed `predefined_type` filters / an area aggregate over
unpopulated fields; `planner_v002` now steers to `model_vocabulary` probes and the ontology
candidate relabels schema predefined types as `schema_possible_predefined_types`. Re-ran only the
affected bounded cases; all four now behave per §12.

## Cold / warm timing + token usage

- Cold first active-model question ≈65–71 s end-to-end (one-time BGE-M3 load + per-model semantic
  index build ≈15–25 s + two `gpt-5-nano` reasoning calls). Warm semantic resolution ≈18 ms;
  warm vocabulary/index cached. Token usage per question 13.8k–34.7k (planner+answerer), included
  in the standard per-question `[OpenAI usage]` summary.

## Automated test commands / results

- `poetry run ruff format . && poetry run ruff check .` → clean.
- `poetry run pytest` → **434 passed**. New suites: `tests/semantic/` (ontology, vocabulary,
  resolution), `tests/query_hybrid/{test_probe_plan,test_probe_evidence,test_probe_result}.py`,
  `tests/query_live/{test_vocabulary_live,test_resolution_live,test_probes_live,test_task16_regression}.py`,
  plus `embed_documents` coverage. Public OpenAPI contract unchanged (response envelope additive),
  so no frontend regeneration/redesign was required.

## Database / rag_documents / source IFC / viewer-artifact before-after

Confirmed unchanged (see live-validation table). No migration, no re-import, no re-vectorization,
no PostGIS, no viewer-artifact edits; IfcOpenShell/`bim_rag` are not imported by the backend
runtime.

## Remaining limitations

- Only IFC2X3 is bundled; a model on an unbundled schema (IFC4/IFC4X3) degrades truthfully to its
  observed vocabulary + exact schema catalog (no ontology candidates).
- The current model has no `IfcSpace` and no quantity sets, so horizontal-circulation and any
  area/volume totals are genuinely unavailable and are reported as representation gaps.
- `gpt-5-nano` needs explicit prompt steering to prefer model-vocabulary discovery over
  schema-predefined-type guessing; a stronger planner model would likely need less.
- The roof viewer highlight set (536) is broader than the tight `Type=Roof` count (103) because it
  includes every verified roof-relevant vocabulary candidate; the exact counts in the answer remain
  authoritative.
