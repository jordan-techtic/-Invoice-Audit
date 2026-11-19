import { expect, test } from "@playwright/test";
import { makePng } from "./png";

test("upload three invoices, fix the odometer, mark as checked", async ({ page }) => {
  const stamp = Date.now();
  const files = [1, 2, 3].map((i) => ({
    name: `e2e-${stamp}-${i}.png`,
    mimeType: "image/png",
    buffer: makePng(stamp % 100000 + i * 7919),
  }));

  await page.goto("/clients");

  await expect(page.getByRole("heading", { name: "Clients" })).toBeVisible();
  await page.getByRole("button", { name: "Work on Lone Prairie Freight" }).click();
  await expect(page.getByTestId("active-client")).toHaveText("Lone Prairie Freight");

  await expect(page.getByRole("heading", { name: "Upload invoices" })).toBeVisible();
  await page.locator("#file-input").setInputFiles(files);

  for (const f of files) {
    const row = page.getByRole("row").filter({ hasText: f.name });
    await expect(row).toBeVisible();
    await expect(row.getByText("Needs review", { exact: false }).first()).toBeVisible({ timeout: 60_000 });
  }
  await expect(page.locator('tr[data-status="queued"], tr[data-status="reading"]')).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Review invoices" }).first()).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Review" }).click();
  await page.getByRole("navigation", { name: "Review sections" }).getByRole("link", { name: "Invoices" }).click();
  await page.getByLabel("Show").selectOption("needs_review");
  await page.getByRole("link").filter({ hasText: /./ }).and(page.locator("tbody a")).first().click();

  const odometer = page.getByLabel("Odometer", { exact: true });
  await expect(odometer).toBeVisible();
  await expect(page.getByTestId("review-status")).toHaveText("Needs review");
  await odometer.fill("123456");
  await odometer.press("Enter");
  await expect(page.getByText("Saved").first()).toBeVisible();

  await page.getByRole("button", { name: "Mark as checked" }).click();
  await expect(page.getByTestId("review-status")).toHaveText("Checked");
});
