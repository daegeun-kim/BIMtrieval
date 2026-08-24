// Structural guards for the static demo (spec_v013 §11.1).
//
// The demo works by aliasing exactly two modules and touching nothing under
// `src/`. Both halves of that are invisible at runtime and easy to break by
// accident months later, so they are asserted here, in the offline gate.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const FRONTEND = join(__dirname, "..");
const SRC = join(FRONTEND, "src");
const DEMO = join(FRONTEND, "demo-site");
const FIXTURES = join(DEMO, "fixtures");

function walk(dir: string, match: RegExp): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full, match));
    else if (match.test(entry)) out.push(full);
  }
  return out;
}

const srcFiles = walk(SRC, /\.(ts|tsx)$/);

describe("demo aliasing stays possible", () => {
  // The demo replaces the backend by aliasing one module. That only works while
  // `api` has exactly one import site; a second one would leave half the demo
  // talking to a backend that does not exist, and the failure would appear in
  // the browser rather than here.
  it("src/api/client is imported exactly once", () => {
    const importers = srcFiles.filter((f) =>
      /from\s+["'][^"']*\/api\/client["']/.test(readFileSync(f, "utf8")),
    );
    expect(importers.map((f) => relative(FRONTEND, f))).toEqual([
      join("src", "state", "controller.ts"),
    ]);
  });

  // Likewise for the composer: one import site is what lets the picker replace
  // the free-text field without editing ChatPanel.
  it("src/chat/Composer is imported exactly once", () => {
    const importers = srcFiles.filter((f) =>
      /from\s+["']\.\/Composer["']/.test(readFileSync(f, "utf8")),
    );
    expect(importers.map((f) => relative(FRONTEND, f))).toEqual([
      join("src", "chat", "ChatPanel.tsx"),
    ]);
  });

  it("the aliased replacements exist", () => {
    const config = readFileSync(join(DEMO, "vite.config.ts"), "utf8");
    expect(config).toContain("fixtureClient.ts");
    expect(config).toContain("DemoComposer.tsx");
    expect(() => statSync(join(DEMO, "src", "fixtureClient.ts"))).not.toThrow();
    expect(() => statSync(join(DEMO, "src", "DemoComposer.tsx"))).not.toThrow();
  });
});

describe("the demo depends on src, never the reverse", () => {
  // spec_v013's central constraint. If a file under src/ ever reaches into
  // demo-site/, the demo has stopped being additive and the real application
  // can no longer be built without it.
  it("no file under src/ imports from demo-site", () => {
    const offenders = srcFiles.filter((f) => /demo-site/.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => relative(FRONTEND, f))).toEqual([]);
  });
});

describe("fixture manifest", () => {
  const manifest = JSON.parse(readFileSync(join(FIXTURES, "questions.json"), "utf8")) as {
    questions: Array<{
      id: string;
      text: string;
      route: string;
      basis: string;
      operation: string | null;
      presentation: string | null;
      blurb: string;
      preSelection: { globalIds: string[]; note: string } | null;
      recorded: { latencyMs: number };
    }>;
  };

  it("offers the three questions spec_v013 §5 selected", () => {
    expect(manifest.questions.map((q) => q.id)).toEqual(["count-01", "group-01", "describe-01"]);
  });

  // Each question is here to show the system doing something DIFFERENT. If a
  // re-capture ever collapses them onto one operation, the demo still works but
  // has stopped making its argument, and that should fail loudly.
  it("covers three different bound operations", () => {
    const operations = manifest.questions.map((q) => q.operation ?? `none:${q.id}`);
    expect(new Set(operations).size).toBe(operations.length);
  });

  it("reaches more than one retrieval basis", () => {
    expect(new Set(manifest.questions.map((q) => q.basis)).size).toBeGreaterThan(1);
  });

  // The badge shows `basis`, never `route`: every active-model question returns
  // "hybrid" in the current pipeline, so a route badge would print one word
  // three times. This asserts the reason, so a future reader does not "fix" the
  // badge back to route.
  it("records a route that is uniform, which is why the badge shows basis", () => {
    expect(new Set(manifest.questions.map((q) => q.route)).size).toBe(1);
  });

  it("has a recorded answer file for every question", () => {
    for (const q of manifest.questions) {
      expect(() => statSync(join(FIXTURES, "answers", `${q.id}.json`))).not.toThrow();
    }
  });

  // The instant replay must never read as a performance claim (§6.4), so every
  // question carries the live system's real cost and the UI shows it.
  it("carries a real recorded cost for every question", () => {
    for (const q of manifest.questions) {
      expect(q.recorded.latencyMs).toBeGreaterThan(1000);
    }
  });

  it("resolves every pre-selected entity it claims", () => {
    const resolve = JSON.parse(readFileSync(join(FIXTURES, "resolve.json"), "utf8")) as {
      resolved?: Array<{ global_id: string }>;
    };
    const known = new Set((resolve.resolved ?? []).map((e) => e.global_id));
    for (const q of manifest.questions) {
      for (const guid of q.preSelection?.globalIds ?? []) {
        expect(known, `pre-selection ${guid} for ${q.id} is not in resolve.json`).toContain(guid);
      }
    }
  });
});

describe("the demo ships no secrets", () => {
  // Matching the posture of backend/tests/test_deployment_policy.py: a static
  // site published to the open web is the last place a credential should reach.
  it("no credential-shaped string in demo sources, fixtures, or config", () => {
    const files = [
      ...walk(join(DEMO, "src"), /\.(ts|tsx|css)$/),
      ...walk(FIXTURES, /\.json$/),
      join(DEMO, "vite.config.ts"),
      join(DEMO, "index.html"),
    ];
    const credential = /\b(sk-[A-Za-z0-9]{16,}|postgres(ql)?:\/\/[^\s"']*:[^\s"']*@)/;
    for (const file of files) {
      expect(credential.test(readFileSync(file, "utf8")), `${relative(FRONTEND, file)}`).toBe(false);
    }
  });

  it("no OPENAI_API_KEY reference anywhere in the demo", () => {
    const files = [...walk(join(DEMO, "src"), /\.(ts|tsx)$/), join(DEMO, "vite.config.ts")];
    for (const file of files) {
      expect(readFileSync(file, "utf8")).not.toContain("OPENAI_API_KEY");
    }
  });
});
