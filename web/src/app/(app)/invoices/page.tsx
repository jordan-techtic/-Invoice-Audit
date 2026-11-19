"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, money, shortDate, type InvoiceSummary, type ReviewStatus } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import StatusMark from "@/components/StatusMark";

type Filter = "" | ReviewStatus;

export default function InvoicesPage() {
  return <NeedClient>{(c) => <List cid={c.id} />}</NeedClient>;
}

function List({ cid }: { cid: string }) {
  const [filter, setFilter] = useState<Filter>(() => {
    const s = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("status");
    return s === "needs_review" || s === "ready" || s === "reviewed" ? s : "";
  });
  const [rows, setRows] = useState<InvoiceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.invoices(cid, filter || undefined)
      .then((r) => { if (live) { setRows(r); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Couldn't load invoices. Refresh the page."); });
    return () => { live = false; };
  }, [cid, filter]);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl">Review invoices</h1>
          <p className="mt-1 text-muted">Open an invoice to compare it with the original page and fix anything that was misread.</p>
        </div>
        <div>
          <label htmlFor="status-filter" className="mb-1 block text-sm font-medium">Show</label>
          <select id="status-filter" className="field min-w-[200px]" value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            <option value="">All invoices</option>
            <option value="needs_review">Needs review</option>
            <option value="ready">Ready</option>
            <option value="reviewed">Checked</option>
          </select>
        </div>
      </div>

      {error && <p role="alert" className="mt-6 text-danger">{error}</p>}

      {rows && rows.length === 0 && (
        <p className="mt-8 max-w-prose text-lg">
          {filter ? "No invoices with this status. Choose All invoices to see the rest." : <>No invoices yet. <Link href="/upload" className="text-primary underline underline-offset-4">Upload invoices</Link> to start the audit.</>}
        </p>
      )}

      {rows && rows.length > 0 && (
        <div className="mt-6 overflow-x-auto bg-surface">
          <table className="w-full min-w-[820px] border-collapse">
            <caption className="sr-only">Invoices</caption>
            <thead>
              <tr>
                <th scope="col" className="th">Shop</th>
                <th scope="col" className="th">Invoice number</th>
                <th scope="col" className="th">Date</th>
                <th scope="col" className="th">Unit</th>
                <th scope="col" className="th text-right">Total</th>
                <th scope="col" className="th">Status</th>
                <th scope="col" className="th text-right">Fields to check</th>
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
                  <td className="td num text-right">{r.fields_to_check || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
