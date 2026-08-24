import { defineConfig, devices } from "@playwright/test";

// Browser suite for the static demo (spec_v013 §11.2). Separate from the
// application's `playwright.config.ts` so neither suite starts the other's dev
// server, and so `npx playwright test` keeps its existing meaning.
//
// Run with: npm run test:e2e:demo
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: {
    // The demo is served under the GitHub Pages base path even in dev.
    baseURL: "http://localhost:5174/BIMtrieval/",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev:demo",
    url: "http://localhost:5174/BIMtrieval/",
    cwd: "..",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
