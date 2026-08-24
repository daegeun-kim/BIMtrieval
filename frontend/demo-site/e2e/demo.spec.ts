// Browser test for the static demo (spec_v013 §11.2).
//
// Covers the three things that are demo-specific and would fail silently: the
// model loads WITHOUT a confirmation click, the picker withholds the route until
// a question is asked, and the CC BY attribution is actually on the page.
//
// The 3D artifact is stubbed with the small tracked `smoke-wall.frag` fixture
// rather than the demo's real 5.5 MB model, which is not in Git until the
// licence check clears (§8.3). The source fingerprint is only ever used as a
// cache key, never validated against the bytes, so the substitution loads
// cleanly — and this still exercises the real Fragments worker and WebGL.
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const FIXTURE_FRAG = path.resolve(
  import.meta.dirname,
  "..",
  "..",
  "tests",
  "fixtures",
  "smoke-wall.frag",
);

async function stubModel(page: Page) {
  const frag = readFileSync(FIXTURE_FRAG);
  await page.route("**/model.frag", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/octet-stream",
      body: frag,
      headers: { ETag: '"demo-e2e"' },
    }),
  );
}

test.describe("static demo", () => {
  test.beforeEach(async ({ page }) => {
    await stubModel(page);
  });

  test("boots straight into the model, with no confirmation click", async ({ page }) => {
    await page.goto("/");

    // The real application asks "Load model?" before touching the viewer. The
    // demo performs that confirmation itself (§4.6), so a visitor never sees it.
    await expect(page.getByRole("button", { name: /^Load$/ })).toHaveCount(0);

    // Something is visibly happening while the engine bundle and the model
    // arrive. A motionless grey field reads as a broken page, and this demo's
    // first impression is the whole point of it existing.
    await expect(page.locator(".demo-spinner")).toBeVisible();

    // Loading finishes: the phase overlay retires once the scene is ready.
    await expect(page.locator(".viewer-overlay")).toHaveCount(0, { timeout: 45_000 });

    // And the curtain lifts. It covers the canvas until the opening camera pose
    // is applied (§6.5); if that step ever throws or never runs, the demo would
    // publish a blank viewport that looks like a broken page rather than a
    // building. Worth asserting rather than trusting.
    await expect(page.locator(".demo-curtain")).toHaveClass(/is-lifted/, { timeout: 15_000 });

    // The spinner goes with it — two progress indicators on screen at once, or
    // one that never stops, both say "still working" about a finished page.
    await expect(page.locator(".demo-curtain-inner")).toHaveCSS("opacity", "0");
  });

  test("withholds the route until a question is asked", async ({ page }) => {
    await page.goto("/");

    const cards = page.locator(".demo-question");
    await expect(cards).toHaveCount(3);

    // Before asking, a card carries its question and nothing that gives away
    // which retrieval path the router will choose (§5.1).
    for (const basis of ["exact_sql", "graph_traversal", "hybrid_evidence"]) {
      await expect(page.locator(`.demo-route-${basis}`)).toHaveCount(0);
    }

    const firstQuestion = page.getByRole("button", { name: /Ask: How many doors/ });
    await firstQuestion.click();

    // The question reaches the real transcript through the real controller.
    await expect(page.locator(".demo-question").first()).toHaveClass(/is-answered/);

    // And only now does the card report what the router did, with the recorded
    // cost beside it so an instant replay never reads as a latency claim (§6.4).
    const revealed = page.locator(".demo-question").first().locator(".demo-routed");
    await expect(revealed).toBeVisible();
    await expect(revealed).toContainText("answered by");
    await expect(revealed).toContainText(/took .* s/);
  });

  test("opens on Fast quality, and still offers the other two", async ({ page }) => {
    await page.goto("/");

    // A public demo cannot know what machine it landed on, so it opens at the
    // cheapest quality (§6.6) — while leaving the real control operable, which
    // is the half that would be easy to break without noticing.
    const modes = page.getByRole("radiogroup", { name: /visualization quality/i });
    await expect(modes.getByRole("radio")).toHaveCount(3);
    await expect(modes.getByRole("radio", { name: /fast/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    await modes.getByRole("radio", { name: /fine/i }).click();
    await expect(modes.getByRole("radio", { name: /fine/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  test("labels the single floor band 'Floor plan', not 'Floor 1'", async ({ page }) => {
    await page.goto("/");
    const controls = page.getByTestId("floor-controls");
    await expect(controls).toBeVisible({ timeout: 45_000 });

    // The backend numbers logical bands, so one band arrives as "Floor 1" —
    // which promises a Floor 2 that does not exist and implies this model has
    // meaningful storey structure. Its storey labelling is faulty in the source
    // IFC, and BIMtrieval does not correct source data, so the button says what
    // it does rather than making a claim about the building.
    //
    // Asserted because `capture.ts` regenerates floors.json from the backend:
    // without this, a re-capture would quietly restore "Floor 1".
    await expect(controls.getByRole("button", { name: "Floor plan" })).toBeVisible();
    await expect(controls.getByRole("button", { name: "Floor 1" })).toHaveCount(0);

    // The 3D toggle is untouched.
    await expect(controls.getByRole("button", { name: "3D" })).toBeVisible();
  });

  test("docks the disclosure card above the readout, matching its width", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".demo-curtain")).toHaveClass(/is-lifted/, { timeout: 45_000 });

    // The card's position and width are measured from `.readout` at runtime,
    // because that card sizes to its content. Two bugs have already come out of
    // this corner — covering the quality control, then docking against a
    // half-rendered readout and keeping stale numbers — so the geometry is
    // asserted rather than eyeballed.
    const readout = await page.locator(".readout").boundingBox();
    const banner = await page.locator(".demo-banner").boundingBox();
    expect(readout).not.toBeNull();
    expect(banner).not.toBeNull();

    expect(Math.abs(banner!.x - readout!.x)).toBeLessThan(2);
    expect(Math.abs(banner!.width - readout!.width)).toBeLessThan(2);

    // Above it, and not on top of it.
    const gap = readout!.y - (banner!.y + banner!.height);
    expect(gap).toBeGreaterThan(0);
    expect(gap).toBeLessThan(24);
  });

  test("states that it is a recording, and credits the model", async ({ page }) => {
    await page.goto("/");

    const banner = page.locator(".demo-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/no backend/i);

    // CC BY 4.0 requires the credit to reach the person looking at the work, so
    // its presence on the page is a licence obligation, not decoration (§8.2).
    const attribution = page.locator(".demo-attribution");
    await expect(attribution).toContainText("Schependomlaan");
    await expect(attribution).toContainText("CC BY 4.0");
    await expect(attribution).toContainText(/converted/i);
  });
});
