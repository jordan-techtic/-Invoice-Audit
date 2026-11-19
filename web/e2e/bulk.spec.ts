import { expect, test } from "@playwright/test";
import { makePng } from "./png";

// Uses its own new client, so it never touches other data. Needs the demo provider (AI_PROVIDER=fake FAKE_PROVIDER_DEMO=true).
test("select many invoices, mark them checked, then delete them", async ({ page }) => {
  const api = page.request;
  expect((await api.post("/api/auth/login", { data: { email: "admin@audit-demo.com", password: "admin-password-123" } })).ok()).toBeTruthy();
  const client = await (await api.post("/api/clients", { data: { name: `E2E bulk ${Date.now()}` } })).json();
  try {
  for (let i = 0; i < 5; i++) {
    const r = await api.post(`/api/clients/${client.id}/uploads`, { multipart: { files: { name: `bulk-${i}.png`, mimeType: "image/png", buffer: makePng(Date.now() + i * 104729) } } });
    expect(r.ok()).toBeTruthy();
  }
  await expect.poll(async () => (await (await api.get(`/api/clients/${client.id}/invoices`)).json()).length, {
    timeout: 60_000, message: "5 invoices should appear. This test needs the offline demo provider: run the stack with AI_PROVIDER=fake FAKE_PROVIDER_DEMO=true.",
  }).toBe(5);

  await page.addInitScript(([k, v]) => localStorage.setItem(k, v), ["ia.client", client.id]);
  await page.goto("/invoices");
  await page.getByRole("tab", { name: /^To check/ }).click();
  await expect(page.getByRole("row")).toHaveCount(5 + 2);                       // header + 5 rows + footer
  await expect(page.getByRole("region", { name: "Selected invoices" })).toHaveCount(0);

  // one row, then the selection is cleared when the tab changes
  await page.getByRole("checkbox", { name: /^Select invoice/ }).first().check();
  await expect(page.getByText("1 selected")).toBeVisible();
  await page.getByRole("tab", { name: /^All/ }).click();
  await expect(page.getByRole("region", { name: "Selected invoices" })).toHaveCount(0);
  await page.getByRole("tab", { name: /^To check/ }).click();

  // select all, then deselect one: the header box shows a partial state
  const all = page.getByRole("checkbox", { name: /^Select all 5 invoices/ });
  await all.check();
  await expect(page.getByText("5 selected")).toBeVisible();
  await page.getByRole("checkbox", { name: /^Select invoice/ }).first().uncheck();
  await expect(page.getByText("4 selected")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Select all|Clear selection of all/ })).toHaveJSProperty("indeterminate", true);

  await page.screenshot({ path: "screenshots/bulk-selected.png" });

  // mark the 4 as checked (needs a confirmation)
  await page.getByRole("button", { name: "Mark 4 as checked" }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toContainText("Mark 4 invoices as checked?");
  await page.screenshot({ path: "screenshots/bulk-confirm.png" });
  await dlg.getByRole("button", { name: "Mark 4 as checked" }).click();
  await expect(page.getByRole("status").filter({ hasText: "4 invoices marked as checked." })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^To check/ })).toContainText("1");
  await expect(page.getByRole("tab", { name: /^Checked/ })).toContainText("4");
  await expect(page.getByRole("region", { name: "Selected invoices" })).toHaveCount(0);

  // delete everything from the All tab: the dialog needs DELETE typed
  await page.getByRole("tab", { name: /^All/ }).click();
  await page.getByRole("checkbox", { name: /^Select all 5 invoices/ }).check();
  await page.getByRole("button", { name: "Delete 5" }).click();
  const del = page.getByRole("dialog");
  await expect(del).toContainText("Delete 5 invoices?");
  const confirm = del.getByRole("button", { name: "Delete 5" });
  await expect(confirm).toBeDisabled();
  await del.getByLabel(/Type DELETE/).fill("DELETE");
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByRole("status").filter({ hasText: "5 invoices deleted." })).toBeVisible();
  await expect(page.getByText(/No invoices yet/)).toBeVisible();
  expect((await (await api.get(`/api/clients/${client.id}/invoices`)).json()).length).toBe(0);
  await page.screenshot({ path: "screenshots/bulk-after-delete.png" });
  } finally {
    // leave no test client behind, even when a step above failed
    await api.post(`/api/clients/${client.id}/delete-everything`, { data: { confirm: client.name } });
  }
});
