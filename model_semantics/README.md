# `model_semantics/` — generated semantic manifests

One deterministic JSON artifact per imported IFC model (task25 §2.1):

```
model_semantics/{source_model_id}/{file_fingerprint}.semantic.json
```

## What it is

A complete inventory of the **queryable concepts** in one source model — entity and
relationship classes, types, attributes, property and quantity containers, materials,
classifications, spatial structure, value vocabularies, and coverage states. It is the
semantic API the query pipeline's binder reads in order to understand how *this* model is
represented before binding a question to it.

It is **not** a copy of the model. Individual GUIDs and full occurrence records stay in
PostgreSQL and in `rag_documents`; the manifest describes what exists and what can be asked,
and retrieval fetches the rows.

Each artifact carries four views of the same authoritative data:

| section | contents |
|---|---|
| `object_level` | present occurrence classes and their identity/attribute vocabulary |
| `type_property_level` | property and quantity containers, materials, classifications |
| `relationship_level` | relationship classes with endpoint roles and endpoint classes |
| `global_level` | whole-model inventory, storeys, spatial containment, missing capabilities |

## How it is generated

By `ifc_to_db()` during ingestion — deterministically, from imported canonical facts only.
No LLM, no embedding model, no network call. The same IFC and the same builder/schema
versions always produce byte-identical content and therefore an identical `content_hash`.

Run `ingestion/notebooks/ingestion.ipynb` to import a model and generate everything it needs;
that notebook also verifies readiness (database rows, a fingerprint-matched manifest, vectors,
and the viewer artifact) before reporting a model as query-ready.

## Coverage states

Every field and container carries a typed coverage state, and the distinctions matter:

- `populated` / `partial` — present, on all or some occurrences;
- `absent` — an **exact zero**: the concept is known and no occurrence carries it;
- `unsupported` / `extraction_failure` — the pipeline cannot determine the value;
- `unsupported_source_structure` — the **source IFC** does not expose this container in a
  reliably interpretable structure, so its fields cannot be resolved as queryable properties.

The last state is descriptive, never corrective. When a container's field space is both
unstable and too large to enumerate, the manifest records a bounded diagnostic (container,
field count, occurrence count, measured ratio, reason) and stops — it does not attempt to
infer what the field names were meant to mean. Questions needing those properties are answered
`unavailable` with the limitation stated, rather than silently answered against a broader set.

## Version control

These artifacts are **generated, local, and gitignored** — they are rebuilt from the database
by re-running ingestion, and can be large. Only this README and any small fixtures under
`model_semantics/fixtures/` are tracked.
