# Frontend (placeholder)

This directory establishes the repository-level backend/frontend boundary
required by `specs/spec_v002_query_architecture.md` (Section 19). No
frontend implementation exists yet — Task 04 explicitly excludes building
the Three.js/IFC viewer or the chat UI ("Do not implement the actual
Three.js frontend").

Structure (mirrors spec_v002 Section 19):

```text
frontend/
├── src/
│   ├── viewer/       # Three.js/web-ifc viewer (later spec)
│   ├── chat/         # conversational chat UI
│   ├── api/          # POST /api/query client
│   ├── state/        # session/selection state
│   └── components/   # shared UI components
└── tests/
```

Implementation, framework choice, and build tooling are deferred to the
later frontend specification referenced in spec_v002 Section 23 ("Later
frontend specification").
