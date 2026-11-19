"use client";

import { useMemo, useState } from "react";
import { money, shortDate, type Breakdown, type Snapshot } from "@/lib/api";

const TOP = 10;

function share(part: number, whole: number) {
  return whole > 0 ? `${((part / whole) * 100).toFixed(1)}%` : "";
}

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "money" }) {
  return (
    <div className="print-avoid rounded-lg border border-line bg-surface p-4">
      <p className="kpi-label">{label}</p>
      <p className={`kpi-value ${tone === "money" ? "text-money" : ""}`}>{value}</p>
      {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
    </div>
  );
}

/** Bars for the biggest items plus a table with every item, so nothing is hidden. */
function Breakdown({ title, noun, items, total }: { title: string; noun: string; items: Breakdown[]; total: number }) {
  const [all, setAll] = useState(false);
  if (items.length === 0) return null;
  const sorted = [...items].sort((a, b) => b.amount - a.amount);
  const max = Math.max(sorted[0]?.amount ?? 0, 1);
  const bars = sorted.slice(0, TOP);
  const rows = all ? sorted : sorted.slice(0, TOP);
  const count = sorted.reduce((n, i) => n + i.count, 0);
  return (
    <section className="report-block min-w-0 rounded-lg border border-line bg-surface p-4 sm:p-5" aria-label={title}>
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="text-lg">{title}</h3>
        <p className="text-sm text-muted">{sorted.length} {sorted.length === 1 ? noun : `${noun}s`}</p>
      </div>
      <ul className="mt-4 space-y-2.5" aria-hidden>
        {bars.map((i, n) => (
          <li key={i.label} className="grid grid-cols-[minmax(80px,180px)_1fr_auto] items-center gap-3 text-sm">
            <span className="truncate" title={i.label}>{i.label}</span>
            <span className="h-3 rounded-sm bg-sunken"><span className="block h-3 rounded-sm" style={{ width: `${Math.max((i.amount / max) * 100, 1)}%`, background: n === 0 ? "var(--amber)" : "var(--primary)" }} /></span>
            <span className="num text-right sm:w-24">{money(i.amount)}</span>
          </li>
        ))}
      </ul>
      <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[400px] table-fixed border-collapse text-sm">
        <thead><tr>
          <th scope="col" className="py-2 pr-4 text-left font-medium text-muted">{noun.replace(/^./, (c) => c.toUpperCase())}</th>
          <th scope="col" className="w-16 py-2 text-right font-medium text-muted">Findings</th>
          <th scope="col" className="w-20 py-2 text-right font-medium text-muted">Share</th>
          <th scope="col" className="w-28 py-2 pl-4 text-right font-medium text-muted">Amount</th>
        </tr></thead>
        <tbody>{rows.map((i) => (
          <tr key={i.label} className="border-t border-line">
            <td className="truncate py-2 pr-4" title={i.label}>{i.label}</td>
            <td className="num py-2 text-right">{i.count}</td>
            <td className="num py-2 text-right text-muted">{share(i.amount, total)}</td>
            <td className="num py-2 pl-4 text-right">{money(i.amount)}</td>
          </tr>
        ))}</tbody>
        <tfoot><tr className="border-t-2 border-line-strong font-bold">
          <td className="py-2 pr-4">Total</td><td className="num py-2 text-right">{count}</td><td className="num py-2 text-right">100%</td>
          <td className="num py-2 pl-4 text-right">{money(sorted.reduce((n, i) => n + i.amount, 0))}</td>
        </tr></tfoot>
      </table></div>
      {sorted.length > TOP && (
        <button className="btn-secondary btn-sm no-print mt-3" onClick={() => setAll(!all)} aria-expanded={all}>
          {all ? `Show top ${TOP}` : `Show all ${sorted.length}`}
        </button>
      )}
    </section>
  );
}

function Findings({ rows }: { rows: Snapshot["appendix"] }) {
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"amount" | "date">("amount");
  const types = useMemo(() => [...new Set(rows.map((r) => r.type_label))].sort(), [rows]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => (!type || r.type_label === type) && (!needle || [r.invoice_number, r.shop, r.unit, r.reason].some((v) => v?.toLowerCase().includes(needle))))
      .sort((a, b) => (sort === "amount" ? b.amount - a.amount : String(a.date ?? "").localeCompare(String(b.date ?? ""))));
  }, [rows, type, q, sort]);
  const sum = shown.reduce((n, r) => n + r.amount, 0);

  return (
    <section className="mt-10" aria-label="Accepted findings">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl">Accepted findings</h2>
          <p className="mt-1 text-muted">Every finding included in this report, one row each.</p>
        </div>
        <div className="no-print flex flex-wrap gap-3">
          <div>
            <label htmlFor="ft" className="mb-1 block text-sm font-medium">Type</label>
            <select id="ft" className="field min-w-[200px]" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="fs" className="mb-1 block text-sm font-medium">Sort by</label>
            <select id="fs" className="field min-w-[160px]" value={sort} onChange={(e) => setSort(e.target.value as "amount" | "date")}>
              <option value="amount">Largest amount</option>
              <option value="date">Invoice date</option>
            </select>
          </div>
          <div>
            <label htmlFor="fq" className="mb-1 block text-sm font-medium">Search</label>
            <input id="fq" type="search" className="field w-full sm:w-[220px]" placeholder="Invoice, shop, unit…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
      </div>
      <div className="mt-4 overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead><tr>
            {["Invoice", "Date", "Shop", "Unit", "Type", "What we found"].map((h) => <th key={h} scope="col" className="px-3 py-2.5 text-left font-medium text-muted">{h}</th>)}
            <th scope="col" className="px-3 py-2.5 text-right font-medium text-muted">Amount</th>
          </tr></thead>
          <tbody>{shown.map((a, i) => (
            <tr key={i} className="border-t border-line align-top">
              <td className="num px-3 py-3">{a.invoice_number}</td>
              <td className="num whitespace-nowrap px-3 py-3">{shortDate(a.date)}</td>
              <td className="px-3 py-3">{a.shop}</td>
              <td className="num px-3 py-3">{a.unit}</td>
              <td className="whitespace-nowrap px-3 py-3">{a.type_label}</td>
              <td className="max-w-[48ch] px-3 py-3">{a.reason}</td>
              <td className="num whitespace-nowrap px-3 py-3 text-right text-money">{money(a.amount)}</td>
            </tr>
          ))}</tbody>
          <tfoot><tr className="border-t-2 border-line-strong font-bold">
            <td className="px-3 py-3" colSpan={6}>{shown.length} of {rows.length} {rows.length === 1 ? "finding" : "findings"}</td>
            <td className="num px-3 py-3 text-right text-money">{money(sum)}</td>
          </tr></tfoot>
        </table>
      </div>
    </section>
  );
}

export default function ReportView({ snapshot: s }: { snapshot: Snapshot }) {
  const pct = Number.isFinite(s.summary.pct_of_spend) ? s.summary.pct_of_spend.toFixed(1) : "0";
  const rec = s.summary.recoverable;
  return (
    <article className="px-0 py-2 print:p-0">
      <header className="report-block rounded-lg border border-line bg-surface px-6 py-6 sm:px-8">
        <p className="text-sm font-medium uppercase tracking-wide text-muted">{s.branding.company_name || "Repair invoice audit"} · Repair invoice audit</p>
        <h1 className="mt-1 text-2xl">{s.cover.client_name}</h1>
        <p className="mt-2 text-muted">
          Audit date <span className="num">{shortDate(s.cover.audit_date)}</span>
          {s.cover.period ? <> · Period <span className="num">{s.cover.period}</span></> : null}
          {" "}· Report version <span className="num">{s.version}</span>
        </p>
      </header>

      <section className="report-block mt-6" aria-label="Summary">
        {s.empty ? (
          <div className="rounded-lg border border-line bg-surface p-6">
            <p className="max-w-prose text-xl font-bold" data-testid="headline">{s.summary.headline}</p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[1.3fr_2fr]">
            <div className="rounded-lg border border-line bg-surface p-6">
              <p className="kpi-label">Likely recoverable</p>
              <p className="num mt-2 text-[2.5rem] font-bold leading-tight text-money sm:text-hero" data-testid="recoverable" style={{ boxShadow: "0 4px 0 0 var(--amber)", display: "inline-block", paddingBottom: 4 }}>{money(rec)}</p>
              <p className="mt-4 text-lg" data-testid="sentence">
                likely recoverable, <span className="num">{pct}%</span> of <span className="num">{money(s.summary.total_spend)}</span> reviewed
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-2">
              <Kpi label="Spend reviewed" value={money(s.summary.total_spend)} />
              <Kpi label="Share of spend" value={`${pct}%`} sub="recoverable ÷ spend" tone="money" />
              <Kpi label="Invoices reviewed" value={String(s.cover.invoices_reviewed)} />
              <Kpi label="Accepted findings" value={String(s.summary.flag_count)} sub={s.summary.flag_count ? `avg ${money(rec / s.summary.flag_count)} each` : undefined} />
            </div>
          </div>
        )}
      </section>

      {!s.empty && s.summary.top_findings.length > 0 && (
        <section className="report-block mt-6 rounded-lg border border-line bg-surface p-6" aria-label="Top findings">
          <h2 className="text-lg">Top findings</h2>
          <ol className="mt-3 divide-y divide-line">
            {s.summary.top_findings.slice(0, 5).map((f, i) => (
              <li key={i} className="grid grid-cols-[1.5rem_1fr] gap-x-3 gap-y-1 py-3 sm:grid-cols-[1.5rem_1fr_auto] sm:gap-x-4">
                <span className="num font-bold text-muted">{i + 1}</span>
                <span>{f.sentence}</span>
                <span className="num col-start-2 font-bold text-money sm:col-start-3 sm:text-right">{money(f.amount)}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {!s.empty && (
        <>
          <div className="mt-6"><Breakdown title="By type of problem" noun="type" items={s.breakdown.by_type} total={rec} /></div>
          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <Breakdown title="By shop" noun="shop" items={s.breakdown.by_shop} total={rec} />
            <Breakdown title="By vehicle" noun="vehicle" items={s.breakdown.by_vehicle} total={rec} />
          </div>
          {s.narratives.length > 0 && (
            <section className="mt-10" aria-label="What we found">
              <h2 className="text-xl">What we found</h2>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {s.narratives.map((n) => (
                  <div key={n.type} className="report-block rounded-lg border border-line bg-surface p-5">
                    <div className="flex items-baseline justify-between gap-4">
                      <h3 className="text-lg">{n.label}</h3>
                      <p className="num shrink-0 font-bold text-money">{money(n.amount)}</p>
                    </div>
                    <p className="text-sm text-muted">{n.count} {n.count === 1 ? "finding" : "findings"}</p>
                    <p className="mt-2">{n.paragraph}</p>
                  </div>
                ))}
              </div>
            </section>
          )}
          {s.appendix.length > 0 && <Findings rows={s.appendix} />}
        </>
      )}

      <section className="report-block mt-10 rounded-lg border border-line bg-surface p-6" aria-label="Next steps">
        <h2 className="text-xl">What to do next</h2>
        <p className="mt-3 max-w-prose whitespace-pre-line">{s.next_steps.text}</p>
      </section>

      {s.note && <p className="mt-6 max-w-prose text-sm text-muted">{s.note}</p>}
      {s.branding.footer && <p className="mt-6 text-sm text-muted">{s.branding.footer}</p>}
    </article>
  );
}
