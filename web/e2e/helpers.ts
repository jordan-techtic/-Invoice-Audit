import { expect, type APIRequestContext, type Page } from "@playwright/test";

export async function apiLogin(request: APIRequestContext) {
  const res = await request.post("/api/auth/login", { data: { email: "admin@audit-demo.com", password: "admin-password-123" } });
  expect(res.ok()).toBeTruthy();
  const clients = await (await request.get("/api/clients")).json();
  const cid: string = clients.find((c: { name: string }) => c.name === "Lone Prairie Freight").id;
  return cid;
}

/** Makes sure checks have run, then returns every flag for the client. */
export async function ensureFlags(request: APIRequestContext, cid: string) {
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
