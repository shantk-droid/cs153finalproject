import { expect, test } from "@playwright/test";

/**
 * Doesn't actually fetch a real dataset — that requires the API to be running. Just verifies
 * the dashboard route shell renders client-side without throwing. A full SKU-detail e2e test
 * would require running the Python API alongside Next dev, which we wire up in CI via a
 * separate job. For local smoke this is enough.
 */
test("dashboard route for a fake id renders the layout shell or a graceful error", async ({ page }) => {
  await page.goto("/dashboard/not-a-real-id");
  // Either the layout sidebar appears (in which case the API is up) or the page surfaces
  // a 404/empty state — neither should crash with a runtime error overlay.
  const errorOverlay = page.locator("text=/Application error|Unhandled Runtime Error/i");
  await expect(errorOverlay).toHaveCount(0);
});
