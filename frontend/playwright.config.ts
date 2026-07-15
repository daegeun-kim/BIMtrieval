import { defineConfig, devices } from "@playwright/test";

// Critical-path browser suite (spec_v006 §18.2). The dev server is started
// automatically; tests stub network/viewer so they never touch OpenAI or
// PostgreSQL. Chromium desktop only — this is a desktop-first local prototype.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
