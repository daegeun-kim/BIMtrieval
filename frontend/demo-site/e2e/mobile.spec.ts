// Mobile layout checks (spec_v013 §6.7).
//
// The application is desktop-first, and the demo restyles its panels into a
// stacked phone layout entirely from CSS in the demo layer. Nothing about that
// is visible to a desktop test, so it gets its own suite at a phone viewport.
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

test.use({ viewport: { width: 390, height: 844 } });

test.describe("mobile layout", () => {
  test.beforeEach(async ({ page }) => {
    await stubModel(page);
    await page.goto("/");
    await expect(page.locator(".demo-curtain")).toHaveClass(/is-lifted/, { timeout: 45_000 });
  });

  test("stacks the viewer above the panel, both full width", async ({ page }) => {
    const viewer = (await page.locator(".viewer-canvas").boundingBox())!;
    const panel = (await page.locator(".panel").boundingBox())!;
    const width = page.viewportSize()!.width;

    // Full width each — the desktop layout docks the panel to the right of the
    // viewer, which is the thing being undone here.
    expect(Math.round(viewer.width)).toBe(width);
    expect(Math.round(panel.width)).toBe(width);

    // Viewer on top, panel below, meeting rather than overlapping.
    expect(viewer.y).toBeLessThan(panel.y);
    expect(Math.abs(viewer.y + viewer.height - panel.y)).toBeLessThan(2);

    // Both get a usable share of the screen.
    expect(viewer.height).toBeGreaterThan(200);
    expect(panel.height).toBeGreaterThan(200);
  });

  test("keeps the question picker and the quality control reachable", async ({ page }) => {
    // The picker is the only way to ask anything, so it has to be on screen and
    // clickable at this size, not merely present in the DOM.
    const first = page.locator(".demo-question").first();
    await expect(first).toBeVisible();
    await first.click();
    await expect(first).toHaveClass(/is-answered/);

    // The readout sheds its text lines on mobile but keeps its actions row.
    await expect(page.locator(".readout-line")).toBeHidden();
    const modes = page.getByRole("radiogroup", { name: /visualization quality/i });
    await expect(modes.getByRole("radio", { name: /fast/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await modes.getByRole("radio", { name: /standard/i }).click();
    await expect(modes.getByRole("radio", { name: /standard/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  test("does not scroll sideways", async ({ page }) => {
    // The single most common phone-layout failure, and invisible on desktop.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("still discloses that it is a recording, with attribution", async ({ page }) => {
    // The disclosure and the CC BY credit are obligations, not decoration, and
    // a narrow screen is exactly where a card like this tends to get dropped.
    await expect(page.locator(".demo-banner")).toBeVisible();
    await expect(page.locator(".demo-attribution:visible")).toContainText("CC BY 4.0");
  });
});
