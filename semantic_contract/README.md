# Semantic access contract

Repository-owned, versioned data files shared by ingestion and the backend
(task26 §3.2). Neither Python package imports the other; each has its own small
reader for these files.

## Files

- `access_contract_v001.json` — the semantic access contract: legal capability
  kinds, permitted uses, operators per data type, coverage-state semantics, and
  the symbolic physical accessor IDs (`entity.class`, `json.property_value`,
  `spatial.effective_membership`, …). Physical table names, JSON paths, joins,
  and SQL stay backend-owned and are never part of this contract or of any
  binder prompt.
- `semantic_manifest_v002.schema.json` — JSON Schema for the per-model semantic
  manifest artifact written by ingestion under
  `model_semantics/{source_model_id}/{fingerprint}.semantic.json`.

## Invariants

1. Every manifest capability marked `executable: true` must name an accessor
   declared in the contract, and the backend must register a compiler adapter
   for that accessor supporting the declared uses/operators/result shapes.
2. Every backend compiler capability intended for binder use must be declared
   here and emitted by the manifest when the model supports it.
3. Descriptive/non-queryable concepts stay visible only with
   `executable: false`, an explicit `limitation`, and no executable uses.
4. No compiler adapter may accept a kind or operator it did not declare.

Bidirectional completeness is enforced by tests on both sides
(ingestion: manifest builder tests; backend: adapter-registry tests).

## Versioning

- Bump `access_contract_vNNN.json` when capability kinds, uses, operators, or
  accessor IDs change meaning. Readers pin the version they support.
- The manifest schema version (`v002`) and builder version are carried in each
  artifact's identity block; the contract version consumed at build time is
  recorded there too.
