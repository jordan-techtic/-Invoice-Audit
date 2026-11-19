import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { makePng } from "./png";

export async function apiLogin(request: APIRequestContext) {
  const res = await request.post("/api/auth/login", { data: { email: "admin@audit-demo.com", password: "admin-password-123" } });
  expect(res.ok()).toBeTruthy();
  const clients = await (await request.get("/api/clients")).json();
  const cid: string = clients.find((c: { name: string }) => c.name === "Lone Prairie Freight").id;
  return cid;
}

/** The demo provider turns every uploaded image into one invoice (same shop, unit, date and total), so a few uploads
 *  give the duplicate rule something to find. Only uploads when the client has no invoices, so specs work on a fresh database. */
async function ensureInvoices(request: APIRequestContext, cid: string) {
  const have = await (await request.get(`/api/clients/${cid}/invoices`)).json();
  if (have.length >= 4) return;
  for (let i = 0; i < 4; i++) {
    const res = await request.post(`/api/clients/${cid}/uploads`, {
      multipart: { files: { name: `seed-${Date.now()}-${i}.png`, mimeType: "image/png", buffer: makePng(Date.now() + i * 7919) } },
    });
    expect(res.ok()).toBeTruthy();
  }
  for (let i = 0; i < 40; i++) {
    const ups = await (await request.get(`/api/clients/${cid}/uploads`)).json();
    if (!ups.some((u: { status: string }) => u.status === "queued" || u.status === "reading")) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/** Makes sure checks have run, then returns every flag for the client. */
export async function ensureFlags(request: APIRequestContext, cid: string) {
  await ensureInvoices(request, cid);
  const run = await (await request.post(`/api/clients/${cid}/run-flags`)).json();
  for (let i = 0; i < 40; i++) {
    const r = await (await request.get(`/api/clients/${cid}/flag-runs/${run.job_id}`)).json();
    if (r.status === "done" || r.status === "failed") break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  const all = await (await request.get(`/api/clients/${cid}/flags?status=`)).json();
  return all.flags as { id: string; status: string }[];
}

export async function uiLogin(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@audit-demo.com");
  await page.getByLabel("Password").fill("admin-password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Work on Lone Prairie Freight" }).click();
  await expect(page.getByTestId("active-client")).toHaveText("Lone Prairie Freight");
}

/** Applies accept or reopen to every flag whose status matches, 8 requests at a time. */
export async function bulk(request: APIRequestContext, cid: string, flags: { id: string; status: string }[], action: "accept" | "reopen") {
  const todo = flags.filter((f) => (action === "accept" ? f.status === "open" : f.status !== "open"));
  for (let i = 0; i < todo.length; i += 8) {
    await Promise.all(todo.slice(i, i + 8).map((f) => request.post(`/api/clients/${cid}/flags/${f.id}/${action}`, { data: {} })));
  }
}
