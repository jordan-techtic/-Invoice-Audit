"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, dateTime, money, type ReportItem } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useProgress } from "@/lib/progress";
import { copyText, shareLink } from "@/lib/clipboard";
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
  const confirmDialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ text: string; conflict?: boolean } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [manual, setManual] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const load = useCallback(() => api.reports(cid).then(setRows).catch((e) => setProblem({ text: e instanceof Error ? e.message : "Couldn't load reports." })), [cid]);
  useEffect(() => { load(); }, [load]);

  function ask() { setProblem(null); setDone(null); confirmDialog.current?.showModal(); }

  // Creating uses the standard settings (30-day link, default offer text). There is nothing to fill in.
  async function create() {
    if (busy) return;
    confirmDialog.current?.close();
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      const { default_offer_text } = await api.reportSettings(cid);
      const r = await api.createReport(cid, { expires_days: 30, offer_text: default_offer_text });
      await load();
      prog?.refresh();
      setDone(`Report version ${r.version} created.`);
    } catch (err) {
      const status = (err as { status?: number }).status;
      setProblem({ text: err instanceof Error ? err.message : "Couldn't create the report. Try again.", conflict: status === 409 });
    } finally { setBusy(false); }
  }

  async function copy(r: ReportItem) {
    if (!r.share_url) return;
    const link = shareLink(r.share_url);
    if (await copyText(link)) { setManual(null); setCopied(r.id); }
    // The browser refused (some locked-down browsers do): show the link so it can be copied by hand.
    else { setCopied(null); setManual(link); }
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
      <div className="flex flex-wrap items-center gap-2 xl:justify-end">
        <Link href={`/reports/${r.id}`} className={`btn-primary${sz}`}>Open report</Link>
        <a href={apiUrl(`/clients/${cid}/reports/${r.id}/pdf`)} download className={`btn-secondary${sz}`}>Download PDF</a>
        {r.share_url && live(r) && <button className={`btn-secondary${sz} min-w-[112px]`} onClick={() => copy(r)}>{copied === r.id ? "Link copied ✓" : "Copy link"}</button>}
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
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div>
          <p className="eyebrow">Step 3 of 3</p>
          <h1 className="mt-1 text-xl">Create and share the report</h1>
          <p className="mt-1 max-w-prose text-muted">A report is a frozen copy of the flags you accepted. Share its link with the client or send the PDF.</p>
        </div>
        <button className="btn-primary btn-lg w-full sm:w-auto" onClick={ask} disabled={busy}>{latest ? "Create report (new version)" : "Create report"}</button>
      </div>

      {openFlags > 0 && (
        <p className="mt-6 flex flex-wrap items-center gap-3 rounded-md border border-amber bg-amber-soft px-4 py-3">
          <span><b>{openFlags} {openFlags === 1 ? "flag is" : "flags are"} still open.</b> Review them first so the report is complete.</span>
          <Link href="/review" className="btn-secondary btn-sm">Review flags</Link>
        </p>
      )}

      {manual && (
        <div role="status" className="mt-6 rounded-lg border border-line-strong bg-surface p-4">
          <label htmlFor="manual-link" className="block font-medium">Your browser blocked copying. Copy this link by hand:</label>
          <input id="manual-link" readOnly value={manual} className="field mt-2" autoFocus onFocus={(e) => e.currentTarget.select()} />
        </div>
      )}
      {done && <p role="status" className="mt-6 font-medium text-confirmed">{done}</p>}
      {problem && (
        <p role="alert" className="mt-6 text-danger">{problem.text}{problem.conflict && <> <Link href="/review" className="btn-link">Review flags</Link></>}</p>
      )}

      {!rows && !problem && <p className="mt-6 text-muted" role="status">Loading reports…</p>}
      {rows && rows.length === 0 && (
        <div className="card mt-8 max-w-prose">
          <p className="text-lg font-bold">No reports yet.</p>
          <p className="mt-1 text-muted">When every flag is reviewed, create the first report.</p>
          <button className="btn-primary mt-4" onClick={ask} disabled={busy}>Create report<IconArrow /></button>
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
              {latest.out_of_date && <><dt className="text-muted">Decisions</dt><dd className="font-medium text-danger">Out of date: a flag decision changed after this report was created. Create a new version.</dd></>}
            </dl>
          </div>
          <div className="mt-5">{actions(latest, true)}</div>
        </section>
      )}

      {rows && rows.length > 0 && (
        <>
          <h2 className="mt-10 text-lg">All versions ({rows.length})</h2>
          <ul className="mt-3 divide-y divide-line rounded-lg border border-line bg-surface" data-testid="report-versions">
            {[...rows].sort((a, b) => b.version - a.version).map((r) => (
              <li key={r.id} className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
                <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                  <div>
                    <dt className="text-sm text-muted">Version</dt>
                    <dd className="num font-bold">Version {r.version}</dd>
                    <dd className="text-sm text-muted">{dateTime(r.generated_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-muted">Recoverable</dt>
                    <dd className="num font-bold text-money">{money(r.recoverable)}</dd>
                    <dd className="text-sm text-muted">{r.flag_count} {r.flag_count === 1 ? "finding" : "findings"}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-sm text-muted">Share link</dt>
                    <dd className={`font-medium ${live(r) ? "text-confirmed" : "text-dismissed"}`}>{stateOf(r)}</dd>
                    <dd className="text-sm text-muted">{r.expires_at ? `Expires ${dateTime(r.expires_at)}` : "No expiry"}</dd>
                  </div>
                </dl>
                {actions(r)}
              </li>
            ))}
          </ul>
        </>
      )}
      <dialog ref={confirmDialog} aria-labelledby="new-report-title"
        onClick={(e) => { if (e.target === confirmDialog.current) confirmDialog.current?.close(); }}
        className="w-[min(440px,92vw)] rounded-lg border border-line-strong bg-surface p-0 text-ink backdrop:bg-ink/40">
        <div className="p-6">
          <h2 id="new-report-title" className="text-lg">New report</h2>
          <p className="mt-2">
            It will include <b className="text-money">{money(prog?.confirmedTotal ?? 0)}</b> of accepted findings from <b>{prog?.invoices ?? 0}</b> invoices.
          </p>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button type="button" className="btn-secondary" onClick={() => confirmDialog.current?.close()}>Cancel</button>
            <button type="button" className="btn-primary" onClick={create}>Create report</button>
          </div>
        </div>
      </dialog>

      {busy && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(27, 43, 58, 0.55)" }} role="alertdialog" aria-modal="true" aria-labelledby="creating-title" aria-describedby="creating-text">
          <div className="w-[min(380px,92vw)] rounded-lg border border-line-strong bg-surface p-8 text-center shadow-lg">
            <span aria-hidden className="mx-auto block h-12 w-12 animate-spin rounded-full border-4 border-sunken border-t-primary" />
            <p id="creating-title" role="status" className="mt-5 text-lg font-bold">Creating your report…</p>
            <p id="creating-text" className="mt-1 text-muted">This takes a few seconds. Please keep this page open.</p>
          </div>
        </div>
      )}
    </div>
  );
}
