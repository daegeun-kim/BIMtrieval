# model_assets/

Prepared viewer artifacts (That Open Fragments) served by the backend at
`GET /api/models/{source_model_id}/viewer-asset` (spec_v006 §9).

Layout:

```text
model_assets/
└── {source_model_id}/
    └── {source_fingerprint}.frag        # generated, NOT committed
        {source_fingerprint}.frag.meta.json
```

Artifacts are generated locally with the one-time preparation tool:

```powershell
cd frontend
npm run prepare:model -- --input "<path to .ifc>" --model-id <id>
```

The fingerprint is the SHA-256 of the source IFC — the same value ingestion
stores in `ifc_source_models.file_fingerprint` — so the backend can derive the
expected filename from database identity alone.

Everything in this directory except this README and `fixtures/` is gitignored;
generated artifacts are large and reproducible.
