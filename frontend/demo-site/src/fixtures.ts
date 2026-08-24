// Frozen fixture access for the static demo (spec_v013 §7).
//
// Every payload here is a VERBATIM response envelope recorded from a real local
// backend run against the Schependomlaan model (spec_v013 §7.2). Nothing is
// hand-authored to look plausible: if a value is on screen in the demo, the live
// system produced it.
//
// JSON imports arrive typed as their own literal shape, which does not
// structurally satisfy the OpenAPI-derived unions in `src/api/types.ts` (a
// recorded `"sql"` is a `string` to TypeScript, not a `QueryRoute`). The casts
// below are therefore unavoidable; the guarantee is moved to runtime instead, in
// `frontend/tests/demo-fixtures.test.ts`, which asserts every recorded envelope
// still carries the fields the UI reads.
import type {
  EntityDetailsResponse,
  HighlightGroupResponse,
  HighlightScope,
  ModelFloorsResponse,
  ModelListResponse,
  QueryResponseEnvelope,
  ResolveEntitiesResponse,
} from "../../src/api/types";

import floorsJson from "../fixtures/floors.json";
import loadModelJson from "../fixtures/load-model.json";
import modelsJson from "../fixtures/models.json";
import questionsJson from "../fixtures/questions.json";
import resolveJson from "../fixtures/resolve.json";

/** One canned question, as offered by the picker and replayed on click. */
export interface DemoQuestion {
  /** Case id this was recorded under (spec_v013 §5). */
  id: string;
  /** The exact question text submitted to the backend during capture. */
  text: string;
  /**
   * What the recorded run actually did. All four come from the captured
   * envelope, never from hand-written metadata, so the label on a card cannot
   * contradict the answer beneath it.
   *
   * `basis` is the meaningful one: every active-model question returns
   * `route: "hybrid"` in the current pipeline, because retrieval mode is derived
   * from the bound operation rather than classified up front.
   */
  route: string;
  basis: string;
  operation: string | null;
  presentation: string | null;
  /** One line on what this question demonstrates. */
  blurb: string;
  /**
   * Viewer selection the recorded run was made with. `graph-01` was asked with a
   * storey already selected, and the question is meaningless without it
   * (spec_v013 §5.3).
   */
  preSelection: { globalIds: string[]; note: string } | null;
  /**
   * What the live system actually took for this question, measured during
   * capture. Displayed with every answer so an instant replay never reads as a
   * latency claim (spec_v013 §6.4).
   */
  recorded: { latencyMs: number };
}

interface QuestionsManifest {
  questions: DemoQuestion[];
}

export const demoQuestions: DemoQuestion[] = (questionsJson as QuestionsManifest).questions;

export const modelsFixture = modelsJson as unknown as ModelListResponse;
export const floorsFixture = floorsJson as unknown as ModelFloorsResponse;
export const loadModelFixture = loadModelJson as unknown as QueryResponseEnvelope;
export const resolveFixture = resolveJson as unknown as ResolveEntitiesResponse;

/** Find the question a submitted string corresponds to, if any. */
export function questionForText(text: string): DemoQuestion | undefined {
  const needle = text.trim().toLowerCase();
  return demoQuestions.find((q) => q.text.trim().toLowerCase() === needle);
}

/**
 * Recorded answer envelopes, split out of the initial bundle. They are needed
 * only once a visitor picks a question, so the first paint does not carry them.
 */
export async function answerFor(question: DemoQuestion): Promise<QueryResponseEnvelope> {
  switch (question.id) {
    case "count-01":
      return (await import("../fixtures/answers/count-01.json"))
        .default as unknown as QueryResponseEnvelope;
    case "group-01":
      return (await import("../fixtures/answers/group-01.json"))
        .default as unknown as QueryResponseEnvelope;
    case "describe-01":
      return (await import("../fixtures/answers/describe-01.json"))
        .default as unknown as QueryResponseEnvelope;
    default:
      throw new Error(`No recorded answer for question ${question.id}`);
  }
}

// The captured detail and highlight sets are the demo's largest payloads and are
// read only when a visitor clicks an element, so they load on demand and are
// cached after the first use.
let entitiesCache: Record<string, EntityDetailsResponse> | null = null;
let highlightsCache: Record<string, HighlightGroupResponse> | null = null;

export async function entityDetailsFor(globalId: string): Promise<EntityDetailsResponse | null> {
  if (!entitiesCache) {
    entitiesCache = (await import("../fixtures/entities.json")).default as unknown as Record<
      string,
      EntityDetailsResponse
    >;
  }
  return entitiesCache[globalId] ?? null;
}

export async function highlightGroupFor(
  globalId: string,
  scope: HighlightScope,
): Promise<HighlightGroupResponse | null> {
  if (!highlightsCache) {
    highlightsCache = (await import("../fixtures/highlights.json")).default as unknown as Record<
      string,
      HighlightGroupResponse
    >;
  }
  return highlightsCache[`${globalId}::${scope}`] ?? null;
}
