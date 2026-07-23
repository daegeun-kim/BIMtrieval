# Pipeline Direction Comparison

This document gives a short, flowchart-friendly overview of the three pipeline directions. It
describes only the main stages and does not replace the detailed query architecture specifications.

## Original Pipeline — Main Branch

**Direction: extract broad evidence, narrow it down later.**

1. The user query is submitted to the first LLM.
2. The first LLM breaks the query into concepts and chooses the allowed retrieval methods: SQL,
   RAG, graph, or a combination. It knows the retrieval options, but does not inspect the active
   database structure.
3. The system matches the concepts against the BIM ontology, cached model information, and the
   database to generate candidate object and property groups.
4. The chosen retrieval methods collect evidence for these candidate groups. SQL provides exact
   structured results, RAG finds similar information, and graph search follows BIM relationships.
5. The retrieved evidence is organized into groups. Each group includes its meaning, count or
   coverage, and representative BIM objects.
6. Up to 50 detailed example rows are distributed across the groups. This is not a simple top 50
   from one combined list; group summaries remain available even when their rows are limited.
7. The final LLM receives the query, group summaries, and example rows. It selects the relevant
   groups and generates the answer.
8. The system retrieves and highlights the BIM objects represented by the groups selected for the
   3D viewer.

## Experimental Pipeline — Binding Branch

**Direction: make a detailed plan first, extract smaller evidence.**

1. The user query goes to the deterministic slate builder.
2. The slate reads cached model information and the database profile. It creates a small,
   bounded set of subject, property, value, location, and relationship candidates. The number is
   limited, but is not fixed at four to six.
3. The first LLM selects from the slate and creates one or more answer parts. Each part states its
   operation, subject, scope, and conditions.
4. The system validates the plan, includes the correct IFC subtypes, and compiles each valid answer
   part into an executable BIM query.
5. The system derives the retrieval method from the operation. Structured questions use SQL,
   qualitative ranking may use scoped RAG, and relationship questions use graph search.
6. Each answer part is executed once and ends as exact, zero, partial, unavailable, or ambiguous.
7. Structured results and bounded examples are placed into a compact evidence packet.
8. The final LLM generates a uniform answer from this evidence. It does not select again from a
   large raw candidate pool.
9. The system checks the answer and creates the 3D highlight from the same executed result.

## Latest Pipeline — Complete-Semantics Branch

**Direction: expose the complete active-model semantics, then bind and execute only the proven
interpretation.**

1. During IFC ingestion, the system writes the structured entities and relationships, builds and
   validates a complete compact semantic manifest for that source model, and then generates the
   existing vector and viewer artifacts.
2. For a question, the system loads the complete manifest for the active model and creates
   deterministic high-recall recommendations. The recommendations help navigation but do not limit
   which manifest concepts the binder may select.
3. The system also creates a typed constraint ledger covering every required subject, condition,
   value, scope, relationship, output, and viewer request in the question and inherited context.
4. The first LLM receives the complete manifest, recommendations, and ledger. It selects semantic
   IDs and decomposes the request into up to eight typed answer parts; it does not write SQL or
   choose one global retrieval mode.
5. A deterministic gate validates semantic IDs, roles, fields, operators, values, units,
   relationships, Boolean structure, source-model scope, and coverage of every required ledger
   item.
6. If the gate proves a recoverable binding gap, the system may make one corrective binding call
   focused on the failed ledger items and then validates again. Genuine ambiguity, unavailable
   model data, and exact zero results do not trigger correction.
7. Each valid answer part is compiled and executed by the appropriate authoritative method: SQL
   for structured facts, SQL-scoped RAG for qualitative ranking, seeded graph traversal for
   relationships, or cached deterministic facts for whole-model summaries.
8. The system compares the executed evidence with the plan and ledger, assigning an exact, zero,
   partial, unavailable, or ambiguous state and assembling a compact adjudicated evidence packet.
9. The final LLM writes a grounded answer from that packet. It does not receive the full manifest,
   rejected candidates, raw queries, raw graph dumps, or viewer identity lists.
10. Deterministic validation checks the final answer, and the 3D viewer highlights identities
    derived from the same executed predicate as the answer.

Normally this branch uses two LLM calls: semantic binding and grounded answer writing. A proven
recoverable binding gap may add one corrective call, for a maximum of three.
