# Task 05: Implement and Validate the SQL and IFC Graph Query Path

## Prerequisites

Require:

```text
tasks/task04_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
```

If Task 04 is incomplete, stop.

## Objective

Implement the complete deterministic catalog, SQL, and relational IFC-graph query service. Validate it independently by supplying typed plans directly, without depending on OpenAI planning.

## Required work

1. Review Task 04 interfaces and the actual completed database schema.
2. Apply the additive model-family/catalog-metadata migration after verifying it cannot disturb existing BIM tables or IDs.
3. Implement sanitized semantic schema discovery for tables, fields, IFC classes, property/quantity names, units, and relationship roles.
4. Implement typed SQL/catalog/graph plan schemas.
5. Implement all approved string and typed operators, bounded Boolean expressions, sorting, pagination, and limits.
6. Implement deterministic field resolution across attributes, dimensions, quantities, properties, and type facts with provenance.
7. Implement missing-value distinctions and instance/type conflict results.
8. Implement parameterized read-only SQL compilation and execution.
9. Implement catalog queries, version queries, exact entity queries, aggregates, selected-object lookup, relationship queries, and depth-bounded traversal.
10. Hydrate all direct endpoints when a relationship is returned and classify primary/context entities.
11. Enforce normalized units and coverage-aware aggregation.
12. Implement read-only-role verification and statement timeouts. If role creation needs administrator privileges, stop and report the required user action.
13. Produce compact SQL evidence compatible with Task 04 schemas.
14. Add initial manually editable catalog metadata for the current source model only when values are known; do not invent building use/version metadata.

## Authorized execution

Claude may connect to the existing database, apply the reviewed additive catalog migration, run read-only queries, and make narrowly scoped corrections. It may not alter completed IFC/vector contents or canonical IDs.

## Prohibited actions

- No raw model-generated SQL.
- No OpenAI calls are required or authorized for path validation.
- No RAG query implementation.
- No vector regeneration or mutation.
- No frontend implementation.
- No cross-model detailed queries except explicit catalog operations.
- No PostGIS or graph database.

## Required validation

Run direct typed-plan tests and live read-only database tests for:

- model catalog list/filter/version/rank operations
- count/list/get/filter/group/aggregate entities
- all five string match modes
- property and quantity paths with provenance
- unit conversions to mm/mm²/mm³/degrees
- ambiguous resolution and clarification outcome
- missing-value states
- exact count despite sample limits
- every relationship class for direct inspection
- containment, aggregation, type, property, material, opening/filling, group, boundary, and connection traversal where present
- endpoint hydration, depth, cycles, and source isolation
- injection attempts, unsupported operations, timeouts, and max limits
- viewer GlobalId output

Create a small benchmark with manually verified exact answers and canonical IDs.

## Completion report

Report migration, files, tests, live-query results, catalog metadata state, read-only-role status, benchmark results, warnings, and explicit confirmation:

```text
SQL/catalog path: IMPLEMENTED AND VALIDATED
IFC graph path: IMPLEMENTED AND VALIDATED
Existing canonical BIM IDs: PRESERVED
RAG query path: NOT IMPLEMENTED
OpenAI orchestration: NOT EXECUTED
```

Rename to `task05_done.md` only when all criteria pass.

