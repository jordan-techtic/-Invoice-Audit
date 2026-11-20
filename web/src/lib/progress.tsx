"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { api, type Flag, type FlagType, type InvoiceSummary, type ReportItem, type UploadRow } from "./api";

/** Where the active client's audit stands, and the one thing to do next. Computed from existing list endpoints. */

export type StepState = "done" | "current" | "todo";
export type StepKey = "check" | "review" | "report";
export interface Step { key: StepKey; n: number; label: string; short: string; href: string; state: StepState; detail: string }
export interface NextAction { step: "upload" | "check" | "run" | "review" | "report" | "finished"; title: string; text: string; href: string; cta: string }

export interface Progress {
  loading: boolean;
  error: string | null;
  files: number; filesBusy: number; filesFailed: number;
  invoices: number; needReview: number; ready: number; checked: number; spend: number;
  flags: number; flagsOpen: number; openTotal: number; confirmedTotal: number; dismissed: number;
  byType: { type: FlagType; count: number; open: number; amount: number }[];
  checksRun: boolean; checksStale: boolean;
  reports: number; latestReport: ReportItem | null;
  firstOpenFlag: string | null; firstInvoiceToCheck: string | null;
  steps: Step[];
  next: NextAction;
  refresh: () => Promise<void>;
  markChecksRun: () => void;
  /** Call when reference data (thresholds, warranty rules, vehicles) changed: the checks are then out of date and run again on the Review page. */
  markChecksStale: (forClient?: string) => void;
  /** True while the audit checks are running (started from any page). */
  running: boolean;
  /** Runs the audit checks and resolves with the number of flags found. A run already in progress is shared, never doubled. */
  runChecks: () => Promise<number>;
}

const RUN_KEY = (cid: string) => `ia.checksRun.${cid}`;
const RUN_POLL_LIMIT_MS = 10 * 60 * 1000;
const num = (v: number | string | null | undefined) => (v === null || v === undefined || v === "" ? 0 : Number(v) || 0);

function readRun(cid: string): string | null {
  try { return localStorage.getItem(RUN_KEY(cid)); } catch { return null; }
}

interface Raw { uploads: UploadRow[]; invoices: InvoiceSummary[]; flags: Flag[]; open: number; confirmed: number; reports: ReportItem[] }

export function compute(raw: Raw, lastRun: string | null) {
  const { uploads, invoices, flags, reports } = raw;
  const filesBusy = uploads.filter((u) => u.status === "queued" || u.status === "reading").length;
  const filesFailed = uploads.filter((u) => u.status === "failed").length;
  const needReview = invoices.filter((i) => i.review_status === "needs_review").length;
  const ready = invoices.filter((i) => i.review_status === "ready").length;
  const checked = invoices.filter((i) => i.review_status === "reviewed").length;
  const spend = invoices.reduce((s, i) => s + num(i.total), 0);
  const flagsOpen = flags.filter((f) => f.status === "open").length;
  const dismissed = flags.filter((f) => f.status === "dismissed").length;
  const types = new Map<FlagType, { type: FlagType; count: number; open: number; amount: number }>();
  for (const f of flags) {
    const t = types.get(f.type) ?? { type: f.type, count: 0, open: 0, amount: 0 };
    t.count += 1;
    if (f.status === "open") t.open += 1;
    if (f.status !== "dismissed") t.amount += num(f.impact);
    types.set(f.type, t);
  }
  // Compare real times, not strings: the server sends "+05:30"-style offsets while the last-run time is stored in UTC.
  const newestUpload = uploads.reduce((m, u) => Math.max(m, Date.parse(u.created_at) || 0), 0);
  const checksRun = flags.length > 0 || !!lastRun;
  const checksStale = !!lastRun && newestUpload > (Date.parse(lastRun) || 0);
  const latestReport = reports.reduce<ReportItem | null>((m, r) => (!m || r.version > m.version ? r : m), null);
  const firstOpenFlag = [...flags].filter((f) => f.status === "open").sort((a, b) => num(b.impact) - num(a.impact))[0]?.id ?? null;
  const firstInvoiceToCheck = invoices.find((i) => i.review_status === "needs_review")?.id ?? null;

  const uploadDone = invoices.length > 0 && filesBusy === 0;
  const checkDone = uploadDone && needReview === 0;
  const runDone = uploadDone && checksRun && !checksStale;
  const reviewDone = runDone && flagsOpen === 0;
  const reportDone = reviewDone && !!latestReport;

  const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  const raw3: Omit<Step, "state">[] = [
    { key: "check", short: "Upload & check", n: 1, label: "Upload and check invoices", href: "/invoices",
      detail: filesBusy ? `${plural(filesBusy, "file")} being read` : !invoices.length ? "No files yet" : needReview ? `${plural(needReview, "invoice")} to check` : checked === invoices.length ? `${plural(invoices.length, "invoice")}, all checked` : `${plural(invoices.length, "invoice")}, none need checking` },
    { key: "review", short: "Review flags", n: 2, label: "Review flags", href: "/review",
      detail: checksStale ? "New files since last run" : !checksRun ? "Checks not run yet" : flagsOpen ? `${plural(flagsOpen, "flag")} open` : `${plural(flags.length, "flag")}, all reviewed` },
    { key: "report", short: "Report", n: 3, label: "Create report", href: "/reports",
      detail: latestReport ? `Version ${latestReport.version} created` : "No report yet" },
  ];
  const done = [checkDone, reviewDone, reportDone];
  const firstOpen = done.findIndex((d) => !d);
  const steps: Step[] = raw3.map((s, i) => ({ ...s, state: done[i] ? "done" : i === firstOpen ? "current" : "todo" }));

  let next: NextAction;
  if (!invoices.length && !filesBusy) {
    next = { step: "upload", title: "Upload this client's invoices", text: "Drop PDFs, scans or phone photos. The AI reads them for you.", href: "/invoices", cta: "Upload invoices" };
  } else if (filesBusy) {
    next = { step: "upload", title: "Invoices are being read", text: `${plural(filesBusy, "file")} still being read. You can start checking the ones that are ready.`, href: "/invoices", cta: "See progress" };
  } else if (needReview) {
    next = { step: "check", title: `Check ${plural(needReview, "invoice")}`, text: "The AI was unsure of some values. Compare them with the page image and fix them.", href: firstInvoiceToCheck ? `/invoices/${firstInvoiceToCheck}` : "/invoices?status=needs_review", cta: "Check next invoice" };
  } else if (!checksRun || checksStale) {
    next = { step: "run", title: checksStale ? "Run checks again" : "Run the audit checks", text: checksStale ? "New invoices arrived since the last run. The checks update on their own when you open step 2." : "Open step 2 and the checks run on their own. Six rules look for overbilling, repeats, warranty claims, duplicates and maths errors.", href: "/review", cta: "Go to step 2" };
  } else if (flagsOpen) {
    next = { step: "review", title: `Review ${plural(flagsOpen, "flag")}`, text: "Accept the real problems and dismiss the rest. Biggest amounts come first.", href: firstOpenFlag ? `/review/${firstOpenFlag}` : "/review", cta: "Review next flag" };
  } else if (!latestReport) {
    next = { step: "report", title: "Create the client report", text: "Every flag is reviewed. Turn the accepted findings into a report and share link.", href: "/reports", cta: "Create report" };
  } else {
    next = { step: "finished", title: "Audit complete", text: "The report is ready. Share the link or download the PDF.", href: `/reports/${latestReport.id}`, cta: "Open report" };
  }

  return {
    files: uploads.length, filesBusy, filesFailed, invoices: invoices.length, needReview, ready, checked, spend,
    flags: flags.length, flagsOpen, openTotal: raw.open, confirmedTotal: raw.confirmed, dismissed,
    byType: [...types.values()].sort((a, b) => b.amount - a.amount),
    checksRun, checksStale, reports: reports.length, latestReport, firstOpenFlag, firstInvoiceToCheck, steps, next,
  };
}

async function fetchRaw(cid: string): Promise<Raw> {
  const [uploads, invoices, fl, reports] = await Promise.all([api.uploads(cid), api.invoices(cid), api.flags(cid, {}), api.reports(cid)]);
  return { uploads, invoices, flags: fl.flags, open: fl.open_total, confirmed: fl.confirmed_total, reports };
}

const Ctx = createContext<Progress | null>(null);

export function useProgress(): Progress | null {
  return useContext(Ctx);
}

export function ProgressProvider({ cid, children }: { cid: string | null; children: React.ReactNode }) {
  const path = usePathname();
  const [raw, setRaw] = useState<Raw | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<string | null>(null);

  const apply = useCallback((r: Raw) => { setRaw(r); setLastRun(cid ? readRun(cid) : null); setError(null); }, [cid]);
  const fail = useCallback((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the audit progress."), []);

  const refresh = useCallback(async () => {
    if (!cid) return;
    try { apply(await fetchRaw(cid)); } catch (e) { fail(e); }
  }, [cid, apply, fail]);

  // Reload on every page change so the step bar always matches what the user just did.
  useEffect(() => {
    if (!cid) return;
    let live = true;
    fetchRaw(cid).then((r) => { if (live) apply(r); }, (e) => { if (live) fail(e); });
    return () => { live = false; };
  }, [cid, path, apply, fail]);
  // While files are being read, keep the step bar current.
  const busy = !!raw?.uploads.some((u) => u.status === "queued" || u.status === "reading");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  const markChecksRun = useCallback(() => {
    if (!cid) return;
    const now = new Date().toISOString();
    try { localStorage.setItem(RUN_KEY(cid), now); } catch { /* ignore */ }
    setLastRun(now);
  }, [cid]);

  const markChecksStale = useCallback((forClient?: string) => {
    const target = forClient ?? cid;  // the Settings page can belong to a client other than the one being worked on
    if (!target) return;
    const long_ago = new Date(0).toISOString();
    try { localStorage.setItem(RUN_KEY(target), long_ago); } catch { /* ignore */ }
    if (target === cid) setLastRun(long_ago);
  }, [cid]);

  const [running, setRunning] = useState(false);
  const runRef = useRef<Promise<number> | null>(null);
  const runChecks = useCallback((): Promise<number> => {
    if (runRef.current) return runRef.current;
    if (!cid) return Promise.reject(new Error("Choose a client first."));
    setRunning(true);
    const p = (async () => {
      const { job_id } = await api.runFlags(cid);
      const started = Date.now();
      for (;;) {
        await new Promise((res) => setTimeout(res, 2000));
        // A run that never reports back must not leave the page waiting for ever (the server treats a run stuck for 15 minutes as dead).
        if (Date.now() - started > RUN_POLL_LIMIT_MS) throw new Error("The checks are taking longer than expected. They may still finish: look at the Review page in a few minutes, or run them again.");
        const r = await api.flagRun(cid, job_id);
        if (r.status === "done") { markChecksRun(); await refresh(); return r.summary?.flags ?? 0; }
        if (r.status === "failed") throw new Error(r.error || "The checks didn't finish. Run them again in a moment.");
      }
    })().finally(() => { runRef.current = null; setRunning(false); });
    runRef.current = p;
    return p;
  }, [cid, markChecksRun, refresh]);

  const value = useMemo<Progress | null>(() => {
    if (!cid) return null;
    const empty: Raw = { uploads: [], invoices: [], flags: [], open: 0, confirmed: 0, reports: [] };
    return { loading: raw === null, error, ...compute(raw ?? empty, lastRun), refresh, markChecksRun, markChecksStale, running, runChecks };
  }, [cid, raw, error, lastRun, refresh, markChecksRun, markChecksStale, running, runChecks]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
