import { money, shortDate, type Breakdown, type Snapshot } from "@/lib/api";

function Bars({ title, items }: { title: string; items: Breakdown[] }) {
  if (items.length === 0) return null;
  const max = Math.max(...items.map((i) => i.amount), 1);
  const top = items.reduce((a, b) => (b.amount > a.amount ? b : a));
  return (
    <section className="report-block mt-10" aria-label={title}>
      <h3 className="text-lg">{title}</h3>
      <ul className="mt-4 space-y-3">
        {items.map((i) => (
          <li key={i.label} className="grid grid-cols-[minmax(120px,220px)_1fr_auto] items-center gap-4">
            <span className="truncate">{i.label}</span>
            <span className="h-4 bg-sunken" aria-hidden><span className="block h-4" style={{ width: `${(i.amount / max) * 100}%`, background: i === top ? "var(--amber)" : "var(--primary)" }} /></span>
            <span className="num text-right">{money(i.amount)}</span>
          </li>
        ))}
      </ul>
      <table className="mt-4 w-full table-fixed border-collapse text-sm">
        <thead><tr><th scope="col" className="py-2 pr-4 text-left font-medium text-muted">{title.replace("By ", "").replace(/^./, (c) => c.toUpperCase())}</th><th scope="col" className="w-20 py-2 text-right font-medium text-muted">Flags</th><th scope="col" className="w-36 py-2 pl-4 text-right font-medium text-muted">Amount</th></tr></thead>
        <tbody>{items.map((i) => (
          <tr key={i.label} className="border-t border-line"><td className="py-2 pr-4">{i.label}</td><td className="num py-2 text-right">{i.count}</td><td className="num py-2 pl-4 text-right">{money(i.amount)}</td></tr>
        ))}</tbody>
      </table>
    </section>
  );
}

export default function ReportView({ snapshot: s }: { snapshot: Snapshot }) {
  const pct = Number.isFinite(s.summary.pct_of_spend) ? s.summary.pct_of_spend.toFixed(1) : "0";
  return (
    <article className="bg-surface px-6 py-8 sm:px-10 print:p-0">
      <header className="report-block">
        <p className="text-sm text-muted">Repair invoice audit</p>
        <h1 className="mt-1 text-2xl">{s.cover.client_name}</h1>
        <p className="mt-2 text-muted">
          <span className="num">{shortDate(s.cover.audit_date)}</span> · <span className="num">{s.cover.invoices_reviewed}</span> {s.cover.invoices_reviewed === 1 ? "invoice" : "invoices"} reviewed
        </p>
      </header>

      <section className="report-block mt-12" aria-label="Summary">
        {s.empty ? (
          <p className="max-w-prose text-xl font-bold" data-testid="headline">{s.summary.headline}</p>
        ) : (
          <>
            <p className="num text-hero font-bold text-money" data-testid="recoverable" style={{ boxShadow: "0 4px 0 0 var(--amber)", display: "inline-block", paddingBottom: 4 }}>{money(s.summary.recoverable)}</p>
            <p className="mt-4 max-w-prose text-lg" data-testid="sentence">
              likely recoverable, <span className="num">{pct}%</span> of <span className="num">{money(s.summary.total_spend)}</span> reviewed
            </p>
            {s.summary.top_findings.length > 0 && (
              <>
                <h2 className="mt-10 text-lg">Top findings</h2>
                <ul className="mt-3 max-w-prose divide-y divide-line">
                  {s.summary.top_findings.slice(0, 5).map((f, i) => (
                    <li key={i} className="flex items-baseline justify-between gap-6 py-3"><span>{f.sentence}</span><span className="num shrink-0 text-money">{money(f.amount)}</span></li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </section>

      {!s.empty && (
        <>
          <Bars title="By type" items={s.breakdown.by_type} />
          <Bars title="By shop" items={s.breakdown.by_shop} />
          <Bars title="By vehicle" items={s.breakdown.by_vehicle} />
          {s.narratives.length > 0 && (
            <section className="mt-12" aria-label="What we found">
              <h2 className="text-xl">What we found</h2>
              {s.narratives.map((n) => (
                <div key={n.type} className="report-block mt-6 max-w-prose">
                  <h3 className="text-lg">{n.label}</h3>
                  <p className="mt-1">{n.paragraph}</p>
                </div>
              ))}
            </section>
          )}
        </>
      )}

      <section className="report-block mt-12" aria-label="Next steps">
        <h2 className="text-xl">What to do next</h2>
        <p className="mt-3 max-w-prose whitespace-pre-line">{s.next_steps.text}</p>
      </section>

      {s.note && <p className="mt-10 max-w-prose text-sm text-muted">{s.note}</p>}

      {!s.empty && s.appendix.length > 0 && (
        <section className="mt-12" aria-label="Appendix">
          <h2 className="text-xl">Accepted findings</h2>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead><tr>
                {["Invoice", "Date", "Shop", "Unit", "What we found"].map((h) => <th key={h} scope="col" className="py-2 pr-4 text-left font-medium text-muted">{h}</th>)}
                <th scope="col" className="py-2 text-right font-medium text-muted">Amount</th>
              </tr></thead>
              <tbody>{s.appendix.map((a, i) => (
                <tr key={i} className="border-t border-line align-top">
                  <td className="num py-3 pr-4">{a.invoice_number}</td><td className="num py-3 pr-4 whitespace-nowrap">{shortDate(a.date)}</td>
                  <td className="py-3 pr-4">{a.shop}</td><td className="num py-3 pr-4">{a.unit}</td>
                  <td className="max-w-[48ch] py-3 pr-4">{a.reason}</td><td className="num py-3 text-right text-money">{money(a.amount)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
      )}
      {s.branding.footer && <p className="mt-10 text-sm text-muted">{s.branding.footer}</p>}
    </article>
  );
}
