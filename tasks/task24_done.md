# Task 24: Provisional Model-Aware LLM Query Agent

## Status

This task is a **provisional design and experimental plan**. It is not yet the final Task 24 and
is expected to receive additional requirements from the user.

Do not replace the production query pipeline or begin broad implementation from this draft alone.
The purpose of the current file is to preserve the user's exact architectural intention, the
suggested pipeline changes discussed so far, and the shape of an isolated experimental path. When
the user finalizes Task 24, this status and the remaining open decisions must be updated before
implementation begins.

Do not use earlier task files as architectural authority for this work. Task 23 is complete, and
`specs/test_query.md` records evaluation performed after the Task 23 changes. Task 24 is motivated
by the remaining failures observed in that post-Task-23 evaluation.

---

# 1. User intention

The current pipeline is too rigid. It divides natural-language understanding, retrieval-mode
selection, semantic candidate resolution, evidence-group construction, relevance judgment, and
answer writing across several strict boundaries. These boundaries were intended to improve safety
and grounding, but they also repeatedly lose, broaden, or misinterpret the user's meaning.

The intended direction is to give the LLM more authority to work in a bounded, human-like manner.
The LLM should be able to:

- inspect a compact representation of what the active IFC model actually contains;
- form one or more hypotheses about how the user's concept is represented;
- request multiple useful database investigations in one batch;
- inspect compact intermediate results;
- detect when an initial interpretation was wrong or incomplete;
- revise the interpretation or query once when justified;
- distinguish direct stored evidence from indirect clues and unavailable information;
- produce an honest `I don't know` / `cannot be determined from this model` result when the IFC
  does not provide sufficient evidence.

This is a deliberate movement away from forcing every question through a rigid sequence of blind
policy planning, broad semantic candidate creation, and final evidence-group repair. It is not a
movement toward sending the entire IFC database to an LLM or allowing unrestricted database
access.

The design should learn from the human-like working pattern used to establish the expected answers
in `specs/test_query.md`: inspect the available model structure, run several targeted queries,
compare intermediate results, correct a mistaken interpretation, and only then state the answer.
The production pipeline does not need to reproduce that process exactly, but it should use the
same useful capabilities within explicit bounds.

Token use may increase from the current version when the additional tokens carry useful model
vocabulary, field coverage, intermediate query results, or competing interpretations. Lower token
use remains preferable when answer quality is equal. Response time remains important, so the
design must prefer batched database investigations and a bounded number of LLM round trips over an
open-ended agent loop.

---

# 2. Core architectural direction

Explore replacing much of the current model-blind planning and broad evidence-group machinery with
a **model-aware LLM query agent** backed by a small set of safe, typed investigation tools.

Target conceptual flow:

```text
user question
    + bounded conversation state
    + compact active-model manifest
        -> LLM query agent
        -> one batch of typed SQL / semantic / graph investigations
        -> deterministic backend execution
        -> compact intermediate results
        -> either:
             A. deterministic exact or unavailable answer
             B. one LLM correction or qualitative-synthesis round
        -> deterministic validation
        -> viewer identities from the accepted executed result
```

This is a maximum-two-call normal path, not a requirement to make two calls for every question.

## 2.1 Simple exact path

For a straightforward count, list, filter, exact property query, catalog query, exact zero, absent
class, or absent field:

```text
LLM call 1: compile the question into one or more typed investigations
backend: execute and validate exact results
backend: render the answer and viewer action deterministically
```

The final answer LLM should not be called when the backend already has a complete, unambiguous
answer. This should reduce both latency and the risk that a correct count is omitted, changed, or
relabelled.

## 2.2 Complex or qualitative path

For a multi-part, ambiguous, qualitative, or semantically defined question:

```text
LLM call 1: propose a bounded batch of investigations
backend: execute independent investigations, concurrently where safe
LLM call 2: inspect the compact results, select or revise the interpretation, and synthesize
backend: validate claims, evidence scope, and viewer scope
```

## 2.3 Exceptional correction path

Permit one bounded correction when deterministic checks show that the first interpretation cannot
support the requested answer. The correction is exceptional and must not become an open-ended
agent loop.

Examples of reasons to permit correction:

- only a type/style definition was selected for a physical occurrence request;
- component classes were mixed with assemblies in a count;
- a qualified concept is supported only by an unqualified broad class;
- the requested field is not populated on the selected result class;
- an exact zero conflicts with a plausible alternate representation that was not investigated;
- overlapping parent and child classes would be double-counted;
- a logical building concept, such as a floor level, was confused with raw IFC entity count;
- a graph question did not execute graph traversal;
- a multi-part question has missing result parts;
- the proposed answer scope and viewer scope do not match.

The correction input must report the concrete conflict or missing coverage. It must not ask the LLM
to restart the entire investigation without guidance.

---

# 3. Compact active-model manifest

The first LLM should no longer be intentionally blind to all active-model structure. Give it a
bounded, cached manifest that helps it choose from information the model actually exposes without
sending entity-scale data.

The manifest should be deterministic, read-only, provenance-aware, and derived from existing
ingested data. It should contain the minimum useful representation of:

- observed IFC entity classes and exact counts;
- observed relationship classes;
- occurrence versus type/style/component/relationship role;
- relevant IFC inheritance and class-family information;
- queryable attributes, type facts, property fields, and quantity fields by class;
- populated and missing coverage for fields and quantities;
- bounded common categorical values with occurrence counts;
- material and classification availability;
- logical floor/elevation bands in addition to raw `IfcBuildingStorey` entities;
- supported relationship and graph traversal capabilities;
- model/catalog identity needed to describe the active model truthfully.

The manifest must not contain:

- full canonical JSON for every entity;
- complete entity lists;
- embedding vectors;
- secrets or credentials;
- unrestricted SQL text;
- thousands of viewer identities;
- unbounded distinct property values.

When the manifest omits a value due to bounds, the LLM must be able to request a typed inspection
of that class or field rather than treating manifest absence as model absence.

---

# 4. Typed investigation interface

The LLM should request typed operations rather than generate unrestricted raw SQL. Reuse existing
safe compiler, repository, graph, RAG, source-model isolation, statement timeout, and read-only
mechanisms wherever they remain suitable.

The experimental interface should remain small and conceptually include the following capability
families.

## 4.1 Inspect model

Return compact, relevant model metadata for a requested subject or characteristic:

- candidate occurrence classes and their roles;
- exact class counts and class-family membership;
- queryable fields and coverage;
- bounded observed values and counts;
- quantity availability and units;
- relationship endpoints and supported traversals;
- logical spatial bands.

## 4.2 Execute structured query

Support safe typed operations including:

- exact count;
- bounded entity list;
- Boolean filters;
- field-value distribution;
- group-by and grouped counts;
- existence;
- populated/missing coverage;
- minimum, maximum, and sum when underlying numeric data exists;
- class-family aggregation without parent/child double-counting;
- viewer identity hydration from the same executed predicate.

## 4.3 Semantic search

Use semantic retrieval only for concepts that cannot be represented confidently by an exact
structured predicate or when the user explicitly asks for qualitative/semantic evidence.

Semantic search returns bounded candidates with provenance and coverage. Its candidate count is not
an exact model total. When an exact structured scope exists, semantic search must run inside that
scope and must never widen an empty scope to the whole model.

## 4.4 Graph traversal

Support bounded traversal for connectivity, containment, assignment, endpoints, neighborhoods, and
paths. A graph claim may be made only from executed graph results. Relationship descriptions or
broad entity classes cannot substitute for traversal.

---

# 5. Batched investigation

One LLM output may request several independent investigations. Prefer executing those queries
concurrently where the existing database/session rules allow it.

Example intent:

```text
Question: How many fire-rated walls are there, and what rating do they have?

Investigation batch:
1. Resolve the wall occurrence family and count each non-overlapping occurrence class.
2. Inspect fire-rating field coverage across that family.
3. Group populated fire-rating values and count them.
```

The LLM should receive compact results such as:

```text
wall occurrence family total: 1,981
fire-rating field: Pset_WallCommon.FireRating
populated occurrences: 720
values: EI60 = 720
```

The LLM should not receive all 720 entities unless the user requested a list or representative
details. The exact result and full viewer identities remain backend-owned.

Multiple cheap, useful database queries in one execution round are preferable to multiple
sequential LLM calls. Database investigation may increase when it decreases semantic guesswork.

---

# 6. Conversation and previous-result scope

Do not send only opaque previous entity IDs to the LLM. Preserve a typed bounded description of the
previous accepted result, for example:

```text
subject concept: doors
accepted occurrence classes: IfcDoor
exact count: 551
scope handle: previous_primary_result
source predicate: all IfcDoor occurrences in the active model
```

The backend retains the actual canonical entity scope. The LLM refers to the bounded scope handle
when resolving phrases such as `those`, `them`, or `only the external ones`.

Follow-up operations must intentionally extend, filter, replace, or aggregate the previous scope.
They must not rely on semantic similarity to the previous user sentence alone.

---

# 7. LLM authority and deterministic boundaries

The intention is to grant the LLM more authority over semantic investigation, not over database
safety or factual arithmetic.

The LLM may:

- select relevant classes and fields from the bounded manifest;
- request several typed investigations;
- compare intermediate results;
- reject an initial interpretation;
- request one bounded revision;
- decide when direct evidence is sufficient for a qualitative conclusion;
- distinguish direct evidence from indirect clues;
- synthesize qualitative findings.

Deterministic backend code retains authority over:

- source-model isolation;
- read-only enforcement;
- allowed operations, fields, operators, and traversal types;
- SQL compilation and parameter binding;
- numeric calculation and unit conversion;
- statement, row, sample, and traversal limits;
- exact counts and grouped counts;
- coverage calculations;
- canonical IDs and viewer identities;
- validation of result and viewer scope;
- enforcement of the normal and exceptional round limits;
- prompt-injection resistance at the execution boundary.

Do not add unrestricted SQL execution merely to make the system more agentic. If raw SQL is ever
considered later, it requires a separate explicit user decision and security design; it is not part
of this provisional task.

---

# 8. Insufficient IFC information

A poor or incomplete IFC file is a normal input condition, not itself a pipeline defect. The
pipeline must preserve the distinction between:

- requested class absent;
- class present but requested field absent;
- field present but requested value absent;
- exact query returned zero;
- semantic candidates found but not verified;
- operation unsupported by the current execution path;
- execution failure.

Direct typed evidence, indirect clues, and unavailable evidence must remain separate.

If the IFC does not contain enough direct evidence, the response must state that the answer cannot
be determined from the model. Indirect names, descriptions, or associated objects may be mentioned
only as explicitly labelled, inconclusive context when they are genuinely helpful. They must not be
converted into a fabricated property, classification, material, quantity, connectivity result, or
exact total.

---

# 9. Answer generation and validation

## 9.1 Deterministic answers

Render exact and unambiguous results without a final answer LLM, including:

- exact counts;
- exact zero results;
- absent classes;
- absent fields or quantities;
- exact value distributions;
- catalog listings;
- bounded database-backed sample details;
- supported-operation limitations.

## 9.2 LLM-synthesized answers

Use the second LLM call only when the user needs qualitative synthesis, semantic comparison,
interpretation of multiple evidence sources, or an answer that cannot be rendered from one exact
result contract.

The second LLM should receive accepted investigation results and explicit coverage, rather than a
large collection of broad groups it must repair.

## 9.3 Deterministic response checks

Before returning an LLM-synthesized answer, verify at minimum:

- every asserted exact number exists in an accepted investigation result;
- individual entity names come from accepted bounded evidence;
- a qualified concept is not supported only by an unqualified class count;
- type/style/component objects are not silently presented as physical occurrences;
- the answer does not claim sufficient evidence when direct evidence is unavailable;
- every requested part of a multi-part question is answered or explicitly marked unavailable;
- viewer identities derive from the same accepted executed predicate as the direct answer;
- rejected investigation results do not appear in the answer or viewer.

When these checks fail, use a safe deterministic fallback from the validated investigation results.
Do not add a third verifier LLM solely to judge the second LLM.

---

# 10. Token and latency policy

The user authorizes a moderate increase in token use when it improves model awareness, correction,
and answer accuracy.

Prefer spending tokens on:

- the compact active-model manifest;
- typed previous-result context;
- field and quantity coverage;
- compact intermediate result summaries;
- explicit competing interpretations when real ambiguity remains;
- qualitative evidence that the final LLM genuinely needs.

Do not spend additional tokens on:

- full IFC entity data;
- long repeated prompt instructions;
- large numbers of entity examples for exact questions;
- complete viewer ID lists;
- unbounded ontology descriptions;
- verbose hidden planning text that is not used by execution or validation.

The experimental path must measure actual input, reasoning, and output tokens separately. Do not
assume that a larger configured completion ceiling improves reasoning. Prefer a stronger or more
appropriate model, useful context, and explicit reasoning-effort configuration when evaluation
shows a benefit.

Normal target:

- simple exact question: one LLM call;
- complex or qualitative question: two LLM calls;
- exceptional corrected question: at most one additional bounded correction round, with its reason
  recorded.

Do not implement an unbounded inspect/query/replan loop.

---

# 11. Experimental path

Implement the proposed design first as an isolated experimental query path. It must not silently
replace the current production path during evaluation.

The experiment should reuse existing safe backend capabilities where practical, including:

- schema and model-vocabulary extraction;
- ontology hierarchy;
- typed SQL filters and compiler;
- read-only database sessions and statement timeouts;
- semantic index and scoped RAG;
- graph traversal implementation;
- session storage;
- viewer identity hydration;
- request/response contracts where they do not prevent a clean comparison.

Do not preserve existing layers merely because they already exist. The experiment is specifically
intended to determine whether the query-agent contract can simplify or retire parts of:

- query-only retrieval-policy planning;
- planner-selected SQL/RAG/graph flags;
- broad threshold-free candidate execution;
- evidence-group competition for exact questions;
- fixed example allocation for count questions;
- final group relevance judgment for exact results;
- clarification caused by one failed semantic candidate when another bounded investigation could
  resolve the question.

The experimental and existing paths must be comparable using the same model, active IFC data,
questions, and expected results. Do not tune behavior only to the literal wording in
`specs/test_query.md`; add paraphrases and structurally equivalent cases so improvements are
general rather than query-specific.

---

# 12. Observability and evaluation

Record bounded structured investigation traces for development and evaluation without exposing
private chain-of-thought. For each question, capture:

- model and reasoning configuration;
- manifest version and bounds;
- LLM-proposed investigation IDs, purposes, and typed operations;
- execution mode actually used;
- compact result counts, coverage states, and class histograms;
- whether a correction was triggered and the deterministic reason;
- accepted and rejected investigation IDs;
- deterministic versus LLM-synthesized answer path;
- viewer result count and scope identity;
- per-stage latency;
- input, reasoning, and output token usage;
- final evaluation verdict and failure category.

Do not log raw full IFC data, embeddings, secrets, credentials, unrestricted chat history, or
thousands of entity identities.

Evaluate at minimum:

- all current PASS, PARTIAL, and FAIL entries in `specs/test_query.md`;
- paraphrases of the recurring failures;
- simple exact counts;
- qualified counts and Boolean filters;
- occurrence versus type/style/component distinctions;
- exact zero, absent class, absent field, and absent quantity;
- multi-part aggregates;
- logical floor bands versus raw storey entities;
- conversational follow-up scope;
- catalog metadata;
- sample-detail intent;
- semantic qualitative questions;
- graph/connectivity questions;
- poor/incomplete IFC evidence;
- prompt injection and unsupported operations.

Compare:

- total and category-specific pass rate;
- unsupported or fabricated claims;
- answer/viewer scope agreement;
- planner/query correction rate;
- number of LLM calls;
- number of database investigations;
- p50 and p95 latency by stage;
- input, reasoning, output, and total tokens;
- exact-question deterministic bypass rate.

Lower call count, tokens, or latency is an improvement only when the final answer and viewer still
meet the required correctness and grounding criteria.

---

# 13. Model experimentation

Planner/query-agent and qualitative-answer models must remain independently configurable.

Do not change both roles simultaneously during the first comparison. Recommended experiment order:

1. current model with the new model-aware investigation contract;
2. stronger query-agent model with the current qualitative-answer model;
3. stronger query-agent plus deterministic exact-answer bypass;
4. efficient versus stronger qualitative-answer model for the remaining qualitative cases;
5. reasoning-effort comparison using the same questions and model.

This isolates whether improvement comes from the architecture, the query-agent model, the answer
model, or increased reasoning/token use.

---

# 14. Explicit non-goals of this provisional draft

- Do not send the entire IFC database to an LLM.
- Do not permit unrestricted raw SQL.
- Do not remove deterministic safety and source-model isolation.
- Do not trust the LLM for arithmetic that the database can compute exactly.
- Do not create an unbounded autonomous agent loop.
- Do not add a separate router, reranker, critic, and verifier LLM chain.
- Do not increase semantic thresholds or evidence limits as the primary fix.
- Do not tune hard-coded answers for the literal evaluation questions.
- Do not replace the production path before the experiment demonstrates a measured benefit.
- Do not treat incomplete IFC information as permission to infer a confident answer.

---

# 15. Open decisions to finalize later

This provisional Task 24 intentionally leaves the following decisions open for the user's later
additions:

- exact typed investigation schema;
- whether the correction round may issue one query batch or several dependent queries;
- exact manifest bounds and refresh/cache rules;
- model choices and reasoning-effort defaults;
- token and latency budgets;
- experimental endpoint or feature-flag shape;
- compatibility requirements for the current public response schema;
- exact production promotion criteria;
- which existing group-pipeline modules should be retired after successful evaluation;
- whether a future API migration is in scope.

Do not resolve these open decisions by assumption in the provisional implementation plan.
