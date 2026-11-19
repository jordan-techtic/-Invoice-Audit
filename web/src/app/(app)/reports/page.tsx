"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, dateTime, money, type ReportItem } from "@/lib/api";
import { useSession } from "@/lib/session";
import NeedClient from "@/components/NeedClient";

export default function ReportsPage() {
  return <NeedClient>{(c) => <Reports cid={c.id} />}</NeedClient>;
}

function stateOf(r: ReportItem) { return r.revoked ? "Link revoked" : r.expired ? "Link expired" : "Shared"; }

function Reports({ cid }: { cid: string }) {
  const { user } = useSession();
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

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl">Reports</h1>
          <p className="mt-1 max-w-prose text-muted">A report is a frozen copy of what you confirmed, with a link you can share.</p>
        </div>
        <button className="btn-primary" onClick={openPanel} aria-expanded={panel}>Create report</button>
      </div>

      {panel && (
        <form onSubmit={create} className="mt-6 max-w-[720px] border border-line-strong bg-surface p-5">
          <label htmlFor="days" className="mb-1 block text-sm font-medium">Link expires after</label>
          <select id="days" className="field max-w-[200px]" value={days} onChange={(e) => setDays(e.target.value)}>
            {[7, 14, 30, 60].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
          <label htmlFor="offer" className="mb-1 mt-4 block text-sm font-medium">Our ongoing-service offer</label>
          <textarea id="offer" className="field py-2" rows={5} value={offer} onChange={(e) => setOffer(e.target.value)} />
          {problem && (
            <p role="alert" className="mt-3 text-danger">{problem.text}{problem.conflict && <> <Link href="/review" className="font-medium text-primary underline underline-offset-4">Review flags</Link></>}</p>
          )}
          <div className="mt-4 flex gap-3">
            <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Creating…" : "Create report"}</button>
            <button type="button" className="btn-secondary" onClick={() => setPanel(false)}>Cancel</button>
          </div>
        </form>
      )}
      {!panel && problem && <p role="alert" className="mt-4 text-danger">{problem.text}</p>}

      {rows && rows.length === 0 && <p className="mt-8 max-w-prose text-lg">No reports yet. Review your flags, then create the first report.</p>}
      {rows && rows.length > 0 && (
        <div className="mt-8 overflow-x-auto bg-surface">
          <table className="w-full min-w-[960px] border-collapse">
            <caption className="sr-only">Reports</caption>
            <thead><tr>
              <th scope="col" className="th">Version</th><th scope="col" className="th">Created</th>
              <th scope="col" className="th text-right">Recoverable</th><th scope="col" className="th text-right">Flags</th>
              <th scope="col" className="th">Link expires</th><th scope="col" className="th">Status</th><th scope="col" className="th"><span className="sr-only">Actions</span></th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="tr align-top">
                  <td className="td num whitespace-nowrap font-medium">Version {r.version}</td>
                  <td className="td whitespace-nowrap">{dateTime(r.generated_at)}</td>
                  <td className="td num text-right text-money">{money(r.recoverable)}</td>
                  <td className="td num text-right">{r.flag_count}</td>
                  <td className="td whitespace-nowrap">{r.expires_at ? dateTime(r.expires_at) : "No expiry"}</td>
                  <td className={`td whitespace-nowrap font-medium ${r.revoked || r.expired ? "text-dismissed" : "text-confirmed"}`}>{stateOf(r)}</td>
                  <td className="td">
                    <div className="flex flex-wrap items-center justify-end gap-x-5 gap-y-1">
                      <Link href={`/reports/${r.id}`} className="font-medium text-primary underline underline-offset-4">Open dashboard</Link>
                      <a href={apiUrl(`/clients/${cid}/reports/${r.id}/pdf`)} download className="font-medium text-primary underline underline-offset-4">Download PDF</a>
                      {r.share_url && !r.revoked && !r.expired && <button className="min-h-[44px] font-medium text-primary underline underline-offset-4" onClick={() => copy(r)}>{copied === r.id ? "Link copied" : "Copy link"}</button>}
                      {user.role === "admin" && !r.revoked && (
                        confirm === r.id ? (
                          <span className="inline-flex items-center gap-3">
                            <span className="text-sm">Anyone with the link loses access.</span>
                            <button className="btn-secondary" onClick={() => revoke(r.id)}>Revoke link</button>
                            <button className="min-h-[44px] underline underline-offset-4" onClick={() => setConfirm(null)}>Cancel</button>
                          </span>
                        ) : <button className="min-h-[44px] font-medium text-primary underline underline-offset-4" onClick={() => setConfirm(r.id)}>Revoke link</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
