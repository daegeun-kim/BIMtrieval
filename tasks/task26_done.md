# Task 26: Executable Semantic Contract, Loss-Aware Hybrid Retrieval, and Continuous Query Tracing

## Goal

Turn the current Task 25 pipeline into `experiment2_v4` by removing the remaining
places where a fact is described at one stage but cannot be resolved, compiled,
validated, or reported at the next stage.

The central requirement is:

> Every model fact offered as queryable must carry one continuous, testable contract
> from source evidence to a logical operation, an applicable physical access path,
> an execution result, an answer claim, and a viewer set.

This is not a request to add more prompt text, more retrieval stores, or more LLM
calls. The semantic artifact and runtime payloads must become smaller and clearer
while becoming more executable.

Keep the current pipeline's strongest properties:

- model-specific semantics generated during ingestion;
- typed model output rather than model-written SQL;
- deterministic SQL, RAG, and graph execution;
- exact, zero, partial, unavailable, and ambiguous result states;
- normally two LLM calls: binding and final grounded writing;
- at most one targeted corrective binding call;
- exact viewer identities derived from an explicitly identified result set;
- no ungrounded fallback to a broader class or the whole model.

Add the missing properties:

- one versioned semantic access contract shared by manifest generation, resolution,
  validation, and compilation;
- applicability and coverage per semantic concept, subject class, operation, and
  access path;
- normalized, provenance-bearing spatial membership that works across containment
  and aggregation representations;
- a deterministic retrieval-requirement ledger rather than a list of keywords;
- always-parallel lexical, typo-tolerant, value, dense, and structural recall;
- a typed logical query algebra that can express presence, grouping, grouped
  argmax, samples, profiles, and bounded multi-hop traversal;
- proof of coverage before an exact zero is allowed;
- useful partial answers whenever a safe sub-result exists;
- scoped but sufficiently broad RAG evidence for qualitative synthesis;
- stage-local handling of provider failures;
- one permanent append-only query log that records the complete diagnostic flow of
  every app query.

## Owner decisions and constraints

These are settled requirements, not implementation questions:

1. Task 25 is complete. Build on the current repository and do not reopen or rename
   `tasks/task25_done.md`.
2. `tasks/solution.md` is reference material only. Keep it unchanged; adopt only
   proposals that survive inspection of the current code and all four models.
3. Repository-wide changes are authorized, including ingestion and additive database
   schema/index changes when they remove a structural loss point.
4. Do not modify the configured LLM models, add an LLM stage, or change anything
   outside this repository.
5. The normal active-model path remains two LLM calls. One corrective call is allowed
   only for a proven mechanical binding gap.
6. The total measured provider cost of one app query must not exceed USD 0.03.
7. "Floor" means an occupiable/usable building floor unless the user explicitly asks
   for raw IFC storeys, reference levels, roof levels, or another meaning.
8. Ask a clarification when materially different interpretations remain. If any
   independent or contextual portion is still safe, return it as a partial result
   rather than discarding it.
9. RAG evidence is useful for qualitative and incompletely structured questions. The
   final LLM may synthesize from a bounded, slightly broader evidence set, but RAG
   evidence never proves an exact count or absence.
10. Embedding retrieval is an always-run parallel recall channel, not a lexical
    fallback. It must be cached/precomputed so this requirement does not re-embed the
    manifest for each ledger item.
11. Do not solve recall by sending the entire database, every stored value, duplicate
    manifest views, or a larger candidate slate to the binder.
12. Every request submitted through the app's query endpoint must append one terminal
    record to one permanent, Git-tracked JSONL file. Do not rotate, truncate, or
    overwrite it.
13. Existing query/failure logs should be migrated as explicitly incomplete
    `experiment2_v3` records. Never fabricate intermediate data the old logs did not
    capture.
14. Bad, malformed, or genuinely missing IFC data may remain unavailable. The system
    must identify that limitation accurately; it is not required to infer a real-world
    answer the source does not support.

---

# 1. Audited baseline: what the four models prove

The design must be based on all four currently ingested models, including the two new
samples. The following measurements were read from the generated manifests and live
database, not inferred from the v3 answers.

| Metric | Model 1 | Model 2 | Model 3 (new) | Model 4 (new) |
| --- | ---: | ---: | ---: | ---: |
| Source | Schependomlaan | FOJAB Landsarkivet | SampleArchitecture | Wellness Center |
| Queryable entities | 6,989 | 20,975 | 102,403 | 4,705 |
| Relationships | 3,473 | 19,938 | 99,895 | 3,565 |
| RAG documents | 10,462 | 40,913 | 202,298 | 8,270 |
| Present entity classes | 22 | 41 | 36 | 39 |
| Raw `IfcBuildingStorey` rows | 1 | 45 | 8 | 5 |
| `IfcSpace` rows | 0 | 778 | 187 | 0 |
| Manifest bytes | 97,304 | 401,062 | 455,211 | 204,686 |
| Conservative manifest tokens (`bytes / 3`) | about 32k | about 134k | about 152k | about 68k |
| Flattened manifest concepts | 263 | 646 | 1,014 | 595 |

All four models have complete RAG embeddings, but RAG text truncation is real:
approximately 2,336 documents in model 1, 297 in model 2, 376 in model 3, and 18 in
model 4 are marked truncated. A truncated document can still provide evidence; it can
never prove that an omitted fact was absent.

## 1.1 Spatial representation is class- and exporter-dependent

Models 2 and 3 independently expose the same representation:

- model 2 has 778 `IfcSpace` rows; all 778 have
  `canonical_json.storey = null`;
- model 3 has 187 `IfcSpace` rows; all 187 have
  `canonical_json.storey = null`;
- in both models, 100% of those spaces are linked to an
  `IfcBuildingStorey` through `IfcRelAggregates`;
- ordinary elements such as doors, windows, and walls generally carry a denormalized
  scalar storey derived from `IfcRelContainedInSpatialStructure`.

The current manifest's spatial coverage counts only
`canonical_json.storey.global_id`. The current predicate compiler also turns every
floor scope into that same scalar JSON predicate. Information is therefore present in
the relationship tables, lost from the manifest's executable description, and then
reported as a false zero.

This is not an `IfcSpace` special case. It is evidence that spatial membership is a
zero-to-many relationship with multiple valid access mechanisms, while the current
pipeline models it as one nullable scalar.

## 1.2 Raw storeys are not occupiable floors

- Model 2's 45 storey rows include ordinary levels, underside-of-slab levels,
  multi-wing sublevels, and roof references. Elevation clustering produces nine
  physical bands, but the lowest band has no room-category spaces and the highest
  band is roof-only.
- Model 3 has eight clean elevation levels, while room-category spaces occur on only
  three of them. Absence of spaces on the other levels may describe source quality,
  not proof that those levels are unusable.
- Model 4 contains `Street level`, misspelled `Grond floor`, `First floor`,
  `Roof floor`, and `Roof`. It contains no `IfcSpace`, so a spaces-only floor rule
  would fail even though ordinary architectural elements provide useful evidence.
- Model 1 has one storey and no ordinal ambiguity.

Minimum/maximum raw elevation and raw `IfcBuildingStorey` count are therefore not
valid definitions of "first floor", "top floor", or "how many floors".

For the recorded model 2 follow-up sequence, relationship-derived evidence shows:

- 568 total room-category spaces;
- 57 room-category spaces in the first band with strong room/occupancy evidence;
- 36 room-category spaces in the uppermost band with strong room/occupancy evidence;
- 203 wall occurrences and 18 windows in that first occupiable band.

These values are diagnostic ground truth for the representation loss. They must not
be encoded as model-specific rules.

## 1.3 Field applicability and coverage are currently over-broad

The manifest currently measures a property field against all rows carrying its
container and gives the field the union of all classes carrying that container. That
loses the association between field and subject class.

Observed examples:

- Model 3 `Identity Data.Number` is advertised as applicable to 25 classes with
  aggregate partial coverage, but its 187 populated rows are all `IfcSpace`.
- Model 4 `Pset_ProductRequirements.Name` is advertised across roughly 32 classes,
  but its populated rows are only the five `IfcBuildingStorey` rows.
- Model 2 `Pset_WallCommon.FireRating = EI60` is distributed across both
  `IfcWall` and `IfcWallStandardCase`; the aggregate 720/1,981 total hides each
  class's separate applicability and coverage.

A binder can therefore select a real field for an incompatible class, validation can
accept it, SQL can return zero, and the pipeline can label that zero exact. This is a
manifest-structure defect, not an LLM wording defect.

Materials and classifications have the same issue. "Populated" currently means that
some value exists for the class, not that every eligible object carries one. Examples
include 1 of 6 model 2 ramps with material data, 15 of 60 model 3 stairs, and 9 of 13
model 4 slabs. Classification coverage is also sparse, such as 318 of 551 model 2
doors and 2 of 435 model 3 doors.

## 1.4 Descriptive and executable semantic universes diverge

Current code exposes concepts that cannot be executed:

- materials and classifications exist in canonical entity JSON and in the manifest,
  but the recommendation field adapter excludes them;
- relationship endpoint-role concepts exist, but relationship candidates are built
  from the parent relationship concept's empty applicability field, so direction and
  endpoint compatibility disappear;
- high-cardinality fields are marked `searchable`, but request-time authoritative
  value linking is not implemented;
- the manifest contains no symbolic compiler/access-path capability;
- semantic IDs can exceed the 40-character limit in parts of the LLM output schema.

The reverse divergence also exists:

- logical floor bands, building profiles, presence predicates, grouped argmax, and
  other compiler operations are not represented as stable semantic capabilities;
- quantities are declared absent solely because `quantity_sets` is empty, even when
  area/volume-like numeric facts occur in reliable property paths or reversible
  exporter wrappers;
- a broad `IfcBuilding` row is accepted as a target for a summary or cost question,
  even though counting or describing that row cannot answer the requested metric.

## 1.5 Prompt size duplicates the same information

The binder receives:

1. the complete manifest as the stable instruction prefix; and
2. a dynamic `CandidateSlate` that serializes the complete subjects, fields, values,
   spatial candidates, and relationships again.

For model 2 the logged dynamic slate is about 1.5 MB and includes more than 6,300
value candidates. Binder calls are around 132k prompt tokens. The larger new model 3
manifest is already about 152k conservative tokens before dynamic duplication.

Embedding recall currently runs only when lexical recall returns fewer than three
hits and re-embeds the remaining concept texts per ledger item. This contradicts the
required always-parallel recall behavior and does unnecessary work.

## 1.6 Result meanings and failure handling are overloaded

Current execution assigns a base predicate count to `exact_total` before knowing the
operation-specific answer set. Consequences visible in v3 include:

- a fire-rating distribution reports all 1,981 scanned walls instead of the 720
  walls with a recorded rating;
- `sample_detail` reports/highlights all 551 eligible doors instead of one sample;
- a union count is presented where separate requested counts were needed;
- grouped argmax cannot represent floor + per-floor count + top-one ordering;
- graph execution caps seeds at 50 and can still label the result exact;
- scoped RAG materializes the full SQL scope into a Python ID list, which is unsafe
  for the new 102,403-entity model.

Provider errors are also request-wide. A corrective-call 429 currently discards the
whole request and returns "The language model is currently unavailable", even when
an initial plan or safe partial result exists. An answer-writer failure should never
discard an already executed deterministic result.

## 1.7 Current logs cannot locate the loss

The current success log omits the exact ledger, recommendations, binder output,
validation, compiled predicates, SQL, RAG/graph evidence, exact delivered envelope,
and highlighted GlobalIds. Failures are written to a second file with only a short
error. The active pipeline is also mislabeled `task24_binding`.

The requested continuous diagnostic use case is therefore impossible from the
current logs alone.

---

# 2. Failure taxonomy and causal grouping

Use the following stable failure codes in validation, evaluation, and the continuous
log. Do not group failures merely by the final wrong answer.

| Code | Loss stage | Meaning | Recorded examples |
| --- | --- | --- | --- |
| `SOURCE_UNRESOLVABLE` | IFC/extraction | Source structure is malformed, ambiguous, or lacks the requested fact | genuinely absent units/quantities; unsupported wrapper fragments |
| `FACT_PATH_DROPPED` | canonical facts | A valid alternate relationship/property path was not preserved as queryable | spaces related to storeys only through aggregation |
| `MANIFEST_CAPABILITY_GAP` | manifest | Data is present but no executable capability/access path is advertised | materials, classifications, spatial aggregation |
| `MANIFEST_APPLICABILITY_ERROR` | manifest | Coverage/applies-to is aggregated across incompatible subjects | M3/M4 property examples above |
| `RESOLUTION_RECALL_MISS` | recommendation | The correct executable concept exists but no useful candidate reaches its ledger slot | typos, multilingual terms, high-cardinality values |
| `LEDGER_ROLE_ERROR` | ledger | A phrase is fragmented, mis-typed, or treated as a keyword without an executable obligation | broad building topic; "fire rated"; thematic requests |
| `BINDING_OMISSION` | binder | A resolvable requirement is absent or bound to the wrong role/part | missing presence condition; merged compound parts |
| `UNSUPPORTED_LOGICAL_SHAPE` | binder schema | User intent cannot be represented by the typed plan | grouped argmax; true one-sample result; multi-hop traversal |
| `COMPILER_ACCESS_GAP` | compiler | A valid logical node has no physical adapter or is silently compiled away | floor scalar-only path; `IS_PRESENT` returning no predicate |
| `COVERAGE_PROOF_GAP` | pre-execution gate | Execution could run, but completeness/applicability cannot justify exact/zero | partial materials; capped graph seeds |
| `RESULT_SET_MISMATCH` | execution/result | Scanned, matched, grouped, sampled, and viewer sets are conflated | B9, C4, C8 |
| `EVIDENCE_SCOPE_ERROR` | RAG/graph | Evidence is unscoped, truncated without disclosure, or a bounded miss is treated as absence | broad circulation retrieval; exact graph after seed cap |
| `ANSWER_GROUNDING_ERROR` | final answer | Generated claims or terminology are not supported by the answer packet | frequent deterministic fallbacks in v3 |
| `PROVIDER_STAGE_FAILURE` | LLM client | Binder, correction, or answer call fails; stage determines recoverability | Swedish correction 429; first-floor window correction 429 |
| `TRACE_INCOMPLETE` | observability | A request has no terminal record or lacks the stage needed to diagnose it | current split success/failure logs |

The v3 non-passes and the user's live sequence group as follows:

- **Spatial fact/access loss:** space-by-floor queries, room follow-ups, and any
  subject whose storey is represented through a relation rather than the scalar path.
- **Floor semantic loss:** "first floor", "top floor", and "how many floors" when raw
  reference/roof/sublevels are treated as occupiable levels.
- **Manifest/executor drift:** door/building materials, classifications, connectivity,
  and values marked searchable but not linked.
- **Ledger/binding contribution loss:** cost mapped to `IfcBuilding`, circulation
  mapped to all spaces, accessibility causing total refusal, and broad topics
  satisfying retrieval obligations.
- **Logical operation/result-set loss:** fire-rated distribution, one sample detail,
  separate compound counts, and floor grouped argmax.
- **Provider/answer loss:** corrective-call TPM failures and valid results discarded
  because answer terminology was absent from the packet.
- **Observability loss:** no exact binder/SQL/viewer trace for the above.

## 2.1 Recorded non-pass/query-to-cause map

The first failing stage below is the one Task 26 must repair or classify honestly.
Later symptoms are consequences, not separate root causes.

| Query/case | First information loss | Downstream symptom | Required structural response |
| --- | --- | --- | --- |
| B4, "Describe the circulation of this building" | `LEDGER_ROLE_ERROR`: the theme does not become executable thematic requirements | all 778 spaces become the exact result and weakly scoped RAG describes that broad set | thematic-profile logical result with resolved structured concepts plus bounded RAG |
| B5, construction cost | `LEDGER_ROLE_ERROR`: `IfcBuilding` topic is accepted in place of the requested cost metric | one building row is presented as if it answered cost | topic cannot discharge metric; return unavailable unless a cost capability/evidence resolves |
| B6, spaces on second floor (marked pass in v3) | `FACT_PATH_DROPPED`: benchmark and compiler both inspect only scalar storey | relationship-backed spaces are mislabeled an expected zero | re-audit ground truth through effective membership and version the corrected expectation |
| B7, door materials | `MANIFEST_CAPABILITY_GAP`: material values are described but excluded from executable fields | correction cannot produce a legal material predicate/output and the query declines | ordinary material field capability with per-class coverage and compiler adapter |
| B9, fire-rated wall count/distribution | `COMPILER_ACCESS_GAP`: `IS_PRESENT` produces no physical predicate | all 1,981 scanned walls become the reported exact total instead of the covered 720 | real presence predicate plus covered/matched distribution result |
| B11, top floor contents | floor-semantic `FACT_PATH_DROPPED`: highest raw roof reference is treated as top occupiable floor | exact zero on a roof-only band | derived occupiable bands, explicit interpretation, and clarification on uncertain boundary |
| B12, spaces connected to stairs | `UNSUPPORTED_LOGICAL_SHAPE` plus missing relationship meaning/path | whole query is declined despite available graph facts | typed traversal contracts; clarify if "connected" is not represented unambiguously |
| B14, building summary | `UNSUPPORTED_LOGICAL_SHAPE`: global profile is represented as one `IfcBuilding` occurrence | exact total 1 supplies no useful summary evidence | derived building-profile result with structured aggregates and scoped evidence |
| B16, accessible/wheelchair ramps | gate/result partiality loss | six known ramps are discarded because accessibility classification is unavailable | return "6 ramps; accessibility unknown" as contextual partial, never six accessible ramps |
| B18, floor count | raw storey target is substituted for occupiable-floor intent | 45 reference/sublevel rows are called floors | separate raw-storey and derived occupiable-floor targets |
| C4, one sample door | `RESULT_SET_MISMATCH`: eligible predicate cardinality is reused as answer/viewer cardinality | 551 reported/highlighted instead of one sample | typed sample result with eligible count and one deterministic sample/viewer ID |
| C7, Swedish window count | `RESOLUTION_RECALL_MISS`/`BINDING_OMISSION` leads to a full corrective call | 130k-token correction hits TPM and returns generic unavailability | always-parallel multilingual/dense recall, compact correction, stage-local failure |
| C8, three counts plus floor with most doors | `UNSUPPORTED_LOGICAL_SHAPE`: separate parts and grouped argmax are not representable reliably | 1,060 union count and a global 551-door "extremum" | independent peer counts plus group/aggregate/order/limit |
| C9, "What is this building made of?" on model 1 | heterogeneous wrapper is suppressed container-wide; material relations are absent and RAG text is often truncated | query declines even though some reversible wrapper facts may exist | expose only structurally parseable wrapper subsets; remain unavailable for the rest |
| room follow-up, "top floor" | scalar space membership is absent and top raw band is roof-only | false zero | inherited room predicate + effective spatial membership + top occupiable band |
| room follow-up, "first floor" | scalar space membership is absent and lowest raw band has no room evidence | false zero | inherited room predicate + effective membership + first occupiable band |
| walls on first floor | first raw elevation band is treated as first occupiable band | zero despite 203 walls in the first strongly occupiable band | floor interpretation repair; existing wall membership can then execute |
| windows on first floor | floor semantics/ledger cause a corrective call whose duplicated prompt exceeds TPM | generic "language model unavailable" | floor/recommendation repair, compact correction, and correction-stage degradation |

---

# 3. Core architecture: one executable semantic contract

## 3.1 Separate four things that are currently conflated

Use these terms consistently in code and documentation:

1. **Canonical occurrence facts**
   - Per-entity/per-relationship source facts in PostgreSQL.
   - Preserve values, source identity, and extraction warnings.
   - Do not send them wholesale to an LLM.

2. **Semantic access contract**
   - A small, versioned, repository-owned declaration of supported logical
     capabilities and symbolic physical adapters.
   - Contains no model occurrences and no LLM instructions.
   - Defines which roles, operators, grains, output shapes, and access-path IDs are
     legal.

3. **Model semantic manifest**
   - A deterministic ingestion artifact stating which contract capabilities are
     present for one model, for which subject classes, with what coverage,
     provenance, unit status, and resolvability.
   - Contains no SQL and no full occurrence dump.

4. **Request resolution packet**
   - The small, dynamic ledger, candidate recommendations, exact value matches,
     scopes, and bounded context for one question.
   - Contains no duplicate complete candidate universe.

The binder receives a complete compact projection of item 3 as a stable cacheable
prefix and item 4 as the dynamic request. Backend validation retains the full parsed
manifest in memory. The final answer model receives neither the manifest nor rejected
recommendations.

## 3.2 Add a repository-owned contract

Add a versioned contract under a neutral repository path such as:

```text
semantic_contract/
  access_contract_v001.json
  semantic_manifest_v002.schema.json
  README.md
```

Both ingestion and backend may read these data files through their own small readers;
do not make either Python package import the other.

The access contract must declare symbolic adapter IDs such as:

- `entity.class`;
- `json.attribute`;
- `json.property_value`;
- `json.quantity_value`;
- `json.material_name`;
- `json.classification_field`;
- `spatial.effective_membership`;
- `relationship.member_edge`;
- `derived.physical_floor`;
- `derived.building_profile`;
- `derived.thematic_profile`.

Names are illustrative, but each final ID must be stable and versioned. Physical table
names, JSON paths, joins, SQL snippets, and vector-store implementation details remain
backend-owned and are never sent to the binder.

For every logical capability the contract declares:

- semantic kind and grain;
- permitted uses: `target`, `filter`, `scope`, `group`, `aggregate`, `order`,
  `report`, `traverse`, or `topic_context`;
- data type and legal operators;
- legal output/result shapes;
- required subject and endpoint compatibility;
- symbolic physical adapter/access-path ID;
- whether unit metadata is required;
- whether exact absence can be proved;
- whether the result can produce viewer-hydratable entities.

## 3.3 Bidirectional completeness checks

At build/test time, enforce both directions:

1. Every manifest capability marked executable resolves to a registered backend
   compiler adapter supporting the declared role/operator/result shape.
2. Every backend compiler capability intended for binder use is represented in the
   access contract and emitted by the manifest when supported.
3. A descriptive/non-queryable concept may remain visible only with
   `executable: false`, an explicit reason, and no executable roles.
4. No compiler adapter may silently accept a semantic kind or operator it did not
   declare.

Do not require every descriptive concept to compile. Require every claimed executable
capability to compile.

## 3.4 Proof-carrying execution invariant

Every executed logical node must retain:

```text
ledger requirement
→ selected semantic concept
→ permitted use
→ applicable subject/endpoint
→ symbolic access path
→ model-specific coverage/provenance
→ compiled physical node
→ result-set contribution
```

Validation must be able to walk that chain before execution. The continuous query log
must record the bounded identifiers and verdicts needed to inspect it afterward.

---

# 4. Ingestion and canonical fact structure

## 4.1 Preserve relationship authority; do not duplicate the graph into every entity

Keep `ifc_relationships` and `relationship_members` as the authoritative general IFC
edge store. The current direct `canonical_json.storey` value may remain as a fast,
backward-compatible observation, but it is not the definition of spatial membership.

Do not add every relationship or inverse relationship as a large nested array inside
each entity's canonical JSON.

## 4.2 Add normalized effective spatial membership

Create one ingestion-owned normalized projection for entity-to-storey membership. An
additive table is recommended because the same relation is required by manifest
generation, floor derivation, SQL predicates, RAG scoping, follow-up scopes, viewer
hydration, and diagnostics:

```text
entity_spatial_memberships
  source_model_id
  entity_id
  entity_global_id
  storey_entity_id
  storey_global_id
  source_relationship_id
  source_kind
  hop_count
  resolution_status
  is_primary
  provenance
```

Final column types/names may follow repository conventions, but the following meaning
is mandatory:

- zero-to-many memberships per entity;
- `source_kind` distinguishes direct containment, aggregation, and any supported
  bounded nested path;
- `resolution_status` distinguishes resolved, dangling, and ambiguous facts;
- provenance identifies the IFC relationship role/path without copying full source
  JSON;
- an effective distinct `(entity, storey)` view is available even if multiple source
  paths corroborate it;
- source-model isolation is part of every key and predicate.

Populate this projection deterministically after relationship members exist. Backfill
all four current models through the production ingestion path.

If measurement shows that a SQL view over existing tables meets all latency and
provenance requirements without duplicating rows, a view is acceptable instead of a
table. This decision must be made from `EXPLAIN (ANALYZE, BUFFERS)` on models 2 and 3
and recorded in the Task 26 completion report. Do not retain two active authorities.

Add only indexes justified by the compiled access patterns. At minimum, benchmark
lookups by `(source_model_id, entity_id)`, `(source_model_id, storey_global_id)`, and
relationship role/path. Avoid a broad new entity-fact table.

## 4.3 Preserve metric meaning and units

Capability is semantic, not determined solely by whether a value happened to land
under `quantity_sets`.

During ingestion:

- preserve declared IFC property/quantity unit information when present;
- resolve project unit assignments through one deterministic unit registry;
- store normalized numeric magnitude and canonical unit only when conversion is
  provable;
- retain the original magnitude/unit for provenance;
- distinguish a numeric value with unknown unit from a unitless value;
- do not permit cross-unit comparison or aggregate when the unit contract is unknown.

A reliably named area or volume fact in a property path may support an area/volume
capability if its meaning and unit are provable. It must not be called unavailable
merely because `quantity_sets` is empty. Conversely, a number whose metric or unit is
unclear remains descriptive/unavailable.

## 4.4 Segment heterogeneous exporter wrappers; do not suppress a whole container

Replace container-wide all-or-nothing reliability with field- and class-specific
assessment.

For exporter wrappers:

- parse only reversible, deterministic namespace syntax;
- for example, a key that structurally encodes a property-set/quantity namespace may
  be split without guessing its business meaning;
- group reliability by source namespace, field signature, and subject class;
- emit stable subsets and leave unparseable/noisy subsets unavailable;
- preserve the original source path as manifest-level provenance rather than copying
  it into every binder record;
- never add a rule for a filename, model ID, expected query, or observed answer.

This allows reliable facts inside model 1's Synchro/ArchiCAD wrapper and model 3's
heterogeneous `Other` container to survive without dumping thousands of unstable keys
into the manifest.

## 4.5 Distinguish fact endpoints from viewer entities

Material and classification endpoints may be valid IFC facts while lacking GlobalIds
and therefore lacking `ifc_entities` rows. Relationship coverage must separately
record:

- endpoint fact present/resolvable;
- endpoint entity resolvable;
- endpoint viewer-hydratable.

A material name can be reported or filtered without pretending it is a selectable
viewer object.

## 4.6 Ingestion readiness

Update the existing one-run ingestion notebook and production pipeline so a completed
model verifies:

1. canonical entities and relationships;
2. normalized spatial memberships;
3. semantic manifest v002 and binder projection metrics;
4. RAG documents and embeddings;
5. viewer artifact;
6. catalog metadata required for the model to appear in the app.

Models 2–4 currently lack catalog entries. Readiness must either create a minimal
deterministic entry from source metadata or explicitly report catalog setup as
incomplete; it must not call those models fully app-ready while omitting them from the
catalog.

---

# 5. Semantic manifest v002

## 5.1 Replace duplicated descriptive views with normalized capability records

Keep the existing artifact location and fingerprint isolation:

```text
model_semantics/{source_model_id}/{full_fingerprint}.semantic.json
```

Bump the manifest schema and builder versions. Do not overwrite a v001 artifact under
the same identity/version.

The v002 artifact should have one normalized semantic record namespace. The four v001
conceptual views may be derived by readers for diagnostics, but do not serialize
duplicate copies of the same concept merely to preserve four sections.

A representative field capability is:

```json
{
  "id": "prop:Pset_WallCommon.FireRating",
  "kind": "field",
  "label": "Fire rating",
  "aliases": ["fire rated", "fire resistance rating"],
  "grain": "entity",
  "uses": ["filter", "group", "report"],
  "data_type": "text",
  "operators": ["equals", "not_equals", "is_present", "is_missing"],
  "accessor": "json.property_value",
  "applicability": [
    {
      "subject": "cls:IfcWall",
      "coverage": "present_partial",
      "known_count": 4,
      "eligible_count": 52
    },
    {
      "subject": "cls:IfcWallStandardCase",
      "coverage": "present_partial",
      "known_count": 716,
      "eligible_count": 1929
    }
  ],
  "value_policy": "request_lookup",
  "provenance": ["property_sets.Pset_WallCommon.FireRating"]
}
```

This is an example of structure, not a requirement to hardcode these counts or aliases.
Generate observed counts from the active model.

## 5.2 Sparse applicability without false certainty

Coverage must be keyed by:

```text
semantic concept × subject class × operation/access path
```

For each applicability entry record:

- eligible subject count;
- known/populated count;
- distinct value count where meaningful;
- coverage state;
- accessor/path ID;
- provenance/resolution status;
- unit state for numeric operations;
- whether complete scanning can prove absence.

Use a sparse representation:

- serialize classes for which a capability is populated, explicitly checked absent,
  unsupported, or failed;
- use a finite contract-defined domain to infer omitted `checked_absent` cases;
- do not enumerate every imaginable IFC property as absent;
- do not claim open-world absence for a capability the extractor did not check.

Required coverage states must distinguish at least:

- `present_complete`;
- `present_partial`;
- `checked_absent`;
- `source_unresolvable`;
- `extractor_unsupported`;
- `extraction_failed`.

Map them to user-facing exact/partial/unavailable behavior by operation. For example,
`checked_absent` can prove `is_present` matches zero and `is_missing` matches the
eligible set, but it cannot produce an average value.

## 5.3 Make materials and classifications ordinary executable fields

Represent material and classification facts through field-like capabilities with
normal roles/operators/coverage:

- `material.name`;
- `classification.system`;
- `classification.code`;
- `classification.description`.

Use entity canonical JSON as the normal fast path when it already contains normalized
facts. Relationship endpoints are provenance/fallback paths. The binder should not
need a special non-executable "material concept" that validation accepts but the
compiler cannot use.

## 5.4 Traversal contracts

For each relationship class, derive explicit role-pair traversal records:

```json
{
  "id": "path:IfcRelVoidsElement.RelatingBuildingElement->RelatedOpeningElement",
  "kind": "traversal",
  "relationship": "IfcRelVoidsElement",
  "from_role": "RelatingBuildingElement",
  "to_role": "RelatedOpeningElement",
  "direction": "outgoing",
  "from_classes": ["IfcWall", "IfcWallStandardCase", "IfcSlab"],
  "to_classes": ["IfcOpeningElement"],
  "relationship_count": 2069,
  "resolved_from_count": 2069,
  "resolved_to_count": 2069,
  "accessor": "relationship.member_edge",
  "max_supported_hops": 1
}
```

Generate both supported directions when valid. Keep role names and endpoint classes
together; do not flatten them into unrelated concepts.

For bounded multi-hop paths, compose validated one-hop contracts in the logical plan.
Do not enumerate every possible path in the manifest or infer real-world adjacency
from co-membership alone.

## 5.5 Derived spatial concepts

The manifest must expose both:

- raw IFC storeys/reference levels; and
- derived physical/occupiable floor candidates.

Derive physical bands from elevation with robust outlier handling. Each band records:

- member storey IDs and names;
- elevation range and derivation version;
- effective entity/space/room/opening/furnishing counts;
- positive and negative occupancy evidence;
- classification: `occupiable`, `non_occupiable_reference`, or `uncertain`;
- confidence/reason codes and provenance.

Names may contribute evidence, including roof/reference terminology and misspellings,
but cannot be the sole authority. Spatially assigned spaces and ordinary
architectural-use elements are stronger evidence. Roof-only/slab-only bands are
negative evidence.

Resolution rules:

- ordinal and "top" floor default to `occupiable` bands;
- an `uncertain` boundary band that materially changes the answer triggers a concise
  clarification listing the available interpretations;
- an explicit raw-storey/name query may select raw storeys;
- a model with one unambiguous storey resolves normally;
- floor interpretation and evidence are always logged and summarized to the user.

Do not add model-specific floor names, IDs, or elevation thresholds.

## 5.6 Derived profile capabilities

Add executable profile concepts instead of using a broad `IfcBuilding` occurrence as
the answer:

- `derived.building_profile` for global class/spatial/material summary;
- `derived.thematic_profile` for a user-named theme such as circulation, envelope,
  or accessibility.

A thematic profile is not a hardcoded list for one query. It uses the resolved ledger
theme, executable related concepts, bounded structured aggregates, and scoped RAG
evidence. If no relevant facts resolve, it is unavailable rather than a description
of one `IfcBuilding` row.

`IfcBuilding` may remain as `topic_context` or an explicit occurrence target. It may
not discharge a cost, use, summary, or thematic retrieval requirement unless it
contributes an executable field/profile node.

## 5.7 Value policy and artifact size

Do not serialize complete value vocabularies in the binder-facing projection.

- Low-cardinality values may retain at most a few representative examples for
  diagnostics.
- Every executable field supports bounded authoritative request-time value lookup.
- High-cardinality values are never omitted as a capability; they use
  `value_policy: request_lookup`.
- Exact user values, fuzzy matches, and stored normalization are sent only in the
  request resolution packet for the relevant ledger slot.

The machine artifact may retain compact diagnostic counts, but the stable binder
projection must omit:

- full value lists;
- duplicate class inventories;
- verbose repeated limitation prose;
- raw GlobalId occurrence sets;
- raw canonical JSON;
- SQL/JSON physical paths;
- embeddings.

## 5.8 Binder projection

Derive a deterministic, complete, compact binder projection from the v002 manifest.
It must include every binder-selectable semantic ID and enough information to choose
correctly:

- ID, kind, label, bounded aliases;
- permitted uses and operators;
- subject/endpoint applicability;
- concise coverage state;
- symbolic accessor/path ID;
- derived floors/profile/traversal contracts.

Backend validation uses the full parsed manifest, not the serialized prompt
projection.

Remove the dynamic serialization of the complete `CandidateSlate` universe. The
dynamic request includes only:

- ledger/retrieval requirements;
- bounded per-slot recommendations;
- exact request-time value matches;
- available request scopes;
- bounded history/selection metadata.

Performance targets on the current corpus:

- the complete binder projection for the largest current model is at most 80,000
  estimated tokens and materially below the v001 full-manifest request;
- the request-specific dynamic payload is at most 12,000 estimated tokens for the
  acceptance suite;
- model 2 and model 3 total binder input is reduced by at least 40% from the
  comparable v3 cold request;
- no executable semantic concept is truncated to meet the target;
- ordinary cached queries do not resend a duplicate universe or value catalog.

---

# 6. Deterministic retrieval-requirement ledger

## 6.1 Replace word accounting with phrase-level obligations

Keep the ledger deterministic, but make it model- and execution-aware.

The ledger is a graph of request requirements, not a bag of meaningful words. It must
represent:

- requested operation;
- target entity/value set;
- optional topic context;
- filter/qualifier;
- spatial or inherited scope;
- grouping;
- aggregate;
- ordering/extremum;
- limit/sample size;
- traversal/relationship intent;
- requested output/projection;
- qualitative evidence theme;
- viewer intent;
- Boolean/conjunction links and answer-part hints.

A multi-word phrase should normally be one requirement. Do not generate a phrase
subject plus one required condition for every individual word.

Examples:

- "external walls" creates a target requirement for walls and a filter requirement
  for externality;
- "curtain walls" may resolve as one target class rather than an invented
  `curtain = true` condition;
- "this building" is normally `topic_context`/active-model scope, not a required
  `IfcBuilding` extraction target;
- "construction cost" is one requested metric/output requirement that cannot be
  discharged by the word "building";
- "which floor has the most doors" creates target, group, aggregate, order, and
  limit requirements.

## 6.2 Two deterministic ledger phases

Build the ledger in two deterministic phases:

1. **Intent skeleton**
   - Detect exact source spans, phrases, quoted values, numbers, units, negation,
     ordinals, conjunctions, inherited/selection references, operations, and output
     language.
   - Preserve the user's exact text and character offsets.

2. **Model resolution**
   - Attach required capability/use, candidate semantic IDs, applicability,
     access-path availability, and a resolution state from the manifest and
     recommendation engine.

The LLM does not create or delete ledger requirements. It binds/decomposes the typed
requirements.

## 6.3 Required ledger record

Each material requirement must carry at least:

```json
{
  "id": "L3",
  "source_text": "fire rated",
  "start": 14,
  "end": 24,
  "role": "filter",
  "required_use": "filter",
  "target_hint": "L1",
  "required": true,
  "resolution": "resolvable",
  "candidate_ids": ["prop:Pset_WallCommon.FireRating"],
  "partial_policy": "return_base_set_as_context_only"
}
```

Required resolution states:

- `resolvable`;
- `ambiguous`;
- `checked_absent`;
- `not_representable`;
- `unsupported_operation`.

Keep source provenance for inherited scope and viewer selection distinct from current
question text.

## 6.4 Contribution, not mention

A ledger requirement is discharged only when its selected semantic ID contributes to
a compatible typed logical node.

- a filter requirement must contribute a filter/presence node;
- a scope requirement must contribute a scope node;
- a grouping requirement must contribute a group node;
- an ordering/extremum requirement must contribute order + limit;
- a relationship requirement must contribute a typed traversal path;
- a requested output must appear in the result projection;
- a topic-context concept does not discharge an executable requirement.

Validation must compare dispositions to logical node IDs and later to dry-compiled
physical nodes. A model cannot silence the ledger by emitting `bound_condition`
without an actual condition.

## 6.5 Partial-answer policy

An unresolved material requirement remains in the ledger. It is never dropped.

Examples:

- "Are there accessible ramps?" may safely report the total ramps as contextual
  evidence while saying the model does not determine how many are accessible.
  It must not call all ramps accessible.
- "What is the construction cost?" has no useful independent result merely because
  one building row exists. It is unavailable, not "1".
- a compound request with two valid parts and one unavailable part executes the two
  valid parts and reports the third limitation.

The ledger must state whether a safe contextual/base result exists and how it may be
used. The compiler and answer packet, not the final prose model, enforce the
difference between requested and contextual sets.

---

# 7. High-recall recommendation and value resolution

## 7.1 Run independent channels for every material slot

For each ledger requirement, always run all applicable channels:

1. exact and normalized phrase/alias matching;
2. IFC identifier and singular/plural matching;
3. character n-gram or bounded edit-distance typo matching;
4. authoritative stored-value linking;
5. dense semantic similarity;
6. capability/use compatibility;
7. subject/endpoint/access-path applicability;
8. optional local graph-neighborhood support for relationship slots.

"Always run" means the channels contribute independent ranked lists. It does not mean
every channel must return a candidate.

Dense retrieval must not be conditional on weak lexical recall.

## 7.2 Cache concept embeddings by manifest hash

Build one normalized concept-vector matrix per manifest content hash:

- embed each distinct concept/alias text once;
- cache the matrix and ID ordering process-wide;
- embed each material query span once;
- invalidate on manifest hash, embedding model, normalization version, or concept
  text change;
- do not serialize vectors into the prompt or query trace;
- do not re-embed all remaining concepts for every ledger item.

A deterministic on-disk sidecar is allowed only if cold-start measurement justifies
it and fingerprint/model/version invalidation is complete. Prefer the simpler
process cache first.

## 7.3 Fuse ranks, then enforce structural compatibility

Use Reciprocal Rank Fusion as the initial score-normalization-free baseline for
lexical, typo, value, and dense ranked lists. Treat the fusion choice as measurable:
retain per-channel ranks in diagnostics and compare against a tuned deterministic
weighted fusion on the annotated suite.

After fusion:

- reject uses the concept does not support;
- reject subject/endpoint combinations with no applicable path;
- distinguish `descriptive_only` from executable;
- boost exact stored-value identity and exact alias matches;
- diversify per ledger slot and answer-part hint;
- never allow a semantically similar but non-executable concept to outrank the only
  applicable executable concept solely due to embedding score.

## 7.4 Request-time value linking

Implement the v001 manifest's promised authoritative lookup:

- search only fields compatible with the ledger slot/subject candidates;
- preserve exact quoted values;
- support normalized case/Unicode/locale matching;
- surface typo/fuzzy alternatives with match kind and stored value;
- keep per-field provenance so a value from one field cannot bind another;
- bound returned matches and database work;
- log the lookup query summary, candidate field IDs, matched values, and ranks.

Do not enumerate all high-cardinality values before the request.

## 7.5 Recommendation record and prompt meaning

Each recommendation sent to the binder must say how it could be used:

```json
{
  "ledger_id": "L3",
  "concept_id": "prop:Pset_WallCommon.FireRating",
  "label": "Fire rating",
  "use_as": "filter",
  "supported_operators": ["equals", "is_present", "is_missing"],
  "applicable_subjects": ["cls:IfcWall", "cls:IfcWallStandardCase"],
  "coverage": "present_partial",
  "accessor": "json.property_value",
  "channels": ["alias", "embedding"],
  "channel_ranks": {"alias": 1, "embedding": 3},
  "fused_rank": 1
}
```

Recommendations remain advisory. The binder may select any compatible ID in the
complete compact manifest projection. They are high-recall hints, not retrieved
evidence and not proof that a fact exists on every entity.

Use a bounded top-k per ledger slot, with a small guaranteed allocation for every
material slot in compound questions. A global prompt cap may trim low-ranked extras
only after every slot retains its minimum allocation.

---

# 8. Binder and typed logical query algebra

## 8.1 Binder role

The first LLM:

- maps ledger requirements to manifest semantic IDs;
- decomposes independent answer parts;
- chooses semantic roles/operators and typed logical structure;
- declares unresolved/ambiguous requirements;
- does not select SQL/RAG/graph as a route;
- does not write physical schema, JSON paths, SQL, vector limits, or graph algorithms;
- does not decide whether evidence is sufficient after execution.

The prompt must explicitly distinguish:

- complete manifest universe;
- advisory high-recall recommendations;
- exact authoritative value matches;
- topic-context concepts;
- executable capabilities;
- descriptive-only concepts;
- requested result set versus safe contextual result.

## 8.2 Replace the flat answer part with a static discriminated algebra

Evolve the strict output schema so an answer part can contain typed nodes for:

- target entity/value set;
- filter or presence predicate;
- spatial scope;
- traversal path;
- group-by;
- aggregate;
- order-by;
- limit/sample;
- projection/output fields;
- result kind;
- viewer-set policy;
- unresolved requirement.

Required result kinds:

- `entity_set`;
- `scalar`;
- `distribution`;
- `sample`;
- `profile`;
- `qualitative_evidence`;
- `graph_endpoints`.

Use a static discriminated Pydantic schema. Do not generate a dynamic enum containing
every manifest ID, because that duplicates the manifest and destabilizes cache size.
Validate IDs/kinds/capabilities deterministically against the loaded manifest.

Use one shared semantic-ID length limit that safely accepts every manifest ID, or
adopt a tested compact stable-ID scheme. No valid manifest ID may be rejected merely
because a Pydantic field still has a 40-character Task 24 limit.

## 8.3 Required logical shapes

The algebra must express:

- text/numeric/Boolean equality and comparisons;
- `is_present` and `is_missing`;
- flat bounded AND/OR with preserved grouping;
- relationship-backed spatial membership;
- separate requested counts for compound peer subjects;
- field distribution over only the matching/covered set;
- grouped aggregate + order + limit for "which group has most";
- a real sample with `limit = 1`;
- global and thematic profiles;
- one-hop and bounded composed multi-hop traversals;
- exact previous-result/selection scope;
- contextual base sets for partial answers.

The LLM output must remain bounded: maximum parts/nodes/depth should match compiler
limits and be enforced by schema.

## 8.4 Typed requested, contextual, and viewer sets

Do not use an unchecked prose `answer_set`. Every part must identify:

- `requested_set`: entities/values satisfying all resolvable requested constraints;
- `context_set`: an optional base set that may be reported only as contextual partial
  evidence when a required constraint is unavailable;
- `viewer_set`: `requested_set`, `context_set`, one sample, graph endpoints, or none;
- the reason a contextual set is allowed.

The model chooses from legal policies; deterministic validation verifies them against
ledger resolution and result kind.

## 8.5 Common cached prefix for initial and correction calls

The initial binder and corrective binder must share an actually identical stable
prefix containing the compact manifest and common contract instructions. Put
request/correction-specific instructions after that prefix.

The corrective call receives:

- the original typed plan;
- exact mechanical validation/dry-compile failures;
- affected ledger/node IDs;
- a bounded expanded candidate/value set for only those failures;
- immutable valid parts it must preserve.

Do not resend a duplicate universe in the dynamic correction payload.

---

# 9. Deterministic validation, sufficiency gate, and cost budget

## 9.1 Validation layers

Run these layers in order and log each verdict:

1. **Schema/structural validation**
   - strict result shape, node counts, IDs, Boolean groups, and references.

2. **Manifest identity validation**
   - every selected ID exists in the active fingerprint-matched manifest.

3. **Capability/use validation**
   - concept kind supports target/filter/group/report/traverse use and operator.

4. **Applicability validation**
   - concept/access path is valid for the selected subject and endpoint classes.

5. **Ledger contribution validation**
   - every resolvable required ledger slot maps to a compatible logical node;
   - every narrowing node maps to question/inherited provenance;
   - broad topic concepts do not discharge executable requirements.

6. **Unit/value validation**
   - value belongs to the selected field; unit conversion is deterministic.

7. **Traversal validation**
   - role pair, direction, endpoints, and composed-hop compatibility are legal.

8. **Dry compilation**
   - every logical node compiles to a physical node without executing it.

9. **Coverage proof**
   - selected subject × operation × accessor coverage supports the proposed result
     status and exactness.

10. **Result-shape validation**
    - requested, contextual, and viewer sets are coherent for the operation.

## 9.2 Per-part gate states

Replace request-wide all-or-nothing behavior with per-part states:

- `ready`;
- `partial_executable`;
- `correctable_binding_gap`;
- `needs_clarification`;
- `unavailable`;
- `invalid`.

Request behavior:

- execute all `ready` parts;
- execute the safe plan/context for `partial_executable` parts and preserve their
  unknown requirements;
- ask a clarification for materially ambiguous parts;
- attempt one correction only for mechanical `correctable_binding_gap` parts;
- never correct an honest source absence/unresolvable capability;
- never let one failed part erase independent valid parts.

## 9.3 Exact zero requires a proof

An exact zero is legal only when all are true:

- target semantics resolved;
- every required filter/scope/traversal compiled;
- selected access paths are applicable to the target classes;
- coverage state proves the operation was checkable for the relevant eligible set;
- execution completed without truncation/cap;
- no required ledger item remains ambiguous/unavailable;
- the final matched cardinality is zero.

Record a compact coverage proof in the physical plan/result. A bounded RAG miss,
unresolved field, incompatible class, capped graph seed set, or unknown unit can never
produce an exact zero.

## 9.4 Correction policy

One correction is allowed only for:

- missing/mis-kinded ledger disposition;
- invalid manifest ID where compatible candidates exist;
- omitted logical node;
- illegal but locally replaceable operator/result shape;
- dry-compile failure with a known compatible capability.

Do not correct:

- checked absence;
- source-unresolvable/extraction failure;
- genuine floor/relationship ambiguity;
- provider failure;
- final-answer grounding failure;
- a result that is already safely partial.

## 9.5 USD 0.03 request budget

Add a request-scoped deterministic budget manager using the existing versioned price
registry:

- track actual token categories/cost after every completed call;
- estimate the next call from serialized prompt tokens, cache status when known,
  configured maximum output, and rate card;
- reserve enough budget for the final answer call before permitting correction;
- skip correction and return partial/clarification if the conservative estimate would
  exceed USD 0.03;
- bound output tokens per role;
- never report unknown pricing as zero;
- log estimated, reserved, actual, and skipped-call budget decisions.

Prompt compaction is the primary solution. The budget gate is the final safeguard, not
a reason to drop semantic requirements.

---

# 10. Predicate compiler and physical plans

## 10.1 Compile a typed relational AST

Refactor the predicate compiler around the access contract. A physical plan should
support:

- class/family entity sets;
- JSON attribute/property/quantity/material/classification fields;
- value and presence predicates;
- normalized spatial membership joins/`EXISTS`;
- relationship role-pair joins;
- bounded composed traversal paths;
- group, aggregate, order, and limit;
- samples;
- reusable predicate subqueries for RAG and graph seeding;
- derived building/thematic profiles.

Do not add query-specific SQL strings. Map symbolic accessor IDs to allowlisted
SQLAlchemy compiler adapters.

## 10.2 Spatial predicate

A logical floor scope compiles against effective spatial membership, not directly
against one JSON field. The same compiler shape works for spaces, walls, doors,
windows, or another class because manifest applicability chooses the available
membership access path.

Direct scalar storey may be used as an indexed fast path only when its per-class
coverage proof is complete for the selected operation. Relationship-backed membership
must cover the remainder. The logical plan does not change by class.

## 10.3 Presence and missing predicates

Implement `is_present` and `is_missing` as real physical predicates. They must never
return `None` and disappear.

For partially covered fields:

- `is_present` selects rows with a usable value;
- `is_missing` selects eligible rows without one;
- distribution/aggregate reports both matched and covered denominators;
- exactness follows the operation-specific coverage proof.

## 10.4 Materials, classifications, and numeric facts

Add compiler adapters for normalized material/classification arrays and qualified
numeric facts. Support:

- filter by exact/normalized value;
- presence/missing;
- distribution;
- output projection;
- numeric comparison/aggregate only with compatible known units.

Do not force material/classification lookup through viewer-entity relationship
endpoints when the canonical fast path already holds the fact.

## 10.5 Grouped argmax and samples

For "which floor has the most doors":

```text
target doors
→ group by derived floor
→ count per group
→ order descending
→ limit 1
```

Return the winning floor and its count, plus tie handling. Do not report the global
door count as the extremum result.

For `sample`:

- retain `eligible_cardinality`;
- deterministically choose one sample with a stable order/seed policy;
- `answer_cardinality = 1`;
- viewer set contains only that sample;
- do not overload the eligible total as the answer.

## 10.6 No Python materialization of large scopes

Replace full predicate-to-Python-ID-list RAG scoping with a database-side subquery/CTE
or equivalent joined filter. The same logical predicate must seed SQL, RAG, graph, and
viewer operations without sending 100k IDs through Python or a giant `IN` list.

## 10.7 Physical-plan diagnostics

The compiler returns a serializable diagnostic form containing:

- logical node IDs;
- selected accessor/path IDs;
- tables/roles at a symbolic level;
- parameterized SQL statement role and fingerprint;
- typed/redacted parameters;
- expected coverage proof;
- whether result completeness depends on a cap;
- result-set selector IDs.

The binder never sees this form.

---

# 11. RAG and graph retrieval

## 11.1 How the semantic pipeline affects all three retrieval modes

Recommendations do not directly execute SQL, RAG, or graph queries. Their selected
concepts become the binder's typed logical plan, which then affects all three:

- SQL uses target, filter, scope, group, and aggregate nodes;
- RAG uses the validated target/predicate subquery and requested qualitative theme;
- graph uses the validated seed predicate and traversal contracts;
- graph-expanded entities may then scope associated RAG evidence.

The manifest and recommendations therefore affect RAG/graph through validated seeds,
paths, and evidence intent, not through SQL-only keywords.

## 11.2 Scoped, slightly broader RAG evidence

For qualitative/profile/partially structured parts, retrieve a bounded evidence
bundle with:

- a primary high-relevance slice;
- a small diversity/near-neighbor slice below the primary cutoff;
- entity and relationship documents associated with validated SQL/graph scope;
- explicit unscoped fallback only when structured scope is unavailable;
- document/entity/relationship IDs, similarity scores, text-truncation flag, and
  bounded excerpts.

The final LLM may decide which supplied excerpts are useful for qualitative
synthesis. It may not:

- turn candidate count into an exact total;
- infer absence from a miss;
- override deterministic SQL counts;
- assert a graph connection not returned by traversal.

Keep the total evidence packet within a measured token budget. More evidence is useful
only while context relevance and answer faithfulness remain stable.

## 11.3 Typed graph execution

Graph execution must use:

```text
validated subject predicate
→ complete or explicitly bounded seed set
→ validated relationship role/path contracts
→ endpoint/entity facts
→ optional associated RAG documents
```

Record:

- seed selector and cardinality;
- traversed seed cardinality;
- role/path IDs, direction, and hop limit;
- relationship/path count;
- endpoint fact/entity counts;
- truncation/completeness;
- bounded result IDs.

If only 50 of 500 seeds are traversed, the result is illustrative/partial, never
exact. Exact graph results require complete seed coverage or a database-side traversal
that proves completeness.

Do not call co-containment "connected" unless the selected traversal meaning is made
explicit and accepted. Ask a clarification when "connected" could mean fills/voids,
path connection, spatial containment, adjacency not present in IFC, or another
materially different relation.

## 11.4 No GraphRAG re-indexing stack

Do not add Microsoft GraphRAG's LLM-extracted graph, community summaries, another
vector database, or a second graph store. The IFC relationship tables are already the
authoritative graph. Adopt only the seed → bounded graph expansion → associated text
evidence pattern.

---

# 12. Operation-specific results, answer packet, and viewer

## 12.1 Replace overloaded `exact_total`

Use discriminated result variants. They must expose only meaningful cardinalities:

- `EntitySetResult`
  - scanned cardinality;
  - matched/answer cardinality;
  - exactness/coverage;
  - selector for answer entities.
- `ScalarResult`
  - function/value/unit;
  - covered and eligible cardinalities.
- `DistributionResult`
  - base cardinality;
  - covered cardinality;
  - bucket counts;
  - missing count.
- `SampleResult`
  - eligible cardinality;
  - sample cardinality;
  - selected sample.
- `ProfileResult`
  - structured profile facts and qualitative evidence IDs.
- `QualitativeEvidenceResult`
  - evidence IDs/excerpts and scope/completeness limitations.
- `GraphEndpointResult`
  - seed/traversed cardinality;
  - endpoint/path counts;
  - completeness.

Retain the public response contract where practical, but populate
`result_summary.exact_total` only when it truly represents the requested answer.
Additive fields may clarify scanned, covered, answer, and viewer cardinalities.

## 12.2 Partial result contract

Every partial result carries:

- exact known facts;
- unknown/unresolvable requirements;
- whether known facts describe the requested set or only a contextual base set;
- safe viewer policy;
- concise limitation/provenance.

The final answer must state the split. It must not blend "six ramps exist" with "six
ramps are accessible".

## 12.3 Answer packet

The final answer packet contains:

- every answer part and status;
- operation-specific structured facts with stable fact IDs;
- requested/contextual distinction;
- resolved interpretation labels, including floor;
- allowed domain terminology derived from selected semantic concepts;
- bounded RAG excerpts with evidence IDs;
- bounded graph path/endpoints;
- limitations and coverage;
- primary viewer part/policy.

It does not contain:

- full manifest;
- rejected recommendation universe;
- raw canonical rows;
- embeddings;
- unbounded GlobalId lists;
- model reasoning;
- unrelated evidence.

## 12.4 Final claim validation

Extend structured claims:

- numeric/structured claims cite `fact_id`;
- qualitative model claims cite one or more supplied `evidence_id` values;
- connection claims cite a graph/path fact;
- limitation claims cite the result limitation.

Include selected subject/scope/property labels in the packet's grounded terminology
allowlist. The validator must permit ordinary wording such as "rooms", "first floor",
or the selected storey name when that term came from the validated plan/result. Do not
loosen it to arbitrary BIM nouns.

If final generation fails or validation rejects it, return a deterministic
operation-aware fallback from the same results. Never discard an exact SQL result
because the answer writer is unavailable.

## 12.5 Viewer contract

Viewer identities come from the typed `viewer_set`, not from whichever predicate was
scanned first.

- exact/list entity set: matching answer entities;
- sample: the one sample;
- distribution: the filtered/covered set appropriate to the question;
- graph result: selected endpoint set if requested;
- contextual partial: only when policy explicitly allows it, labeled as context;
- zero/unavailable/ambiguous: no fallback highlights.

Log exactly the GlobalIds sent to the frontend, the total matching viewer set,
truncation, and action. Do not log all database rows.

---

# 13. Stage-local provider and runtime failures

Handle failures at the stage that owns them:

- **Initial binder unavailable**
  - no safe logical plan exists;
  - return the stable provider-unavailable response;
  - terminal trace says `binding_llm`.
- **Correction unavailable**
  - retain the initial valid/partial parts;
  - execute them when safe;
  - report the unresolved mechanical gap;
  - do not replace the whole response with generic LLM unavailability.
- **Answer writer unavailable**
  - return deterministic fallback from the answer packet;
  - viewer/result remain intact.
- **SQL part failure**
  - preserve independent successful parts;
  - mark the failed part unavailable/partial with stage/error code.
- **RAG degradation**
  - keep structured results;
  - disclose qualitative evidence unavailable;
  - never convert to zero.
- **Graph degradation/cap**
  - return partial/illustrative graph result with completeness metadata.

Respect provider `Retry-After` through the existing bounded SDK retry policy, but do
not add an unbounded sleep or another semantic call. Prompt-size reduction and
stage-local degradation are the fixes for the recorded correction TPM failures.

---

# 14. Permanent continuous query log

## 14.1 One tracked append-only file

Create one active log:

```text
backend/app/evaluation/query_trace.jsonl
```

This path is intentionally inside a tracked directory rather than ignored
`backend/logs/`. Add/adjust `.gitignore` only as needed to ensure this one file can be
committed while other transient logs remain ignored.

Requirements:

- one JSON object per app request;
- append only;
- no rotation, truncation, overwrite, or date-based replacement;
- RFC 3339 `started_at` and `completed_at` timestamps plus duration;
- thread-safe append within the app process;
- one terminal record even when failure occurs before DB/SQL;
- a logging serialization/write failure must not replace a successful user response;
  emit a safe stderr diagnostic and attempt a minimal terminal record;
- exact query/answer content is intentionally enabled for this local diagnostic log;
- normal secret redaction remains mandatory.

## 14.2 Request-scoped trace accumulator

Create the trace accumulator at `QueryService.handle_query` entry, before reset,
confirmation, selection validation, catalog routing, LLM creation, or database work.

Every stage appends to the same in-memory record. Flush exactly once in a `finally`
boundary after the exact response envelope is known, or with a terminal error when no
envelope can be built.

This applies to:

- active-model questions;
- catalog questions;
- reset/confirmation actions;
- early input/selection errors;
- manifest unavailable;
- binding/correction/provider failures;
- SQL/RAG/graph failures;
- answer fallback;
- viewer truncation.

## 14.3 Trace identity and version block

Every v4 record includes:

```json
{
  "trace_schema_version": "query_trace_v001",
  "pipeline_version": "experiment2_v4",
  "request_id": "...",
  "session_id": "...",
  "action": "question",
  "started_at": "...",
  "completed_at": "...",
  "terminal_stage": "response_delivery",
  "terminal_status": "success"
}
```

Also record, when available:

- cached process-start Git commit and dirty flag;
- source model ID, name, fingerprint, IFC schema;
- extraction/canonical schema version;
- semantic contract, manifest schema/builder/content hash;
- compact binder projection hash and estimated tokens;
- prompt/schema versions;
- embedding model/index/cache version;
- configured LLM role/model/effort/service tier;
- price registry version.

Never log credentials, database URLs, API keys, authorization headers, or full
environment variables.

## 14.4 Exact input and delivery

Record:

- exact user question;
- bounded history sent to the pipeline;
- exact selected GlobalIds/entity IDs received from the client;
- inherited-scope identity/hash, not a full historical row set;
- exact raw structured binder/correction outputs;
- exact raw structured answer-model output, if produced;
- exact delivered `QueryResponseEnvelope` after fallback/validation;
- exact final answer string;
- exact GlobalIds included in frontend viewer actions, with count/total/truncation.

The delivered envelope is the authoritative "what the user saw" record.

## 14.5 Ordered stage flow

Use an ordered `stages` array. Each stage has:

- name;
- status;
- start/end or duration;
- bounded essential input;
- bounded essential output;
- warnings/failure code;
- terminal flag when execution stops.

Required stages when reached:

1. request/context validation;
2. source-model/manifest load;
3. floor/spatial context resolution where applicable;
4. ledger construction/resolution;
5. recommendation/value linking;
6. initial binder;
7. binding/ledger/capability validation;
8. correction budget and correction, if any;
9. dry compile/coverage proof;
10. SQL execution;
11. RAG retrieval;
12. graph traversal;
13. evidence/result adjudication;
14. answer packet;
15. answer LLM;
16. answer validation/fallback;
17. viewer hydration;
18. response delivery.

Do not add empty fake stages. The terminal stage and skipped-reason fields explain why
later stages were not reached.

## 14.6 Stage payload requirements

### Manifest

- identity/hash/versions;
- relative artifact path;
- bytes/estimated binder tokens;
- concept counts by kind/use;
- relevant capability/coverage summary;
- no full manifest copy.

### Ledger

- complete bounded ledger items;
- exact spans/roles/links/resolution states;
- required capability/use;
- partial policy.

### Recommendations

- per-ledger-slot top candidates;
- channel ranks/fused rank;
- use/applicability/accessor/coverage;
- value-link results;
- candidate counts/timing;
- no embeddings or entire value catalog.

### Binder/correction

- exact parsed structured output;
- provider response ID when available;
- schema/prompt version;
- validation failures and affected nodes;
- correction reason/budget decision;
- no hidden reasoning or full prompt.

### Logical/physical plan

- validated logical nodes/dispositions;
- accessor/path mappings;
- dry-compile verdict and coverage proof;
- requested/context/viewer-set contracts.

### SQL

- parameterized SQL for predicate/result statements needed to diagnose semantics;
- statement role/fingerprint;
- bounded typed/redacted parameters;
- duration and returned/scanned/matched/grouped counts;
- no full database rows;
- hydration/detail statements may be summarized when their SQL is not needed to
  diagnose the predicate.

### RAG

- exact retrieval query text;
- structured scope/filter selector;
- top-k and thresholds;
- candidate document/entity/relationship IDs and scores;
- accepted/diversity/rejected reason;
- text-truncated flags;
- bounded excerpts actually sent to the answer model;
- no vectors.

### Graph

- seed selector/count and traversed count;
- path IDs/direction/hops;
- relationship and endpoint counts;
- completeness/truncation;
- bounded relationship/endpoint IDs.

### Results/answer/viewer

- operation-specific pre-answer result;
- scanned, covered, answer, sample, and viewer cardinalities;
- exact answer packet;
- raw answer output;
- validation failures/fallback;
- exact delivered response;
- exact highlighted IDs.

### Performance/cost

- per-stage latency;
- database statement count;
- per-call uncached/cached/cache-write/output/reasoning tokens;
- per-role and total cost;
- correction cost reservation;
- total serialized bytes/tokens for stable and dynamic prompts.

## 14.7 Boundedness and safety

The log intentionally includes exact user text and exact final response, but must not
include:

- full canonical JSON rows;
- every matching DB row;
- full raw manifest per query;
- embeddings;
- hidden model reasoning;
- full stable prompts;
- secrets.

Use bounded diagnostic samples where identity examples are useful. The one exception
is the exact list of IDs actually sent in viewer actions, because the user explicitly
requires the log to show what was highlighted.

## 14.8 Migrate v3 logs

Add an idempotent migration utility under `backend/app/evaluation/` that reads the
current `backend/logs/query_events.jsonl` and `failure_cases.jsonl`, merges records by
request ID when possible, and appends deduplicated legacy records to the one tracked
file.

Every migrated record includes:

```json
{
  "pipeline_version": "experiment2_v3",
  "legacy_import": true,
  "legacy_pipeline_label": "task24_binding",
  "missing_fields": ["ledger", "binder_output", "compiled_sql", "delivered_response"]
}
```

Preserve original timestamps and payloads. Do not infer missing SQL, responses,
highlighted IDs, or intermediate plans. A failure-only legacy record remains
failure-only and names what is unavailable.

Stop active writes to both old files after v4 is enabled. They may remain as local
migration sources; there is only one active future query log.

---

# 15. Illustrative end-to-end data flow

This example explains the mechanism; it is not a query-specific implementation rule.

Query:

> Describe the materials of the doors on the first floor and the walls they fill.

## 15.1 Deterministic ledger

```text
L1 target: "doors" → requires target capability
L2 scope: "first floor" → requires occupiable-floor scope
L3 output: "materials" → requires reportable material field
L4 traversal: "walls they fill" → requires door/opening/wall path and wall endpoint
L5 operation: "Describe" → qualitative evidence/profile result
```

## 15.2 Recommendations

Per slot, lexical/typo/value/dense/structural channels may recommend:

- `cls:IfcDoor` as target for L1;
- the derived first-occupiable-floor candidate for L2;
- `material.name` as report field for L3;
- a compatible `IfcRelFillsElement` then `IfcRelVoidsElement` path for L4.

`IfcBuilding` may appear only as topic context. It cannot satisfy L1–L4.

## 15.3 First LLM logical output

The binder selects:

```text
target IfcDoor
scope derived first occupiable floor
project material.name
traverse Door ← Fills → Opening ← Voids → Wall
result qualitative_evidence
viewer set doors (or wall endpoints if explicitly requested)
```

It emits no SQL, vector search, or graph algorithm.

## 15.4 Deterministic execution

- SQL resolves the door family and first-floor membership through the applicable
  spatial membership path.
- Structured material retrieval produces normalized values and coverage.
- Graph traversal expands only those door seeds through the validated fill/void
  contracts to wall endpoints.
- RAG retrieves a primary plus small diversity slice for the matched doors,
  relationships, and walls.
- The result packet distinguishes exact structured counts/values from qualitative
  excerpts and graph-established connections.

## 15.5 Final answer

The final LLM synthesizes the supplied evidence, cites structured fact IDs and RAG
evidence IDs, and cannot change the exact counts or invent another relationship.
Viewer hydration uses the typed viewer set. The continuous log shows the complete
bounded chain.

The same mechanism handles a SQL-only query by omitting graph/RAG nodes, a graph-only
relationship query by retaining graph seeds/paths, and a qualitative question by
providing bounded evidence rather than an exact total.

---

# 16. Implementation scope

Modify the active pipeline in place. Do not add another endpoint, feature flag,
parallel legacy pipeline, external orchestration framework, or general agent loop.

## 16.1 Ingestion

Expected areas include:

- canonical extraction and wrapper/unit normalization;
- relationship/spatial membership generation;
- additive schema/migration/index definitions;
- semantic manifest schema/builder/writer;
- readiness reporting and notebook verification;
- regeneration for all four models.

Keep changes generic and source-model isolated.

## 16.2 Backend semantic layer

Expected areas include:

- manifest v002 loader/parser/cache and binder projection;
- access-contract reader and compiler adapter registry;
- derived spatial/floor/profile semantics;
- recommendation/value linking/embedding cache;
- deterministic ledger and validation;
- removal of duplicate complete-universe prompt serialization.

Retire production dependence on `binding/slate.py`. Migrate remaining tests, dev
routes, and diagnostics to the one active recommendation/resolution implementation,
then remove dead code when no import remains.

## 16.3 Binder/client

Expected areas include:

- strict logical query algebra schemas;
- binder/correction prompts and shared stable prefix;
- prompt serialization/token measurement;
- stage-local provider exceptions;
- request cost budget.

Do not change the configured role models or add a third normal-path LLM.

## 16.4 Execution/evidence

Expected areas include:

- typed relational compiler and physical plan;
- presence, spatial membership, material/classification, grouped argmax, and sample
  adapters;
- DB-side RAG scopes;
- completeness-aware graph traversal;
- operation-specific results;
- RAG/graph evidence packet;
- answer/fallback/viewer validation.

## 16.5 Service/observability

Expected areas include:

- request-scoped trace accumulator;
- one tracked JSONL writer and legacy migration;
- exact response/viewer capture on every exit path;
- correct `experiment2_v4` version labels;
- removal of active writes to the two transient legacy files.

Preserve the public API unless an additive result field is required to distinguish
scanned, answer, and viewer cardinalities.

---

# 17. Required tests

## 17.1 Contract and manifest

Test:

- contract JSON/schema validation and version mismatch;
- deterministic v002 content/hash and atomic write;
- writer/reader agreement without cross-package imports;
- bidirectional executable capability ↔ compiler adapter completeness;
- no executable capability without accessor/roles/operators/applicability;
- descriptive-only concept cannot compile;
- semantic IDs fit binder schemas;
- sparse per-class/per-operation coverage;
- exact absent versus unchecked/open-world unknown;
- materials/classifications partial coverage;
- relationship role-pair direction/endpoints;
- fact endpoint versus viewer entity;
- high-cardinality request lookup policy;
- compact projection completeness and size limits;
- no duplicate full value universe in the dynamic binder payload.

Use explicit regression fixtures for:

- one property container shared by many classes but one field populated on only one
  class;
- the model 3 `Identity Data.Number` shape;
- the model 4 `Pset_ProductRequirements.Name` shape;
- mixed `IfcWall`/`IfcWallStandardCase` coverage;
- partially populated materials/classifications;
- reversible wrapper keys mixed with unparseable keys;
- numeric facts with known, unknown, and incompatible units.

## 17.2 Spatial ingestion and floors

Test:

- direct containment;
- `IfcRelAggregates` storey-to-space membership;
- corroborating duplicate paths;
- multiple memberships and ambiguity;
- dangling endpoints;
- source-model isolation;
- effective distinct membership;
- indexes/query plans on models 2 and 3;
- robust elevation bands with sublevels and one extreme outlier;
- room/space/ordinary-element occupancy evidence;
- roof-only/reference bands;
- no-space but otherwise usable architectural floors;
- uncertain floor requiring clarification;
- raw-storey override;
- single-storey behavior;
- top/first occupiable resolution;
- logged interpretation/provenance.

Live assertions must confirm:

- all 778 model 2 spaces and all 187 model 3 spaces resolve through effective
  membership despite null scalar storey;
- the recorded model 2 room follow-ups no longer produce scalar-path false zeros;
- model 1 remains correctly single-storey;
- model 4 does not invent spaces and clarifies any materially uncertain roof-floor
  boundary.

## 17.3 Ledger and recommendations

Test:

- phrase-level targets/filters rather than per-word required items;
- topic context cannot satisfy cost/metric/theme;
- operation/group/order/limit/traversal slots;
- inherited/selection provenance;
- partial policy;
- exact/normalized aliases;
- misspellings and character-level recall;
- multilingual/paraphrased terms;
- dense recall always executes and can admit a non-lexical concept;
- concept embeddings are built once per hash, not per slot/query;
- authoritative high-cardinality value lookup;
- value-field isolation;
- rank-fusion diagnostics;
- structural compatibility and per-slot diversity;
- compound questions retain every material slot under prompt caps;
- valid concept outside recommendations remains selectable.

Measure recommendation recall@k per ledger slot, not just overall candidate presence.

## 17.4 Binder/logical algebra

With injected structured outputs, test:

- target/filter/output role distinction;
- presence/missing;
- AND/OR grouping;
- separate compound answer parts;
- distribution;
- group + aggregate + order + limit;
- one-sample shape;
- building/thematic profile;
- one-hop and composed compatible traversal;
- invalid endpoint/path;
- requested/context/viewer sets;
- partial and unresolved requirements;
- broad topic rejected as non-contributing;
- no dynamic manifest-ID enum;
- initial/correction common cache prefix.

## 17.5 Validation/gate/cost

Test every validation layer independently and together.

Prove:

- wrong-class real field fails applicability before SQL;
- ledger disposition without logical contribution fails;
- every logical node dry-compiles;
- unsupported accessor fails before execution;
- exact zero requires complete proof;
- partial executes safe known/context parts;
- independent valid compound parts survive another part's failure;
- only mechanical gaps trigger correction;
- no second correction is possible;
- correction preserves valid parts;
- correction is skipped when USD 0.03 reserve would be exceeded;
- normal two-call and clarification one-call behavior;
- unknown price cannot pass the budget as zero.

## 17.6 Compiler/execution

Test:

- parameterized class/field predicates;
- `is_present`/`is_missing` produce real SQL;
- material/classification filters/distributions;
- numeric units/comparisons/aggregates;
- relationship-backed floor scope for spaces and direct/normalized path for elements;
- source-model isolation in every subquery;
- grouped argmax and ties;
- sample eligible count versus one answer/viewer entity;
- DB-side RAG predicate scope without large Python ID list;
- building and thematic profile;
- complete versus capped graph seeds;
- multi-hop path provenance;
- exact totals independent of example/viewer limits.

## 17.7 Evidence, answer, and viewer

Test:

- primary + diversity RAG slice remains bounded;
- structured predicate scopes RAG;
- text-truncated evidence is disclosed;
- RAG miss never becomes zero;
- graph-expanded RAG preserves path provenance;
- structured and qualitative claims cite the correct fact/evidence types;
- selected concept/scope terminology is allowed by answer validation;
- hallucinated term/number/path is rejected;
- answer-writer failure returns deterministic fallback;
- sample highlights one;
- partial context highlighting follows explicit policy;
- zero/unavailable highlights none;
- exact IDs sent to viewer equal the logged IDs.

## 17.8 Continuous trace

Test one complete record for:

- ordinary success;
- deterministic answer fallback;
- clarification before SQL;
- manifest unavailable;
- selection conflict;
- binder provider failure;
- correction 429 with retained partial result;
- answer-writer failure with deterministic result;
- SQL part failure plus another successful part;
- RAG degradation;
- graph partial/cap;
- viewer truncation;
- catalog/reset/confirmation.

Assert:

- exactly one terminal v4 record per endpoint request;
- required timestamps/version/hash fields;
- exact query, raw structured outputs, delivered envelope, and highlighted IDs;
- stage ordering and terminal stage;
- parameterized SQL and bounded diagnostics;
- no canonical rows, embeddings, full prompts/manifests, or secrets;
- append-only behavior under concurrent app requests;
- logger failure does not change the response;
- v3 migration is idempotent and declares missing fields;
- no active writes to `query_events.jsonl` or `failure_cases.jsonl`.

## 17.9 Full four-model evaluation

Preserve `specs/test_query_v3.md`. Generate:

```text
specs/test_query_v4.md
```

Run:

- every original v1/v2/v3 query/session sequence;
- the user's recorded room/floor/wall/window sequence;
- held-out paraphrases/typos/multilingual cases;
- representative structured, qualitative, spatial, material, classification,
  relationship, partial, and unsupported queries on all four models.

For each case record from the new permanent trace:

- exact query and expected intent;
- source evidence and audited ground truth;
- ledger and required semantic capabilities;
- recommendation recall;
- initial/corrected logical binding;
- validation/gate/coverage proof;
- SQL/RAG/graph work;
- operation-specific authoritative result;
- raw/final answer and fallback;
- viewer set/count;
- calls/tokens/cache/cost/latency;
- first failing stage/code;
- verdict.

Audit benchmark expectations independently from IFC/DB evidence. The v3 expectation
that a relationship-backed space floor has zero spaces must not remain ground truth
merely because the v3 compiler could only read the scalar path. If an expected value
is corrected, retain the old value and document the independent source query/reason.
Never change expected ground truth merely to match v4 output.

Use deterministic execution assertions as authority for exact counts and identities.
LLM-based evaluators may be used offline only after human calibration; do not add
another runtime LLM judge.

---

# 18. Performance acceptance

Measure cold and warm behavior on all four models.

Task 26 is not complete unless:

- normal successful active-model queries use exactly two LLM calls;
- no request uses more than three;
- measured total provider cost is at most USD 0.03 per query;
- model 2/model 3 binder inputs satisfy the compaction targets in Section 5.8;
- a correction does not resend a 130k-token dynamic universe;
- recommendation warm latency is bounded and concept embeddings are reused;
- RAG scope for model 3 does not materialize a 100k-ID Python list;
- exact graph status never follows truncated seed traversal;
- SQL statement count/latency and query plans are recorded;
- no material regression is hidden by a faster but semantically broader query;
- final answer/viewer limits never change authoritative totals;
- the permanent trace stays bounded per query and does not duplicate full manifests.

External provider latency can vary, so report p50/p95 and cold/warm prompt/cache
metrics rather than asserting a brittle wall-clock number. Any median regression over
v3 must be explained by measured additional authoritative work, not duplicate prompt
content.

---

# 19. Research basis and adoption boundary

Use the following primary sources as architectural guidance, not dependency requests:

- [W3C R2RML](https://www.w3.org/TR/r2rml/) and
  [Ontop](https://ontop-vkg.org/guide/) support an explicit mapping between semantic
  concepts and relational access paths. Adopt the mapping/compilation principle,
  not RDF/SPARQL infrastructure.
- [IRNet / SemQL](https://aclanthology.org/P19-1444/) separates schema linking,
  logical intermediate representation, and deterministic SQL generation. Adopt a
  BIM-specific typed algebra; do not use model-written SQL.
- [DIN-SQL](https://proceedings.neurips.cc/paper_files/paper/2023/hash/72223cc66f63ca1aa59edaec1b3670e6-Abstract-Conference.html)
  supports diagnosing schema linking, decomposition, generation, and correction as
  separate stages. Keep one binder and one targeted correction rather than its
  multi-call prompting stack.
- [BIRD](https://papers.nips.cc/paper_files/paper/2023/file/83fc8fab1710363050bbd1d4b8cc0021-Abstract-Datasets_and_Benchmarks.html)
  demonstrates that database value understanding and dirty/real data matter in
  text-to-SQL. Adopt request-time authoritative value linking.
- [KG²RAG](https://aclanthology.org/2025.naacl-long.449/) and
  [Microsoft GraphRAG local search](https://microsoft.github.io/graphrag/query/local_search/)
  support semantic seeds followed by graph expansion and associated text evidence.
  Use the existing IFC graph/RAG documents; do not add their indexing stacks.
- [RAGChecker](https://arxiv.org/abs/2408.08067) supports separate retrieval and
  generation diagnostics. Adopt stage-specific deterministic metrics before adding
  any supplemental judge.
- [OpenTelemetry database semantic conventions](https://opentelemetry.io/docs/specs/semconv/db/database-spans/)
  support parameterized query text, operation/result metadata, and cautious opt-in
  content capture. Pin this project's own `query_trace_v001` schema; do not add an
  observability platform dependency.

Do not copy or install these projects. Do not add RDF, dbt, GraphRAG, RAGChecker,
OpenTelemetry SDK, another vector database, another graph database, or a new agent
framework unless a later task explicitly authorizes it.

---

# 20. Completion criteria

Task 26 is complete only when all of the following are true:

- one executable semantic access contract connects manifest, resolver, validator, and
  compiler;
- every executable capability has a tested adapter and every public adapter is
  manifested or explicitly unsupported;
- manifest applicability/coverage is per subject class and operation/path;
- normalized spatial membership resolves both model 2 and model 3 spaces;
- first/top floor semantics use occupiable evidence and clarify uncertainty;
- materials/classifications and high-cardinality values are executable when source
  facts support them;
- numeric metrics require proven meaning/units rather than storage-section names;
- recommendations run typo-tolerant lexical, value, dense, and structural channels
  without re-embedding the manifest per query;
- the ledger is phrase-level, retrieval-aware, and contribution-validated;
- the binder can express presence, grouping/argmax, sample, profile, partial, and
  bounded traversal intent;
- `IS_PRESENT`/`IS_MISSING` cannot disappear in compilation;
- exact zero always has a coverage/completeness proof;
- every safe partial answer survives an unrelated unavailable requirement;
- RAG/graph use validated seeds/scopes and disclose boundedness;
- result, answer, and viewer sets are operation-specific and consistent;
- answer/correction provider failures degrade at their own stage;
- all four current models are reingested/regenerated and pass readiness checks;
- `specs/test_query_v4.md` reports stage-level results across all four models;
- every app request appends exactly one complete or explicitly terminal-incomplete
  record to `backend/app/evaluation/query_trace.jsonl`;
- legacy logs are imported as explicit `experiment2_v3` records;
- no future query writes to a second active log;
- normal calls, token size, latency work, and USD cost satisfy this task's budgets;
- full ingestion and backend test suites pass;
- completion evidence contains no model-ID, filename, exact-query, or expected-count
  special case.

After implementation and verification, rename:

```text
tasks/task26.md
```

to:

```text
tasks/task26_done.md
```

Do not perform that rename until every criterion above is satisfied.
