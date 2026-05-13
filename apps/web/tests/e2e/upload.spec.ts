import { expect, test } from "@playwright/test";

test("upload page mounts the dropzone", async ({ page }) => {
  await page.goto("/upload");
  // Dropzone region is labeled "Bring your SKU panel" in the header
  await expect(page.getByText(/Bring your SKU panel/i)).toBeVisible();
});
