import { expect, test, type APIRequestContext } from "@playwright/test";
import { apiLogin, bulk, ensureFlags, uiLogin } from "./helpers";
import { makePng } from "./png";

/**
 * Browser checks for artifact items UI1, UI2 and UI3. Each test names the cause it pins.
 * They need the app running with the demo provider (FAKE_PROVIDER_DEMO=true): every uploaded image becomes one invoice that needs review.
 */

type Inv = { id: string; invoice_number: string | null; review_status: string };
const invoices = async (r: APIRequestContext, cid: string): Promise<Inv[]> => (await r.get(`/api/clients/${cid}/invoices`)).json();

/** Uploads n fresh invoices and returns them (they all start as "needs review"). */
async function uploadNew(request: APIRequestContext, cid: string, n: number): Promise<Inv[]> {
  const before = new Set((await invoices(request, cid)).map((i) => i.id));
  for (let i = 0; i < n; i++) {
    const res = await request.post(`/api/clients/${cid}/uploads`, {
      multipart: { files: { name: `ui-${Date.now()}-${i}.png`, mimeType: "image/png", buffer: makePng(Date.now() + i * 7919 + Math.floor(Math.random() * 1e6)) } },
    });
    expect(res.ok()).toBeTruthy();
  }
  for (let i = 0; i < 40; i++) {
    const ups = await (await request.get(`/api/clients/${cid}/uploads`)).json();
    if (!ups.some((u: { status: string }) => u.status === "queued" || u.status === "reading")) break;
    await new Promise((r) => setTimeout(r, 500));
  }
  return (await invoices(request, cid)).filter((i) => !before.has(i.id));
}

const acceptedCount = async (r: APIRequestContext, cid: string) => (await (await r.get(`/api/clients/${cid}/flags?status=accepted`)).json()).count as number;

/** Every invoice checked and the checks run, so nothing blocks the report. */
async function readyForReport(request: APIRequestContext, cid: string) {
  const all = await invoices(request, cid);
  await request.post(`/api/clients/${cid}/invoices/bulk-check`, { data: { ids: all.map((i) => i.id) } });
  const run = await (await request.post(`/api/clients/${cid}/run-flags`)).json();
  for (let i = 0; i < 40; i++) {
    const r = await (await request.get(`/api/clients/${cid}/flag-runs/${run.job_id}`)).json();
    if (r.status === "done" || r.status === "failed") break;
    await new Promise((r) => setTimeout(r, 500));
  }
}

// ============================================================================================ UI1
test("UI1: moving from one invoice to the next never shows the previous invoice's data", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  const [a] = await uploadNew(request, cid, 2);
  const numberA = a.invoice_number!;
  await uiLogin(page);
  await page.goto(`/invoices/${a.id}`);
  await expect(page.getByLabel("Invoice number")).toHaveValue(numberA);

  await page.getByRole("button", { name: "Mark as checked" }).click();
  const next = page.getByRole("link", { name: /Check next invoice/ }).first();
  await expect(next).toBeVisible();
  const target = (await next.getAttribute("href"))!.split("/").pop()!;
  await page.route(`**/api/clients/*/invoices/${target}`, async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.continue(); });
  await next.click();                                                    // client-side move A -> B, while B is slow to load
  await expect(page).toHaveURL(new RegExp(`/invoices/${target}$`));
  await page.waitForTimeout(800);
  const shown = await page.locator("input").evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value));
  expect(shown, "the page still shows invoice A's data while B loads").not.toContain(numberA);
  const b = (await invoices(request, cid)).find((i) => i.id === target)!;
  await expect(page.getByLabel("Invoice number")).toHaveValue(b.invoice_number!);
});

// ============================================================================================ UI2
async function openFirstOpenFlag(page: import("@playwright/test").Page, request: APIRequestContext, cid: string) {
  const flags = await ensureFlags(request, cid);
  await bulk(request, cid, flags, "reopen");
  await readyForReport(request, cid);
  const open = (await (await request.get(`/api/clients/${cid}/flags?status=open`)).json()).flags as { id: string }[];
  expect(open.length).toBeGreaterThan(2);
  await uiLogin(page);
  await page.goto(`/review/${open[0].id}`);
  await expect(page.getByTestId("key-hint")).toBeVisible();
  return open;
}

test("UI2: holding A accepts at most one flag", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  await openFirstOpenFlag(page, request, cid);
  const before = await acceptedCount(request, cid);
  for (let i = 0; i < 8; i++) await page.keyboard.down("a");           // the browser sends repeats while a key is held
  await page.keyboard.up("a");
  await page.waitForTimeout(1500);
  expect((await acceptedCount(request, cid)) - before).toBe(1);
});

test("UI2: a key pressed while a button has focus does nothing", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  await openFirstOpenFlag(page, request, cid);
  const before = await acceptedCount(request, cid);
  await page.getByRole("button", { name: /Edit flag/ }).focus();
  await page.keyboard.press("a");
  await page.waitForTimeout(1200);
  expect(await acceptedCount(request, cid)).toBe(before);
});

test("UI2: a flag is not accepted by a key while the dismiss panel is open", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  await openFirstOpenFlag(page, request, cid);
  const before = await acceptedCount(request, cid);
  await page.keyboard.press("d");                                        // opens the dismiss panel
  await expect(page.getByRole("button", { name: /^Dismiss/ }).last()).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());   // focus on the page itself, as after clicking the panel's text
  await page.keyboard.press("a");
  await page.waitForTimeout(1200);
  expect(await acceptedCount(request, cid)).toBe(before);
});

// ============================================================================================ UI3
test("UI3: a failed lookup does not count as 'no invoices left' and does not start the checks early", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  const [a] = await uploadNew(request, cid, 1);
  let started = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/run-flags")) started++; });
  await page.route("**/api/clients/*/invoices?status=needs_review", (route) => route.abort());
  await uiLogin(page);
  await page.goto(`/invoices/${a.id}`);
  await expect(page.getByLabel("Invoice number")).toBeVisible();
  await page.getByRole("button", { name: "Mark as checked" }).click();
  await page.waitForTimeout(3500);
  expect(started).toBe(0);
});

test("UI3: the progress poll gives up instead of waiting forever", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  await ensureFlags(request, cid);
  await readyForReport(request, cid);                                   // Review only starts the checks by itself when no invoice is waiting for review
  await page.addInitScript((k) => localStorage.setItem(k, "1970-01-01T00:00:00.000Z"), `ia.checksRun.${cid}`);   // checks look stale, so Review starts them
  await page.route("**/api/clients/*/run-flags", (route) => route.fulfill({ status: 202, json: { job_id: "stuck", status: "queued" } }));
  let polls = 0;
  await page.route("**/api/clients/*/flag-runs/*", (route) => { polls++; return route.fulfill({ json: { id: "stuck", status: "running", summary: null, error: null, started_at: null, finished_at: null, cost_usd: 0 } }); });
  await page.clock.install();
  await uiLogin(page);
  await page.goto("/review");
  await expect.poll(() => polls, { timeout: 30_000 }).toBeGreaterThan(0);   // the poll loop is running (and still "running" forever)
  await page.clock.fastForward("12:00");
  await expect(page.getByText(/taking longer than expected/i).first()).toBeVisible();
});

test("UI3: deciding the last flag does not throw the person to the Reports page", async ({ page, request }) => {
  test.setTimeout(150_000);
  const cid = await apiLogin(request);
  const flags = await ensureFlags(request, cid);
  await bulk(request, cid, flags, "reopen");
  await readyForReport(request, cid);
  const open = (await (await request.get(`/api/clients/${cid}/flags?status=open`)).json()).flags as { id: string }[];
  for (const f of open.slice(1)) await request.post(`/api/clients/${cid}/flags/${f.id}/accept`, { data: {} });
  await page.addInitScript((k) => localStorage.setItem(k, new Date(Date.now() + 3600_000).toISOString()), `ia.checksRun.${cid}`);   // checks are fresh
  await uiLogin(page);
  await page.goto(`/review/${open[0].id}`);
  await expect(page.getByRole("button", { name: /Accept flag/ })).toBeVisible();
  await page.keyboard.press("a");
  await page.waitForTimeout(2500);
  expect(page.url(), "jumped to the report page without being asked").not.toContain("/reports");
});

test("UI3: step 1 does not say 'all checked' when invoices are only ready", async ({ page, request }) => {
  const cid = await apiLogin(request);
  await uiLogin(page);
  const fake = [1, 2, 3].map((n) => ({ id: `00000000-0000-0000-0000-00000000000${n}`, shop: "S", invoice_number: `R${n}`, invoice_date: null, unit_number: null, total: 10, review_status: "ready", fields_to_check: 0 }));
  await page.route(`**/api/clients/${cid}/invoices`, (route) => route.fulfill({ json: fake }));
  await page.goto("/invoices");
  await page.waitForTimeout(1500);
  expect(await page.locator("body").innerText()).not.toMatch(/all checked/i);
});

test("UI3: review state is kept per client in sessionStorage", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  await ensureFlags(request, cid);
  await uiLogin(page);
  await page.goto("/review");
  await page.waitForTimeout(1500);
  const keys = await page.evaluate(() => Object.keys(sessionStorage));
  expect(keys.filter((k) => k.startsWith("ia.review"))).not.toEqual([]);
  expect(keys.filter((k) => k.startsWith("ia.review") && !k.includes(cid)), "shared between clients").toEqual([]);
});

test("UI3: 'Mark audit complete' and deleting a warranty rule ask first", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cid = await apiLogin(request);
  const made = await request.post(`/api/clients/${cid}/warranty-rules`, { data: { vmrs_code: "045-001-009", component: "UI3 test rule", months: 12, miles: 1000, covers: "parts" } });
  const ruleId = made.ok() ? (await made.json()).id : null;
  const sent: string[] = [];
  page.on("request", (r) => { if (["POST", "DELETE", "PUT", "PATCH"].includes(r.method()) && /complete|warranty-rules/.test(r.url())) sent.push(`${r.method()} ${r.url()}`); });
  await uiLogin(page);
  await page.goto(`/clients/${cid}/settings`);
  await page.getByRole("button", { name: "Mark audit complete" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(sent.filter((s) => /complete/.test(s)), "completed without asking").toEqual([]);
  await page.keyboard.press("Escape");
  if (ruleId) {
    await page.getByRole("button", { name: "Delete rule for UI3 test rule" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(sent.filter((s) => s.startsWith("DELETE") && s.includes(ruleId)), "deleted without asking").toEqual([]);
    await page.keyboard.press("Escape");
    await request.delete(`/api/clients/${cid}/warranty-rules/${ruleId}`);
  }
});

test("UI3: the public report page and its API answers ask not to be indexed", async ({ request }) => {
  const html = await (await request.get("/r/not-a-real-token")).text();
  expect(html).toMatch(/<meta name="robots" content="noindex, nofollow"/);
  expect(html).toMatch(/<meta name="referrer" content="no-referrer"/);
  const api = await request.get("/api/public/reports/not-a-real-token");
  expect(api.headers()["x-robots-tag"]).toContain("noindex");
  expect(api.headers()["referrer-policy"]).toBe("no-referrer");
});
