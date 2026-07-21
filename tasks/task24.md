# Task 24: Model-Aware Semantic Binding and Authoritative BIM Retrieval

## Purpose

Implement a new active BIM question-answering pipeline that reliably narrows a large model to the
smallest authoritative evidence needed to answer the user's question.

The project is a BIM RAG application. A user should be able to access, analyze, and understand a
complex building model without sending the entire BIM dataset to an LLM. SQL, RAG, and graph
retrieval remain the available evidence engines, but the pipeline must determine the intended BIM
concept and constraints before executing expensive retrieval.

Implement Task 24 as the active query pipeline on the experimental branch. Do not create a feature
flag, parallel endpoint, compatibility route, or separate legacy/new orchestration path. Future
query work will build on the completed Task 24 architecture.

## Fundamental problem

The pipeline currently places model-aware semantic selection at the wrong point in the cycle:

1. the first LLM interprets the question without seeing a bounded view of how relevant concepts
   may be represented in the active model;
2. deterministic resolution produces many possible classes, fields, values, and evidence groups;
3. many candidates are executed before their relevance is established;
4. the final LLM receives competing results and is asked both to decide what the user meant and to
   write the answer.

This can lose relevant evidence, execute the wrong representation, dilute correct evidence among
irrelevant candidates, or make the final LLM reinterpret exact results. It also wastes database
work, tokens, and response time.

The solution is to make one small, model-aware semantic binding before authoritative execution,
then give the final LLM only the already-adjudicated result.

## Non-negotiable generalization rule

Do not implement any fix whose condition is a specific sample question, phrase, expected value,
IFC file, or test count.

In particular:

- no exact-query string matching;
- no branches for individual phrases from `specs/test_query.md`;
- no hard-coded expected counts;
- no special handling for one named property value, object type, floor expression, or absent
  concept;
- no prompt examples that cause the implementation to work only for the recorded wording;
- no model-2-specific mapping or logic.

Every implementation change must enforce a general invariant, such as:

- scope references and result filters are distinct typed concepts;
- a requested occurrence cannot silently become a type definition or component;
- every executed constraint is grounded in the user's wording or an explicitly inherited scope;
- an exact empty representation outranks a semantically similar but different non-empty class;
- exact, zero, unavailable, and partial evidence are not interchangeable;
- the final LLM cannot choose among unexecuted or competing semantic interpretations.

The questions in `specs/test_query.md` are acceptance tests only. They must not be used as a source
of query-specific production rules. Add unrelated and paraphrased tests for every mechanism so a
sample-specific patch cannot pass validation.

---

# Required architecture

Use this data flow:

```text
user question + bounded history + typed previous scope/selection
    -> deterministic, query-specific candidate slate from cached model semantics
    -> LLM call 1: bind the user's requested answer parts to candidate IDs
    -> deterministic validation, IFC semantic closure, and retrieval-mode derivation
    -> one authoritative execution per answer part
       - typed SQL for exact structured facts
       - SQL-scoped RAG for qualitative semantic ranking
       - seeded graph traversal for relationships/connectivity
    -> compact answer packet containing only adjudicated results
    -> LLM call 2: uniform grounded answer writing
    -> deterministic response validation and viewer identities from the same results
```

Keep exactly two principal LLM calls for a normally answered active-model question:

1. model-aware semantic binding;
2. final grounded response.

Do not add an LLM router, verifier, judge, repair, reflection, correction, reranking, or replanning
call. An invalid binding or invalid final response must not trigger a third model request.

SQL, RAG, graph, model vocabulary, ontology, logical floor bands, typed SQL compilation, session
state, and viewer identity behavior should be reused and corrected rather than rebuilt as parallel
systems.

---

# 1. Build a compact model-aware candidate slate before LLM call 1

## 1.1 Purpose

The candidate slate is a bounded description of plausible ways the current question may be
represented in the active model. It gives the first LLM enough model awareness to select the right
meaning without sending the model manifest, canonical JSON, complete vocabulary, database rows, or
retrieval results.

Build it deterministically from existing cached resources where possible:

- IFC ontology classes, inheritance, definitions, and schema roles;
- active-model class profiles and exact presence/count metadata;
- queryable field registry;
- observed property, quantity, classification, material, type, and attribute profiles;
- field coverage and missing-data states;
- logical floor bands and storey metadata;
- relationship classes and graph capabilities;
- selected objects;
- the previous accepted result's typed scope.

Do not run an exact SQL count for every candidate. Candidate generation is discovery, not
execution. Reuse cached counts and profiles already available in the vocabulary where possible.

## 1.2 Query-driven retrieval of candidates

Build the slate from the entire user question using a deterministic combination of:

- exact and normalized lexical matches;
- IFC label and identifier tokenization;
- ontology-definition similarity;
- existing semantic embeddings;
- active-model presence and field coverage;
- quoted values, numeric values, units, comparison language, and explicit Boolean structure;
- bounded conversation and selection context.

Exact normalized matches must be retained before semantic supplemental candidates are capped. This
prevents a compound question containing several explicit BIM nouns from losing one simply because
another noun ranked higher by embedding similarity.

Do not solve recall by raising a global similarity threshold, increasing existing retrieval limits,
or sending the entire vocabulary. Use a small mixed slate with exact matches first and semantic
supplements second.

## 1.3 Candidate types

The slate must contain typed candidate records with stable request-local IDs. Include only the
candidate types relevant to the current question:

### Subject candidates

Each subject candidate represents one possible requested result concept and contains:

- candidate ID;
- plain-language label;
- bounded ontology definition;
- IFC schema role;
- occurrence family or exact class binding;
- present family members in the active model;
- whether the representation is present or absent;
- cached exact class/family counts when already available;
- semantic role such as occurrence, type definition, property definition, spatial structure,
  relationship, or other non-result metadata;
- whether selecting it would represent one physical/logical result or a supporting component.

An ontology candidate that is semantically exact but absent from the active model must remain
eligible. Do not discard absent exact candidates and replace them with a broader non-empty class.

### Field candidates

Each field candidate contains:

- candidate ID;
- canonical typed field reference;
- plain-language meaning and normalized aliases;
- applicable subject families/classes;
- field kind;
- data type and supported operators;
- coverage state and populated/missing counts where known;
- a few query-relevant normalized observed values, not a global value dump.

Field resolution and value resolution must be separate. Do not require a field-name match and an
observed-value match to succeed in one lexical comparison.

### Spatial candidates

Include spatial candidates only when spatial scope is relevant. They may represent:

- the active model/building scope;
- logical floor bands;
- exact storey entities when the user explicitly asks about storey entities;
- selected spatial containers;
- a previous spatial result.

A reference that identifies the active model is a scope selection. A predicate that restricts
results to a spatial subset is a condition. Represent these as different typed fields so one cannot
accidentally become the other.

### Relationship candidates

Include relationship candidates only for questions about connection, containment, assignment,
aggregation, adjacency, membership, endpoints, or paths. Record:

- relationship candidate ID;
- relationship meaning and IFC class;
- endpoint roles/classes when known;
- availability in the active model;
- supported traversal direction and depth bounds.

### Coverage/capability candidates

Expose only query-relevant capability information, such as whether the selected subject family has
the requested quantity, property, material association, classification, or graph relationship.
Do not send a full model manifest.

## 1.4 Bounds

Keep the serialized slate small enough for a fast planner request. Use conservative caps and test
them with compound questions. As an initial implementation target:

- at most 8 subject candidates after exact candidates and deduplication;
- at most 8 field candidates;
- at most 8 relevant value candidates total;
- at most 6 spatial candidates;
- at most 6 relationship candidates;
- short definitions and profiles rather than representative entity documents.

These are maximum bounds, not quotas. Simple exact questions should usually receive one obvious
subject candidate and only the fields actually implied by the question.

---

# 2. LLM call 1 is a semantic binder, not an investigation agent

## 2.1 Input

The first LLM receives only:

- the current user question;
- bounded conversational text required to resolve references;
- active model/catalog scope;
- selected-object summaries when present;
- typed previous-result scope when present;
- the compact request-specific candidate slate;
- the small output schema and its rules.

It must not receive full canonical JSON, full model vocabulary, database rows, raw embeddings,
candidate SQL results, or viewer identity lists.

## 2.2 Output schema

Replace the broad facet/evidence-group planning contract with one compact typed binding plan.

The plan must contain:

- response language;
- one to four answer parts, matching the actual independent requests in the question;
- viewer intent;
- clarification status only when a material ambiguity cannot be safely bound.

Each answer part must contain:

- stable `part_id`;
- output operation from a bounded enum, covering at least count, existence, list/show, sample detail,
  group/distribution, aggregate, extremum/ranking, description/summary, comparison, and
  relationship/connectivity;
- one primary subject candidate ID, or a bounded explicit union of subject candidate IDs only when
  the user asks for multiple peer concepts;
- scope reference: active model, selected objects, previous accepted result, or another typed
  spatial candidate;
- zero or more typed conditions;
- requested output fields when applicable;
- optional semantic-ranking text only for genuinely qualitative evidence;
- relationship candidate and endpoint target only for relationship/connectivity operations.

Each condition must contain:

- field/spatial/material/classification candidate ID;
- operator;
- user value text/list and unit when present;
- Boolean group position;
- an exact source span from the current question, or an explicit inherited-scope reference.

The model may select only candidate IDs present in the supplied slate. It may not emit IFC classes,
field names, JSON paths, SQL, graph start IDs, arbitrary investigation operations, or new candidate
definitions.

## 2.3 No hypotheses or investigation DAG

Do not add:

- hypotheses;
- investigation lists;
- dependencies or a planner-authored DAG;
- optional exploratory branches;
- iterative tool use;
- correction plans;
- alternate plans to execute and compare.

The LLM chooses one binding per requested answer part. Deterministic execution either supports that
binding, returns a typed absence/coverage state, or requests clarification.

## 2.4 General constraint provenance

Every executed narrowing condition must be traceable to:

- an exact span in the current question;
- the current viewer selection; or
- a typed predicate inherited from the previous accepted result.

Reject invented conditions deterministically. Do not ask the LLM to repair them.

Candidate generation should emit bounded `detected_modifier_spans` for structurally recognizable
modifiers such as quoted values, comparisons, units, numeric bounds, floor/level references,
negation, and field/value matches. The binding must cover each material detected modifier or mark
it unresolved. A required modifier may never be silently dropped so a broader query can execute.

This mechanism must remain general. Do not maintain a list of complete sample-query phrases.

---

# 3. Deterministic IFC semantic closure and validation

## 3.1 One primary semantic result per answer part

Before execution, convert the selected subject candidate into one authoritative semantic result
set.

For an exact count or list, do not execute semantically adjacent candidate classes and ask the final
LLM to choose. One answer part normally has one primary occurrence family.

When a user explicitly asks for multiple peer concepts, preserve them as separate answer parts or
an explicit typed union. Do not automatically add parts, type definitions, styles, relationships,
or supporting elements to the requested occurrence total.

## 3.2 IFC family semantics

Build family closure from IFC ontology inheritance and schema roles:

- a generic superclass request includes applicable present occurrence subtypes;
- an explicitly requested subtype remains specific;
- type/style/property-definition classes are not physical occurrence results;
- semantically related components are not descendants and are not automatically included;
- spatial structure entities and logical floor bands are distinct result kinds;
- relationships are evidence about endpoints, not occurrence results unless explicitly requested.

Do not create a growing table of query phrases mapped to class lists. A small schema-level role or
family registry is acceptable only where the IFC ontology does not expose a required invariant,
and every entry must describe a reusable IFC semantic rule rather than a sample query.

## 3.3 Binding validation

Validate before any authoritative query executes:

- every selected candidate exists in the request slate;
- the subject role is compatible with the requested operation;
- conditions apply to the chosen subject family;
- operator and data type are compatible;
- all required source spans are represented;
- Boolean structure remains within existing typed SQL bounds;
- units are compatible and deterministically convertible;
- previous-result and selected-object scopes belong to the active model;
- relationship seed and endpoint semantics are executable;
- an exact operation is not being based on a bounded semantic-candidate count.

An invalid binding returns a concise clarification or typed unavailable result. It must not trigger
a second planning call, silently broaden the scope, or fall back to all entities of a nearby class.

---

# 4. General field and value normalization

## 4.1 Field concept index

Create or extend a cached field-concept index that describes queryable fields using:

- canonical field and set names;
- split identifier tokens;
- IFC/property definitions where available;
- normalized BIM terminology and reusable aliases;
- subject-family applicability;
- data type, unit, and operator support;
- field coverage.

The alias vocabulary must describe general BIM concepts, not complete query phrases or expected
values. It should support exporter and naming variation without binding one user question directly
to one database path.

## 4.2 Value normalization

After a field is selected, normalize values using reusable rules:

- Unicode and case normalization;
- punctuation and whitespace normalization;
- singular/plural and simple morphological normalization;
- boolean and presence-state synonyms;
- normalized IFC enum values;
- numeric parsing;
- unit conversion through the existing unit system;
- exact quoted values preserved when the user requests exactness;
- controlled contains/starts-with behavior only when requested or semantically necessary.

Query the chosen field's complete indexed value vocabulary when required. Do not resolve a value
against unrelated fields or against only a globally capped set of top facts.

## 4.3 Presence, distribution, and aggregate operations

Support presence/absence and field-value distributions through the existing typed SQL machinery.

When a question asks how many objects have a property and what values it has, prefer one scoped
group/distribution result over inventing a value condition. Presence, group-by, missing-value,
aggregate, and extremum are distinct operations and must retain their correct coverage semantics.

---

# 5. Authoritative retrieval execution

## 5.1 Mode is derived, not chosen by the LLM

Derive retrieval from the bound operation:

- structured count, existence, filter, list, group, distribution, aggregate, extremum, and exact
  ranking use typed SQL;
- qualitative semantic ranking uses RAG;
- a qualitative request with a structured subject/conditions executes SQL scope first and RAG only
  within the resulting IDs;
- connection, containment, assignment, aggregation, membership, endpoint, and path questions use
  seeded graph traversal;
- relationship-document RAG may help retrieve qualitative relationship context but cannot replace
  graph execution for a claimed connection.

Do not expose SQL/RAG/graph route flags for the LLM to set. The external response may continue to
use the existing route vocabulary, but actual execution must follow the operation contract.

## 5.2 One authoritative execution per answer part

Execute only the selected interpretation.

- Do not count every subject candidate.
- Do not execute every field/value candidate.
- Do not build independent competing exact evidence groups.
- Do not fetch viewer identities while evaluating candidates.
- Do not ask the final LLM to select the authoritative result.

An answer part should normally require one typed structured query. A bounded multi-part question
may execute one query per answer part. Batch compatible operations where the existing SQL path can
do so safely without creating another query engine.

## 5.3 Scoped RAG

RAG is bounded semantic evidence, never an exact total.

When structured scope exists:

1. execute the authoritative SQL predicate;
2. search/rank only entities inside that scope;
3. keep an empty scoped RAG result empty;
4. do not widen to whole-model RAG;
5. retain the SQL count separately from the bounded semantic candidates.

Use only a few final RAG examples in the answer packet. Do not send full entity documents or large
candidate lists to the final LLM.

## 5.4 Graph execution

Wire graph operations into the active pipeline rather than only recording that graph retrieval was
requested.

The graph executor must receive:

- seed identities from the selected subject predicate, selected objects, or typed previous result;
- relationship class/role binding;
- direction;
- existing bounded maximum depth;
- optional endpoint subject family;
- source-model isolation.

Filter endpoint results to the requested endpoint semantics. If the model does not contain the
required relationship representation or traversal cannot establish the requested connection,
return unavailable/partial evidence. Never fabricate connected names from a broad entity list.

---

# 6. Evidence status and coverage contract

Every answer part must finish with one of these result states:

- `exact`: the requested representation and required data were queried with complete structured
  coverage; the result may be nonzero;
- `zero`: the requested representation was safely identified and completely queried, but no
  matches were found;
- `unavailable`: the required property, quantity, relationship, or representation cannot be
  established from the model;
- `partial`: a useful part is exact or directly supported, but another requested part is
  unavailable or incomplete;
- `ambiguous`: multiple materially different bindings remain and user clarification is required.

Preserve more detailed internal missing-value states where the existing SQL path supports them,
but map them into this concise answer-part contract for the final LLM.

Rules:

- zero is not unavailable;
- missing field coverage is not a zero value;
- an absent explicit representation describes the BIM model, not necessarily the real building;
- a bounded RAG miss is not proof of absence;
- failed graph execution is not evidence of no real-world connection;
- partial evidence must identify the known and unknown parts separately;
- no unavailable condition may be silently removed to produce a broader exact result.

---

# 7. Typed previous-result scope and conversation

Replace the current previous-result state that carries only a bounded ID list with a compact,
reproducible typed scope.

Store at least:

- source model ID;
- selected subject family/result kind;
- complete typed predicate or reproducible operation binding;
- accepted answer-part ID;
- exact count/status;
- bounded example IDs only when useful;
- complete viewer identity information only in the existing response/viewer channel, not session
  prompt context.

A follow-up may explicitly:

- inherit the previous result and add a condition;
- inherit it and request another property/aggregate;
- replace it with a new subject;
- refer to the current viewer selection.

Do not scope a large follow-up to the first 50 or 200 previous IDs. Re-execute the stored typed
predicate when complete scope is required.

Clear or invalidate the previous scope when the active model changes, the session resets, or the
stored source model does not match the request.

---

# 8. Compact answer packet for LLM call 2

## 8.1 Final LLM responsibility

The final LLM remains mandatory for answered queries so response style, language, qualifications,
and multi-part presentation remain uniform.

Its responsibility is only to express adjudicated results. It must not:

- select a target class or field;
- accept/reject candidate groups;
- choose retrieval modes;
- add counts from associated classes;
- reinterpret zero as unavailable or unavailable as zero;
- infer a connection not established by graph evidence;
- broaden the viewer scope;
- invent model facts.

## 8.2 Answer packet

Send one compact result object per answer part containing only:

- part ID and the corresponding user request;
- selected interpretation in plain language;
- result status;
- authority and coverage;
- exact total, aggregate, extremum, or value distribution when applicable;
- relevant class/value breakdown only when requested or necessary;
- at most 3 representative examples by default;
- up to the explicit user list limit for a list request, bounded by existing limits;
- bounded relationship paths/endpoints for graph answers;
- one concise limitation/reason for zero, unavailable, partial, or ambiguous results;
- stable fact/result IDs for grounding;
- response language and requested level of detail.

Do not send:

- rejected candidates;
- semantic similarity scores;
- planner reasoning;
- ontology candidates not selected;
- repeated group IDs that the answerer must classify;
- 50 cross-group examples;
- complete viewer identities;
- raw canonical JSON;
- database IDs or SQL.

## 8.3 Final output and deterministic validation

Use a small structured final-answer schema containing:

- answer text;
- answer-part IDs used;
- structured factual claims referencing supplied fact/result IDs;
- whether inference or general knowledge was used;
- whether a material limitation was disclosed.

Validate deterministically that:

- all referenced answer parts and fact IDs exist;
- structured numeric claims match the authoritative values and units;
- zero/unavailable/partial status is preserved;
- any named classes, properties, materials, or relationship endpoints in structured claims appear in
  the answer packet;
- the model did not claim complete coverage from bounded RAG evidence;
- viewer selection remains backend-owned.

Do not call the LLM again after validation failure. Return a concise safe fallback assembled from
the authoritative answer-part results and record the validation failure. The final LLM is still
called in the normal cycle; the fallback is an exceptional grounding safeguard, not a separate
answer path chosen by query type.

---

# 9. Viewer identity consistency

The final answer, exact total, and viewer identities must derive from the same authoritative
answer-part result.

- Fetch complete viewer identities only after execution has established the final result.
- Do not highlight type/style/property-definition records for a physical occurrence result.
- Supporting qualitative or graph context may use the existing context visualization only when it
  is explicitly part of the answer packet and remains visually distinct.
- Exact zero, unavailable, catalog, and non-visual summary answers should not highlight an unrelated
  fallback set.
- Viewer identity limits must never change the exact total supplied to the final LLM.
- Multi-part questions need an explicit primary visual answer part; do not union all answer-part IDs
  merely because they were retrieved.

---

# 10. Performance and token requirements

The architecture must reduce work rather than compensate with larger limits.

## 10.1 LLM calls

- exactly two principal LLM calls for a normally answered active-model question;
- no format-repair, correction, verifier, or retry LLM call;
- keep `gpt-5-nano` as the initial planner and answer-model baseline;
- keep planner and answer model settings independently configurable for later A/B evaluation;
- do not upgrade a model merely to compensate for an oversized prompt or ambiguous contract.

## 10.2 Prompt bounds

- keep the candidate slate query-specific and normally far below its maximum caps;
- keep the binding schema small enough that it does not produce long reasoning-like output;
- send only adjudicated answer parts to LLM call 2;
- default to at most 3 examples per answer part;
- omit fields whose values are null/irrelevant rather than serializing large empty structures;
- log serialized prompt sizes and actual prompt/completion tokens by role.

Do not increase the number of evidence groups, RAG top-k, semantic-resolution top-k, example budget,
graph depth, list limit, or LLM output-token limit as a solution.

## 10.3 Database work

- no sequential exact query per semantic candidate;
- normally one authoritative retrieval per answer part;
- viewer identity hydration occurs after result selection;
- reuse caches for ontology, class profiles, field profiles, and logical floors;
- avoid rebuilding or embedding the model vocabulary per question;
- no per-question full canonical-JSON scan;
- batch compatible multi-part operations when it measurably reduces round trips;
- record statement counts and stage latency in diagnostics.

## 10.4 Retry behavior

Prevent nested retry multiplication:

- disable SDK-internal retries when application retry behavior is active;
- do not automatically retry a full LLM timeout;
- permit at most one bounded application retry for a short transient connection, rate-limit, or
  provider 5xx failure;
- do not retry schema, validation, refusal, or deterministic execution failures;
- preserve sanitized failure messages and never log credentials.

## 10.5 Performance evidence

Measure separately:

- candidate-slate build time and serialized size;
- LLM 1 latency and tokens;
- binding validation/semantic closure time;
- SQL, RAG, and graph execution time and statement counts;
- answer-packet size;
- LLM 2 latency and tokens;
- viewer hydration time;
- total response latency and tokens.

Compare the complete Task 24 run against the timings recorded in `specs/test_query.md`. Provider
latency varies, so acceptance is based on both end-to-end evidence and structural reductions. The
new implementation must demonstrate fewer executed candidate queries, smaller final prompts, no
extra LLM calls, and a lower median token/latency result across the same live suite.

---

# 11. Catalog, summary, and special operations

## 11.1 Catalog

Catalog questions remain model-catalog operations but must use the same final-answer contract for
uniform response style. Include all safe recorded display metadata needed to identify a model,
including the existing filename when a display name is absent. Do not fabricate missing catalog
metadata.

## 11.2 Building summary

Provide a deterministic, cached or efficiently batched building-profile operation for broad model
summaries. It may include only useful high-level facts such as:

- logical floor count;
- major occurrence-family counts;
- major space categories;
- directly recorded material/property summaries;
- explicit model limitations relevant to the summary.

Do not generate a summary by executing every semantic candidate group or sending the model
vocabulary to the final LLM.

## 11.3 Sample detail

Sample selection is an output operation, not a semantic filter. After the subject predicate is
executed, choose one deterministic matching occurrence and hydrate its bounded details through the
existing detail path. A planner-invented sample condition must never block the operation.

## 11.4 Logical spatial abstractions

When the answer operation asks about logical floors/levels, use the existing elevation-band model.
When the user explicitly asks about raw storey entities, use raw IFC spatial entities. Preserve
both concepts and do not let a generic entity count silently substitute for a logical building
abstraction.

---

# 12. Implementation boundaries

Modify the current active query pipeline in place. Reuse and simplify existing packages rather than
creating a second orchestration tree.

Expected implementation areas include:

- LLM schemas and the two prompts;
- planner/context assembly;
- semantic ontology/vocabulary candidate generation;
- field/value resolution and coverage;
- IFC class-family/role resolution;
- typed SQL plan composition;
- active hybrid orchestration;
- RAG scoping;
- graph seed/execution wiring;
- session previous-result state;
- answer evidence serialization and validation;
- viewer identity hydration;
- diagnostic logging and evaluation fixtures.

Remove or retire active-path behavior whose only purpose is to:

- execute many competing evidence groups;
- allocate examples across competing groups;
- ask the final LLM to accept/reject semantic candidates;
- preserve query-only isolation from all model-aware semantic candidates;
- carry previous results only as truncated identity lists.

Do not remove reusable typed SQL, RAG, graph, ontology, vocabulary, floor-band, field-registry,
viewer, or session infrastructure merely because the orchestration changes.

Do not change IFC ingestion, regenerate source IFC files, rebuild the database schema, or recreate
vector data unless implementation proves a required general semantic field is genuinely absent
from the existing stored/indexed information. Data already present must be solved in the query
pipeline.

---

# 13. Required testing

## 13.1 Layered tests

Tests must identify the first failing boundary rather than evaluating only final prose.

For each test case, independently validate:

1. candidate slate recall and size;
2. LLM binding or deterministic binding fixture;
3. selected semantic family and schema role;
4. field/value/spatial/relationship bindings;
5. compiled authoritative operation;
6. pre-LLM result status, count, distribution, examples, and coverage;
7. compact answer packet contents and exclusions;
8. final LLM grounded output or safe validation fallback;
9. answer/viewer identity consistency;
10. LLM calls, database statements, prompt tokens, and latency stages.

## 13.2 Candidate and binding tests

Cover at least:

- exact lexical candidates surviving semantic caps;
- multiple explicit subjects in one compound question;
- semantically exact absent candidates retained;
- occurrence versus type definition;
- generic superclass versus explicit subtype;
- related component versus requested whole occurrence;
- spatial scope versus active-model reference;
- quoted exact values;
- numeric comparison and units;
- negation and nested OR within existing bounds;
- invented condition rejected through missing/invalid source provenance;
- required modifier not silently omitted;
- selected-object scope;
- inherited previous-result scope;
- model change invalidating prior scope;
- multilingual binding where supported by the existing embedding/model path.

## 13.3 Field/value and coverage tests

Use several unrelated BIM fields and classes to prove general behavior:

- canonical identifiers and plain-language synonyms;
- boolean properties;
- singular/plural stored values;
- property values, type facts, classifications, materials, quantities, and attributes;
- exact, contains, comparison, distribution, aggregate, present, and missing operations;
- complete zero versus missing field versus extraction/unsupported state;
- unit conversion;
- the same concept represented differently in two models;
- a field existing on one subject family but not another.

## 13.4 Retrieval tests

Cover:

- one structured operation per answer part;
- structured family expansion without type/style/component leakage;
- scoped RAG never widening after an empty scoped result;
- RAG candidate counts never becoming exact totals;
- graph execution actually running when the operation requires it;
- graph seeds honoring structured constraints and previous scope;
- endpoint filtering;
- unavailable graph coverage producing no fabricated connection;
- multi-part execution retaining independent results;
- primary viewer identities coming from the same predicate as the answer;
- no viewer fallback for zero/unavailable results.

## 13.5 Final-answer tests

Cover:

- uniform LLM call 2 for exact, zero, unavailable, partial, qualitative, catalog, and multi-part
  results;
- exact numbers and units preserved;
- no summing of components or supporting concepts into a primary total;
- concise exact response without inventory dumping;
- appropriate model-limited language for absence;
- useful partial answers that distinguish known and unknown parts;
- same-language response;
- answer packet contains no rejected candidates or complete viewer IDs;
- invalid fact IDs or changed numeric claims rejected without a third LLM call;
- safe fallback uses authoritative results and does not fabricate.

## 13.6 Anti-overfitting and metamorphic tests

For each corrected mechanism, add at least one unrelated query or paraphrase that was not copied
from `specs/test_query.md`.

Also test that:

- changing active-model values changes the result without changing production prompt rules;
- injecting an irrelevant high-count class candidate does not change the selected result family;
- an absent exact class is not replaced by a broad present class;
- changing only query wording preserves the same binding where meaning is unchanged;
- changing from an occurrence request to an explicit type/component request changes the binding;
- adding a valid condition narrows the same authoritative result rather than spawning independent
  totals;
- removing a required field changes exact/zero to unavailable rather than a broader result;
- a follow-up over a result larger than the session ID cap still uses the complete predicate.

## 13.7 Full live suite

Run every query in `specs/test_query.md` against its specified model and session behavior. Record:

- binding;
- authoritative pre-answer result;
- final answer;
- expected result;
- verdict;
- answer/viewer counts;
- modes actually executed;
- LLM calls and tokens by role;
- database statement count;
- stage and total latency;
- whether final validation fallback was used.

Continue correcting general mechanisms and rerunning the complete suite until the acceptance
criteria below are met. Do not stop after the originally motivating queries pass.

---

# 14. Acceptance criteria

Task 24 is complete only when all of the following are demonstrated:

## Correctness

- every material user constraint survives into one authoritative execution;
- subject families contain the intended occurrences and exclude unrelated type/style/component
  records;
- field and value normalization works across unrelated classes and properties;
- logical spatial concepts are not replaced by raw entity counts;
- exact, zero, unavailable, partial, and ambiguous states are correct and user-facing;
- graph claims come from executed graph evidence;
- follow-ups reuse complete typed scope;
- compound questions return every requested answer part;
- no fabricated model fact is accepted;
- final answer and viewer identities agree.

## Architecture

- LLM call 1 selects only from a bounded model-aware candidate slate;
- the backend derives SQL/RAG/graph execution from the bound operation;
- only the selected interpretation is authoritatively executed;
- LLM call 2 receives only adjudicated answer parts;
- no third LLM call exists in the normal, invalid-plan, or invalid-answer path;
- no parallel legacy/new orchestration or feature flag remains;
- no query-specific production patch or expected count is present.

## Performance

- exactly two principal LLM calls for normally answered active-model questions;
- simple questions do not execute a query per semantic candidate;
- answer examples are bounded per answer part rather than allocated across candidate groups;
- SDK/application retries cannot multiply;
- a full LLM timeout is not automatically repeated;
- prompt sizes, tokens, statement counts, and stage timings are logged;
- full-suite median token usage and end-to-end latency improve over the recorded baseline;
- local retrieval/execution time for simple exact questions is not dominated by semantic candidate
  enumeration.

## Regression safety

- source-model isolation and read-only behavior remain;
- existing SQL allowlists and graph depth limits remain;
- RAG never becomes exact count authority;
- selection, catalog, reset, confirmation, viewer loading, viewer highlighting, and entity detail
  behavior remain functional;
- malformed input and prompt injection remain safely handled;
- no IFC, database, or vector artifact is changed without a separately documented general need.

---

# 15. Specification updates and completion record

Update these specifications during implementation so they describe the completed Task 24 pipeline
as the current source of truth:

```text
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

Preserve completed task history. Do not rewrite older task files to make them appear consistent
with the new architecture.

After implementation and validation:

1. append a concise completion report to this file;
2. record the final schemas, data flow, removed/superseded active-path behavior, tests, live-suite
   results, token/latency comparison, and genuine remaining limitations;
3. confirm that no query-specific patches or expected counts were added to production code;
4. rename this file to `tasks/task24_done.md` only after every required acceptance item is complete.
