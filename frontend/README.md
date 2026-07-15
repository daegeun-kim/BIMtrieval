# BIM RAG Frontend

Local desktop BIM viewer + conversational frontend (spec_v006). React +
TypeScript + Vite, with a That Open Fragments 3D viewer and a floating chat
panel over the full-viewport scene. Talks only to the local FastAPI backend —
never to PostgreSQL or OpenAI directly.

## Development

```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173 (backend expected at :8000)
```

Configuration: copy `.env.example` to `.env.local` if the backend runs
elsewhere (`VITE_API_BASE_URL`). No secrets belong in frontend env files.

## Scripts

| command | purpose |
| --- | --- |
| `npm run dev` | Vite dev server on :5173 |
| `npm run build` | type-checked production build to `dist/` |
| `npm run typecheck` | strict TypeScript project check |
| `npm run lint` | ESLint |
| `npm run test` | Vitest unit/component suite (mocked API + viewer) |
| `npm run test:e2e` | Playwright critical path (stubbed backend, real viewer) |
| `npm run gen:api` | regenerate `src/types/api.ts` from the backend OpenAPI snapshot |
| `npm run prepare:model` | one-time IFC → Fragments artifact preparation |

## Preparing a viewer artifact

The viewer renders a prepared immutable Fragments artifact, never raw IFC:

```powershell
npm run prepare:model -- --input "<path to .ifc>" --model-id 1 --check-guid "<known GlobalId>"
```

Output goes to `<repo>/model_assets/{model-id}/{sha256-of-ifc}.frag` (the same
fingerprint ingestion stores, so the backend can serve it). The tool validates
the artifact by reloading it and checking GlobalId identity before the atomic
rename. It never writes the database or modifies the source IFC.

## Structure

```text
src/
├── api/        # single typed client over generated OpenAPI types
├── chat/       # floating panel, messages, composer, evidence, candidates
├── components/ # selector, dialogs, status readout, icons
├── state/      # zustand store (serializable) + controller (async flows)
├── storage/    # IndexedDB artifact cache (LRU, fingerprint-keyed)
├── styles/     # "measured drawing" design tokens, bright mode only
├── types/      # generated api.ts (do not edit)
└── viewer/     # ViewerAdapter: all imperative That Open/Three.js code
scripts/        # prepare-viewer-model.ts (manual, never run by dev/backend)
tests/          # Vitest suites + small IFC/Fragments fixtures
e2e/            # Playwright critical-path suite
```

Key boundaries: React components never mutate the Three.js scene (only
`ViewerAdapter` does); no component issues raw `fetch` (only `api/client.ts`);
deterministic operations (selection resolution, model load, clear/reset) never
invoke the LLM.

## Regenerating API types

The OpenAPI snapshot is produced from the backend without starting a server:

```powershell
cd backend
poetry run python -c "import json; from app.main import app; open('../frontend_openapi_snapshot.json','w').write(json.dumps(app.openapi(), indent=2))"
cd ../frontend
npm run gen:api
```
