"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, dateTime, money, type ReportItem } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useProgress } from "@/lib/progress";
import NeedClient from "@/components/NeedClient";
import { IconArrow } from "@/components/Icons";

export default function ReportsPage() {
  return <NeedClient>{(c) => <Reports cid={c.id} />}</NeedClient>;
}

function stateOf(r: ReportItem) { return r.revoked ? "Link revoked" : r.expired ? "Link expired" : "Link active"; }
const live = (r: ReportItem) => !r.revoked && !r.expired;

function Reports({ cid }: { cid: string }) {
  const { user } = useSession();
  const prog = useProgress();
  const [rows, setRows] = useState<ReportItem[] | null>(null);
  const [panel, setPanel] = useState(() => typeof window !== "undefined" && new URLSearchParams(window.location.search).get("create") === "1");
  const startOpen = useRef(panel);
  const [days, setDays] = useState("30");
  const [offer, setOffer] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ text: string; conflict?: boolean } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const load = useCallback(() => api.reports(cid).then(setRows).catch((e) => setProblem({ text: e instanceof Error ? e.message : "Couldn't load reports." })), [cid]);
  useEffect(() => { load(); }, [load]);

  function openPanel() {
    setPanel(true);
    setProblem(null);
    api.reportSettings(cid).then((s) => setOffer(s.default_offer_text)).catch(() => undefined);
  }
  useEffect(() => {
    if (startOpen.current) api.reportSettings(cid).then((s) => setOffer(s.default_offer_text)).catch(() => undefined);
  }, [cid]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.createReport(cid, { expires_days: Number(days), offer_text: offer });
      setPanel(false);
      await load();
      prog?.refresh();
    } catch (err) {
      const status = (err as { status?: number }).status;
      setProblem({ text: err instanceof Error ? err.message : "Couldn't create the report. Try again.", conflict: status === 409 });
    } finally { setBusy(false); }
  }

  async function copy(r: ReportItem) {
    if (!r.share_url) return;
    try { await navigator.clipboard.writeText(r.share_url); } catch { /* clipboard may be blocked */ }
    setCopied(r.id);
  }

  async function revoke(id: string) {
    try { await api.revokeReport(cid, id); setConfirm(null); await load(); }
    catch (err) { setProblem({ text: err instanceof Error ? err.message : "Couldn't revoke the link." }); }
  }

  const latest = rows?.reduce<ReportItem | null>((m, r) => (!m || r.version > m.version ? r : m), null) ?? null;
  const openFlags = prog?.flagsOpen ?? 0;

  function actions(r: ReportItem, big = false) {
    const sz = big ? "" : " btn-sm";
    return (
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Link href={`/reports/${r.id}`} className={`btn-primary${sz}`}>Open dashboard</Link>
        <a href={apiUrl(`/clients/${cid}/reports/${r.id}/pdf`)} download className={`btn-secondary${sz}`}>Download PDF</a>
        {r.share_url && live(r) && <button className={`btn-secondary${sz} min-w-[120px]`} onClick={() => copy(r)}>{copied === r.id ? "Link copied ✓" : "Copy link"}</button>}
        {user.role === "admin" && !r.revoked && (
          confirm === r.id ? (
            <span className="inline-flex flex-wrap items-center gap-2">
              <span className="text-sm">Anyone with the link loses access.</span>
              <button className={`btn-danger${sz}`} onClick={() => revoke(r.id)}>Yes, revoke</button>
              <button className={`btn-secondary${sz}`} onClick={() => setConfirm(null)}>Cancel</button>
            </span>
          ) : <button className={`btn-danger${sz}`} onClick={() => setConfirm(r.id)}>Revoke link</button>
        )}
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl">Step 5 · Create and share the report</h1>
          <p className="mt-1 max-w-prose text-muted">A report is a frozen copy of the flags you accepted. Share its link with the client or send the PDF.</p>
        </div>
        {!panel && <button className={latest ? "btn-secondary" : "btn-primary btn-lg"} onClick={openPanel} aria-expanded={panel}>{latest ? "Create report (new version)" : "Create report"}</button>}
      </div>

      {openFlags > 0 && (
        <p className="mt-6 flex flex-wrap items-center gap-3 rounded-md border border-amber bg-amber-soft px-4 py-3">
          <span><b>{openFlags} {openFlags === 1 ? "flag is" : "flags are"} still open.</b> Review them first so the report is complete.</span>
          <Link href="/review" className="btn-secondary btn-sm">Review flags</Link>
        </p>
      )}

      {panel && (
        <form onSubmit={create} className="card mt-6 max-w-[720px]">
          <h2 className="text-lg">New report</h2>
          {prog && (
            <p className="mt-1 text-muted">It will include <b className="text-money">{money(prog.confirmedTotal)}</b> of accepted findings from <b>{prog.invoices}</b> invoices.</p>
          )}
          <label htmlFor="days" className="mb-1 mt-4 block text-sm font-medium">Share link expires after</label>
          <select id="days" className="field max-w-[200px]" value={days} onChange={(e) => setDays(e.target.value)}>
            {[7, 14, 30, 60].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
          <label htmlFor="offer" className="mb-1 mt-4 block text-sm font-medium">Our ongoing-service offer (shown at the end of the report)</label>
          <textarea id="offer" className="field py-2" rows={5} value={offer} onChange={(e) => setOffer(e.target.value)} />
          {problem && (
            <p role="alert" className="mt-3 text-danger">{problem.text}{problem.conflict && <> <Link href="/review" className="btn-link">Review flags</Link></>}</p>
          )}
          <div className="mt-5 flex gap-3">
            <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Creating…" : "Create report"}</button>
            <button type="button" className="btn-secondary" onClick={() => setPanel(false)}>Cancel</button>
          </div>
        </form>
      )}
      {!panel && problem && <p role="alert" className="mt-4 text-danger">{problem.text}</p>}

      {!rows && !problem && <p className="mt-6 text-muted" role="status">Loading reports…</p>}
      {rows && rows.length === 0 && !panel && (
        <div className="card mt-8 max-w-prose">
          <p className="text-lg font-bold">No reports yet.</p>
          <p className="mt-1 text-muted">When every flag is reviewed, create the first report.</p>
          <button className="btn-primary mt-4" onClick={openPanel}>Create report<IconArrow /></button>
        </div>
      )}

      {latest && (
        <section aria-label="Latest report" className="card mt-8 border-l-[6px] border-l-confirmed">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="kpi-label">Latest report · version {latest.version}</p>
              <p className="num mt-1 text-2xl font-bold text-money">{money(latest.recoverable)}</p>
              <p className="text-muted">likely recoverable from {latest.flag_count} accepted {latest.flag_count === 1 ? "finding" : "findings"}</p>
            </div>
            <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
              <dt className="text-muted">Created</dt><dd>{dateTime(latest.generated_at)}</dd>
              <dt className="text-muted">Link expires</dt><dd>{latest.expires_at ? dateTime(latest.expires_at) : "No expiry"}</dd>
              <dt className="text-muted">Status</dt><dd className={`font-medium ${live(latest) ? "text-confirmed" : "text-dismissed"}`}>{stateOf(latest)}</dd>
            </dl>
          </div>
          <div className="mt-5">{actions(latest, true)}</div>
        </section>
      )}

      {rows && rows.length > 0 && (
        <>
          <h2 className="mt-10 text-lg">All versions ({rows.length})</h2>
          <div className="mt-3 overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[980px] border-collapse">
              <caption className="sr-only">Reports</caption>
              <thead><tr>
                <th scope="col" className="th">Version</th><th scope="col" className="th">Created</th>
                <th scope="col" className="th text-right">Recoverable</th><th scope="col" className="th text-right">Findings</th>
                <th scope="col" className="th">Link expires</th><th scope="col" className="th">Status</th><th scope="col" className="th"><span className="sr-only">Actions</span></th>
              </tr></thead>
              <tbody>
                {[...rows].sort((a, b) => b.version - a.version).map((r) => (
                  <tr key={r.id} className="tr">
                    <td className="td num whitespace-nowrap font-medium">Version {r.version}</td>
                    <td className="td whitespace-nowrap">{dateTime(r.generated_at)}</td>
                    <td className="td num text-right text-money">{money(r.recoverable)}</td>
                    <td className="td num text-right">{r.flag_count}</td>
                    <td className="td whitespace-nowrap">{r.expires_at ? dateTime(r.expires_at) : "No expiry"}</td>
                    <td className={`td whitespace-nowrap font-medium ${live(r) ? "text-confirmed" : "text-dismissed"}`}>{stateOf(r)}</td>
                    <td className="td py-2">{actions(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
