"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, type FieldState, type InvoiceDetail, type InvoiceLine } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import StatusMark from "@/components/StatusMark";
import FieldInput, { display } from "@/components/FieldInput";
import { IconAlert } from "@/components/Icons";

export default function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <NeedClient>{(c) => <Detail cid={c.id} id={id} />}</NeedClient>;
}

const HEADER: { field: string; label: string; wide?: boolean }[] = [
  { field: "shop_name", label: "Shop name", wide: true },
  { field: "shop_address", label: "Shop address", wide: true },
  { field: "invoice_number", label: "Invoice number" },
  { field: "invoice_date", label: "Invoice date" },
  { field: "unit_number", label: "Unit number" },
  { field: "odometer", label: "Odometer" },
  { field: "vin", label: "VIN", wide: true },
  { field: "subtotal", label: "Subtotal" },
  { field: "tax", label: "Tax" },
  { field: "total", label: "Total" },
];

const LINE_COLS: { field: string; label: string; w: string }[] = [
  { field: "part_number", label: "Part number", w: "w-[110px]" },
  { field: "qty", label: "Qty", w: "w-[64px]" },
  { field: "parts_price", label: "Parts price", w: "w-[96px]" },
  { field: "labour_hours", label: "Labour hours", w: "w-[84px]" },
  { field: "labour_rate", label: "Labour rate", w: "w-[92px]" },
  { field: "line_total", label: "Line total", w: "w-[100px]" },
];

function Detail({ cid, id }: { cid: string; id: string }) {
  const [data, setData] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(false);
  const [marking, setMarking] = useState(false);
  const [markError, setMarkError] = useState<string | null>(null);
  const pending = useRef<Set<Promise<unknown>>>(new Set());

  const load = useCallback(async () => {
    try { setData(await api.invoice(cid, id)); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Couldn't load this invoice. Refresh the page."); }
  }, [cid, id]);
  useEffect(() => {
    api.invoice(cid, id).then(setData).catch((e) => setError(e instanceof Error ? e.message : "Couldn't load this invoice. Refresh the page."));
  }, [cid, id]);

  async function save(field: string, value: string | null, lineId?: string) {
    const p = api.editField(cid, id, field, value, lineId);
    pending.current.add(p);
    try {
      await p;
    } finally {
      pending.current.delete(p);
    }
    setData((d) => {
      if (!d) return d;
      const fix = (s: FieldState | undefined): FieldState => ({ value, confidence: 1, ...s, needs_review: false, note: null, corrected: true } as FieldState);
      if (!lineId) return { ...d, header: { ...d.header, [field]: { ...fix(d.header[field]), value } } };
      return { ...d, lines: d.lines.map((l) => (l.id === lineId ? { ...l, [field]: { ...fix(l[field] as FieldState), value } } : l)) };
    });
    load();
  }

  async function markChecked() {
    setMarking(true);
    setMarkError(null);
    try {
      await Promise.allSettled([...pending.current]);
      await api.markChecked(cid, id);
      await load();
    } catch (e) {
      setMarkError(e instanceof Error ? e.message : "Couldn't mark this invoice as checked. Try again.");
    } finally {
      setMarking(false);
    }
  }

  if (error) return <p role="alert" className="text-danger">{error} <Link href="/invoices" className="text-primary underline underline-offset-4">Back to invoices</Link></p>;
  if (!data) return <p className="text-muted" role="status">Loading invoice…</p>;

  const toCheck = [...Object.values(data.header), ...data.lines.flatMap((l) => Object.values(l).filter((v): v is FieldState => typeof v === "object" && v !== null))]
    .filter((f) => f.needs_review).length;
  const checked = data.review_status === "reviewed";
  const pg = data.pages[Math.min(page, data.pages.length - 1)];

  return (
    <div className="grid gap-8 min-[900px]:grid-cols-[3fr_2fr]">
      <section aria-label="Original invoice page" className="min-w-0">
        <div className="top-6 min-[900px]:sticky">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            {data.pages.length > 1 ? (
              <div className="flex items-center gap-2" role="group" aria-label="Page">
                <button className="btn-secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous page</button>
                <span className="num">Page {page + 1} of {data.pages.length}</span>
                <button className="btn-secondary" disabled={page >= data.pages.length - 1} onClick={() => setPage(page + 1)}>Next page</button>
              </div>
            ) : <span className="text-muted">{data.source_filename}</span>}
            <button className="btn-secondary" onClick={() => setZoom(!zoom)} aria-pressed={zoom}>{zoom ? "Fit to window" : "Zoom to 100%"}</button>
          </div>
          <div className="max-h-[70vh] min-[900px]:max-h-[calc(100vh-9rem)] min-h-[320px] overflow-auto bg-sunken p-3">
            {pg ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={apiUrl(pg.url)}
                alt={`Invoice page ${pg.n}`}
                onClick={() => setZoom(!zoom)}
                className={`mx-auto bg-surface ${zoom ? "max-w-none cursor-zoom-out" : "h-auto w-full cursor-zoom-in"}`}
              />
            ) : <p className="p-6 text-muted">The original page isn&apos;t available. It may have been removed under the retention policy.</p>}
          </div>
        </div>
      </section>

      <section aria-label="Extracted fields" className="min-w-0">
        <Link href="/invoices" className="text-primary underline underline-offset-4">Back to invoices</Link>
        <h1 className="mt-3 text-xl">Invoice {display("invoice_number", data.header.invoice_number?.value ?? null) || "without a number"}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          <span data-testid="review-status"><StatusMark status={data.review_status} /></span>
          {toCheck > 0 && <span className="num text-muted">{toCheck} {toCheck === 1 ? "field" : "fields"} to check</span>}
        </p>

        <div className="mt-5">
          <button className="btn-primary w-full text-lg" style={{ minHeight: 56 }} onClick={markChecked} disabled={checked || marking}>
            {checked ? "Checked" : marking ? "Marking…" : "Mark as checked"}
          </button>
          {markError && <p role="alert" className="mt-2 text-danger">{markError}</p>}
          {!checked && toCheck > 0 && <p className="mt-2 text-sm text-muted">Fix or confirm the fields marked Check, then mark this invoice as checked.</p>}
        </div>

        <h2 className="mt-10 text-lg">Invoice details</h2>
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-4">
          {HEADER.map((h) => (
            <FieldInput key={h.field} field={h.field} label={h.label} state={data.header[h.field]}
              className={h.wide ? "col-span-2" : ""} onSave={(v) => save(h.field, v)} />
          ))}
        </div>

        <h2 className="mt-10 text-lg">Line items</h2>
        {data.lines.length === 0 ? <p className="mt-2 text-muted">No line items were read from this invoice.</p> : (
          <div className="mt-3 overflow-x-auto bg-surface">
            <table className="w-full min-w-[760px] border-collapse">
              <caption className="sr-only">Line items</caption>
              <thead>
                <tr>
                  <th scope="col" className="th w-[250px] min-w-[250px]">Description</th>
                  {LINE_COLS.map((c) => <th key={c.field} scope="col" className={`th ${c.field !== "part_number" ? "text-right" : ""}`}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l) => <LineRow key={l.id} line={l} onSave={(f, v) => save(f, v, l.id)} />)}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function LineRow({ line, onSave }: { line: InvoiceLine; onSave: (field: string, v: string | null) => Promise<void> }) {
  const [editCode, setEditCode] = useState(false);
  const code = line.vmrs_code as FieldState | undefined;
  const n = line.line_no;
  return (
    <tr className="border-t border-line align-top">
      <td className="px-2 py-3">
        <FieldInput field="description" label={`Description, line ${n}`} hideLabel compact state={line.description as FieldState} onSave={(v) => onSave("description", v)} />
        <div className="mt-1 text-sm text-muted">
          {editCode ? (
            <div onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setEditCode(false); }}>
              <FieldInput field="vmrs_code" label={`Job type code, line ${n}`} compact state={code} onSave={(v) => onSave("vmrs_code", v)} />
            </div>
          ) : (
            <p className="whitespace-nowrap">
              Job type: <span className="num text-ink">{code?.value ?? "not set"}</span>{" "}
              <button className="min-h-[32px] text-primary underline underline-offset-4" onClick={() => setEditCode(true)} aria-label={`Edit job type, line ${n}`}>Edit</button>
              {code?.needs_review && <span className="ml-2 inline-flex items-center gap-1 font-bold text-ink"><IconAlert />Check</span>}
            </p>
          )}
        </div>
      </td>
      {LINE_COLS.map((c) => (
        <td key={c.field} className={`px-2 py-3 ${c.w}`}>
          <FieldInput field={c.field} label={`${c.label}, line ${n}`} hideLabel compact state={line[c.field] as FieldState} onSave={(v) => onSave(c.field, v)} />
        </td>
      ))}
    </tr>
  );
}
