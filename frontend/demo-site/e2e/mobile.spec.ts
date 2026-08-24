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

// Checked BEFORE the model loads, which every other case here skips past by
// waiting for the curtain. That window is not a detail: until the model arrives
// the status readout is an empty shell with no measurable width, so the
// disclosure card cannot dock and falls back to CSS. The desktop fallback put it
// inside the panel sheet on a phone, and no test that waits for load could see
// it.
test.describe("mobile layout before the model loads", () => {
  test("keeps the disclosure card in the viewer band, not over the panel", async ({ page }) => {
    // Deliberately never fulfilled: this pins the page in its loading state.
    await page.route("**/model.frag", () => {});
    await page.goto("/");

    const banner = (await page.locator(".demo-banner").boundingBox())!;
    const panel = await page.locator(".panel").boundingBox();
    expect(banner).not.toBeNull();

    // Inside the viewer band, which is the top 46% of the screen.
    const viewerBottom = page.viewportSize()!.height * 0.46;
    expect(banner.y + banner.height).toBeLessThanOrEqual(viewerBottom + 1);

    if (panel) {
      expect(banner.y + banner.height).toBeLessThanOrEqual(panel.y + 1);
    }
  });
});

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

  test("survives crossing the breakpoint, as a rotation does", async ({ page }) => {
    // The disclosure card measures the status readout to dock against it, and
    // crossing the breakpoint reflows that readout. Measuring mid-reflow once
    // pinned the card at 34 px wide and 1200 px tall, off the top of the screen
    // — reachable by simply rotating a phone.
    const sane = async () => {
      const readout = (await page.locator(".readout").boundingBox())!;
      const banner = (await page.locator(".demo-banner").boundingBox())!;
      expect(banner.width).toBeGreaterThan(80);
      expect(banner.y).toBeGreaterThanOrEqual(0);
      expect(Math.abs(banner.width - readout.width)).toBeLessThan(2);
      expect(banner.y + banner.height).toBeLessThan(readout.y + 1);
    };

    await sane();

    // portrait -> landscape -> desktop -> back
    for (const size of [
      { width: 844, height: 390 },
      { width: 1280, height: 800 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(size);
      await page.waitForTimeout(400); // past the settle re-measure
      await sane();
    }
  });

  test("still discloses that it is a recording, with attribution", async ({ page }) => {
    // The disclosure and the CC BY credit are obligations, not decoration, and
    // a narrow screen is exactly where a card like this tends to get dropped.
    await expect(page.locator(".demo-banner")).toBeVisible();
    await expect(page.locator(".demo-attribution:visible")).toContainText("CC BY 4.0");
  });
});
