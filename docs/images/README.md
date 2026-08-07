# Screenshots

Five images the README expects. Until they exist, the README's image block is
commented out, so nothing renders broken.

**To publish them:** capture the files below into this folder, then open
`README.md` and delete the two `<!-- SCREENSHOTS ... -->` comment markers near
the top.

Use real application output. A mockup that a reviewer later discovers was not
the running system costs more credibility than having no screenshot at all.

## The five

| File | What to show | Notes |
| --- | --- | --- |
| `hero.png` | The whole app: 3D model on the left, a chat answer on the right, matching objects highlighted | This is the one that decides whether anyone scrolls. Use a model with recognisable massing, not a single wall |
| `viewer.png` | The 3D viewer alone, model loaded, camera on an informative angle | Shows the Fragments/Three.js viewer is real |
| `chat-answer.png` | A question and its grounded answer, with the count visible | Pick a question with an exact numeric answer — that is the claim that distinguishes this from a chatbot |
| `selection.png` | Query results highlighted in the model, with the selection chips visible | Shows the answer and the geometry are linked |
| `floor-plan.png` | Floor-plan mode on a storey, black wall poché visible | Shows the AEC-native output, not a generic 3D toy |
| `explanation.png` | The Query Explanation panel open, showing why an answer was produced | The product instinct the evaluation singles out — worth its own shot |

Six files are listed; `hero.png` may be a crop of the same session as the others.

## Capture notes

- **Window size:** 1600×1000 or wider. A narrow window collapses the layout and
  the screenshots stop showing the three-panel design.
- **Format:** PNG. Keep each under ~500 KB — these are committed, and this
  repository has already carried one 63 MB file it should not have.
- **Theme:** whatever the app renders by default. Do not retouch.
- **Redaction:** nothing here should contain a path, a key, or a client's
  building name. Check the window title and any visible file paths before
  saving.

## What costs money

Loading a model, orbiting the viewer, switching floors, and clicking through
selection make **no** OpenAI calls at all — those screenshots are free.

Only `chat-answer.png` and `explanation.png` require live queries, since both
need a real answer to exist.

## Optional: a 60-second demo

If you record one, put it on YouTube or as a GitHub release asset rather than
committing the video, and link it from the README next to the hero image. A
broken or missing video link is worse than no video, so only add the link once
it resolves.

Suggested arc: load a model (5 s) → ask an exact count and watch the objects
highlight (20 s) → open the explanation panel (15 s) → switch to floor-plan mode
(10 s) → ask something the model cannot answer and show it refuse (10 s).

That last beat is the one worth keeping. Anything can look good answering a
question it knows; the refusal is what shows the grounding works.
