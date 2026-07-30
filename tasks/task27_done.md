# Task 27: IFC-Native Dimension Units and Minimal Numeric Query Access

## Goal

Make supported dimensional values reliably available to the existing structured query
pipeline after running the single production ingestion notebook on any IFC model whose
source data provides trustworthy IFC measure types and units.

The supported scope is deliberately limited to:

- **length**, including width, height, depth, thickness, perimeter, and other values whose
  IFC value type is a length measure;
- **area**;
- **volume**.

Preserve the value in the effective unit embedded in the IFC. Do not bulk-convert every
stored value into a project-wide canonical unit. Store the model's unit definitions once,
link typed values to their measure type, and store an occurrence-level unit override only
when the IFC explicitly provides one.

Then make the smallest backend changes required for the existing semantic-manifest,
binding, deterministic SQL, aggregate, and answer-evidence path to use those numeric
values and report their units safely.

The ingestion workflow remains:

```text
ingestion/notebooks/ingestion.ipynb
    -> production ingestion source
    -> structured database facts
    -> semantic manifest
    -> RAG documents/vectors
    -> viewer artifact
    -> readiness verification
```

Do not create a second ingestion entrypoint or put production extraction logic in the
notebook.

---

## 1. Fixed scope and exclusions

### 1.1 Supported source facts

Extract supported dimensional metadata from standards-based IFC structure:

- direct IFC entity attributes whose declared IFC type is a supported length, area, or
  volume measure;
- `IfcPropertySingleValue` and other supported simple-property values whose actual IFC
  wrapped value type identifies length, area, or volume;
- `IfcPhysicalSimpleQuantity` subtypes for length, area, and volume;
- the model-level defaults in `IfcProject.UnitsInContext`;
- an explicit property/quantity unit when the IFC supplies one.

Use the IFC schema/value type and unit graph as authority. A Python `float` is not a
measure type.

### 1.2 No model- or exporter-specific inference

Do not add behavior conditioned on:

- an IFC filename, fingerprint, source-model ID, project name, or catalog name;
- Schependomlaan, FOJAB, SampleArchitecture, Wellness Center, ArchiCAD, Revit, Synchro,
  or another named product/exporter;
- a particular observed count or expected answer;
- a property-name substring such as `Area`, `Length`, `Width`, `Height`, or `Volume`;
- an exporter-specific property prefix or pseudo-quantity namespace.

An untyped `IfcReal`, integer, string, or other generic scalar does not become a
dimension merely because its field name sounds dimensional. Preserve the raw value as
before, but leave its dimensional measure type and unit unavailable.

This means the flattened Schependomlaan `IFCREAL` properties may remain unavailable as
dimensions. That is the correct standards-based outcome unless their source IFC carries
trustworthy type/unit information that can be resolved without name inference.

### 1.3 Explicitly out of scope

Do not add:

- mass, weight, angle, time, temperature, currency, count, or other measure families;
- density calculation;
- mass divided by volume or any other derived unit algebra;
- geometry-derived dimensions, areas, or volumes;
- bounding-box measurement;
- inference from 3D viewer geometry;
- unit conversion of the stored corpus into `mm`, `mm²`, `mm³`, SI, or another canonical
  target;
- automatic cross-unit aggregation;
- frontend or component-panel changes.

Mass ingestion by itself is not the main difficulty, but density is a separate derived
calculation requiring mass/volume pairing, compatible coverage, unit algebra, and new
execution semantics. Keep both out of this task so the fragile backend change stays
bounded. Do not prevent a later task from adding another explicitly supported measure
family.

---

## 2. Ingestion-owned unit contract

### 2.1 Store unit definitions once per source model

Keep the current relational schema. Do not add a new table, column, or migration for this
task.

Extend `ifc_source_models.extraction_metadata` with one deterministic, versioned unit
registry derived from the source IFC. It must contain:

- the default unit reference for `length`, `area`, and `volume` when supplied by
  `IfcProject.UnitsInContext`;
- one de-duplicated definition for every referenced default or explicit override unit;
- enough source-faithful information to identify and display the unit without guessing,
  including the IFC unit type, SI/conversion-based identity as applicable, prefix/name,
  and a deterministic display symbol;
- an explicit unavailable/unsupported state when a default cannot be resolved.

Use stable internal unit keys. Per-value records refer to those keys rather than repeating
the complete unit definition.

The exact JSON key names are implementation details, but the shape must follow this
single-source pattern:

```json
{
  "dimension_units": {
    "contract_version": "v001",
    "defaults": {
      "length": "unit-key-1",
      "area": "unit-key-2",
      "volume": "unit-key-3"
    },
    "definitions": {
      "unit-key-1": {
        "ifc_unit_type": "LENGTHUNIT",
        "symbol": "mm"
      }
    }
  }
}
```

Do not store credentials, local paths, model-specific aliases, or a manually entered unit
map.

### 2.2 Preserve measure type with the value

Retain the existing canonical JSON locations for identity, properties, and quantities so
unrelated backend behavior does not break.

For a property or quantity whose source IFC declares a supported measure type, augment
its existing entry with:

- `measure_type`: exactly `length`, `area`, or `volume`;
- an optional `unit_override_key`, present only when the source occurrence explicitly
  overrides the project default;
- existing raw `value` and provenance.

Do not duplicate the model's default unit on every value. The effective unit is:

```text
unit_override_key
    otherwise dimension_units.defaults[measure_type]
```

Do not write a null override key when no override exists.

For supported direct IFC attributes not currently retained in canonical JSON, add one
bounded, deterministic measurement-attribute container that preserves:

- exact IFC attribute name;
- raw value;
- supported measure type;
- attribute provenance;
- optional explicit unit override when the IFC schema permits one.

Do not copy arbitrary entity attributes into this container. Only direct attributes with
a declared supported IFC measure type belong there.

### 2.3 Remove the current false normalization

The current quantity extractor applies one project length factor to every numeric
quantity and emits `normalized_unit="m"`. That is invalid for area and volume.

Replace that behavior. New extraction must not:

- apply a linear scale to an area or volume;
- label an area or volume as metres;
- derive area/volume units by squaring/cubing the length unit;
- emit a normalized value that was not actually established by the IFC unit definition.

Preserve raw source values and effective IFC units instead.

### 2.4 Extraction version and repeatable updates

Increment the canonical extraction version. Persist the new version in both entity
canonical metadata and the source-model extraction metadata, including on an existing
source-model row.

Rerunning `ifc_to_db()` for an unchanged fingerprint must:

- keep the same `source_model_id`;
- keep existing entity IDs for the same GlobalIds;
- update canonical JSON in place with the new measurement metadata;
- preserve relationship/entity isolation;
- refresh downstream artifacts whose source hash/content changed;
- avoid duplicate entities, relationships, relationship members, RAG documents, manifests,
  or catalog entries.

Do not delete and recreate a source model merely to apply the extraction change.

---

## 3. Semantic-manifest update

Update the ingestion-owned semantic-manifest builder and the backend reader together.
Bump the active manifest schema/builder version so a manifest generated under the old
measurement contract cannot be mistaken for a current one.

For every supported numeric field, the manifest must report:

- physical source: direct attribute, property, or quantity;
- measure type: length, area, or volume;
- numeric data type and existing applicability/coverage;
- effective unit when all populated occurrences resolve to the same unit;
- unit state: `uniform`, `mixed`, or `unknown`;
- bounded unit variants/counts when mixed;
- whether numeric comparison and aggregation are safe;
- the limitation when they are not safe.

The manifest must derive these facts from canonical measurement metadata and the
source-model unit registry. It must not re-open the IFC or infer measure type from a field
name.

Coverage distinctions remain mandatory:

- a supported field with one uniform known unit is executable;
- missing values produce partial coverage, not a fabricated zero;
- a field with unknown measure type/unit is unavailable for dimensional calculation;
- mixed effective units must not be silently summed or compared as one scale.

Regenerate the manifest through the production ingestion path. Do not hand-edit generated
semantic JSON.

---

## 4. Minimal backend adaptation

Treat the backend as fragile. Make focused changes only where the new ingestion contract
must be consumed.

### 4.1 Preserve the existing query architecture

Do not change:

- query routing or session behavior;
- constraint-ledger construction;
- subject/family/role closure;
- LLM model assignments, reasoning effort, prompts, or normal call count;
- correction-call policy;
- RAG or graph retrieval semantics;
- deterministic grounding validation or fallback behavior;
- result limits, source-model isolation, read-only database use, or statement timeout;
- viewer identity derivation;
- public response shapes except populating already-optional unit fields;
- any frontend source, tests, dependencies, build output, or OpenAPI client snapshot.

No frontend file under `frontend/` may change.

### 4.2 Carry manifest measurement metadata

Extend the backend manifest model and field candidate with only the measurement data
needed for execution:

- measure type;
- effective unit/symbol when uniform;
- unit state;
- unit availability/safe-aggregation flag.

Use the existing `unit_available` and optional aggregate-unit concepts rather than
creating a parallel numeric query pipeline.

The complete manifest remains the semantic authority. A newly ingested typed field should
be discoverable without adding its literal name to backend source code.

### 4.3 Numeric filtering and aggregation

Update the deterministic field resolver/compiler/aggregate path so:

- raw stored numbers are cast and calculated without rewriting the corpus into another
  unit;
- a uniform known effective IFC unit is returned with `sum`, `minimum`, `maximum`, and
  `average`;
- coverage count and matched count remain exact;
- a numeric literal without an explicit unit is interpreted in the field's uniform
  effective IFC unit and that interpretation is disclosed;
- an explicitly requested unit may execute only when it is the same effective unit,
  allowing deterministic spelling/symbol normalization such as `metre` versus `m`;
- a different requested unit returns an honest unavailable/clarification result in this
  task rather than performing conversion;
- a mixed-unit or unknown-unit field is not aggregated or compared as if uniform;
- no LLM performs arithmetic or unit reasoning.

Remove or replace the current `mm`-only/linear-normalization assumptions. Do not leave two
competing unit paths active.

Populate the existing aggregate result's optional unit instead of adding a second result
contract.

### 4.4 Unrelated behavior must remain stable

Existing non-numeric count, list, property, spatial, relationship, RAG, and viewer queries
must retain their current behavior. A model lacking trustworthy typed dimensions must
return the existing truthful unavailable behavior rather than erroring.

Do not update the component-details endpoint or its allowlists in this task.

---

## 5. Notebook behavior and four-model re-ingestion

`ingestion/notebooks/ingestion.ipynb` remains the one user-facing ingestion notebook.

Running:

```python
run_full_ingestion("path/to/new-model.ifc")
```

must automatically perform and verify the new measurement extraction through production
source code. Do not require manual unit entry, a model-specific configuration file, a
second metadata notebook, or post-ingestion JSON edits.

Extend the notebook's report/readiness output with bounded measurement diagnostics:

- resolved model defaults for length, area, and volume;
- count of typed measurement values by measure type and provenance;
- count of fields with uniform, mixed, and unknown unit state;
- active extraction/manifest versions;
- manifest validation and downstream readiness.

Keep the notebook as a one-file function. Do not add folder watching or implicit bulk
ingestion as production behavior.

After source and backend changes pass focused tests, execute the production notebook
function once for each existing IFC file:

```text
ingestion/ifc_original/IFC Schependomlaan incl planningsdata.ifc
ingestion/ifc_original/FOJAB_Landsarkivet.ifc
ingestion/ifc_original/SampleArchitecture.ifc
ingestion/ifc_original/Wellness_center_Sama.ifc
```

This is a one-time execution/validation step, not model-specific production logic.

For all four models:

- preserve current source-model IDs/fingerprints and stable entity IDs;
- update existing canonical rows in place;
- regenerate and validate the active semantic manifest;
- refresh RAG documents/vectors when their deterministic source text/hash changes;
- reuse or verify the viewer artifact when its source fingerprint is unchanged;
- finish the notebook readiness check successfully.

Report typed/untyped dimensional coverage honestly. Do not make the four models appear
equally capable by inference or fabricated metadata.

---

## 6. Documentation alignment

The owner decision in this task is to preserve and use the effective units embedded in
each IFC, without bulk-normalizing the corpus.

Update the active unit sections in:

- `specs/spec_v002_query_architecture.md`;
- `specs/spec_v003_sql_query_path.md`;
- relevant README/workflow diagnostics if their operational instructions change.

Remove the conflicting requirement that every supported value be stored/calculated in
`mm`, `mm²`, or `mm³`. Preserve the invariant that calculations require a trustworthy
measure type and unit.

Do not rewrite unrelated historical task files.

---

## 7. Validation

### 7.1 Ingestion tests

Add synthetic, model-agnostic tests covering:

- a model whose defaults deliberately differ by measure type, such as millimetres for
  length but square metres and cubic metres for area/volume;
- metric and imperial IFC unit definitions;
- typed direct attributes;
- typed property values;
- typed physical quantities;
- explicit unit overrides;
- uniform and mixed effective-unit fields;
- missing project defaults;
- generic `IfcReal` values with dimension-like and unrelated names remaining untyped;
- deterministic unit keys/metadata and canonical JSON ordering;
- idempotent re-ingestion that preserves IDs and updates the extraction version;
- no linear factor being applied to area or volume.

Do not use a production filename, model ID, expected production count, or exporter name as
the behavior trigger.

### 7.2 Manifest tests

Verify:

- measure type, effective unit, and unit state are complete and deterministic;
- uniform fields are executable;
- mixed/unknown fields carry explicit limitations;
- values absent from some matching entities remain partial;
- an untyped numeric field is not promoted by its name;
- old manifest versions are rejected as stale and regenerated by ingestion.

### 7.3 Backend tests

Without live OpenAI calls, verify:

- a typed uniform field is present in the complete manifest/candidate universe;
- count/list and unrelated query behavior is unchanged;
- exact numeric filter and aggregate operations read raw values correctly;
- aggregate evidence includes the effective IFC unit;
- matched/coverage counts remain truthful;
- a unitless literal uses and discloses the field's effective unit;
- an equivalent spelling of the same unit is accepted;
- a different explicit unit is unavailable rather than silently converted;
- mixed or unknown units cannot produce a misleading aggregate;
- missing dimensional data remains unavailable rather than zero;
- source-model isolation and parameter binding remain intact;
- no response-contract or LLM-call-count regression is introduced.

Run the existing ingestion test suite and relevant backend offline/live read-only suites.
Run a focused regression set for non-numeric queries. Do not run the costly live LLM
benchmark solely for this ingestion/units task.

### 7.4 Four-model completion evidence

For each of the four production files, record:

- source-model ID and unchanged fingerprint;
- entity/relationship/RAG row counts before and after;
- extraction and manifest versions;
- resolved default length/area/volume units;
- typed value and field counts by measure type;
- uniform/mixed/unknown field counts;
- one deterministic supported numeric query when the source provides a suitable typed
  field;
- an honest unavailable result where the source lacks trustworthy typed dimensional data;
- final notebook readiness verdict.

Do not include credentials, full canonical JSON, vectors, or unbounded value dumps in the
completion report.

---

## Acceptance outcome

After Task 27:

1. Running `ingestion/notebooks/ingestion.ipynb` for a new IFC automatically captures
   standards-based length, area, and volume measure metadata and the IFC's original
   effective units.
2. Model default unit definitions are stored once; values store their measure type and
   only an explicit occurrence override when present.
3. The semantic manifest exposes supported numeric fields, coverage, and safe unit state
   without field-name or model-specific inference.
4. The existing backend can filter and aggregate uniform typed values and return their
   effective IFC unit.
5. Different requested units, mixed units, unknown units, and untyped numeric values fail
   honestly instead of being silently converted or mislabelled.
6. All four existing IFC files have been re-ingested through the production notebook
   function, with stable model/entity identity and regenerated current manifests.
7. No frontend source changes, new derived calculations, density logic, geometry-derived
   measurements, extra LLM calls, or unrelated backend redesign have been introduced.

---

## Completion record (merged into `specs/spec_v001_ifc_to_db.md` §20)

Extraction **v001 → v002**; manifest schema/builder **v001 → v002**; unit contract **v001**.

The full contract, the four-model evidence table, the test coverage, and the status block live in
`specs/spec_v001_ifc_to_db.md` §20. The active unit sections of
`specs/spec_v002_query_architecture.md` (§9.1, §9.2) and `specs/spec_v003_sql_query_path.md`
(§4, §10, §14) were rewritten in place, and `docs/architecture_v003.md` records that its
`mm`-only caveat is superseded.

### Acceptance outcome

1. `run_full_ingestion()` captures standards-based length/area/volume measure metadata and each
   IFC's own effective units automatically — no manual unit entry, no per-model config, no
   post-ingestion JSON edit. **Met.**
2. Model unit definitions are stored once in `extraction_metadata.dimension_units`; a value stores
   its `measure_type` and only an explicit `unit_override_key`. **Met.**
3. The manifest exposes supported numeric fields, coverage, and unit state with no field-name or
   model-specific inference. **Met.**
4. The backend filters and aggregates uniform typed values and returns the effective IFC unit
   (`sum`/`min`/`max`/`average`). **Met.**
5. Different, mixed, unknown, and untyped units fail honestly. **Met.**
6. All four IFC files re-ingested through the production notebook function with stable identity and
   regenerated current manifests. **Met.**
7. No frontend change, derived calculation, density logic, geometry-derived measurement, extra LLM
   call, or unrelated backend redesign. **Met**, with one in-scope repair recorded below.

### The one fix outside the literal scope

`binding/validate.py` rejected every ordered comparison, because a field candidate advertises its
capabilities in the typed SQL vocabulary (`gt`, `lte`) while a binding speaks the `BoundOperator`
vocabulary (`greater_than`, `less_or_equal`) and the support check compared the two directly. No
numeric filter could ever validate, so §4.3 was unsatisfiable while it stood. The check now
translates between the vocabularies; the slate payload is unchanged.

### Two observations left for the owner

- **Vector cost of a canonical-JSON change.** `stage2_embed` keys its skip on
  `hash(canonical_json)`, so adding measure metadata invalidated every entity document and bumping
  the extraction version invalidated every relationship document — ~350k documents re-embedded for
  text that was byte-identical, and identical vectors written back. This is the behaviour §2.4 asks
  for ("refresh downstream artifacts whose source hash/content changed") and was left alone. A
  future task could make the skip compare `text_hash` first and treat `source_hash` as advisory.
- **Model 1 cannot answer dimensional questions, by design of its source.** Schependomlaan carries
  exactly one typed dimensional value (its single storey `Elevation`). Its 276,491 property values
  are `IfcReal`/`IfcLabel`/`IfcBoolean` and its 205 doors leave `OverallHeight`/`OverallWidth`
  unset. Any future benchmark expecting door or window dimensions from this model will get an
  honest `unavailable`.
