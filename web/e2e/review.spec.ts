import { expect, test } from "@playwright/test";
import { apiLogin, bulk, ensureFlags, uiLogin } from "./helpers";

test("review flags with keyboard shortcuts", async ({ page, request }) => {
  test.setTimeout(180_000);
  const cid = await apiLogin(request);
  const flags = await ensureFlags(request, cid);
  expect(flags.length).toBeGreaterThan(2);
  await bulk(request, cid, flags, "reopen");

  await uiLogin(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Review" }).click();
  await expect(page.getByRole("heading", { name: "Flags to review" }).or(page.getByRole("link", { name: "Flags to review" }))).toBeVisible();
  await expect(page.getByTestId("hero")).not.toHaveText("$0.00");

  await page.locator("tbody tr").first().getByRole("link", { name: "Review" }).click();
  await expect(page).toHaveURL(/\/review\/[0-9a-f-]+$/);
  await expect(page.getByTestId("key-hint")).toContainText("A accept");
  await expect(page.getByTestId("position")).toContainText(/1 of \d+ open flags/);
  const first = page.url();

  // J moves to the next flag, K moves back.
  await page.keyboard.press("j");
  await expect(page.getByTestId("position")).toContainText(/^2 of/);
  await page.keyboard.press("k");
  await expect(page).toHaveURL(first);

  // A accepts and moves on to the next open flag.
  await expect(page.getByTestId("position")).toContainText(/^1 of/);
  await expect(page.getByRole("button", { name: /Accept flag/ })).toBeVisible();
  await page.keyboard.press("a");
  await expect(page).not.toHaveURL(first);
  const acceptedId = first.split("/").pop()!;
  const accepted = await (await request.get(`/api/clients/${cid}/flags/${acceptedId}`)).json();
  expect(accepted.status).toBe("accepted");

  // D opens the dismiss panel; pick a reason and confirm.
  await expect(page.getByTestId("position")).toContainText(/^1 of/);
  const second = page.url();
  await page.keyboard.press("d");
  await page.getByLabel("Shop had a valid reason").check();
  await page.getByRole("button", { name: "Dismiss flag" }).last().click();
  await expect(page).not.toHaveURL(second);
  const dismissed = await (await request.get(`/api/clients/${cid}/flags/${second.split("/").pop()}`)).json();
  expect(dismissed.status).toBe("dismissed");

  // Reviewed flags show their status words.
  await page.goto(`/review/${acceptedId}`);
  await expect(page.getByTestId("flag-status")).toContainText("Accepted");
  await page.goto(second);
  await expect(page.getByTestId("flag-status")).toContainText("Dismissed");
  await expect(page.getByTestId("key-hint")).toBeVisible();
});
