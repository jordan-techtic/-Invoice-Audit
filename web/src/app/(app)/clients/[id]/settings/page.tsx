"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, dateTime, type Benchmark, type Client, type WarrantyRule } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useSession } from "@/lib/session";

export default function SettingsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, clients } = useSession();
  const client = clients.find((c) => c.id === id);
  const admin = user.role === "admin";
  if (!client) return <p>That client wasn&apos;t found. <Link href="/clients" className="text-primary underline underline-offset-4">Back to clients</Link></p>;
  return (
    <div>
      <Link href="/clients" className="text-primary underline underline-offset-4">Back to clients</Link>
      <h1 className="mt-3 text-xl">{client.name} settings</h1>
      <Warranty cid={id} admin={admin} />
      <Benchmarks cid={id} admin={admin} />
      {admin && <AuditAndData client={client} />}
    </div>
  );
}

function Warranty({ cid, admin }: { cid: string; admin: boolean }) {
  const [rules, setRules] = useState<WarrantyRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ vmrs_code: "", component: "", months: "", miles: "" });
  const load = useCallback(() => api.warrantyRules(cid).then(setRules).catch((e) => setError(e.message)), [cid]);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); await load(); } catch (e) { setError(e instanceof Error ? e.message : "That change didn't save. Try again."); await load(); }
  }
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  return (
    <section className="mt-10" aria-labelledby="warranty-h">
      <h2 id="warranty-h" className="text-lg">Warranty rules</h2>
      <p className="mt-1 max-w-prose text-muted">
        {admin ? "A repair on a part inside these limits may still be covered by warranty. Changes save when you leave a field." : "These rules are set by an admin. You can read them here but not change them."}
      </p>
      {error && <p role="alert" className="mt-3 text-danger">{error}</p>}
      {rules && rules.length === 0 && <p className="mt-4 text-lg">No warranty rules yet.{admin ? " Add one below." : ""}</p>}
      {rules && rules.length > 0 && (
        <div className="mt-4 overflow-x-auto bg-surface">
          <table className="w-full min-w-[640px] border-collapse">
            <thead><tr>
              <th className="th" scope="col">Component</th><th className="th" scope="col">Job type code</th>
              <th className="th text-right" scope="col">Months</th><th className="th text-right" scope="col">Miles</th>
              {admin && <th className="th" scope="col"><span className="sr-only">Action</span></th>}
            </tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className="tr">
                  {admin ? (
                    <>
                      <td className="td"><Cell label={`Component for ${r.component}`} value={r.component} onSave={(v) => act(() => api.updateWarrantyRule(cid, r.id, { component: v }))} /></td>
                      <td className="td num">{r.vmrs_code}</td>
                      <td className="td text-right"><Cell num label={`Months for ${r.component}`} value={String(r.months)} onSave={(v) => act(() => api.updateWarrantyRule(cid, r.id, { months: Number(v) }))} /></td>
                      <td className="td text-right"><Cell num label={`Miles for ${r.component}`} value={r.miles == null ? "" : String(r.miles)} onSave={(v) => act(() => api.updateWarrantyRule(cid, r.id, { miles: num(v) }))} /></td>
                      <td className="td text-right"><button className="btn-secondary" aria-label={`Delete rule for ${r.component}`} onClick={() => act(() => api.deleteWarrantyRule(cid, r.id))}>Delete</button></td>
                    </>
                  ) : (
                    <>
                      <td className="td font-medium">{r.component}</td><td className="td num">{r.vmrs_code}</td>
                      <td className="td num text-right">{r.months}</td><td className="td num text-right">{r.miles == null ? "No limit" : r.miles.toLocaleString("en-US")}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {admin && (
        <form className="mt-6 flex flex-wrap items-end gap-4" noValidate onSubmit={(e) => {
          e.preventDefault();
          act(async () => {
            await api.addWarrantyRule(cid, { vmrs_code: draft.vmrs_code.trim(), component: draft.component.trim(), months: Number(draft.months), miles: num(draft.miles) });
            setDraft({ vmrs_code: "", component: "", months: "", miles: "" });
          });
        }}>
          {([["component", "Component", "w-[220px]"], ["vmrs_code", "Job type code", "w-[160px]"], ["months", "Months", "w-[110px]"], ["miles", "Miles (optional)", "w-[150px]"]] as const).map(([k, l, w]) => (
            <div key={k}>
              <label htmlFor={`wr-${k}`} className="mb-1 block text-sm font-medium">{l}</label>
              <input id={`wr-${k}`} className={`field ${w}`} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
            </div>
          ))}
          <button type="submit" className="btn-secondary" disabled={!draft.component.trim() || !draft.vmrs_code.trim() || !draft.months.trim()}>Add rule</button>
        </form>
      )}
    </section>
  );
}

function Cell({ value, label, onSave, num }: { value: string; label: string; onSave: (v: string) => void; num?: boolean }) {
  const [v, setV] = useState(value);
  const [editing, setEditing] = useState(false);
  return (
    <input aria-label={label} className={`field min-h-[40px] ${num ? "num w-[110px] text-right" : ""}`} value={editing ? v : value}
      onFocus={() => { setV(value); setEditing(true); }} onChange={(e) => setV(e.target.value)}
      onBlur={() => { setEditing(false); if (v !== value) onSave(v); }}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
  );
}

function Benchmarks({ cid, admin }: { cid: string; admin: boolean }) {
  const [rows, setRows] = useState<Benchmark[] | null>(null);
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const load = useCallback(() => api.benchmarks(cid).then(setRows).catch((e) => setMsg({ text: e.message, error: true })), [cid]);
  useEffect(() => { load(); }, [load]);

  async function pick(f: File | undefined) {
    if (!f) return;
    setMsg(null);
    try {
      const r = await api.importBenchmarks(cid, f);
      setMsg({ text: `Imported ${r.imported} ${r.imported === 1 ? "benchmark" : "benchmarks"}.` });
      await load();
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : "The import didn't work. Check the file and try again.", error: true }); }
  }

  return (
    <section className="mt-14" aria-labelledby="bench-h">
      <h2 id="bench-h" className="text-lg">Labour benchmarks</h2>
      <p className="mt-1 max-w-prose text-muted">Typical hours for each job type. Labour above these hours is flagged.</p>
      {admin && (
        <div className="mt-4">
          <label htmlFor="bench-file" className="mb-1 block font-medium">Import benchmarks (CSV)</label>
          <input id="bench-file" type="file" accept=".csv,text/csv" className="block text-base" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
          <p className="mt-1 text-sm text-muted">Columns: vmrs_code, benchmark_hours</p>
        </div>
      )}
      <p role="status" className={`mt-3 ${msg?.error ? "text-danger" : "text-confirmed"}`}>{msg?.text}</p>
      {rows && rows.length === 0 && <p className="mt-4 text-lg">No benchmarks yet.{admin ? " Import a CSV to add them." : ""}</p>}
      {rows && rows.length > 0 && (
        <div className="mt-4 overflow-x-auto bg-surface">
          <table className="w-full min-w-[640px] border-collapse">
            <thead><tr>
              <th className="th" scope="col">Code</th><th className="th" scope="col">Job type</th>
              <th className="th text-right" scope="col">Typical hours</th><th className="th" scope="col">Source</th><th className="th text-right" scope="col">Samples</th>
            </tr></thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.vmrs_code} className="tr">
                  <td className="td num">{b.vmrs_code}</td><td className="td">{b.component}</td>
                  <td className="td num text-right">{b.hours.toFixed(1)}</td><td className="td">{b.source}</td>
                  <td className="td num text-right">{b.sample_count ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AuditAndData({ client }: { client: { id: string; name: string } }) {
  const router = useRouter();
  const { refreshClients } = useSession();
  const cid = client.id;
  const [info, setInfo] = useState<Client | null>(null);
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const [dialog, setDialog] = useState<null | "raw" | "all">(null);
  const load = useCallback(() => api.client(cid).then(setInfo).catch(() => undefined), [cid]);
  useEffect(() => { load(); }, [load]);

  async function complete() {
    setMsg(null);
    try { await api.auditComplete(cid); await load(); setMsg({ text: "Audit marked complete." }); }
    catch (e) { setMsg({ text: e instanceof Error ? e.message : "Couldn't mark the audit complete.", error: true }); }
  }

  return (
    <section className="mt-14" aria-labelledby="audit-h">
      <h2 id="audit-h" className="text-lg">Audit and data</h2>
      <p className="mt-3" data-testid="audit-state">Audit marked complete: <span className="num font-medium">{info?.audit_completed_at ? dateTime(info.audit_completed_at) : "not yet"}</span></p>
      <p className="mt-1 max-w-prose text-muted">Raw invoice files are deleted automatically <span className="num">{info?.raw_retention_days ?? "a set number of"}</span> days after the audit is marked complete.</p>
      {info?.raw_files_deleted_at && <p className="mt-1 font-medium">Raw files deleted on <span className="num">{dateTime(info.raw_files_deleted_at)}</span></p>}
      {msg && <p role={msg.error ? "alert" : "status"} className={`mt-3 ${msg.error ? "text-danger" : "text-confirmed"}`}>{msg.text}</p>}
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-secondary" onClick={complete}>Mark audit complete</button>
        <button className="btn-secondary" onClick={() => setDialog("raw")}>Delete raw files now</button>
      </div>

      <div className="mt-10 max-w-prose border border-danger p-5">
        <h3 className="text-lg text-danger">Delete everything for this client</h3>
        <p className="mt-1">This removes the client with all its invoices, flags and reports. It cannot be undone.</p>
        <button className="btn-secondary mt-4 border-danger text-danger" onClick={() => setDialog("all")}>Delete everything for this client</button>
      </div>

      <ConfirmDialog open={dialog === "raw"} title="Delete raw files now" confirmWord="DELETE" actionLabel="Delete raw files"
        body={`This deletes the original invoice files and page images for ${client.name}. Extracted data and reports are kept. This cannot be undone.`}
        onClose={() => setDialog(null)} onConfirm={async () => { await api.deleteRaw(cid); setDialog(null); await load(); setMsg({ text: "Raw files deleted." }); }} />
      <ConfirmDialog open={dialog === "all"} title="Delete everything for this client" confirmWord={client.name} actionLabel="Delete everything"
        body={`This deletes ${client.name} and every invoice, flag and report that belongs to it. This cannot be undone.`}
        onClose={() => setDialog(null)} onConfirm={async () => { await api.deleteEverything(cid, client.name); await refreshClients(); router.push("/clients"); }} />
    </section>
  );
}
