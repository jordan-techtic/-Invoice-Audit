"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, money, REVIEW_QUERY_KEY, REVIEW_IDS_KEY, STATUS_WORD, TYPE_NAME, type FlagList } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import ReviewTabs from "@/components/ReviewTabs";

export default function ReviewPage() {
  return <NeedClient>{(c) => <Review cid={c.id} />}</NeedClient>;
}

function Review({ cid }: { cid: string }) {
  const router = useRouter();
  const [list, setList] = useState<FlagList | null>(null);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("open");
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
          const n = r.summary?.flags ?? 0;
          setMessage({ text: `Checks finished. ${n} ${n === 1 ? "flag" : "flags"} found.` });
          break;
        }
        if (r.status === "failed") { setMessage({ text: r.error || "The checks didn't finish. Run them again in a moment.", error: true }); break; }
      }
      await load();
      setAnyFlags(true);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Couldn't start the checks. Try again.", error: true });
    } finally { setRunning(false); }
  }

  const hasOpen = (list?.open_total ?? 0) > 0;
  const finished = status === "open" && list !== null && list.count === 0 && !hasOpen && (list.confirmed_total > 0 || anyFlags === true) && !type && !shop && !unit;
  const none = list !== null && list.count === 0 && !finished && anyFlags !== true && !type && !shop && !unit;

  return (
    <div>
      <ReviewTabs current="flags" />
      <div className="mt-8 flex flex-wrap items-start justify-between gap-6">
        <div>
          <p className="text-base text-muted">Still to review</p>
          <p className="num text-hero font-bold text-money" data-testid="hero" style={{ boxShadow: "0 4px 0 0 var(--amber)", display: "inline-block", paddingBottom: 4 }}>
            {list ? money(list.open_total) : "$–"}
          </p>
          <p className="mt-4 text-lg">
            <span className="text-confirmed">Confirmed: <span className="num font-bold" data-testid="confirmed">{list ? money(list.confirmed_total) : "$–"}</span></span>
          </p>
        </div>
        <div className="max-w-[320px] text-right">
          <button className="btn-primary" onClick={run} disabled={running}>{running ? "Running checks…" : "Run checks"}</button>
          <p role="status" className={`mt-2 text-sm ${message?.error ? "text-danger" : "text-muted"}`}>{running ? "This takes a few seconds." : message?.text}</p>
        </div>
      </div>

      <div className="mt-10 flex flex-wrap gap-4">
        <Select id="f-type" label="Type" value={type} onChange={setType} all="All types" options={Object.entries(TYPE_NAME).map(([k, v]) => [k, v])} />
        <Select id="f-status" label="Status" value={status} onChange={setStatus} all="All statuses" options={Object.entries(STATUS_WORD)} />
        <Select id="f-shop" label="Shop" value={shop} onChange={setShop} all="All shops" options={filters.shops.map((s) => [s, s])} />
        <Select id="f-unit" label="Unit" value={unit} onChange={setUnit} all="All units" options={filters.units.map((s) => [s, s])} />
      </div>

      {error && <p role="alert" className="mt-6 text-danger">{error}</p>}
      {none && <p className="mt-8 max-w-prose text-lg">No flags yet. Run checks after your invoices are read.</p>}
      {finished && (
        <div className="mt-8 max-w-prose" data-testid="finished">
          <p className="text-lg font-bold">All flags are reviewed.</p>
          <p className="mt-1 text-muted">Create a report to share what was confirmed.</p>
          <button className="btn-primary mt-4 text-lg" style={{ minHeight: 56 }} onClick={() => router.push("/reports?create=1")}>Create report</button>
        </div>
      )}
      {list && list.flags.length === 0 && !finished && !none && <p className="mt-8 max-w-prose text-lg">No flags match these filters. Change a filter to see more.</p>}
      {list && list.flags.length > 0 && (
        <div className="mt-6 overflow-x-auto bg-surface">
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
                </tr>
              ))}
            </tbody>
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
