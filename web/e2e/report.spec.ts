import { expect, test } from "@playwright/test";
import { apiLogin, bulk, ensureFlags, uiLogin } from "./helpers";

test("create a report, download the PDF and open the public link", async ({ page, request, browser, context }) => {
  test.setTimeout(180_000);
  const cid = await apiLogin(request);
  const flags = await ensureFlags(request, cid);
  await bulk(request, cid, flags, "accept");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);

  await uiLogin(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Reports" }).click();
  await page.getByRole("button", { name: "Create report" }).first().click();
  await page.getByRole("button", { name: "Create report" }).last().click();
  const row = page.locator("tbody tr").first();
  await expect(row).toContainText(/Version \d+/);

  const pdfHref = await row.getByRole("link", { name: "Download PDF" }).getAttribute("href");
  const pdf = await request.get(pdfHref!);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");

  await row.getByRole("link", { name: "Open dashboard" }).click();
  await expect(page.getByTestId("recoverable").or(page.getByTestId("headline")).first()).toBeVisible();
  await page.goBack();

  await page.locator("tbody tr").first().getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByText("Link copied").first()).toBeVisible();
  const shared = await page.evaluate(() => navigator.clipboard.readText());
  const token = new URL(shared, "http://localhost:3000").pathname.split("/").pop()!;

  const fresh = await browser.newContext({ baseURL: "http://localhost:3000" });
  const pub = await fresh.newPage();
  await pub.goto(`/r/${token}`);
  await expect(pub.getByTestId("recoverable").or(pub.getByTestId("headline")).first()).toBeVisible();
  await expect(pub.getByRole("link", { name: "Download PDF" })).toBeVisible();
  await expect(pub.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await fresh.close();
});
