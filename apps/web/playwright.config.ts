import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright smoke tests for the inventory-optimizer web app.
 *
 * Coverage:
 *   - tests/e2e/landing.spec.ts: landing page renders + Try-a-demo creates a dataset
 *   - tests/e2e/upload.spec.ts:  drop a CSV, confirm mapping, dashboard renders
 *   - tests/e2e/sku-detail.spec.ts: forecast / schedule / coverage all render
 *   - tests/e2e/chat.spec.ts: chat panel sends a message and renders a tool call
 *
 * Local run:
 *   cd apps/web && npm install && npx playwright install chromium && npm run test:e2e
 *
 * CI run: see .github/workflows/ci.yml — uses webServer to spin up the Next dev server.
 *
 * Notes on the chat smoke test: when ANTHROPIC_API_KEY is unset in CI, the orchestrator
 * falls back to an SSE error event ("ANTHROPIC_API_KEY is not set"). The chat test asserts
 * the message bubble appears with some error text — it does NOT assert real LLM output.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Spin up Next dev server for local + CI runs unless an external URL is provided.
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: "http://localhost:3000",
        reuseExistingServer: !process.env.CI,
        stdout: "pipe",
        stderr: "pipe",
        timeout: 120 * 1000,
      },
});
