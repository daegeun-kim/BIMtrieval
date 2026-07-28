# Task 25: Complete Model Semantics and Constraint-Guided Retrieval

## Goal

Replace the restrictive semantic-selection part of the current query pipeline with a complete,
model-specific semantic view that lets the first LLM understand how the active IFC model is
represented before binding the question.

Keep the current pipeline's strongest parts:

- typed plans rather than model-written SQL;
- deterministic SQL, scoped RAG, and graph execution;
- exact, zero, partial, unavailable, and ambiguous evidence states;
- compact adjudicated evidence for the final answer;
- deterministic grounding validation;
- viewer identities derived from the same executed predicate as the answer.

Replace the current information-loss points:

- model semantics are built lazily and incompletely at query time;
- the binder sees only a very small candidate slate;
- semantic similarity may reorder exact-admitted subjects but cannot admit a missing concept;
- fixed global caps can omit one subject or condition from a compound question;
- material constraints are protected mainly by token heuristics;
- an incomplete binding has no targeted recovery path.

Accuracy is the priority. Do not add a general agent loop, another retrieval store, an LLM router,
an LLM retrieval judge, model-written SQL, or more LLM calls to ordinary questions.

## Generalization rule

Do not implement a condition, mapping, prompt example, or fallback for any exact question, phrase,
IFC filename, model ID, expected count, or value in `specs/test_query.md` or
`specs/test_query_v2.md`. Those logs are acceptance evidence only.

Every change must enforce a reusable invariant: complete semantic coverage, typed constraint
provenance, correct IFC role/family semantics, source-model isolation, deterministic retrieval
authority, or grounded answering. Add unrelated and paraphrased tests for every corrected
mechanism.

---

# 1. Required data flow

```text
IFC ingestion
    -> structured entities and relationships
    -> complete compact semantic manifest for that source model
    -> existing vector generation

question + bounded history/selection
    -> validate and load the complete active-model manifest
    -> deterministic high-recall recommendations + constraint ledger
    -> LLM call 1: precise semantic binding and decomposition
    -> deterministic binding/sufficiency gate
    -> optional one-time corrective binding call, only for a proven recoverable gap
    -> authoritative SQL, scoped RAG, and/or seeded graph execution
    -> deterministic evidence coverage check
    -> compact adjudicated answer packet
    -> final grounded LLM answer
    -> deterministic answer validation and same-predicate viewer identities
```

Normally answered active-model questions use exactly two LLM calls:

1. semantic binding;
2. final grounded answer writing.

A proven difficult/incomplete binding may use one corrective call. No request may exceed three LLM
calls. SQL, RAG, and graph are derived per answer part from its bound operation; the LLM does not
choose one global mode.

---

# 2. Ingestion-generated semantic manifest

## 2.1 Lifecycle and location

Add an ingestion-owned manifest builder. Invoke it from
`ingestion/src/bim_rag/pipeline_structured.py::ifc_to_db()` after entities, relationships, and
relationship members are committed and before vector generation. This applies to every IFC passed
to `ifc_to_db()`, including files under `ingestion/ifc_original/`. Do not add a folder watcher,
polling service, or second ingestion entrypoint.

Write one file per source model:

```text
model_semantics/{source_model_id}/{full_file_fingerprint}.semantic.json
```

Use a dedicated configurable artifact root resolved consistently by ingestion and backend. Do not
mix semantic JSON with viewer fragments.

Artifact identity must contain:

- source-model ID and full IFC fingerprint;
- IFC schema and canonical extraction version;
- manifest schema version and builder version;
- deterministic semantic-content hash.

Write a temporary sibling, validate it, then atomically replace the final artifact. The same IFC
and builder/schema versions must produce identical semantic content/hash. A changed fingerprint
must create an isolated artifact; a builder/schema change must regenerate it.

Extend the unified ingestion report with artifact path, versions, hash, semantic record counts,
bytes, conservative token estimate, build time, and validation status. If generation fails, do not
report the model as fully query-ready. Keep the valid imported data so idempotent ingestion can be
rerun.

Keep `ingestion/notebooks/ingestion.ipynb` as the single notebook a user runs once to make any new
IFC model fully ready for the app. Update its documentation and executable flow so one notebook run
performs and verifies:

1. structured entity and relationship import;
2. semantic-manifest generation through the same `ifc_to_db()` implementation described above;
3. existing RAG document/vector generation;
4. existing 3D viewer artifact generation;
5. final readiness checks for database rows, matching semantic fingerprint/hash, vectors, and viewer
   artifact.

Do not duplicate manifest-building logic inside the notebook. It must call the production ingestion
pipeline and display the returned manifest path, source-model ID, fingerprint, semantic record/token
counts, and validation result. Preserve idempotency so rerunning the notebook on the same IFC safely
repairs or validates missing/stale artifacts without duplicating database data.

After the ingestion implementation is complete, invoke the new manifest builder against the
already-ingested source models 1 and 2 so both existing semantic files are physically generated and
validated. Reuse the production builder directly against their existing source-model rows and
fingerprints; do not re-import entities, regenerate vectors, or rebuild viewer artifacts merely to
perform this one-time backfill. This is an implementation execution step, not model-ID-specific
production behavior or a second ingestion entrypoint. Record both artifact paths, hashes, record
counts, token estimates, and validation results in the completion report.

## 2.2 Deterministic, concept-complete content

Generate the artifact without an LLM, using imported canonical facts, relationship rows, the IFC
schema/ontology, and existing query capability definitions. Natural-language labels may come from
observed labels, IFC identifiers/ontology, and deterministic tokenization. Never infer a building
fact from general model knowledge.

The manifest is a complete inventory of unique queryable concepts, representations,
relationships, operations, value vocabularies, and coverage states. It is not a copy of every IFC
row or full canonical JSON. Individual GUIDs and complete occurrence records remain in PostgreSQL
and existing RAG documents until a bound query retrieves them.

Include all model-specific information needed to discover and bind:

- all entity/relationship IFC classes, counts, schema roles, supertypes, present subtypes, and
  occurrence-family closure;
- `PredefinedType`, `ObjectType`, occurrence-to-type relationships, type/family/subtype names,
  subject classes, and counts;
- attributes, property/quantity sets, classifications, materials, units, data types, operators,
  aliases, applicability, and populated/missing/unsupported/extraction-failure coverage;
- useful distinct categorical, type, family, material, classification, and property values with
  counts;
- containment, assignment, aggregation, connectivity, adjacency, assembly, zone, system, and other
  relationships with endpoint roles/classes, direction, and coverage;
- storey names/elevations, containment structure, spatial organization, supported answer
  operations, whole-model inventory, recorded use indicators, and missing capabilities.

For high-cardinality identity/free-text fields, include the field concept, cardinality, coverage,
normalization, and `searchable` capability instead of every value. The query-time high-recall stage
must perform exact authoritative lookup for a requested value and add it as a request-specific
candidate. This preserves complete semantic capability without dumping occurrence data.

Do not reuse current prompt-oriented omission rules such as the 1,500-fact cap, top-value caps,
singleton removal, or rejection of fields merely because they have more than a small number of
distinct values. Deduplicate equivalent records, but never silently omit a unique semantic concept.

Each record needs stable semantic ID, source/model provenance, and enough coverage metadata for the
backend to distinguish exact zero from missing/unsupported data. IFC-provided names and
descriptions are untrusted data, never prompt instructions.

## 2.3 Four conceptual representations

Expose exactly these four views of the same authoritative model. Do not create four databases or
four independent pipelines.

1. **Object level:** individual BIM occurrences such as doors, walls, spaces, and equipment, with
   their exact attributes. The manifest records all present occurrence classes/families and their
   queryable fields; individual rows remain in the structured store until retrieval.
2. **Type/property level:** shared types, classifications, materials, property distributions,
   quantities, and aggregates. Floors may appear as a property/grouping dimension when relevant.
3. **System/relationship level:** containment, connectivity, adjacency, assemblies, zones,
   systems, assignments, and spatial organization, including floor relationships when needed.
4. **Global level:** whole-model class inventory, storey structure, major systems, materials,
   directly recorded use indicators, coverage, and missing capabilities.

Do not add a fifth or separate logical-floor-profile level and do not add floor-specific prompt
rules. Storeys, elevations, containment, and floor relationships must flow through the general
property, relationship, spatial, and global semantics. Existing storey/elevation execution logic
may remain when reached through those general semantics.

## 2.4 Complete-file size policy

Feed the complete validated active-model manifest to LLM call 1. Do not apply top-k or relevance
truncation to the manifest.

Use compact, stable, readable JSON: stable ordering, deduplication, shared dictionaries for repeated
labels where useful, and no repeated prose. Do not use binary/base64 encoding.

Several hundred to a few thousand compact semantic records are acceptable. Do not cut a complete
model inventory merely to preserve the old slate-sized prompt.

Current GPT-5.6 models have a 1,050,000-token context window. Input above 272,000 tokens costs more
and increases latency. Therefore:

- 272,000 tokens is a soft efficiency target for the complete binder request, not a truncation
  boundary;
- reserve context for instructions/schema, query/history, recommendations, ledger, reasoning, and
  output;
- derive the true hard limit from the configured model context minus those reserves;
- keep the two current project models below the 272,000-token soft target;
- if a future artifact crosses it, compact repeated representation and aggregate high-cardinality
  occurrence data without deleting unique semantic IDs/capabilities;
- if it still cannot fit the model's hard limit, mark it incompatible and report why; never silently
  truncate it during a query.

Longer questions receive the same complete manifest. Do not make room by dropping model concepts.

---

# 3. High recall, constraint ledger, and precise binding

## 3.1 Advisory candidate recommendations

Refactor the current candidate slate into high-recall recommendations. They help the binder locate
likely records but are not its allowed universe. The binder may select any valid semantic ID in the
complete manifest, plus validated request-specific candidates from exact authoritative lookup.

Remove tiny global slate caps as correctness gates. Semantic similarity must be able to admit a
plausible subject, field, value, or relationship rather than only reorder exact-admitted subjects.

Generate recommendations from the full question and relevant bounded context using:

- exact/normalized lexical matches and split IFC identifiers;
- manifest aliases, observed categorical/type/family/material/classification/property values;
- quoted values, identifiers, numbers, units, comparisons, negation, and Boolean structure;
- semantic embeddings over manifest concepts and the existing IFC ontology;
- active-model presence/coverage and exact high-cardinality value lookup;
- previous typed scope, current selection, and relationship/endpoint compatibility.

Retain every exact match before bounding semantic supplements. Diversify supplements per material
query span so one noun cannot consume a compound question. Bounds may remove duplicate semantic
supplements per span, but may not drop an exact subject, condition, relationship, scope, or answer
part. An exact absent ontology concept remains representable as absent; never replace it with an
adjacent present class merely to return data.

## 3.2 Typed constraint ledger

Before binding, create stable ledger items for every material request element and explicitly
inherited scope:

- requested subjects and independent answers;
- field/property/material/classification/type modifiers;
- quoted/named values, numbers, units, comparisons, ranges, and aggregates;
- negation and Boolean grouping;
- spatial/selection/previous-result scope;
- relationships, direction, endpoints, and path intent;
- requested output, detail, and viewer behavior.

Each item needs a request-local ID, exact source span or typed inherited provenance, source kind,
tentative role, required/optional status, and Boolean group. Keep useful existing span detection,
but do not rely on untyped token coverage alone.

The binder must mark each required item as bound subject, condition, scope, output/operation,
relationship intent, semantically redundant with another cited item, ambiguous, or unavailable.
Every executed subject/scope/condition/relationship must cite ledger IDs or typed inherited scope.
An extra constraint is valid only if it cites an exact request span missed by the pre-pass. The LLM
may not invent filters, sample conditions, subtypes, type/style records, or spatial restrictions.

## 3.3 Binder contract

LLM call 1 returns strict structured output with:

- response language and up to eight independent answer parts;
- operation, primary subject semantic ID, and explicitly requested union subjects per part;
- output fields, typed scope, conditions/operators/values/units/Boolean grouping;
- relationship/endpoint binding when required;
- viewer intent and one primary visual part where applicable;
- a disposition for every required ledger item;
- clarification only for material ambiguity that the manifest/context cannot resolve.

The model selects semantic IDs and expresses intent. It does not emit SQL, physical table/column
names, graph query text, retrieval limits/thresholds, or a SQL/RAG/graph mode. The manifest is the
semantic API; deterministic compilers own the physical database schema.

Deterministic validation must reject a missing ledger item, invented condition, invalid/source-
mismatched semantic ID, occurrence/type/property/relationship role error, incompatible field,
operator, value, unit, endpoint, Boolean group, or silently broadened interpretation.

---

# 4. One-time corrective binding

After initial binding, return one deterministic gate state:

- `ready`;
- `recoverable_binding_gap`;
- `needs_clarification`;
- `model_data_unavailable`;
- `invalid`.

Only `recoverable_binding_gap` may trigger a corrective LLM call. Examples are an unbound required
ledger span with compatible manifest concepts, incompatible field/subject or operator/unit,
invalid semantic ID with a searchable source span, or a required relationship path not attempted
because of binding mismatch.

The corrective call receives the complete cached manifest, original question/binding, typed gate
failures, and expanded candidates only around failed ledger items. It returns the same binding
schema and must preserve already valid parts and constraints. Revalidate it deterministically.

One correction budget applies to the whole request. If execution later proves a binding/path
mismatch and the budget is unused, correction may revise and re-execute only affected answer parts.
No second correction is possible.

Never correct an exact zero, proven missing IFC field/relationship, honest unavailable/partial
state, genuine ambiguity, provider failure, or final prose/grounding failure. Failed correction
ends as clarification/unavailable, never as a broadened query.

---

# 5. Retrieval, evidence, answer, and viewer

Keep existing typed executors and derive the method per answer part:

- SQL for exact identities, counts, lists, fields, distributions, quantities, comparisons, and
  aggregates;
- SQL-scoped RAG for genuinely qualitative ranking over an already bound subject/scope;
- seeded graph traversal for containment, connectivity, membership, adjacency, assignment,
  aggregation, assemblies, systems, and paths;
- cached deterministic global facts for whole-model summaries, with bounded authoritative queries
  only where necessary.

The four semantic levels do not create four execution engines. Execute only the adjudicated
interpretation of each answer part; do not execute competing subjects and ask the final LLM to
choose. RAG/graph context never becomes exact count authority.

Compare executed evidence coverage with the plan and ledger. This deterministic check may consume
the single correction budget only for a proven binding/path mismatch, never for valid zero or
unavailable evidence.

Use the final LLM for uniform active-model responses, including exact, zero, partial, unavailable,
and clarification packets. It receives the question/language, adjudicated facts with stable fact
IDs, values/units/coverage, bounded examples, and necessary model-limit notes. It does not receive
the full manifest, rejected candidates, SQL, raw graph dumps, similarity scores, or viewer ID lists.
Pure state-changing controls that do not answer a BIM question may remain deterministic.

When data is insufficient, say what the IFC cannot determine. Distinguish “not represented in this
IFC” from real-world nonexistence. Never fill a gap from model knowledge.

Retain deterministic final validation and safe fallback without another LLM call. Viewer identities
must come from the same authoritative predicate. Do not highlight types, styles, property
definitions, or supporting graph components unless explicitly requested.

---

# 6. OpenAI roles, Responses API, and caching

Use these accuracy-first defaults:

| Role | Model | Reasoning |
|---|---|---|
| Initial semantic binder/decomposer | `gpt-5.6-sol` | `high` |
| Conditional corrective binder | `gpt-5.6-sol` | `xhigh` |
| Final grounded answer writer | `gpt-5.6-terra` | `medium` |

The first role is the hardest interpretation step; the second is rare and handles proven difficult
gaps; the final role expresses already adjudicated evidence. Do not use `gpt-5-nano`. Do not use
Luna, `max` reasoning, or pro mode by default. Keep roles independently configurable but implement
these defaults. If a configured model is unavailable, fail clearly; never silently substitute.

Migrate `backend/app/llm/client.py` from Chat Completions to the Responses API and strict Structured
Outputs. Use role-specific output limits; the final writer needs a smaller limit than either
binder.

For binder/correction prompts:

1. place stable instructions/output contract and complete manifest first;
2. add an explicit cache breakpoint after the manifest;
3. append variable query, history, selection, recommendations, ledger, and correction details;
4. key the cache by role, model/effort, source-model ID, fingerprint, manifest hash, and prompt
   version;
5. invalidate it when any keyed value changes.

Record role, model, effort, prompt version, uncached/cached/cache-write tokens, output/reasoning
tokens where available, latency, and call count. Report cold-manifest and warm-cache performance
separately.

## 6.1 Terminal API cost reporting

Extend the existing backend terminal token-usage summary so every completed query also prints the
calculated OpenAI API cost in US dollars for each LLM role and for the complete request. A request
with the optional correction must include all three calls in its total.

Use a small versioned local pricing registry keyed by exact model and actual service tier. Do not
perform a network pricing lookup during a user query. Store the official pricing URL, verification
date, and rates with the registry so it can be updated deliberately when OpenAI pricing changes.

For the standard API tier, use these official rates verified on 2026-07-21. All values are USD per
1,000,000 tokens:

| Model | Uncached input | Cached input | Cache write | Output, including reasoning |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol` | $5.00 | $0.50 | $6.25 | $30.00 |
| `gpt-5.6-terra` | $2.50 | $0.25 | $3.125 | $15.00 |

Calculate each call using mutually exclusive billable token buckets:

```text
call_cost_usd =
    uncached_input_tokens / 1_000_000 * uncached_input_rate
  + cached_input_tokens   / 1_000_000 * cached_input_rate
  + cache_write_tokens    / 1_000_000 * cache_write_rate
  + output_tokens         / 1_000_000 * output_rate

request_cost_usd = sum(call_cost_usd for every LLM call in the request)
```

Derive non-overlapping buckets from the Responses API usage object. Do not charge cached or
cache-write tokens again as uncached input. Reasoning tokens are billed as output tokens and must
remain visible in diagnostics, but must not be added on top of the provider's billable output total.

Use the actual model and returned service tier for each call. Apply an official long-context or
non-standard-tier rate only when that rule exists in the versioned registry. If a model/tier/rule is
unknown, print `cost unavailable` with the reason rather than reporting zero or a guessed amount.

Print sufficient decimal precision for small calls and keep numeric totals available to diagnostics
and `test_query_v3.md`, for example:

```text
[OpenAI cost] binder=$0.012345 correction=$0.000000 answer=$0.004321 total=$0.016666 USD
```

Do not replace the current token summary; print cost beside it. The OpenAI billing dashboard remains
the external billing authority, while this terminal value is the request cost calculated from the
captured usage and the recorded official rate card.

Use the current official documentation as the API source of truth:

- [models](https://developers.openai.com/api/docs/models);
- [GPT-5.6 guidance](https://developers.openai.com/api/docs/guides/latest-model);
- [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching);
- [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs);
- [API pricing](https://developers.openai.com/api/docs/pricing);
- [reasoning-token billing](https://developers.openai.com/api/docs/guides/reasoning#how-reasoning-works).

---

# 7. External reference decision

No external repository is approved for code/dependency reuse. Do not add or copy RAPTOR, Microsoft
GraphRAG, KG2RAG, DIN-SQL, CRAG, RAGChecker, or ARES. Their implementations assume unstructured
text chunks, add large dependency/LLM stacks, duplicate existing IFC infrastructure, or use
incompatible evaluation data.

Adopt only these ideas natively:

- [RAPTOR](https://github.com/parthsarthi03/raptor) and
  [GraphRAG](https://github.com/microsoft/graphrag): multiple abstraction levels, generated
  deterministically from IFC rather than recursive text clustering/summarization;
- [KG2RAG](https://github.com/nju-websoft/KG2RAG): semantic seeds followed by IFC graph expansion;
- [DIN-SQL](https://github.com/MohammadrezaPourreza/Few-shot-NL2SQL-with-prompting): schema linking
  and decomposition without LLM-written SQL;
- [CRAG](https://github.com/HuskyInSalt/CRAG): one deterministic-gated corrective attempt without
  web search or a trained evaluator;
- [RAGChecker](https://github.com/amazon-science/RAGChecker) and
  [ARES](https://github.com/stanford-futuredata/ARES): measure retrieval/binding/execution/answering
  separately using this project's structured ground truth, not new LLM judges.

Do not add another vector database, graph store, orchestration framework, recursive summarizer,
web retrieval, or external evaluation stack.

---

# 8. Implementation scope

Modify the active pipeline in place. Do not create another endpoint, feature flag, compatibility
path, or parallel orchestration tree.

Required ingestion work:

- add the manifest builder/schema and shared artifact-root configuration;
- invoke it at the Phase 3/Phase 4 boundary in `pipeline_structured.py`;
- extend `reporting.py` with manifest diagnostics;
- document the generated `model_semantics/` root and keep real artifacts as local generated data.

Required backend work:

- add a versioned manifest schema, loader, fingerprint/source validator, and process cache under
  `backend/app/query/semantic/`;
- replace the binder's active dependency on the lazy capped vocabulary with the artifact;
- refactor `binding/slate.py` into advisory high-recall recommendations; do not retain the old slate
  as a second gate;
- update `llm/binder_context.py`, LLM schemas/prompts, `binding/spans.py`, and
  `binding/validate.py` for full manifest, ledger, and sufficiency states;
- add one correction method beside the binder method and one request-wide budget in
  `binding/pipeline.py`;
- retain/adapt `execute.py`, evidence states, packet building, answer validation, and viewer
  hydration;
- migrate `llm/client.py`, settings, and usage logging to the role/API/cache contract in Section 6;
- remove the candidate builder's separate logical-floor semantic special case while retaining
  general storey/elevation/containment execution support.

Reuse the current vocabulary builder's aggregation concepts, but do not run old capped and new
manifest builders as competing active semantic sources. Keep one documented JSON contract between
the ingestion writer and backend loader. Do not add a database migration only to store the derived
file path.

---

# 9. Required tests and diagnostics

## 9.1 Ingestion/manifest

Test deterministic content/hash, atomic replacement, same-fingerprint reuse, builder/schema-version
regeneration, changed-fingerprint isolation, source-model validation, corrupt/missing/stale artifact,
all four representation sections, and soft/hard size handling.

Use a varied synthetic IFC/DB fixture to verify classes, occurrence/type/family relationships,
properties, quantities, materials, classifications, relationship endpoints, spatial facts,
coverage, and missing capabilities survive serialization. Verify high-cardinality fields remain
searchable rather than dumped/treated as absent, no semantic concept is silently capped, no LLM or
embedding call occurs, and ingestion reports artifact metrics.

Assert that the binder receives the complete validated manifest in semantic content and the final
answer writer does not.

Test `ingestion/notebooks/ingestion.ipynb` as the one-run readiness workflow. Its cells must call the
production pipeline, expose semantic-generation results, and validate database, semantic, vector,
and viewer readiness without containing a second manifest implementation. After the one-time
backfill, verify real fingerprint-matched semantic artifacts exist and load successfully for source
models 1 and 2.

## 9.2 Candidate recall and ledger/binding

Across unrelated concepts and multiple models, test:

- exact subjects/fields/values always survive;
- embeddings can admit a non-lexical concept;
- compound questions retain every subject/condition/answer part;
- recommendations are diversified per material span;
- a valid manifest ID outside recommendations can be selected;
- exact absent concepts are not replaced by present neighbors;
- high-cardinality values are found by exact authoritative lookup;
- occurrence/type/style/property/component/relationship/spatial roles remain distinct;
- multilingual/paraphrased terms work where supported.

Test ledger coverage for values, singular/plural forms, Boolean properties, negation, AND/OR,
numeric comparisons/units, aggregates, requested outputs, selected/previous/spatial scope,
relationships, and multi-part questions. Reject missing constraints, invented filters, ungrounded
scope, invalid IDs/units/operators, incompatible fields/endpoints, Boolean flattening, and prompt
injection stored in IFC text.

Measure required-concept recommendation recall and ledger/binding accuracy separately from final
answer quality.

## 9.3 Correction/calls

With injected binder fixtures, prove:

- ready questions use two calls;
- a recoverable gap uses one correction and three calls;
- correction receives typed failures and targeted expansion, preserving valid parts;
- only changed parts may be re-executed;
- no second correction is possible;
- exact zero, unavailable data, genuine ambiguity, provider failure, and final-answer failure do not
  trigger correction;
- failed correction ends honestly rather than broadening.

## 9.4 Retrieval/evidence/viewer

Test exact object/property SQL, type/property aggregates, scoped qualitative RAG, seeded graph
traversal, global summaries, all evidence states, independent multi-part results, and final grounding.
Exact totals must not change with example/viewer limits. Final facts and viewer identities must use
the same predicate, with no unrelated fallback highlights.

## 9.5 OpenAI client/performance

Mock calls to verify Responses API, strict schemas, exact role defaults/efforts, role-specific output
limits, no silent model fallback, manifest-first prompt order, cache breakpoint/key invalidation,
cached/cache-write metrics, and bounded retries/call counts.

Add cost tests with known token fixtures for Sol binder, Sol correction, and Terra answer calls.
Cover uncached input, cache hits, cache writes, output with reasoning details, a mixed three-call
request, unknown model/tier, and decimal rounding. Assert token categories are not double-counted,
per-role costs sum to the printed request total, and an unknown price never becomes `$0.00`.

For live runs record manifest size, cold/warm cache behavior, tokens by type/role, correction reason,
per-role/request USD cost and rate-card version, stage/total latency, database statements, RAG/graph
work, authoritative result, final fallback, and viewer count.

## 9.6 Full suite

Run every query/session sequence in `specs/test_query.md` against its specified model. Compare with
`specs/test_query_v2.md` and create `specs/test_query_v3.md` with the same questions/expectations plus:

- required semantic IDs and ledger constraints;
- recommendation recall and initial/corrected binding;
- authoritative pre-answer result, final answer, viewer count, and verdict;
- execution methods, model/effort, calls, token/cache metrics, per-role/request USD cost, pricing
  registry version, database statements, and timings;
- correction/fallback reason and first failing component for any non-pass.

Add held-out paraphrases and unrelated synthetic cases. Never change an expected result to match the
pipeline.

---

# 10. Acceptance and completion

Task 25 is complete only when:

- every ingested source model has one valid fingerprint-matched manifest;
- source models 1 and 2 have generated, validated semantic files and their artifact evidence is
  recorded in the completion report;
- `ingestion/notebooks/ingestion.ipynb` remains the one-run path that makes a new IFC fully ready,
  including semantic generation and readiness validation;
- the artifact is deterministic, concept-complete, LLM-free, and includes exactly the four required
  representations;
- current project models' complete binder requests stay below the 272,000-token soft target without
  semantic truncation;
- recommendations achieve full required-concept recall on the annotated suite but never restrict
  valid manifest choices;
- every material constraint survives ledger, binding, and execution;
- subject roles, fields, values, units, scope, relationships, Boolean logic, and derived executor are
  correct;
- every objectively answerable existing-suite case is correct at the authoritative pre-answer
  layer;
- unavailable is accepted only when source evidence proves the information absent/unsupported and
  the answer states that limitation without fabrication;
- exact/zero/partial/unavailable/ambiguous states remain distinct and answer/viewer identities agree;
- ordinary questions use Sol binder + Terra answer, only a deterministic recoverable gap adds one
  Sol correction, and no request exceeds three calls;
- final validation failure uses deterministic fallback without another call;
- prompt caching is correctly keyed/measured and cold/warm performance is reported against Task 24;
- the terminal retains total token reporting and also prints correct per-role and total USD cost from
  the versioned official pricing registry, without double-counting cached/reasoning tokens;
- no candidate fan-out, agent loop, extra retrieval store, external reference code, query-specific
  patch, or severe unbounded token/latency path is introduced;
- source isolation, read-only queries, SQL allowlists, graph limits, session/selection, viewer, and
  entity details remain functional.

Update these source-of-truth specifications during implementation:

```text
specs/spec_v001_ifc_to_db.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
```

Implement in this order: manifest generation/loading; full-manifest recommendations/ledger; binder
and one-time correction; execution/final/API integration; component and full-suite validation.

After validation, append a concise completion report with final schema/version, model 1/2 semantic
artifact evidence, notebook readiness result, data flow, models, pricing-registry version, tests, v3
results, per-role/request USD cost, cold/warm token and latency comparison, correction frequency,
and genuine limitations. Rename to `tasks/task25_done.md` only after all acceptance items pass.
