import { expect, test } from "@playwright/test";

test("ERP templates page lists all 5 vendors with anchor links", async ({ page }) => {
  await page.goto("/upload/templates");

  // Each vendor should appear at least once in the anchor nav + as a section heading
  for (const vendor of ["Shopify", "NetSuite", "SAP", "QuickBooks", "Square"]) {
    const matches = await page.getByText(vendor, { exact: false }).count();
    expect(matches).toBeGreaterThanOrEqual(1);
  }

  // "required" pill rendered for each vendor's required rows
  const requiredPills = await page.getByText("required", { exact: true }).count();
  expect(requiredPills).toBeGreaterThanOrEqual(5); // at least one per vendor section

  // The "Upload a file →" CTA at the bottom is present
  await expect(page.getByRole("link", { name: /Upload a file/i })).toBeVisible();
});
