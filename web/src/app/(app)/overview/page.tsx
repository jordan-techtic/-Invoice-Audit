"use client";

import Link from "next/link";
import { money, TYPE_NAME } from "@/lib/api";
import { useProgress } from "@/lib/progress";
import NeedClient from "@/components/NeedClient";
import { IconAlert, IconArrow, IconCheck } from "@/components/Icons";

export default function OverviewPage() {
  return <NeedClient>{(c) => <Overview name={c.name} />}</NeedClient>;
}

function Overview({ name }: { name: string }) {
  const p = useProgress();
  if (!p || p.loading) return <p className="text-muted" role="status">Loading the audit…</p>;
  if (p.error) return <p role="alert" className="text-danger">{p.error}</p>;
  const n = p.next;

  return (
    <div>
      <h1 className="text-xl">Audit overview</h1>
      <p className="mt-1 text-muted">Everything for {name} in one place. Follow the steps from left to right.</p>

      {/* The one thing to do now */}
      <section aria-label="Next step" className="card mt-6 border-l-[6px] border-l-amber" data-testid="overview-next">
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="max-w-prose">
            <p className="text-sm font-bold uppercase tracking-wide text-muted">{n.step === "finished" ? "Done" : "Your next step"}</p>
            <h2 className="mt-1 text-xl">{n.title}</h2>
            <p className="mt-2 text-muted">{n.text}</p>
          </div>
          <Link href={n.href} className="btn-primary btn-lg">{n.cta}<IconArrow /></Link>
        </div>
      </section>

      {p.filesFailed > 0 && (
        <p role="alert" className="mt-4 flex items-center gap-2 rounded-md border border-danger bg-surface px-4 py-3 text-danger">
          <IconAlert /> {p.filesFailed} {p.filesFailed === 1 ? "file" : "files"} could not be read.
          <Link href="/invoices" className="btn-link">Retry on the Invoices page</Link>
        </p>
      )}

      {/* Key figures */}
      <section aria-label="Key figures" className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3 [&>*]:min-w-0">
        <Kpi label="Invoices read" value={String(p.invoices)} sub={`${p.files} ${p.files === 1 ? "file" : "files"} uploaded${p.filesBusy ? `, ${p.filesBusy} still reading` : ""}`} href="/invoices" />
        <Kpi label="Spend reviewed" value={money(p.spend) || "$0.00"} sub="Sum of invoice totals" href="/invoices" />
        <Kpi label="Invoices to check" value={String(p.needReview)} sub={`${p.checked} checked, ${p.ready} ready`} href="/invoices?status=needs_review" tone={p.needReview ? "warn" : "ok"} />
        <Kpi label="Open flags" value={money(p.openTotal) || "$0.00"} sub={`${p.flagsOpen} of ${p.flags} flags still to review`} href="/review" tone={p.flagsOpen ? "warn" : undefined} money />
        <Kpi label="Confirmed recoverable" value={money(p.confirmedTotal) || "$0.00"} sub={`${p.dismissed} dismissed`} href="/review" tone="ok" money />
        <Kpi label="Reports" value={String(p.reports)} sub={p.latestReport ? `Latest: version ${p.latestReport.version}` : "None yet"} href="/reports" />
      </section>

      <div className="mt-8 grid gap-6 xl:grid-cols-[1fr_1fr]">
        {/* Checklist */}
        <section aria-label="Audit steps" className="card min-w-0">
          <h2 className="text-lg">Audit steps</h2>
          <ol className="mt-4 divide-y divide-line">
            {p.steps.map((s) => (
              <li key={s.key} className="flex items-center gap-4 py-3">
                <span aria-hidden className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full font-bold ${
                  s.state === "done" ? "bg-confirmed text-white" : s.state === "current" ? "bg-amber text-ink" : "bg-sunken text-muted"}`}>
                  {s.state === "done" ? <IconCheck /> : s.n}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={`font-bold ${s.state === "todo" ? "text-muted" : ""}`}>{s.label}</p>
                  <p className="text-sm text-muted">{s.state === "done" ? "Done · " : s.state === "current" ? "Now · " : ""}{s.detail}</p>
                </div>
                <Link href={s.href} className={s.state === "current" ? "btn-primary btn-sm" : "btn-secondary btn-sm"} aria-label={`Open step ${s.n}: ${s.label}`}>
                  {s.state === "done" ? "View" : "Open"}
                </Link>
              </li>
            ))}
          </ol>
        </section>

        {/* Findings by type */}
        <section aria-label="Findings by type" className="card min-w-0">
          <h2 className="text-lg">Findings by type</h2>
          {p.flags === 0 ? (
            <p className="mt-4 text-muted">{p.checksRun ? "The checks found nothing to flag." : "Run the checks to see findings here."}</p>
          ) : (
            <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[420px] border-collapse">
              <thead>
                <tr>
                  <th scope="col" className="th pl-0">Type</th>
                  <th scope="col" className="th text-right">Flags</th>
                  <th scope="col" className="th text-right">Open</th>
                  <th scope="col" className="th pr-0 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {p.byType.map((t) => (
                  <tr key={t.type} className="border-t border-line">
                    <td className="py-3 pr-4"><Link href={`/review?type=${t.type}&status=`} className="btn-link min-h-0">{TYPE_NAME[t.type] ?? t.type}</Link></td>
                    <td className="num py-3 text-right">{t.count}</td>
                    <td className="num py-3 text-right">{t.open || ""}</td>
                    <td className="num py-3 text-right text-money">{money(t.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
          <p className="mt-3 text-sm text-muted">Amounts exclude dismissed flags.</p>
        </section>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, href, tone, money: isMoney }: { label: string; value: string; sub: string; href: string; tone?: "ok" | "warn"; money?: boolean }) {
  return (
    <Link href={href} className="card block transition-colors hover:border-line-strong">
      <p className="kpi-label">{label}</p>
      <p className={`kpi-value ${isMoney ? "text-money" : ""} ${tone === "warn" && !isMoney ? "text-money" : ""} ${tone === "ok" && isMoney ? "text-confirmed" : ""}`}>{value}</p>
      <p className="mt-1 text-sm text-muted">{sub}</p>
    </Link>
  );
}
