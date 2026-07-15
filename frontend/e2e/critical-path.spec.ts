// Critical-path browser test (spec_v006 §18.2):
//   start -> list models -> confirm/load -> ask -> answer + evidence
//   -> Clear Chat -> Reset App
// The backend is fully stubbed (no OpenAI, no PostgreSQL); the viewer loads the
// small tracked fixture artifact, exercising the real Fragments worker + WebGL.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const FIXTURE_FRAG = path.resolve(import.meta.dirname, "..", "tests", "fixtures", "smoke-wall.frag");
const FP = "70bee96c9fe8db870535b3040052f59af1166616109a87d9e924a1e2e5e095c1";
const WALL_GUID = "0SmokeWallGuid000001xx";

async function stubBackend(page: Page) {
  const frag = readFileSync(FIXTURE_FRAG);

  await page.route("http://localhost:8000/**", async (route) => {
    const url = new URL(route.request().url());
    const body = route.request().postDataJSON?.() as Record<string, unknown> | null;

    if (url.pathname === "/api/models") {
      return route.fulfill({
        json: {
          models: [
            {
              source_model_id: 999,
              display_name: "Smoke House",
              source_fingerprint: FP,
              viewer_asset_status: "ready",
            },
          ],
        },
      });
    }
    if (url.pathname === "/api/models/999/viewer-asset") {
      return route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        body: frag,
        headers: { ETag: `"${FP}"` },
      });
    }
    if (url.pathname === "/api/query") {
      if (body?.reset === true) {
        return route.fulfill({
          json: envelope({ answer: "Session cleared.", route: "explain_general" }),
        });
      }
      if (body?.confirm_model_id != null) {
        return route.fulfill({
          json: envelope({
            answer: "Loaded model Smoke House.",
            active_source_model_id: 999,
            viewer_actions: {
              ...noActions(),
              model_action: "load_model",
              selection_action: "clear",
              load_model_id: 999,
              viewer_source_location: "/api/models/999/viewer-asset",
            },
          }),
        });
      }
      return route.fulfill({
        json: envelope({
          answer: "The model contains **one wall** named Smoke Wall.",
          active_source_model_id: 999,
          primary_entities: [
            { entity_id: 70, global_id: WALL_GUID, ifc_class: "IfcWall", name: "Smoke Wall", summary: null },
          ],
          viewer_actions: {
            ...noActions(),
            selection_action: "select_and_fit",
            primary_global_ids: [WALL_GUID],
          },
          evidence_summary: { basis: "exact_sql", sql_match_count: 1, notes: [] },
        }),
      });
    }
    return route.fulfill({ status: 404, json: { detail: "not stubbed" } });
  });
}

function noActions() {
  return {
    model_action: "keep_current",
    selection_action: "none",
    primary_global_ids: [],
    context_global_ids: [],
    role_groups: [],
    load_model_id: null,
    viewer_source_location: null,
  };
}

function envelope(partial: Record<string, unknown>) {
  return {
    request_id: "e2e",
    session_id: "s",
    status: "success",
    scope: "active_model",
    route: "sql",
    answer_basis: "exact_sql",
    answer: "",
    active_source_model_id: null,
    model_candidates: [],
    primary_entities: [],
    context_entities: [],
    relationships: [],
    viewer_actions: noActions(),
    evidence_summary: { basis: "exact_sql", notes: [] },
    warnings: [],
    ...partial,
  };
}

test("critical path: load, ask, evidence, clear chat, reset app", async ({ page }) => {
  await stubBackend(page);
  await page.goto("/");

  // start: selector populated from the model list
  const select = page.getByRole("combobox");
  await expect(select).toBeEnabled();

  // confirm/load
  await select.selectOption("999");
  await expect(page.getByRole("dialog")).toContainText("Load model?");
  await page.getByRole("button", { name: "Load", exact: true }).click();

  // scene ready (real fragments worker + fixture artifact)
  await expect(page.locator(".readout")).toContainText("ready", { timeout: 20_000 });
  await expect(page.locator(".readout")).toContainText("Smoke House");

  // ask a question
  const composer = page.getByLabel("Ask a question about the model");
  await composer.fill("How many walls are there?");
  await composer.press("Enter");
  await expect(page.locator(".msg-assistant .md")).toContainText("one wall");

  // evidence collapsed by default, expandable, citation present
  const toggle = page.locator(".ev-toggle");
  await expect(toggle).toContainText("sql");
  await expect(page.locator(".cite-primary")).toHaveCount(0); // collapsed
  await toggle.click();
  await expect(page.locator(".cite-primary")).toContainText("Smoke Wall");

  // Clear Chat: messages go, model stays
  await page.getByLabel("Clear chat").click();
  await expect(page.locator(".msg")).toHaveCount(0);
  await expect(page.locator(".readout")).toContainText("Smoke House");

  // Reset App: back to initial state, needs confirmation
  await page.getByLabel("Reset app").click();
  await expect(page.getByRole("dialog")).toContainText("Reset the app?");
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(page.locator(".readout")).toContainText("BIM Model Explorer");
  await expect(page.getByRole("combobox")).toHaveValue("");
});

test("backend unavailable shows a recoverable state", async ({ page }) => {
  await page.route("http://localhost:8000/**", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.locator(".readout")).toContainText("backend offline");
  // chat composer still present (recoverable, not a crash)
  await expect(page.getByLabel("Ask a question about the model")).toBeVisible();
});
