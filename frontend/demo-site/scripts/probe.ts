/**
 * Question probe — a scratch tool for CHOOSING the demo's questions, not for
 * building it (spec_v013 §5).
 *
 * Asks candidate questions against a running local backend, each in its own
 * session, and reports the route, the answer basis, and the evidence counts.
 * Writes no fixtures: `capture.ts` does that, once the questions are settled.
 *
 * It exists because the published benchmark is a record of an earlier pipeline.
 * Which retrieval method a question actually reaches has to be measured against
 * the code as it stands, not assumed from that file.
 *
 *   npx tsx demo-site/scripts/probe.ts "question one" "question two"
 *
 * Pass `--storey` to select the model's first storey before asking, for
 * questions phrased around a selection.
 */
const API = process.env.BIM_DEMO_API ?? "http://localhost:8000";
const MODEL_ID = Number(process.env.BIM_DEMO_MODEL_ID ?? 1);

type Json = Record<string, unknown>;

async function post(path: string, body: unknown): Promise<Json> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return (await res.json()) as Json;
}

async function storeyGlobalId(): Promise<string | undefined> {
  const res = await fetch(`${API}/api/models/${MODEL_ID}/floors`);
  const floors = (await res.json()) as {
    floors?: Array<{ storey_global_ids?: string[] }>;
  };
  return floors.floors?.[0]?.storey_global_ids?.[0];
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const withStorey = args.includes("--storey");
  const questions = args.filter((a) => a !== "--storey");
  if (questions.length === 0) {
    console.error('Usage: tsx probe.ts [--storey] "question" ["question" …]');
    process.exitCode = 1;
    return;
  }

  const storey = withStorey ? await storeyGlobalId() : undefined;
  if (withStorey) console.log(`Selection: ${storey ?? "(none found)"}\n`);

  for (const question of questions) {
    const session = `probe-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    await post("/api/query", {
      question: "load model",
      session_id: session,
      confirm_model_id: MODEL_ID,
    });

    const started = Date.now();
    let envelope: Json;
    try {
      envelope = await post("/api/query", {
        question,
        session_id: session,
        active_source_model_id: MODEL_ID,
        ...(storey ? { selected_global_ids: [storey] } : {}),
      });
    } catch (err) {
      console.log(`✗ ${question}\n    ${err instanceof Error ? err.message : String(err)}\n`);
      continue;
    }
    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    const primary = ((envelope.primary_entities ?? []) as unknown[]).length;
    const context = ((envelope.context_entities ?? []) as unknown[]).length;
    const rels = ((envelope.relationships ?? []) as unknown[]).length;
    const explanation = envelope.answer_explanation as
      | { presentation?: string; operation?: string; groups?: unknown[] }
      | null
      | undefined;

    console.log(question);
    console.log(
      `    route=${String(envelope.route)}  basis=${String(envelope.answer_basis)}  ` +
        `${seconds}s  primary=${primary} context=${context} rels=${rels}`,
    );
    console.log(
      `    operation=${explanation?.operation ?? "-"}  ` +
        `presentation=${explanation?.presentation ?? "(no panel)"}  ` +
        `groups=${explanation?.groups?.length ?? 0}`,
    );
    console.log(`    ${String(envelope.answer ?? "").slice(0, 220).replace(/\s+/g, " ")}\n`);
  }
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exitCode = 1;
});
