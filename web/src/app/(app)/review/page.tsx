"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, money, DISMISS_WORD, REVIEW_QUERY_KEY, REVIEW_IDS_KEY, STATUS_WORD, TYPE_NAME, type DismissReason, type FlagList } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import ConfirmDialog from "@/components/ConfirmDialog";
import ReviewTabs from "@/components/ReviewTabs";
import { IconArrow } from "@/components/Icons";
import { useProgress } from "@/lib/progress";

export default function ReviewPage() {
  return <NeedClient>{(c) => <Review cid={c.id} />}</NeedClient>;
}

function Review({ cid }: { cid: string }) {
  const router = useRouter();
  const [list, setList] = useState<FlagList | null>(null);
  const url = typeof window === "undefined" ? null : new URLSearchParams(window.location.search);
  const [type, setType] = useState(() => url?.get("type") ?? "");
  const [status, setStatus] = useState(() => (url?.has("status") ? url.get("status") ?? "" : "open"));
  const autoRun = useRef(url?.get("run") === "1");
  const prog = useProgress();
  const [shop, setShop] = useState("");
  const [unit, setUnit] = useState("");
  const [sort, setSort] = useState<"impact_desc" | "impact_asc">("impact_desc");
  const [filters, setFilters] = useState<{ shops: string[]; units: string[] }>({ shops: [], units: [] });
  const [anyFlags, setAnyFlags] = useState<boolean | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.flagFilters(cid).then(setFilters).catch(() => undefined); }, [cid]);
  useEffect(() => {
    try { sessionStorage.setItem(REVIEW_QUERY_KEY, JSON.stringify({ type, shop, unit, sort })); } catch { /* ignore */ }
  }, [type, shop, unit, sort]);

  const load = useCallback(() => api.flags(cid, { type, status, shop, unit, sort }).then(async (l) => {
    setList(l);
    try { sessionStorage.setItem(REVIEW_IDS_KEY, JSON.stringify(l.flags.filter((f) => f.status === "open").map((f) => f.id))); } catch { /* ignore */ }
    setError(null);
    if (l.count > 0 || l.confirmed_total > 0 || l.open_total > 0) setAnyFlags(true);
    else setAnyFlags((await api.flags(cid, {})).count > 0);
  }).catch((e) => setError(e instanceof Error ? e.message : "Couldn't load flags. Refresh the page.")), [cid, type, status, shop, unit, sort]);
  useEffect(() => { load(); }, [load]);

  async function run() {
    setRunning(true);
    setMessage(null);
    try {
      const { job_id } = await api.runFlags(cid);
      for (;;) {
        await new Promise((r) => setTimeout(r, 2000));
        const r = await api.flagRun(cid, job_id);
        if (r.status === "done") {
          prog?.markChecksRun();
          const n = r.summary?.flags ?? 0;
          setMessage({ text: `Checks finished. ${n} ${n === 1 ? "flag" : "flags"} found.` });
          break;
        }
        if (r.status === "failed") { setMessage({ text: r.error || "The checks didn't finish. Run them again in a moment.", error: true }); break; }
      }
      await load();
      await prog?.refresh();
      setAnyFlags(true);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Couldn't start the checks. Try again.", error: true });
    } finally { setRunning(false); }
  }

  useEffect(() => {
    if (!autoRun.current) return;
    autoRun.current = false;
    try { window.history.replaceState(null, "", "/review"); } catch { /* ignore */ }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- multi-select (same pattern as the invoices list). A selection only covers what is on screen.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<null | "accept" | "dismiss" | "reopen">(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const shown = list?.flags ?? [];
  const chosen = shown.filter((f) => selected.has(f.id));
  const allOn = shown.length > 0 && chosen.length === shown.length;
  const chosenOpen = chosen.filter((f) => f.status === "open").length;
  const chosenDone = chosen.length - chosenOpen;
  const chosenAmount = chosen.reduce((n, f) => n + Number(f.impact || 0), 0);
  useEffect(() => { if (selectAllRef.current) selectAllRef.current.indeterminate = chosen.length > 0 && !allOn; }, [chosen.length, allOn]);
  function filterBy<T>(set: (v: T) => void) { return (v: T) => { set(v); setSelected(new Set()); }; }
  function toggle(id: string) { setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; }); }
  function toggleAll() { setSelected(allOn ? new Set() : new Set(shown.map((f) => f.id))); }
  const flagWord = (n: number) => `${n} ${n === 1 ? "flag" : "flags"}`;
  async function bulk(action: "accept" | "dismiss" | "reopen", extra: { reason?: DismissReason; note?: string } = {}) {
    const r = await api.bulkFlags(cid, chosen.map((f) => f.id), action, extra);
    const verb = action === "accept" ? "accepted" : action === "dismiss" ? "dismissed" : "reopened";
    setDialog(null); setSelected(new Set());
    setNotice(`${flagWord(r.changed)} ${verb}.${r.unchanged ? ` ${flagWord(r.unchanged)} already ${verb}.` : ""}`);
    await load();
    await prog?.refresh();
  }

  const hasOpen = (list?.open_total ?? 0) > 0;
  const firstOpen = list?.flags.find((f) => f.status === "open");
  const finished = status === "open" && list !== null && list.count === 0 && !hasOpen && (list.confirmed_total > 0 || anyFlags === true) && !type && !shop && !unit;
  const none = list !== null && list.count === 0 && !finished && anyFlags !== true && !type && !shop && !unit;

  return (
    <div>
      <ReviewTabs current="flags" />
      <div className="mt-6">
        <h1 className="text-xl">Steps 3 and 4 · Run checks and review flags</h1>
        <p className="mt-1 max-w-prose text-muted">Run the checks once every invoice is checked. Then open each flag, look at the evidence and accept or dismiss it. Biggest amounts come first.</p>
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-[1fr_auto]">
        <div className="card flex min-w-0 flex-wrap items-end gap-x-10 gap-y-4">
          <div>
            <p className="kpi-label">Still to review</p>
            <p className="num text-[2.5rem] font-bold leading-tight sm:text-hero text-money" data-testid="hero" style={{ boxShadow: "0 4px 0 0 var(--amber)", display: "inline-block", paddingBottom: 4 }}>
              {list ? money(list.open_total) : "$–"}
            </p>
          </div>
          <div>
            <p className="kpi-label">Confirmed</p>
            <p className="kpi-value text-confirmed"><span data-testid="confirmed">{list ? money(list.confirmed_total) : "$–"}</span></p>
          </div>
          <div>
            <p className="kpi-label">Flags open</p>
            <p className="kpi-value">{prog ? prog.flagsOpen : "–"}<span className="text-base font-normal text-muted"> of {prog?.flags ?? "–"}</span></p>
          </div>
        </div>
        <div className="card flex flex-col justify-center gap-3 md:w-[300px]">
          {firstOpen && <Link href={`/review/${firstOpen.id}`} className="btn-primary btn-lg w-full">Start reviewing<IconArrow /></Link>}
          <button className={`${firstOpen ? "btn-secondary" : "btn-primary btn-lg"} w-full`} onClick={run} disabled={running}>
            {running ? "Running checks…" : prog?.checksRun ? "Run checks again" : "Run checks"}
          </button>
          <p role="status" className={`text-sm ${message?.error ? "text-danger" : "text-muted"}`}>
            {running ? "This takes a few seconds." : message?.text ?? (prog?.checksStale ? "New invoices since the last run — run the checks again." : prog?.needReview ? `${prog.needReview} invoices still need checking first.` : "")}
          </p>
        </div>
      </div>

      {prog && prog.byType.length > 0 && (
        <div className="mt-6 flex flex-wrap gap-2" aria-label="Flags by type">
          <button onClick={() => filterBy(setType)("")} className={`chip ${!type ? "border-primary bg-primary text-white" : "border-line-strong bg-surface hover:bg-sunken"}`}>All types</button>
          {prog.byType.map((t) => (
            <button key={t.type} onClick={() => filterBy(setType)(type === t.type ? "" : t.type)} aria-pressed={type === t.type}
              className={`chip ${type === t.type ? "border-primary bg-primary text-white" : "border-line-strong bg-surface hover:bg-sunken"}`}>
              {TYPE_NAME[t.type] ?? t.type}
              <span className={`num rounded-full px-2 text-xs ${type === t.type ? "bg-white/20" : "bg-sunken"}`}>{t.open ? `${t.open} open` : t.count}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-4">
        <Select id="f-status" label="Status" value={status} onChange={filterBy(setStatus)} all="All statuses" options={Object.entries(STATUS_WORD)} />
        <Select id="f-shop" label="Shop" value={shop} onChange={filterBy(setShop)} all="All shops" options={filters.shops.map((s) => [s, s])} />
        <Select id="f-unit" label="Unit" value={unit} onChange={filterBy(setUnit)} all="All units" options={filters.units.map((s) => [s, s])} />
      </div>

      {notice && <p role="status" className="mt-4 font-medium text-confirmed">{notice}</p>}
      {chosen.length > 0 && (
        <div role="region" aria-label="Selected flags" data-testid="flag-selection"
          className="sticky top-0 z-10 mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-line-strong bg-surface px-4 py-3 shadow-sm">
          <span className="font-bold"><span className="num">{chosen.length}</span> selected · <span className="num text-money">{money(chosenAmount)}</span></span>
          {chosenOpen > 0 && <button className="btn-primary btn-sm" onClick={() => setDialog("accept")}>Accept {chosenOpen}</button>}
          {chosenOpen > 0 && <button className="btn-secondary btn-sm" onClick={() => setDialog("dismiss")}>Dismiss {chosenOpen}</button>}
          {chosenDone > 0 && <button className="btn-secondary btn-sm" onClick={() => setDialog("reopen")}>Reopen {chosenDone}</button>}
          <button className="btn-link ml-auto" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

      {error && <p role="alert" className="mt-6 text-danger">{error}</p>}
      {none && <p className="mt-8 max-w-prose text-lg">No flags yet. Run checks after your invoices are read.</p>}
      {finished && (
        <div className="card mt-8 max-w-prose border-l-[6px] border-l-confirmed" data-testid="finished">
          <p className="text-lg font-bold">All flags are reviewed.</p>
          <p className="mt-1 text-muted">Create a report to share what was confirmed.</p>
          <button className="btn-primary btn-lg mt-4" onClick={() => router.push("/reports?create=1")}>Go to step 5 · Create report</button>
        </div>
      )}
      {list && list.flags.length === 0 && !finished && !none && <p className="mt-8 max-w-prose text-lg">No flags match these filters. Change a filter to see more.</p>}
      {list && list.flags.length > 0 && (
        <div className="mt-6 overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[960px] border-collapse">
            <caption className="sr-only">Flags to review</caption>
            <thead>
              <tr>
                <th scope="col" className="th w-12">
                  <label className="flex min-h-[40px] min-w-[40px] cursor-pointer items-center justify-center">
                    <input ref={selectAllRef} type="checkbox" checked={allOn} onChange={toggleAll} className="h-5 w-5" style={{ accentColor: "var(--primary)" }}
                      aria-label={allOn ? `Clear selection of all ${shown.length} flags` : `Select all ${shown.length} flags in this list`} />
                  </label>
                </th>
                <th scope="col" className="th">Type</th>
                <th scope="col" className="th">Shop</th>
                <th scope="col" className="th">Unit</th>
                <th scope="col" className="th">What we found</th>
                <th scope="col" className="th text-right" aria-sort={sort === "impact_desc" ? "descending" : "ascending"}>
                  <button className="min-h-[40px] font-medium" onClick={() => setSort(sort === "impact_desc" ? "impact_asc" : "impact_desc")}>Impact {sort === "impact_desc" ? "↓" : "↑"}</button>
                </th>
                <th scope="col" className="th">Status</th>
                <th scope="col" className="th"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {list.flags.map((f) => (
                <tr key={f.id} className={`tr align-top hover:bg-bg ${selected.has(f.id) ? "bg-sunken" : ""}`} aria-selected={selected.has(f.id)}>
                  <td className="td w-12">
                    <label className="flex min-h-[40px] min-w-[40px] cursor-pointer items-center justify-center">
                      <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} className="h-5 w-5" style={{ accentColor: "var(--primary)" }}
                        aria-label={`Select ${TYPE_NAME[f.type] ?? f.type} flag, ${f.shop || "unknown shop"}, ${money(f.impact)}`} />
                    </label>
                  </td>
                  <td className="td font-medium"><Link href={`/review/${f.id}`} className="text-primary underline-offset-4 hover:underline">{TYPE_NAME[f.type] ?? f.type}</Link></td>
                  <td className="td">{f.shop}</td>
                  <td className="td num whitespace-nowrap">{f.unit}</td>
                  <td className="td max-w-[68ch]">{f.reason}</td>
                  <td className="td num whitespace-nowrap text-right text-money">{money(f.impact)}</td>
                  <td className={`td whitespace-nowrap font-medium ${f.status === "dismissed" ? "text-dismissed" : f.status === "open" ? "" : "text-confirmed"}`}>{STATUS_WORD[f.status] ?? f.status}</td>
                  <td className="td text-right"><Link href={`/review/${f.id}`} className={f.status === "open" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}>{f.status === "open" ? "Review" : "View"}</Link></td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-line-strong">
                <td className="td font-bold" colSpan={5}>{list.flags.length} {list.flags.length === 1 ? "flag" : "flags"} shown</td>
                <td className="td num whitespace-nowrap text-right font-bold text-money">{money(list.flags.reduce((n, f) => n + Number(f.impact || 0), 0))}</td>
                <td className="td" colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <ConfirmDialog open={dialog === "accept"} title={`Accept ${flagWord(chosenOpen)}?`}
        body={`This confirms ${flagWord(chosenOpen)} worth ${money(chosen.filter((f) => f.status === "open").reduce((n, f) => n + Number(f.impact || 0), 0))} as real findings for the report. Open a flag first if you want to look at the evidence. You can reopen them later.`}
        actionLabel={`Accept ${chosenOpen}`} onConfirm={() => bulk("accept")} onClose={() => setDialog(null)} />
      <ConfirmDialog open={dialog === "reopen"} title={`Reopen ${flagWord(chosenDone)}?`}
        body="This puts the selected accepted or dismissed flags back in the list to review. Their decision is cleared."
        actionLabel={`Reopen ${chosenDone}`} onConfirm={() => bulk("reopen")} onClose={() => setDialog(null)} />
      <DismissDialog open={dialog === "dismiss"} count={chosenOpen} onConfirm={(reason, note) => bulk("dismiss", { reason, note })} onClose={() => setDialog(null)} />
    </div>
  );
}

function DismissDialog({ open, count, onConfirm, onClose }: { open: boolean; count: number; onConfirm: (r: DismissReason, note?: string) => Promise<void>; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState<DismissReason | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  function close() { setReason(""); setNote(""); setError(null); onClose(); }
  async function go(e: React.FormEvent) {
    e.preventDefault();
    if (!reason) { setError("Pick a reason."); return; }
    setBusy(true); setError(null);
    try { await onConfirm(reason, note.trim() || undefined); setReason(""); setNote(""); }
    catch (err) { setError(err instanceof Error ? err.message : "That didn't work. Try again."); }
    finally { setBusy(false); }
  }
  return (
    <dialog ref={ref} onClose={close} className="w-[min(520px,92vw)] border border-line-strong bg-surface p-6 text-ink backdrop:bg-ink/40">
      <form onSubmit={go}>
        <h2 className="text-lg">Dismiss {count} {count === 1 ? "flag" : "flags"}?</h2>
        <p className="mt-2 text-muted">Dismissed flags are left out of the report. The same reason is saved on each one. You can reopen them later.</p>
        <fieldset className="mt-4">
          <legend className="mb-2 text-sm font-medium">Reason</legend>
          <div className="grid gap-2">
            {(Object.entries(DISMISS_WORD) as [DismissReason, string][]).map(([k, label]) => (
              <label key={k} className={`flex min-h-[44px] cursor-pointer items-center gap-3 rounded-md border px-3 ${reason === k ? "border-primary bg-sunken" : "border-line"}`}>
                <input type="radio" name="bulk-reason" value={k} checked={reason === k} onChange={() => setReason(k)} className="h-5 w-5" style={{ accentColor: "var(--primary)" }} />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <label htmlFor="bulk-note" className="mb-1 mt-4 block text-sm font-medium">Note (optional)</label>
        <textarea id="bulk-note" className="field min-h-[80px] py-2" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
        {error && <p role="alert" className="mt-3 text-danger">{error}</p>}
        <div className="mt-5 flex gap-3">
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Working…" : `Dismiss ${count}`}</button>
          <button type="button" className="btn-secondary" onClick={close}>Cancel</button>
        </div>
      </form>
    </dialog>
  );
}

function Select({ id, label, value, onChange, all, options }: { id: string; label: string; value: string; onChange: (v: string) => void; all: string; options: string[][] }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">{label}</label>
      <select id={id} className="field min-w-[180px]" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{all}</option>
        {options.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
    </div>
  );
}
