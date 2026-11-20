"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, dateTime, DISMISS_WORD, money, REVIEW_QUERY_KEY, REVIEW_IDS_KEY, STATUS_WORD, TYPE_NAME, type DismissReason, type FlagDetail } from "@/lib/api";
import { useProgress } from "@/lib/progress";
import NeedClient from "@/components/NeedClient";

export default function FlagPage({ params }: { params: Promise<{ flagId: string }> }) {
  const { flagId } = use(params);
  return <NeedClient>{(c) => <Detail key={flagId} cid={c.id} fid={flagId} />}</NeedClient>;
}

function num(v: unknown, d = 2) {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(d) : String(v);
}

function readIds(): string[] {
  try { return JSON.parse(sessionStorage.getItem(REVIEW_IDS_KEY) || "[]"); } catch { return []; }
}

function Detail({ cid, fid }: { cid: string; fid: string }) {
  const router = useRouter();
  const [d, setD] = useState<FlagDetail | null>(null);
  const [ids, setIds] = useState<string[]>(readIds);
  const [error, setError] = useState<string | null>(null);
  const [needsImageCheck, setNeedsImageCheck] = useState(false);   // the flag rests on numbers that were hard to read
  const [panel, setPanel] = useState<null | "dismiss" | "edit">(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(false);
  const [reason, setReason] = useState<DismissReason | "">("");
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const [text, setText] = useState("");
  const idsRef = useRef<string[]>(ids);

  useEffect(() => {
    api.flag(cid, fid).then((x) => {
      setD(x);
      const fp = x.invoice.flagged_page;
      const i = fp ? x.invoice.pages.findIndex((p) => p.n === fp) : 0;
      setPage(Math.max(0, i));
    }).catch((e) => setError(e instanceof Error ? e.message : "Couldn't load this flag. Refresh the page."));
    if (idsRef.current.length) return;
    let q = { type: "", shop: "", unit: "", sort: "impact_desc" };
    try { q = { ...q, ...JSON.parse(sessionStorage.getItem(REVIEW_QUERY_KEY) || "{}") }; } catch { /* default */ }
    api.flags(cid, { ...q, status: "open" }).then((l) => { const a = l.flags.map((f) => f.id); idsRef.current = a; setIds(a); }).catch(() => undefined);
  }, [cid, fid]);

  const openPanel = useCallback((p: "dismiss" | "edit") => {
    if (p === "edit" && d) { setAmount(num(d.impact)); setText(d.reason); setNote(d.note ?? ""); }
    if (p === "dismiss") { setReason(""); setNote(""); }
    setPanel(p);
  }, [d]);

  const progress = useProgress();
  const refreshProgress = progress?.refresh;
  const blocked = (progress?.needReview ?? 0) > 0 || !!progress?.checksStale;
  const go = useCallback((id: string | undefined) => router.push(id ? `/review/${id}` : "/review"), [router]);
  const idx = ids.indexOf(fid);

  const advance = useCallback(() => {
    const rest = idsRef.current.filter((x) => x !== fid);
    idsRef.current = rest;
    try { sessionStorage.setItem(REVIEW_IDS_KEY, JSON.stringify(rest)); } catch { /* ignore */ }
    go(rest[idx < 0 ? 0 : idx] ?? rest[0]);
  }, [fid, idx, go]);

  const act = useCallback(async (action: "accept" | "dismiss" | "edit" | "reopen", body: object = {}) => {
    setBusy(true);
    setError(null);
    try {
      const x = await api.flagAction(cid, fid, action, body);
      setPanel(null);
      refreshProgress?.();
      if (action === "reopen") { setD(x); idsRef.current = idsRef.current.includes(fid) ? idsRef.current : [...idsRef.current, fid]; setIds(idsRef.current); }
      else {
        // That was the last open flag and nothing else blocks the report: go straight to it.
        const left = await api.flags(cid, { status: "open" }).then((l) => l.count, () => null);
        if (left === 0 && !blocked) { router.push("/reports"); return; }
        advance();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "That didn't save. Try again.";
      setError(msg);
      setNeedsImageCheck(action === "accept" && msg.includes("hard to read"));
    }
    finally { setBusy(false); }
  }, [cid, fid, advance, refreshProgress, blocked, router]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      // UI2: never act on a held key, or on a key pressed while a button or link has focus (a flag could be accepted unseen)
      if (e.repeat || ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(t.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "escape") setPanel(null);
      else if (!d) return;
      else if (k === "a" && d.status === "open" && !busy) act("accept");
      else if (k === "d" && d.status === "open") { e.preventDefault(); openPanel("dismiss"); }
      else if (k === "e" && d.status === "open") { e.preventDefault(); openPanel("edit"); }
      else if (k === "j") go(ids[idx + 1] ?? ids.find((x) => x !== fid));
      else if (k === "k") go(idx > 0 ? ids[idx - 1] : ids.filter((x) => x !== fid).pop());
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [d, busy, act, go, ids, idx, fid, openPanel]);

  if (error && !d) return <p role="alert" className="text-danger">{error} <Link href="/review" className="btn-link">Back to flags</Link></p>;
  if (!d) return <p className="text-muted" role="status">Loading flag…</p>;

  const pg = d.invoice.pages[Math.min(page, d.invoice.pages.length - 1)];
  const band = d.line?.y_center != null && pg && pg.n === d.invoice.flagged_page;
  const open = d.status === "open";

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link href="/review" className="btn-link">← Back to flags</Link>
        <p className="text-sm text-muted">
          <span className="num" data-testid="position">{idx >= 0 ? `${idx + 1} of ${ids.length} open flags` : `${ids.length} open flags`}</span>
          <span className="mx-2" aria-hidden>·</span>
          <span data-testid="key-hint">Keys: A accept · D dismiss · E edit · J next · K previous</span>
        </p>
      </div>
      <div className="grid gap-8 min-[900px]:grid-cols-[3fr_2fr]">
        <section aria-label="Original invoice page" className="min-w-0">
          <div className="top-6 min-[900px]:sticky">
            {d.line && <p className="mb-3 bg-amber-soft px-3 py-2 font-medium">Flagged line {d.line.line_no}: {d.line.description}</p>}
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              {d.invoice.pages.length > 1 ? (
                <div className="flex items-center gap-2" role="group" aria-label="Page">
                  <button className="btn-secondary btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous page</button>
                  <span className="num">Page {page + 1} of {d.invoice.pages.length}</span>
                  <button className="btn-secondary btn-sm" disabled={page >= d.invoice.pages.length - 1} onClick={() => setPage(page + 1)}>Next page</button>
                </div>
              ) : <span />}
              <button className="btn-secondary btn-sm" onClick={() => setZoom(!zoom)} aria-pressed={zoom}>{zoom ? "Fit to window" : "Zoom to 100%"}</button>
            </div>
            <div className="max-h-[70vh] min-h-[320px] overflow-auto bg-sunken p-3 min-[900px]:max-h-[calc(100vh-11rem)]">
              {pg ? (
                <div className={`relative mx-auto ${zoom ? "w-max" : "w-full"}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={apiUrl(pg.url)} alt={`Invoice page ${pg.n}`} onClick={() => setZoom(!zoom)}
                    className={`block bg-surface ${zoom ? "max-w-none cursor-zoom-out" : "h-auto w-full cursor-zoom-in"}`} />
                  {band && (
                    <div data-testid="band" aria-hidden className="pointer-events-none absolute left-0 right-0 h-[4%] -translate-y-1/2 border-y-2 border-amber bg-amber/30"
                      style={{ top: `${(d.line!.y_center as number) * 100}%` }} />
                  )}
                </div>
              ) : <p className="p-6 text-muted">The original page isn&apos;t available. It may have been removed under the retention policy.</p>}
            </div>
          </div>
        </section>

        <section aria-label="Flag" className="min-w-0">
          <p className="text-sm text-muted">{TYPE_NAME[d.type] ?? d.type} · {d.invoice.shop} · Unit <span className="num">{d.invoice.unit}</span></p>
          <h1 className="mt-2 max-w-prose text-lg font-bold">{d.reason}</h1>
          <p className="num mt-3 text-2xl font-bold text-money" data-testid="impact">{money(d.impact)}</p>
          {d.evidence_lines.length > 0 && (
            <ul className="mt-3 max-w-prose list-disc space-y-1 pl-5">{d.evidence_lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
          )}

          {error && <p role="alert" className="mt-4 text-danger">{error}</p>}
          {needsImageCheck && <button className="btn-secondary btn-sm mt-2" disabled={busy} onClick={() => act("accept", { extraction_checked: true })}>I checked the invoice image: the numbers are right, accept</button>}

          {open ? (
            <div className="mt-6 grid gap-3">
              <button className="btn-primary btn-lg justify-between" disabled={busy} onClick={() => act("accept")}>Accept flag <kbd className="font-sans text-sm opacity-80">A</kbd></button>
              <button className="btn-secondary btn-lg justify-between" onClick={() => openPanel("dismiss")} aria-expanded={panel === "dismiss"}>Dismiss flag <kbd className="font-sans text-sm text-muted">D</kbd></button>
              <button className="btn-secondary btn-lg justify-between" onClick={() => openPanel("edit")} aria-expanded={panel === "edit"}>Edit flag <kbd className="font-sans text-sm text-muted">E</kbd></button>
            </div>
          ) : (
            <p className={`mt-6 border-l-4 px-3 py-3 ${d.status === "dismissed" ? "border-dismissed bg-dismissed-soft" : "border-confirmed bg-confirmed-soft"}`} data-testid="flag-status">
              <span className="font-bold">{STATUS_WORD[d.status]}</span>
              {d.status === "dismissed" && d.dismiss_reason ? `: ${DISMISS_WORD[d.dismiss_reason]}` : ""}
              {d.reviewed_by ? ` by ${d.reviewed_by}` : ""}{d.reviewed_at ? ` on ${dateTime(d.reviewed_at)}` : ""}.
              {d.note ? <span className="block text-muted">Note: {d.note}</span> : null}
              <button className="btn-secondary btn-sm mt-2" onClick={() => act("reopen")} disabled={busy}>Undo</button>
            </p>
          )}

          {panel === "dismiss" && open && (
            <form className="mt-4 border border-line-strong bg-surface p-4" onSubmit={(e) => { e.preventDefault(); if (reason) act("dismiss", { reason, note: note || undefined }); }}>
              <fieldset>
                <legend className="font-bold">Why dismiss this flag?</legend>
                <div className="mt-2 grid gap-1">
                  {Object.entries(DISMISS_WORD).map(([k, v]) => (
                    <label key={k} className="flex min-h-[44px] items-center gap-3">
                      <input type="radio" name="reason" value={k} checked={reason === k} onChange={() => setReason(k as DismissReason)} className="h-5 w-5 accent-[var(--primary)]" />{v}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label htmlFor="dnote" className="mb-1 mt-3 block text-sm font-medium">Note (optional)</label>
              <textarea id="dnote" className="field py-2" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="mt-3 flex gap-3">
                <button type="submit" className="btn-primary" disabled={!reason || busy}>Dismiss flag</button>
                <button type="button" className="btn-secondary" onClick={() => setPanel(null)}>Cancel</button>
              </div>
            </form>
          )}
          {panel === "edit" && open && (
            <form className="mt-4 border border-line-strong bg-surface p-4" onSubmit={(e) => { e.preventDefault(); act("edit", { amount: amount === "" ? undefined : Number(amount), reason: text, note: note || undefined }); }}>
              <label htmlFor="eamount" className="mb-1 block text-sm font-medium">Amount</label>
              <input id="eamount" type="number" step="0.01" min="0" className="field num max-w-[200px] text-right" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <label htmlFor="ereason" className="mb-1 mt-3 block text-sm font-medium">Reason</label>
              <textarea id="ereason" className="field py-2" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
              <label htmlFor="enote" className="mb-1 mt-3 block text-sm font-medium">Note (optional)</label>
              <textarea id="enote" className="field py-2" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="mt-3 flex gap-3">
                <button type="submit" className="btn-primary" disabled={busy}>Save changes</button>
                <button type="button" className="btn-secondary" onClick={() => setPanel(null)}>Cancel</button>
              </div>
            </form>
          )}

          <h2 className="mt-10 text-lg">Invoice {d.invoice.invoice_number}</h2>
          <p className="mt-1"><Link href={`/invoices/${d.invoice.id}`} className="btn-secondary btn-sm">Fix extracted fields</Link></p>
          <div className="mt-3 overflow-x-auto bg-surface">
            <table className="w-full min-w-[520px] border-collapse">
              <caption className="sr-only">Invoice lines</caption>
              <thead><tr>
                <th scope="col" className="th">Line</th><th scope="col" className="th">Description</th>
                <th scope="col" className="th text-right">Hours</th><th scope="col" className="th text-right">Parts</th><th scope="col" className="th text-right">Total</th>
              </tr></thead>
              <tbody>
                {d.lines.map((l) => (
                  <tr key={l.id} className={`border-t border-line align-top ${l.flagged ? "bg-amber-soft" : ""}`}>
                    <td className="num px-4 py-3">{l.line_no}</td>
                    <td className="px-4 py-3">{l.description}{l.flagged && <span className="mt-1 block text-sm font-bold">Flagged</span>}</td>
                    <td className="num px-4 py-3 text-right">{num(l.labour_hours, 1)}</td>
                    <td className="num px-4 py-3 text-right">{num(l.parts_price)}</td>
                    <td className="num px-4 py-3 text-right">{num(l.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
