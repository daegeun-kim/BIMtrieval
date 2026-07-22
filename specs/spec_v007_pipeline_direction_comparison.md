# Pipeline Direction Comparison

This document gives a short, flowchart-friendly overview of the two pipeline directions. It
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
