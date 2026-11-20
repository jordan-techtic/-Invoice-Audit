"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, dateTime, money, shortDate, type InvoiceSummary, type ReviewStatus } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useProgress } from "@/lib/progress";
import ConfirmDialog from "@/components/ConfirmDialog";
import NeedClient from "@/components/NeedClient";
import UploadPanel from "@/components/UploadPanel";
import StatusMark from "@/components/StatusMark";
import { IconArrow } from "@/components/Icons";

type Filter = "" | ReviewStatus;
type SortKey = "created_at" | "shop" | "invoice_number" | "invoice_date" | "unit_number" | "total" | "fields_to_check";

const TABS: { id: Filter; label: string }[] = [
  { id: "needs_review", label: "To check" },
  { id: "ready", label: "Ready" },
  { id: "reviewed", label: "Checked" },
  { id: "", label: "All" },
];

const PAGE_SIZE = 10;

export default function InvoicesPage() {
  return <NeedClient>{(c) => <List key={c.id} cid={c.id} />}</NeedClient>;
}

function List({ cid }: { cid: string }) {
  const [filter, setFilter] = useState<Filter>(() => {
    const s = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("status");
    return s === "needs_review" || s === "ready" || s === "reviewed" ? s : "";
  });
  const [all, setAll] = useState<InvoiceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  // Default: newest created first (what the server sends). A column header overrides it.
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "created_at", dir: -1 });
  const { user } = useSession();
  const progress = useProgress();
  const isAdmin = user.role === "admin";
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<null | "check" | "delete">(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [checksDone, setChecksDone] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    api.invoices(cid)
      .then((r) => { if (live) { setAll(r); setError(null); setPage(1); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Couldn't load invoices. Refresh the page."); });
    return () => { live = false; };
  }, [cid, reloadKey]);

  // A selection only ever covers what is on screen: changing the tab or the search clears it.
  function changeFilter(f: Filter) { setFilter(f); setSelected(new Set()); setPage(1); }
  function changeSearch(v: string) { setQ(v); setSelected(new Set()); setPage(1); }
  function goTo(n: number) { setPage(n); setSelected(new Set()); }

  const counts = useMemo(() => {
    const c: Record<string, number> = { "": all?.length ?? 0, needs_review: 0, ready: 0, reviewed: 0 };
    (all ?? []).forEach((r) => { c[r.review_status] = (c[r.review_status] ?? 0) + 1; });
    return c;
  }, [all]);

  const rows = useMemo(() => {
    if (!all) return null;
    const needle = q.trim().toLowerCase();
    const list = all.filter((r) => (!filter || r.review_status === filter) &&
      (!needle || [r.shop, r.invoice_number, r.unit_number].some((v) => v?.toLowerCase().includes(needle))));
    const val = (r: InvoiceSummary) => {
      const v = r[sort.key];
      if (sort.key === "created_at") return Date.parse(String(v ?? "")) || 0;
      return sort.key === "total" ? Number(v ?? 0) : sort.key === "fields_to_check" ? Number(v ?? 0) : String(v ?? "").toLowerCase();
    };
    return [...list].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sort.dir);
  }, [all, filter, q, sort]);

  const pages = Math.max(1, Math.ceil((rows?.length ?? 0) / PAGE_SIZE));
  const current = Math.min(page, pages);
  const pageRows = (rows ?? []).slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const total = (rows ?? []).reduce((s, r) => s + (Number(r.total) || 0), 0);
  const chosen = (rows ?? []).filter((r) => selected.has(r.id));
  const eligibleToCheck = chosen.filter((r) => r.review_status !== "reviewed").length;
  const allOn = pageRows.length > 0 && pageRows.every((r) => selected.has(r.id));
  useEffect(() => { if (selectAllRef.current) selectAllRef.current.indeterminate = chosen.length > 0 && !allOn; }, [chosen.length, allOn]);

  function toggle(id: string) {
    setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  function toggleAll() { setSelected(allOn ? new Set() : new Set(pageRows.map((r) => r.id))); }
  const plural = (n: number) => `${n} ${n === 1 ? "invoice" : "invoices"}`;
  async function doCheck() {
    const r = await api.bulkCheck(cid, chosen.map((x) => x.id));
    setDialog(null); setSelected(new Set()); setReloadKey((k) => k + 1); void progress?.refresh();
    const blockedNote = r.blocked?.length ? ` ${plural(r.blocked.length)} not marked: ${r.blocked.length === 1 ? "it still has" : "they still have"} fields marked Check. Open ${r.blocked.length === 1 ? "it" : "each"} and fix or confirm each field, or confirm the numbers as printed.` : "";
    const done = `${plural(r.checked)} marked as checked.${r.already_checked ? ` ${plural(r.already_checked)} ${r.already_checked === 1 ? "was" : "were"} already checked.` : ""}${blockedNote}`;
    setNotice(done);
    setChecksDone(false);
    // When nothing is left to check, the audit checks start on their own.
    const left = await api.invoices(cid, "needs_review").catch(() => null);
    if (left && left.length === 0 && progress) {
      setNotice(`${done} Running the audit checks…`);
      progress.runChecks().then(
        (flags) => { setNotice(`${done} Checks finished. ${flags} ${flags === 1 ? "flag" : "flags"} found.`); setChecksDone(true); },
        (e) => setNotice(`${done} ${e instanceof Error ? e.message : "The checks didn't finish. Run them again from step 2."}`),
      );
    }
  }
  async function doDelete() {
    const r = await api.bulkDelete(cid, chosen.map((x) => x.id));
    setDialog(null); setSelected(new Set()); setReloadKey((k) => k + 1); void progress?.refresh();
    setNotice(`${plural(r.deleted)} deleted.`);
  }
  const nextToCheck = all?.find((r) => r.review_status === "needs_review");
  const reloadInvoices = useCallback(() => setReloadKey((k) => k + 1), []);

  function head(key: SortKey, label: string, right = false) {
    const on = sort.key === key;
    return (
      <th scope="col" className={`th ${right ? "text-right" : ""}`} aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
        <button className="min-h-[40px] font-medium hover:text-ink" onClick={() => { setPage(1); setSort({ key, dir: on ? (sort.dir === 1 ? -1 : 1) : key === "total" || key === "fields_to_check" || key === "created_at" ? -1 : 1 }); }}>
          {label} {on ? (sort.dir === 1 ? "↑" : "↓") : ""}
        </button>
      </th>
    );
  }

  return (
    <div>
      <UploadPanel cid={cid} onChange={reloadInvoices} header={<>
        <p className="eyebrow">Step 1 of 3</p>
        <h1 className="mt-1 text-xl">Upload and check invoices</h1>
        <p className="mt-1 text-muted">Add every repair invoice for this client. The AI reads each page. Then check the ones it was unsure about.</p>
      </>} />

      <div className="mt-10 flex flex-wrap items-end justify-between gap-4 border-t border-line pt-8">
        <div>
          <h2 id="check-heading" className="scroll-mt-6 text-lg">Check invoices</h2>
          <p className="mt-1 max-w-prose text-muted">Open each invoice marked <b>Needs review</b>, compare the highlighted fields with the page image, fix them, then mark it checked.</p>
        </div>
        {nextToCheck && <Link href={`/invoices/${nextToCheck.id}`} className="btn-primary btn-lg">Check next invoice<IconArrow /></Link>}
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Filter by status">
          {TABS.map((t) => (
            <button key={t.id || "all"} role="tab" aria-selected={filter === t.id} onClick={() => changeFilter(t.id)}
              className={`chip ${filter === t.id ? "border-primary bg-primary text-white" : "border-line-strong bg-surface text-ink hover:bg-sunken"}`}>
              {t.label} <span className={`num rounded-full px-2 text-xs ${filter === t.id ? "bg-white/20" : "bg-sunken"}`}>{counts[t.id] ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="w-full sm:w-[300px]">
          <label htmlFor="inv-search" className="sr-only">Search invoices</label>
          <input id="inv-search" type="search" className="field" placeholder="Search shop, invoice or unit" value={q} onChange={(e) => changeSearch(e.target.value)} />
        </div>
      </div>

      {notice && (
        <p role="status" className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 font-medium text-confirmed">
          {progress?.running && <span aria-hidden className="h-5 w-5 shrink-0 animate-spin rounded-full border-[3px] border-sunken border-t-primary" />}
          <span>{notice}</span>
          {checksDone && <Link href="/review" className="btn-link">Review flags</Link>}
        </p>
      )}
      {chosen.length > 0 && (
        <div role="region" aria-label="Selected invoices" className="sticky top-0 z-10 mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-line-strong bg-surface px-4 py-3 shadow-sm">
          <span className="font-bold"><span className="num">{chosen.length}</span> selected</span>
          <button className="btn-primary btn-sm" disabled={eligibleToCheck === 0} onClick={() => setDialog("check")}>
            Mark {eligibleToCheck === chosen.length ? chosen.length : eligibleToCheck} as checked
          </button>
          {isAdmin && <button className="btn-danger btn-sm" onClick={() => setDialog("delete")}>Delete {chosen.length}</button>}
          <button className="btn-link ml-auto" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}
      {error && <p role="alert" className="mt-6 text-danger">{error}</p>}
      {!all && !error && <p className="mt-6 text-muted" role="status">Loading invoices…</p>}

      {rows && rows.length === 0 && (
        <p className="mt-8 max-w-prose text-lg">
          {all && all.length === 0
            ? "No invoices yet. Drop files in the box above to start the audit."
            : filter === "needs_review" && !q ? "Nothing left to check. Every invoice is checked or ready — go to step 2 and run the checks."
            : "No invoices match. Choose another tab or clear the search."}
        </p>
      )}

      {rows && rows.length > 0 && (
        <div className="mt-4 md:hidden">
          <label className="flex min-h-[44px] items-center gap-3 font-medium">
            <input type="checkbox" checked={allOn} onChange={toggleAll} className="h-5 w-5" style={{ accentColor: "var(--primary)" }}
              aria-label={allOn ? `Clear selection of the ${pageRows.length} invoices on this page` : `Select all ${pageRows.length} invoices on this page`} />
            Select all {pageRows.length} on this page
          </label>
          <ul className="mt-2 flex flex-col gap-3">
            {pageRows.map((r) => (
              <li key={r.id} className={`rounded-lg border border-line p-4 ${selected.has(r.id) ? "bg-sunken" : "bg-surface"}`}>
                <div className="flex items-start gap-3">
                  <label className="flex min-h-[40px] min-w-[40px] cursor-pointer items-center justify-center">
                    <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} className="h-5 w-5" style={{ accentColor: "var(--primary)" }}
                      aria-label={`Select invoice ${r.invoice_number || ""} from ${r.shop || "unknown shop"}`} />
                  </label>
                  <div className="min-w-0 flex-1">
                    <Link href={`/invoices/${r.id}`} className="block font-bold text-primary">{r.shop || "Shop not read"}</Link>
                    <p className="num text-sm text-muted">{[r.invoice_number, shortDate(r.invoice_date), r.unit_number].filter(Boolean).join(" · ")}</p>
                  </div>
                  <p className="num font-bold">{money(r.total)}</p>
                </div>
                <div className="mt-3 flex items-center justify-between gap-3">
                  <span className="flex items-center gap-3">
                    <StatusMark status={r.review_status} />
                    {r.fields_to_check ? <span className="text-sm font-bold text-money">{r.fields_to_check} to check</span> : null}
                  </span>
                  <Link href={`/invoices/${r.id}`} className={r.review_status === "needs_review" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}>
                    {r.review_status === "needs_review" ? "Check" : "View"}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 flex justify-between border-t-2 border-line-strong pt-3 font-bold">
            <span>{rows.length} {rows.length === 1 ? "invoice" : "invoices"}</span><span className="num">{money(total)}</span>
          </p>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="mt-4 hidden overflow-x-auto rounded-lg border border-line bg-surface md:block">
          <table className="w-full min-w-[900px] border-collapse">
            <caption className="sr-only">Invoices</caption>
            <thead>
              <tr>
                <th scope="col" className="th w-12">
                  <label className="flex min-h-[40px] min-w-[40px] cursor-pointer items-center justify-center">
                    <input ref={selectAllRef} type="checkbox" checked={allOn} onChange={toggleAll} className="h-5 w-5" style={{ accentColor: "var(--primary)" }}
                      aria-label={allOn ? `Clear selection of the ${pageRows.length} invoices on this page` : `Select all ${pageRows.length} invoices on this page`} />
                  </label>
                </th>
                {head("created_at", "Added")}
                {head("shop", "Shop")}
                {head("invoice_number", "Invoice number")}
                {head("invoice_date", "Date")}
                {head("unit_number", "Unit")}
                {head("total", "Total", true)}
                <th scope="col" className="th">Status</th>
                {head("fields_to_check", "Fields to check", true)}
                <th scope="col" className="th"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r) => (
                <tr key={r.id} className={`tr hover:bg-bg ${selected.has(r.id) ? "bg-sunken" : ""}`} aria-selected={selected.has(r.id)}>
                  <td className="td w-12">
                    <label className="flex min-h-[40px] min-w-[40px] cursor-pointer items-center justify-center">
                      <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} className="h-5 w-5" style={{ accentColor: "var(--primary)" }}
                        aria-label={`Select invoice ${r.invoice_number || ""} from ${r.shop || "unknown shop"}`} />
                    </label>
                  </td>
                  <td className="td whitespace-nowrap num text-muted">{dateTime(r.created_at)}</td>
                  <td className="td font-medium">
                    <Link href={`/invoices/${r.id}`} className="text-primary underline-offset-4 hover:underline">{r.shop || "Shop not read"}</Link>
                  </td>
                  <td className="td whitespace-nowrap num">{r.invoice_number}</td>
                  <td className="td whitespace-nowrap num">{shortDate(r.invoice_date)}</td>
                  <td className="td whitespace-nowrap num">{r.unit_number}</td>
                  <td className="td num text-right">{money(r.total)}</td>
                  <td className="td whitespace-nowrap"><StatusMark status={r.review_status} /></td>
                  <td className="td num text-right">{r.fields_to_check ? <span className="font-bold text-money">{r.fields_to_check}</span> : ""}</td>
                  <td className="td text-right">
                    <Link href={`/invoices/${r.id}`} className={r.review_status === "needs_review" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}>
                      {r.review_status === "needs_review" ? "Check" : "View"}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-line-strong">
                <td className="td font-bold" colSpan={6}>{rows.length} {rows.length === 1 ? "invoice" : "invoices"}</td>
                <td className="td num text-right font-bold">{money(total)}</td>
                <td className="td" colSpan={3} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {rows && rows.length > PAGE_SIZE && (
        <nav aria-label="Invoice pages" className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="num text-muted" role="status">
            Showing {(current - 1) * PAGE_SIZE + 1}–{Math.min(current * PAGE_SIZE, rows.length)} of {rows.length}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn-secondary btn-sm" disabled={current === 1} onClick={() => goTo(current - 1)}>Previous</button>
            {Array.from({ length: pages }, (_, i) => i + 1)
              .filter((n) => n === 1 || n === pages || Math.abs(n - current) <= 1)
              .map((n, i, arr) => (
                <span key={n} className="flex items-center gap-2">
                  {i > 0 && n - arr[i - 1] > 1 && <span aria-hidden="true" className="text-muted">…</span>}
                  <button type="button" onClick={() => goTo(n)} aria-label={`Page ${n}`} aria-current={n === current ? "page" : undefined}
                    className={n === current ? "btn-primary btn-sm" : "btn-secondary btn-sm"}>{n}</button>
                </span>
              ))}
            <button type="button" className="btn-secondary btn-sm" disabled={current === pages} onClick={() => goTo(current + 1)}>Next</button>
          </div>
        </nav>
      )}

      <ConfirmDialog open={dialog === "check"} title={`Mark ${plural(eligibleToCheck)} as checked?`}
        body="Invoices with no field marked Check are marked as checked. An invoice that still has a field marked Check is left as it is: open it and fix or confirm each field first."
        actionLabel={`Mark ${eligibleToCheck} as checked`} onConfirm={doCheck} onClose={() => setDialog(null)} />
      <ConfirmDialog open={dialog === "delete"} danger title={`Delete ${plural(chosen.length)}?`}
        body="This permanently deletes the selected invoices with their lines and any flags on them. The original uploaded files are kept. Reports that were already created do not change. This cannot be undone."
        confirmWord="DELETE" actionLabel={`Delete ${chosen.length}`} onConfirm={doDelete} onClose={() => setDialog(null)} />
    </div>
  );
}
