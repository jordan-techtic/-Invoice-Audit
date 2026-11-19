"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, money, REVIEW_QUERY_KEY, REVIEW_IDS_KEY, STATUS_WORD, TYPE_NAME, type FlagList } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
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
        <div className="card flex flex-wrap items-end gap-x-10 gap-y-4">
          <div>
            <p className="kpi-label">Still to review</p>
            <p className="num text-hero font-bold text-money" data-testid="hero" style={{ boxShadow: "0 4px 0 0 var(--amber)", display: "inline-block", paddingBottom: 4 }}>
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
          <button onClick={() => setType("")} className={`chip ${!type ? "border-primary bg-primary text-white" : "border-line-strong bg-surface hover:bg-sunken"}`}>All types</button>
          {prog.byType.map((t) => (
            <button key={t.type} onClick={() => setType(type === t.type ? "" : t.type)} aria-pressed={type === t.type}
              className={`chip ${type === t.type ? "border-primary bg-primary text-white" : "border-line-strong bg-surface hover:bg-sunken"}`}>
              {TYPE_NAME[t.type] ?? t.type}
              <span className={`num rounded-full px-2 text-xs ${type === t.type ? "bg-white/20" : "bg-sunken"}`}>{t.open ? `${t.open} open` : t.count}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-4">
        <Select id="f-status" label="Status" value={status} onChange={setStatus} all="All statuses" options={Object.entries(STATUS_WORD)} />
        <Select id="f-shop" label="Shop" value={shop} onChange={setShop} all="All shops" options={filters.shops.map((s) => [s, s])} />
        <Select id="f-unit" label="Unit" value={unit} onChange={setUnit} all="All units" options={filters.units.map((s) => [s, s])} />
      </div>

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
                <tr key={f.id} className="tr align-top hover:bg-bg">
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
                <td className="td font-bold" colSpan={4}>{list.flags.length} {list.flags.length === 1 ? "flag" : "flags"} shown</td>
                <td className="td num whitespace-nowrap text-right font-bold text-money">{money(list.flags.reduce((n, f) => n + Number(f.impact || 0), 0))}</td>
                <td className="td" colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
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
