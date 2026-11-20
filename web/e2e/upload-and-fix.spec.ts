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
  await expect(page.getByRole("heading", { name: "Audit overview" })).toBeVisible();
  await expect(page.getByTestId("step-bar")).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Invoices" }).click();
  await expect(page.getByRole("heading", { name: "Upload invoices" })).toBeVisible();
  await page.locator("#file-input").setInputFiles(files);

  // The file list is hidden once files are read; the "To check" tab count shows when all of them are in.
  await expect(page.getByRole("tab", { name: new RegExp(`To check\\s*${files.length}`) })).toBeVisible({ timeout: 60_000 });

  await page.getByRole("tab", { name: /To check/ }).click();
  await page.getByRole("link").filter({ hasText: /./ }).and(page.locator("tbody a")).first().click();

  const odometer = page.getByLabel("Odometer", { exact: true });
  await expect(odometer).toBeVisible();
  await expect(page.getByTestId("review-status")).toHaveText("Needs review");
  await odometer.fill("123456");
  await odometer.press("Enter");
  await expect(page.getByText("Saved").first()).toBeVisible();

  // Every other field still marked Check has to be confirmed one by one before the invoice can be marked checked.
  const looksRight = page.getByRole("button", { name: /looks right$/ });
  for (let i = 0; i < 60 && (await looksRight.count()) > 0; i++) {
    await looksRight.first().click();
    await page.waitForTimeout(300);
  }
  await page.getByRole("button", { name: "Mark as checked" }).click();
  await expect(page.getByTestId("review-status")).toHaveText("Checked");
  await expect(page.getByTestId("next-invoice")).toBeVisible();
});
