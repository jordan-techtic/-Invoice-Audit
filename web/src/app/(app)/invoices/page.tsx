"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, money, shortDate, type InvoiceSummary, type ReviewStatus } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import ReviewTabs from "@/components/ReviewTabs";
import StatusMark from "@/components/StatusMark";
import { IconArrow } from "@/components/Icons";

type Filter = "" | ReviewStatus;
type SortKey = "shop" | "invoice_number" | "invoice_date" | "unit_number" | "total" | "fields_to_check";

const TABS: { id: Filter; label: string }[] = [
  { id: "needs_review", label: "To check" },
  { id: "ready", label: "Ready" },
  { id: "reviewed", label: "Checked" },
  { id: "", label: "All" },
];

export default function InvoicesPage() {
  return <NeedClient>{(c) => <List cid={c.id} />}</NeedClient>;
}

function List({ cid }: { cid: string }) {
  const [filter, setFilter] = useState<Filter>(() => {
    const s = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("status");
    return s === "needs_review" || s === "ready" || s === "reviewed" ? s : "";
  });
  const [all, setAll] = useState<InvoiceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "invoice_date", dir: -1 });

  useEffect(() => {
    let live = true;
    api.invoices(cid)
      .then((r) => { if (live) { setAll(r); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Couldn't load invoices. Refresh the page."); });
    return () => { live = false; };
  }, [cid]);

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
      return sort.key === "total" ? Number(v ?? 0) : sort.key === "fields_to_check" ? Number(v ?? 0) : String(v ?? "").toLowerCase();
    };
    return [...list].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sort.dir);
  }, [all, filter, q, sort]);

  const total = (rows ?? []).reduce((s, r) => s + (Number(r.total) || 0), 0);
  const nextToCheck = all?.find((r) => r.review_status === "needs_review");

  function head(key: SortKey, label: string, right = false) {
    const on = sort.key === key;
    return (
      <th scope="col" className={`th ${right ? "text-right" : ""}`} aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
        <button className="min-h-[40px] font-medium hover:text-ink" onClick={() => setSort({ key, dir: on ? (sort.dir === 1 ? -1 : 1) : key === "total" || key === "fields_to_check" ? -1 : 1 })}>
          {label} {on ? (sort.dir === 1 ? "↑" : "↓") : ""}
        </button>
      </th>
    );
  }

  return (
    <div>
      <ReviewTabs current="invoices" />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl">Step 2 · Check invoices</h1>
          <p className="mt-1 max-w-prose text-muted">Open each invoice marked <b>Needs review</b>, compare the highlighted fields with the page image, fix them, then mark it checked.</p>
        </div>
        {nextToCheck && <Link href={`/invoices/${nextToCheck.id}`} className="btn-primary btn-lg">Check next invoice<IconArrow /></Link>}
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Filter by status">
          {TABS.map((t) => (
            <button key={t.id || "all"} role="tab" aria-selected={filter === t.id} onClick={() => setFilter(t.id)}
              className={`chip ${filter === t.id ? "border-primary bg-primary text-white" : "border-line-strong bg-surface text-ink hover:bg-sunken"}`}>
              {t.label} <span className={`num rounded-full px-2 text-xs ${filter === t.id ? "bg-white/20" : "bg-sunken"}`}>{counts[t.id] ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="w-full sm:w-[300px]">
          <label htmlFor="inv-search" className="sr-only">Search invoices</label>
          <input id="inv-search" type="search" className="field" placeholder="Search shop, invoice or unit" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      {error && <p role="alert" className="mt-6 text-danger">{error}</p>}
      {!all && !error && <p className="mt-6 text-muted" role="status">Loading invoices…</p>}

      {rows && rows.length === 0 && (
        <p className="mt-8 max-w-prose text-lg">
          {all && all.length === 0
            ? <>No invoices yet. <Link href="/upload" className="btn-link">Upload invoices</Link> to start the audit.</>
            : filter === "needs_review" && !q ? "Nothing left to check. Every invoice is checked or ready — go to step 3 and run the checks."
            : "No invoices match. Choose another tab or clear the search."}
        </p>
      )}

      {rows && rows.length > 0 && (
        <div className="mt-4 overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[900px] border-collapse">
            <caption className="sr-only">Invoices</caption>
            <thead>
              <tr>
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
              {rows.map((r) => (
                <tr key={r.id} className="tr hover:bg-bg">
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
                <td className="td font-bold" colSpan={4}>{rows.length} {rows.length === 1 ? "invoice" : "invoices"}</td>
                <td className="td num text-right font-bold">{money(total)}</td>
                <td className="td" colSpan={3} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
