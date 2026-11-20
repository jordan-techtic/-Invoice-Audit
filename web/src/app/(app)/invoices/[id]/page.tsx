"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, type FieldState, type InvoiceDetail, type InvoiceLine } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import StatusMark from "@/components/StatusMark";
import FieldInput, { display } from "@/components/FieldInput";
import { IconAlert, IconArrow } from "@/components/Icons";
import { useProgress } from "@/lib/progress";

export default function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <NeedClient>{(c) => <Detail key={id} cid={c.id} id={id} />}</NeedClient>;
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
  const [canConfirm, setCanConfirm] = useState(false);   // the numbers failed a check: the person may confirm them exactly as printed
  const [edited, setEdited] = useState(false);
  const [recheck, setRecheck] = useState<{ busy?: boolean; text?: string; error?: string }>({});
  const pending = useRef<Set<Promise<unknown>>>(new Set());
  const [nextId, setNextId] = useState<string | null | undefined>(undefined); // undefined = not looked up yet
  const progress = useProgress();
  const refreshProgress = progress?.refresh;
  // After the last invoice is checked the audit checks start on their own.
  const [auto, setAuto] = useState<{ state: "idle" | "running" | "done" | "error"; flags?: number; error?: string }>({ state: "idle" });

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
    setEdited(true);
    setRecheck({});
    setData((d) => {
      if (!d) return d;
      const fix = (s: FieldState | undefined): FieldState => ({ value, confidence: 1, ...s, needs_review: false, note: null, corrected: true } as FieldState);
      if (!lineId) return { ...d, header: { ...d.header, [field]: { ...fix(d.header[field]), value } } };
      return { ...d, lines: d.lines.map((l) => (l.id === lineId ? { ...l, [field]: { ...fix(l[field] as FieldState), value } } : l)) };
    });
    load();
  }

  async function runRecheck() {
    setRecheck({ busy: true });
    try {
      const r = await api.recheck(cid, id);
      setRecheck({ text: `Checks updated: ${r.flags} ${r.flags === 1 ? "flag" : "flags"} (added ${r.added}, removed ${r.removed})` });
    } catch (e) { setRecheck({ error: e instanceof Error ? e.message : "Couldn't re-check this invoice. Try again." }); }
  }

  async function confirmField(field: string, lineId?: string) {
    await api.confirmField(cid, id, field, lineId);
    await load();
  }

  async function markChecked(confirmAsPrinted = false) {
    setMarking(true);
    setMarkError(null);
    setCanConfirm(false);
    try {
      await Promise.allSettled([...pending.current]);
      await api.markChecked(cid, id, confirmAsPrinted);
      await load();
      // A failed lookup is "we don't know", not "nothing is left": only start the checks when the list really came back empty.
      const left = await api.invoices(cid, "needs_review").catch(() => null);
      const next = left?.find((r) => r.id !== id)?.id ?? null;
      setNextId(next);
      refreshProgress?.();
      if (left && !next && progress) {
        setAuto({ state: "running" });
        progress.runChecks().then(
          (flags) => setAuto({ state: "done", flags }),
          (e) => setAuto({ state: "error", error: e instanceof Error ? e.message : "The checks didn't finish. Run them again from step 2." }),
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Couldn't mark this invoice as checked. Try again.";
      setMarkError(msg);
      setCanConfirm(msg.includes("exactly as printed"));
    } finally {
      setMarking(false);
    }
  }

  if (error) return <p role="alert" className="text-danger">{error} <Link href="/invoices" className="btn-link">Back to invoices</Link></p>;
  if (!data) return <p className="text-muted" role="status">Loading invoice…</p>;

  const toCheck = [...Object.values(data.header), ...data.lines.flatMap((l) => Object.values(l).filter((v): v is FieldState => typeof v === "object" && v !== null))]
    .filter((f) => f.needs_review).length;
  const checked = data.review_status === "reviewed";
  const pg = data.pages[Math.min(page, data.pages.length - 1)];

  return (
    <div>
    <div className="grid gap-8 min-[900px]:grid-cols-[3fr_2fr]">
      <section aria-label="Original invoice page" className="min-w-0">
        <div className="top-6 min-[900px]:sticky">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            {data.pages.length > 1 ? (
              <div className="flex items-center gap-2" role="group" aria-label="Page">
                <button className="btn-secondary btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous page</button>
                <span className="num">Page {page + 1} of {data.pages.length}</span>
                <button className="btn-secondary btn-sm" disabled={page >= data.pages.length - 1} onClick={() => setPage(page + 1)}>Next page</button>
              </div>
            ) : <span className="text-muted">{data.source_filename}</span>}
            <button className="btn-secondary btn-sm" onClick={() => setZoom(!zoom)} aria-pressed={zoom}>{zoom ? "Fit to window" : "Zoom to 100%"}</button>
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
        <Link href="/invoices?status=needs_review" className="btn-link">← Back to invoices</Link>
        <h1 className="mt-3 text-xl">Invoice {display("invoice_number", data.header.invoice_number?.value ?? null) || "without a number"}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
          <span data-testid="review-status"><StatusMark status={data.review_status} /></span>
          {toCheck > 0 && <span className="num text-muted">{toCheck} {toCheck === 1 ? "field" : "fields"} to check</span>}
        </p>

        {edited && (
          <div className="mt-5 border-l-4 border-primary bg-surface px-4 py-3" data-testid="recheck-banner">
            {recheck.text ? (
              <p>{recheck.text}. <Link href="/review" className="btn-link">Back to flags to review</Link></p>
            ) : (
              <>
                <p className="mb-2">Your changes are saved. Re-check this invoice to update its flags.</p>
                <button className="btn-secondary btn-sm" onClick={runRecheck} disabled={recheck.busy}>{recheck.busy ? "Re-checking…" : "Re-check this invoice"}</button>
                {recheck.error && <p role="alert" className="mt-2 text-danger">{recheck.error}</p>}
              </>
            )}
          </div>
        )}

        <div className="mt-5">
          {checked && nextId !== undefined ? (
            <div className="rounded-md border border-confirmed bg-confirmed-soft p-4" data-testid="next-invoice">
              <p className="font-bold text-confirmed">Invoice checked.</p>
              {nextId ? (
                <Link href={`/invoices/${nextId}`} className="btn-primary btn-lg mt-3 w-full">Check next invoice<IconArrow /></Link>
              ) : (
                <>
                  <p className="mt-1">That was the last invoice to check.</p>
                  {auto.state === "running" && (
                    <p role="status" className="mt-3 flex items-center gap-3 font-medium">
                      <span aria-hidden className="h-5 w-5 shrink-0 animate-spin rounded-full border-[3px] border-sunken border-t-primary" />
                      Running the audit checks…
                    </p>
                  )}
                  {auto.state === "done" && (
                    <>
                      <p role="status" className="mt-3 font-medium">Checks finished. {auto.flags} {auto.flags === 1 ? "flag" : "flags"} found.</p>
                      <Link href="/review" className="btn-primary btn-lg mt-3 w-full">Go to step 2 · Review flags<IconArrow /></Link>
                    </>
                  )}
                  {auto.state === "error" && (
                    <>
                      <p role="alert" className="mt-3 text-danger">{auto.error}</p>
                      <Link href="/review" className="btn-primary btn-lg mt-3 w-full">Go to step 2<IconArrow /></Link>
                    </>
                  )}
                </>
              )}
            </div>
          ) : (
            <button className="btn-primary btn-lg w-full" onClick={() => markChecked()} disabled={checked || marking}>
              {checked ? "Checked" : marking ? "Marking…" : "Mark as checked"}
            </button>
          )}
          {markError && <p role="alert" className="mt-2 text-danger">{markError}</p>}
          {canConfirm && <button className="btn-secondary mt-2 w-full" onClick={() => markChecked(true)} disabled={marking}>The numbers are exactly as printed: mark as checked</button>}
          {!checked && toCheck > 0 && <p className="mt-2 text-sm text-muted">Fix each field marked Check, or press Looks right if it matches the image. Then mark this invoice as checked.</p>}
        </div>

        <h2 className="mt-10 text-lg">Invoice details</h2>
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-4">
          {HEADER.map((h) => (
            <FieldInput key={h.field} field={h.field} label={h.label} state={data.header[h.field]}
              className={h.wide ? "col-span-2" : ""} onSave={(v) => save(h.field, v)} onConfirm={() => confirmField(h.field)} />
          ))}
        </div>

      </section>
    </div>
      <section aria-label="Line items" className="mt-10">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg">Line items</h2>
          <p className="text-sm text-muted">{data.lines.length} {data.lines.length === 1 ? "line" : "lines"} · fields marked Check need a look</p>
        </div>
        {data.lines.length === 0 ? <p className="mt-2 text-muted">No line items were read from this invoice.</p> : (
          <div className="mt-3 overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[900px] border-collapse">
              <caption className="sr-only">Line items</caption>
              <thead>
                <tr>
                  <th scope="col" className="th min-w-[280px]">Description</th>
                  {LINE_COLS.map((c) => <th key={c.field} scope="col" className={`th ${c.field !== "part_number" ? "text-right" : ""}`}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l) => <LineRow key={l.id} line={l} onSave={(f, v) => save(f, v, l.id)} onConfirm={(f) => confirmField(f, l.id)} />)}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function LineRow({ line, onSave, onConfirm }: { line: InvoiceLine; onSave: (field: string, v: string | null) => Promise<void>; onConfirm: (field: string) => Promise<void> }) {
  const [editCode, setEditCode] = useState(false);
  const code = line.vmrs_code as FieldState | undefined;
  const n = line.line_no;
  return (
    <tr className="border-t border-line align-top">
      <td className="px-2 py-3">
        <FieldInput field="description" label={`Description, line ${n}`} hideLabel compact state={line.description as FieldState} onSave={(v) => onSave("description", v)} onConfirm={() => onConfirm("description")} />
        <div className="mt-1 text-sm text-muted">
          {editCode ? (
            <div onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setEditCode(false); }}>
              <FieldInput field="vmrs_code" label={`Job type code, line ${n}`} compact state={code} onSave={(v) => onSave("vmrs_code", v)} />
            </div>
          ) : (
            <p className="whitespace-nowrap">
              Job type: <span className="num text-ink">{code?.value ?? "not set"}</span>{" "}
              <button className="btn-link min-h-[32px]" onClick={() => setEditCode(true)} aria-label={`Edit job type, line ${n}`}>Edit</button>
              {code?.needs_review && <span className="ml-2 inline-flex items-center gap-1 rounded bg-[#fdecea] px-1.5 font-bold text-danger"><IconAlert />Check</span>}
              {code?.needs_review && (
                <button className="btn-link ml-2 min-h-[32px]" onClick={() => onConfirm("vmrs_code")} aria-label={`Job type, line ${n}, looks right`}>
                  {code?.value ? "Looks right" : "No job type needed"}
                </button>
              )}
            </p>
          )}
        </div>
      </td>
      {LINE_COLS.map((c) => (
        <td key={c.field} className={`px-2 py-3 ${c.w}`}>
          <FieldInput field={c.field} label={`${c.label}, line ${n}`} hideLabel compact state={line[c.field] as FieldState} onSave={(v) => onSave(c.field, v)} onConfirm={() => onConfirm(c.field)} />
        </td>
      ))}
    </tr>
  );
}
