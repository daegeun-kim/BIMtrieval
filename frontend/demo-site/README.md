# Demo site

The public static demo. Specified by
[`specs/spec_v013_demo_site.md`](../../specs/spec_v013_demo_site.md).

**Live:** https://daegeun-kim.github.io/BIMtrieval/

## What this is

The real BIMtrieval frontend, with the backend replaced by frozen fixtures. A
visitor gets the actual 3D viewer and the actual chat interface, and can ask
three questions that were recorded in advance from a live local run. There is no
database, no backend, and no API key behind the page.

| Question | Operation | Basis | Panel |
| --- | --- | --- | --- |
| How many doors are in this model? | `count` | `exact_sql` | result table |
| Break down the elements by IFC class. | `group_distribution` | `exact_sql` | bar chart |
| Describe the walls in this model. | qualitative | `hybrid_evidence` | — |

Each card shows only its question until it is asked; the retrieval basis, the
bound operation and the recorded latency appear afterwards, so a visitor watches
the system decide rather than reading a label. The badge shows `answer_basis`
rather than `route` because the current pipeline returns `route: "hybrid"` for
every active-model question.

It exists because the application is otherwise unreachable without cloning the
repository, standing up PostgreSQL, importing an IFC model, and supplying an
OpenAI key. That remains the right posture for the application — see the README's
deployment section — but it is a wall between the project and anyone who just
wants to look at it.

## How it works

Nothing under `frontend/src/` is modified. The demo is composed from it by
aliasing exactly **two** modules in `vite.config.ts`:

| Real module | Replaced by | Why one alias is enough |
| --- | --- | --- |
| `src/api/client.ts` | `src/fixtureClient.ts` | `api` is exported once and imported once (`src/state/controller.ts`); every backend call passes through it |
| `src/chat/Composer.tsx` | `src/DemoComposer.tsx` | zero-prop default export, imported once (`src/chat/ChatPanel.tsx`) |

Everything else — viewer, transcript, explanation panel, component panel, store,
controller — runs unmodified and unaware.

`frontend/tests/demo-site.test.ts` asserts both modules stay single-import and
that no file under `src/` ever imports from `demo-site/`. Those tests run in the
normal offline gate, so a refactor that breaks the demo fails there rather than
in a browser.

## Commands

Run from `frontend/`:

```bash
npm run dev:demo
```

```bash
npm run build:demo
```

```bash
npm run preview:demo
```

The demo's commands are all suffixed `:demo`. `npm test`, `npm run typecheck`,
`npm run lint`, and `npm run build` keep their existing meaning and do not build
the demo.

## Re-capturing the fixtures

The fixtures in `fixtures/` are verbatim recordings. To refresh them, start the
local stack with your own `.env` (the model imported as `source_model_id 1`),
then:

```bash
npm run capture:demo
```

This records the three questions — the only step that spends tokens — plus the
catalog, floor bands, selection resolution, entity details, and highlight groups,
which are deterministic and LLM-free.

Each question is asked three times and the best-scoring answer kept, because the
same question does not give the same answer twice: one run of "what elements are
contained in this storey?" said 3,505 elements and the next said "contains none".
Every attempt is logged so the spread is visible. This selects among **real**
recorded runs — nothing is edited — but it does show the system at its best, and
spec_v013 §7.4 says so.

Tune with `BIM_DEMO_API`, `BIM_DEMO_MODEL_ID`, and `BIM_DEMO_ATTEMPTS`.

`scripts/probe.ts` is the companion tool for choosing questions: it asks
candidates and reports route, basis, operation and panel type without writing
fixtures.

    npx tsx demo-site/scripts/probe.ts "a candidate question"

The three questions were chosen by measuring the current backend, not from the
published benchmark — that file records an earlier pipeline (spec_v013 §5.4).

The script never reads `.env` and never handles a key; it talks HTTP to a backend
you already started.

Then copy the prepared 3D artifact:

```bash
cp ../../model_assets/1/57fafa59f03b18c05be211a456e346bdd0445d5c35d66522e598d339e81dfcf4.frag public/model.frag
```

## The 3D model

`public/model.frag` (5.5 MB) is committed — it is the demo's payload, not build
output. The deploy workflow fails loudly if it is missing, so the demo cannot
quietly ship with an empty viewer.

The model is redistributed under CC BY 4.0. Attribution lives in
`public/ATTRIBUTION.txt` and, because CC BY requires the credit to actually reach
the viewer, on the page itself — the browser suite asserts it is there.

One residual licence question was identified and consciously accepted rather than
resolved; spec_v013 §8.3 records it and the fallback.
