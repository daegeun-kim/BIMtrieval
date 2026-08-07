# `ifc/` — put your IFC models here

This is the one place BIMtrieval looks for local IFC files. Drop a `.ifc` file in
this folder and import it by name:

```powershell
conda activate bim_rag
bim-import "My Building.ifc"
```

A path also works, from anywhere on disk, so you never have to copy a large file
just to ingest it:

```powershell
bim-import "D:\models\My Building.ifc"
bim-import ../shared/site-model.ifc
```

`bim-import` runs the complete idempotent workflow — structured import, semantic
manifest, and stored vectors. Re-running it on the same file is safe: content is
fingerprinted, so an unchanged model is recognised rather than duplicated.

Run `bim-db-init` once before your first import to create the schema.

## Why there is no upload button

IFC models are large — the four this project was developed against are 21 MB to
170 MB. Pushing that through a browser, or through a public API, would be slow,
failure-prone, and would put someone else's building data on a server. Ingestion
is deliberately a local operation against a local file path.

## Nothing here is committed

`.gitignore` excludes every `*.ifc` in this folder. Building models are large and
usually licensed, so they stay on your machine. Only this README is tracked.

The automated tests do not need a real model: they use the 1.6 KB
`frontend/tests/fixtures/smoke-wall.ifc` fixture, and every database-backed suite
skips cleanly when nothing has been imported.

## The models this project was developed against

None are redistributed here. Each is a publicly available IFC sample from its
own source:

| File | Notes |
| --- | --- |
| `IFC Schependomlaan incl planningsdata.ifc` | The reference model used throughout the specs and evaluation (63 MB) |
| `FOJAB_Landsarkivet.ifc` | Larger multi-storey architectural model (170 MB) |
| `SampleArchitecture.ifc` | (109 MB) |
| `Wellness_center_Sama.ifc` | (21 MB) |
