import { expect, test } from "@playwright/test";

test("landing page renders with primary CTAs", async ({ page }) => {
  await page.goto("/");
  // Heading visible
  await expect(page.locator("h1").first()).toBeVisible();
  // At least one of the demo-related buttons is on the page
  await expect(page.getByRole("button", { name: /demo|coffee|retail/i }).first()).toBeVisible();
});

test("templates link goes to the ERP templates page", async ({ page }) => {
  await page.goto("/upload/templates");
  // The ERP templates page enumerates Shopify, NetSuite, SAP, QuickBooks, Square
  await expect(page.getByText("Shopify", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("NetSuite", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Square", { exact: false }).first()).toBeVisible();
});
