import { expect, test } from "@playwright/test";
import { apiLogin, bulk, ensureFlags } from "./helpers";

// Uses the real API; the demo client already has invoices with flaggable repairs.
test("run checks shows the hero figure and flag rows", async ({ page, request }) => {
  test.setTimeout(180_000);
  const cid = await apiLogin(request);
  await bulk(request, cid, await ensureFlags(request, cid), "reopen");
  await page.goto("/clients");
  await page.getByRole("button", { name: "Work on Lone Prairie Freight" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Review" }).click();
  await page.getByRole("link", { name: "Flags to review" }).click();

  await page.getByRole("button", { name: "Run checks" }).click();
  await expect(page.getByRole("button", { name: "Running checks…" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Run checks" })).toBeEnabled({ timeout: 60_000 });
  await expect(page.getByText(/Checks finished/)).toBeVisible();

  const hero = await page.getByTestId("hero").innerText();
  expect(Number(hero.replace(/[$,]/g, ""))).toBeGreaterThan(0);
  expect(await page.locator("tbody tr").count()).toBeGreaterThan(0);
});
