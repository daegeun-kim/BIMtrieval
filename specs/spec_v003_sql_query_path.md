# Specification v003: SQL and IFC Relationship Query Path

## 1. Purpose

Define the deterministic SQL and relational IFC-graph path governed by `spec_v002_query_architecture.md`.

This path answers exact catalog and active-model questions. The LLM produces a schema-enforced semantic plan; trusted backend code validates it and compiles parameterized SQL. The LLM never emits raw SQL.

This is a blueprint only. Implementation and execution require later task files.

## 2. Scope

Support:

- model catalog listing, filtering, comparison, version selection, and exact aggregates
- entity count, list, lookup, filtering, sorting, grouping, and aggregation
- property, quantity, attribute, material, type, classification, and missing-value queries
- relationship listing, lookup, role filtering, membership, and endpoint traversal
- selected-object lookup for the future viewer/chat interface
- bounded post-query transformation where SQL is insufficient

Do not support arbitrary SQL, PostGIS, unrestricted recursive queries, geometry calculations, or LLM-performed arithmetic.

## 3. Code Organization

Place new backend code under:

```text
backend/src/query/sql/
├── schemas.py
├── operations.py
├── compiler.py
├── field_registry.py
├── catalog.py
├── entities.py
├── relationships.py
├── aggregates.py
├── hydration.py
└── errors.py

backend/src/query/graph/
├── schemas.py
├── registry.py
├── traversal.py
└── hydration.py
```

Shared database access belongs under `backend/src/db/`. SQL-planner schemas integrate with `backend/src/llm/schemas.py`. Do not put SQL execution in prompt files or route handlers.

Preserve working ingestion modules until a dedicated refactoring task.

## 4. Safe Schema Context for the LLM

Give the planner as much useful database information as practical, but only as a sanitized semantic schema catalog—not credentials, raw DDL, unrestricted SQL capability, or massive value dumps.

Provide dynamically generated context including:

- safe table purposes
- allowed semantic operations
- safe fields and data types
- entity and relationship classes present in the selected model
- property-set, quantity-set, property, and quantity names discovered in canonical JSON
- normalized-unit rules
- model catalog metadata fields
- supported relationship direction/role definitions
- valid operators per field type
- safe aggregation functions
- default and maximum limits

Cache this context per source-model fingerprint and extraction version. Refresh when structured data changes.

Do not send full table contents or complete canonical JSON to the planner.

## 5. Catalog Metadata

Add a normalized, manually editable catalog layer without destabilizing ingestion identity. Prefer tables equivalent to:

```text
ifc_model_families
ifc_model_metadata
```

Support:

- family ID and display name
- source model ID
- version label/order/current flag
- project/building use
- discipline
- tags
- short description
- metadata provenance (`ifc_extracted`, `manual`, `derived_exact`)
- viewer source/artifact location
- availability status

Distinct fingerprints may belong to one family. Do not infer version order from filenames. Do not treat LLM-inferred catalog tags as authoritative.

## 6. SQL Plan Schema

Plans must be schema-enforced and use semantic operations such as:

```text
list_models
filter_models
list_model_versions
rank_models_by_entity_count
get_model_metadata
count_entities
list_entities
get_entity
filter_entities
aggregate_entities
group_entities
find_missing_values
list_relationships
get_relationship
get_relationship_members
traverse_relationships
get_selected_entities
```

Example:

```json
{
  "operation": "filter_entities",
  "source_model_id": 1,
  "entity_classes": ["IfcDoor"],
  "filters": [
    {
      "field_kind": "quantity",
      "set_name": "BaseQuantities",
      "field_name": "Width",
      "operator": "gte",
      "value": 900,
      "unit": "mm"
    }
  ],
  "sort": [],
  "limit": 50
}
```

Plans may use only allowlisted operations, field kinds, operators, sort directions, aggregation functions, and relationship traversal modes.

## 7. Filters

Support numeric/date/boolean operators as appropriate:

```text
eq, ne, gt, gte, lt, lte, between, in, not_in
```

Support all five requested string modes:

```text
exact
case_insensitive_exact
contains
starts_with
in
```

Use case-insensitive matching by default for human-readable names. Preserve exact GlobalId behavior.

Support `AND` and `OR` through a bounded typed expression tree. Limit nesting depth and filter count.

All values must be bound parameters. Never concatenate user/model values into SQL.

## 8. Canonical JSON and Field Resolution

Allow queries over any property/quantity name present in canonical JSON after runtime validation against the selected model's semantic schema catalog.

Preserve set names to prevent collisions.

For ambiguous concepts such as `door width`, use a deterministic field-resolution registry that may inspect:

- direct attributes
- normalized dimensions
- quantity sets
- property sets
- assigned type facts

Return provenance with every resolved value. If multiple valid values exist or instance/type facts conflict, return all relevant values rather than silently choosing one.

If ambiguity remains material, the planner returns `clarify` and asks a concise user question instead of guessing.

## 9. Missing-Value Semantics

Distinguish:

```text
absent
present_null
present_empty
extraction_failed
unsupported_value
```

Do not collapse these states into one generic null when the source record preserves the distinction.

## 10. Units and Aggregation

Normalize:

```text
length = mm
area = mm²
volume = mm³
angle = degrees
```

Preserve original values, units, and provenance.

Support exact:

```text
count, sum, min, max, average, group_by
```

Only aggregate numeric values whose semantic field and normalized unit are known. Report missing coverage and do not imply completeness when some matching objects lack the required quantity.

SQL performs filtering, joins, grouping, and aggregation. Pandas may transform bounded results for presentation but must not replace database operations or calculate from a limited sample when the full set is required.

## 11. Result Limits

```text
default list limit = 50
maximum list limit = 500
```

Exact counts and aggregates cover the complete matching set. Returned example records remain bounded.

Require stable deterministic sorting and pagination for lists.

## 12. IFC Relationship Traversal

Use PostgreSQL tables, not a graph database:

```text
ifc_relationships
→ relationship_members
→ ifc_entities
```

Permit direct endpoint inspection for every stored relationship class. Maintain an allowlisted semantic registry for directional interpretations such as containment, aggregation, type definition, property definition, material association, openings/fillings, grouping, boundaries, and connections.

Use exact schema role names such as `RelatingStructure` and `RelatedElements`.

Controls:

```text
default depth = 1
maximum depth = 3
cycle prevention = required
visited entity/relationship tracking = required
source_model isolation = required
```

When a relationship is returned, hydrate all direct endpoint entities. Mark those satisfying the main query as primary and other endpoints as context.

## 13. Model Isolation and Read-Only Execution

Every active-model query must require `source_model_id` in validated application state and SQL predicates.

Catalog queries may span source models only through explicit catalog operations.

Use a dedicated read-only PostgreSQL role for runtime queries. Verify it where possible. If creation requires administrator privileges, document the exact requirement and stop for user action rather than escalating database authority implicitly.

Apply statement timeouts and reject mutations, multiple statements, comments used for bypass, or unsupported database functions.

## 14. SQL Evidence Contract

Return compact structured evidence including:

- operation
- source model
- exact count/aggregate where applicable
- canonical entity/relationship IDs
- IFC classes and names
- GlobalIds for viewer mapping
- matched field values and provenance
- relationship roles
- primary/context classification
- coverage/missing-value statistics
- truncation/pagination metadata
- warnings

Do not expose raw SQL or full canonical JSON to the normal frontend.

## 15. Clarification and Failure Behavior

Ask the user to clarify when:

- model scope is missing for a detailed query
- a concept maps to materially different fields
- a requested calculation lacks a defined metric
- model/version selection is ambiguous
- multiple interpretations would change the result substantially

Use actionable questions such as:

```text
Do you mean the nominal door width or the opening width?
Which model version should I use?
```

Return safe structured errors for unsupported fields, insufficient data, timeout, and unavailable models.

## 16. Tests and Evaluation

Test:

- every operation schema
- all operators and invalid combinations
- parameter binding and injection resistance
- required source-model scoping
- catalog/model-version isolation
- dynamic semantic schema generation
- arbitrary validated property/quantity lookup
- ambiguous field resolution and clarification
- instance/type conflicts
- missing-value distinctions
- unit conversions
- full-set aggregate correctness
- default/max limits and pagination
- every stored relationship class for direct inspection
- semantic relationship registry direction
- endpoint hydration, cycles, and depth limits
- cross-model link rejection
- read-only role and statement timeout behavior

Benchmark representative exact questions and compare canonical IDs/counts with manually verified expected results.

## 17. Acceptance Criteria

The SQL path is acceptable when:

1. The LLM receives rich sanitized schema context but cannot emit arbitrary SQL.
2. Every plan is schema-enforced and compiles to parameterized read-only SQL.
3. Catalog and active-model scopes are isolated.
4. Properties and quantities are queryable dynamically with provenance.
5. Ambiguity produces clarification rather than guessing.
6. Units and aggregates are deterministic and coverage-aware.
7. Relational graph traversal supports stored relationship classes safely.
8. Results return canonical IDs and GlobalIds for hybrid retrieval and viewer highlighting.
9. Normal frontend responses do not expose SQL or full canonical JSON.
10. Tests prove correctness, isolation, limits, and injection resistance.

## 18. Task 05 Implementation Notes

Task 05 (`tasks/task05_done.md`) implemented this specification in full
against the live database: `backend/src/query/sql/*` (schemas, field
registry, compiler, catalog/entities/relationships/aggregates/hydration,
errors) and `backend/src/query/graph/*` (semantic registry, bounded BFS
traversal, hydration). Full command reference and data-specific caveats:
`docs/architecture_v003.md`.

Executed against the database (both idempotent, re-run-safe):
`db.apply_catalog_migration` (created `model_families` and
`source_model_catalog_entries`, verified additive against the five existing
tables' row counts, seeded one catalog entry for `source_model_id=1` using
only derivable fields) and `db.bootstrap_readonly_role` (created
`bim_rag_query_ro`, granted `SELECT`-only on all seven tables, wrote
`DATABASE_URL` to `.env`, verified `INSERT`/`CREATE` are rejected). Every
`query.sql`/`query.graph` operation and every live test runs through that
read-only role, not the ingestion superuser connection.

The only ingested model (Schependomlaan) has zero populated
`quantity_sets`/`materials` and a single messy `property_sets` bucket — the
engine is built spec-complete and generic, but live validation against this
model correctly reports missing quantity/material data as *absent* rather
than fabricating it (see `docs/architecture_v003.md` for details and the
`mm`-only unit-conversion caveat inherited from the v001 ingestion output).

300/300 tests pass (158 pre-existing ingestion + 40 Task 04 + 102 new:
`backend/tests/query_sql`, `query_graph`, `query_live`). `ruff format`/`ruff
check` clean. Benchmark:
`backend/src/evaluation/benchmark_v002_sql_graph_cases.jsonl` (8 manually
verified cases with canonical IDs/exact counts).

```text
SQL/catalog path: IMPLEMENTED AND VALIDATED
IFC graph path: IMPLEMENTED AND VALIDATED
Existing canonical BIM IDs: PRESERVED
RAG query path: NOT IMPLEMENTED
OpenAI orchestration: NOT EXECUTED
```

