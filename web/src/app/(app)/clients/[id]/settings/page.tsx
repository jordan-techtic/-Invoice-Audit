"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, dateTime, type Benchmark, type Client, type Covers, type WarrantyRule } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import ImportPanel from "@/components/settings/ImportPanel";
import ThresholdsSection from "@/components/settings/ThresholdsSection";
import JobCodeList from "@/components/settings/JobCodeList";
import VehiclesSection from "@/components/settings/VehiclesSection";
import { useProgress } from "@/lib/progress";
import { useSession } from "@/lib/session";

const COVERS: Record<Covers, string> = { parts: "Parts only", "parts+labour": "Parts and labour" };

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
      <nav aria-label="On this page" className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
        {[["thresholds", "Thresholds"], ["warranty", "Warranty rules"], ["vehicles", "Vehicles"], ["benchmarks", "Labour benchmarks"], ...(admin ? [["audit", "Audit and data"]] : [])].map(([h, l]) => (
          <a key={h} href={`#${h}`} className="btn-link">{l}</a>
        ))}
      </nav>
      <h2 className="mt-8 text-lg">Reference data</h2>
      <p className="mt-1 max-w-prose text-muted">What the audit checks compare invoices against. Type values in, or import them from files. Changes apply the next time the checks run, which happens on its own when you open Review flags.</p>
      <JobCodeList cid={id} />
      <ThresholdsSection cid={id} admin={admin} />
      <Warranty cid={id} admin={admin} />
      <VehiclesSection cid={id} admin={admin} />
      <Benchmarks cid={id} admin={admin} />
      {admin && <AuditAndData client={client} />}
    </div>
  );
}

function Warranty({ cid, admin }: { cid: string; admin: boolean }) {
  const [rules, setRules] = useState<WarrantyRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ vmrs_code: string; component: string; months: string; miles: string; covers: Covers }>({ vmrs_code: "", component: "", months: "", miles: "", covers: "parts+labour" });
  const [replace, setReplace] = useState(false);
  const [clearAll, setClearAll] = useState(false);
  const [askDelete, setAskDelete] = useState<WarrantyRule | null>(null);
  const markStale = useProgress()?.markChecksStale;
  const load = useCallback(() => api.warrantyRules(cid).then(setRules).catch((e) => setError(e.message)), [cid]);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); await load(); } catch (e) { setError(e instanceof Error ? e.message : "That change didn't save. Try again."); await load(); }
  }
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  async function importFile(f: File) {
    const r = await api.importWarranty(cid, f, replace ? "replace" : "merge");
    await load();
    markStale?.(cid);
    const bits = [`${r.added} added`, `${r.updated} updated`, ...(r.merged.length ? [`${r.merged.length} merged into a rule with the same job code`] : []), ...(r.skipped.length ? [`${r.skipped.length} skipped`] : [])];
    return {
      message: `Read ${r.rows} ${r.rows === 1 ? "row" : "rows"}: ${bits.join(", ")}. ${r.total_rules} ${r.total_rules === 1 ? "rule" : "rules"} now.`,
      details: [
        { title: "Skipped, so add these by hand", items: r.skipped.map((s) => `Row ${s.row} (${s.component}): ${s.reason}`) },
        { title: "Merged", items: r.merged.map((m) => `Row ${m.row} (${m.component}) joined ${m.into}: ${m.reason}`) },
      ],
    };
  }

  return (
    <section className="mt-14" aria-labelledby="warranty-h" id="warranty">
      <h3 id="warranty-h" className="text-lg">Warranty rules</h3>
      <p className="mt-1 max-w-prose text-muted">
        {admin ? "A repair on a part inside these limits may still be covered by warranty. Changes save when you leave a field." : "These rules are set by an admin. You can read them here but not change them."}
      </p>
      {admin && (
        <ImportPanel testId="warranty-import" label="Import warranty rules (CSV)" onImport={importFile}
          help={<>Columns: <b>component</b>, <b>warranty_months</b>, <b>warranty_miles</b> (leave blank or write unlimited for no limit), <b>covers</b> (parts or parts+labour). Optional: <b>description</b> (helps find the job code), <b>vmrs_code</b>. Each component is matched to the job code the app gives invoice lines with that name.</>}>
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" className="h-5 w-5" style={{ accentColor: "var(--primary)" }} checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            Replace the whole list instead of adding to it
          </label>
        </ImportPanel>
      )}
      {error && <p role="alert" className="mt-3 text-danger">{error}</p>}
      {admin && rules && rules.length > 0 && (
        <div className="mt-4 flex justify-end"><button className="btn-danger btn-sm" onClick={() => setClearAll(true)}>Remove all rules</button></div>
      )}
      <ConfirmDialog open={clearAll} danger title={`Remove all ${rules?.length ?? 0} warranty rules?`} confirmWord="REMOVE" actionLabel="Remove all"
        body="This empties the warranty list, so no repair is checked against a warranty until you import or add rules again."
        onClose={() => setClearAll(false)} onConfirm={async () => { await api.deleteAllWarranty(cid); setClearAll(false); markStale?.(cid); await load(); }} />
      <ConfirmDialog open={askDelete !== null} danger title={`Delete the rule for ${askDelete?.component ?? "this component"}?`} actionLabel="Delete rule"
        body="Repairs of this component will no longer be checked against a warranty until you add the rule again."
        onClose={() => setAskDelete(null)} onConfirm={async () => { const r = askDelete; setAskDelete(null); if (r) await act(() => api.deleteWarrantyRule(cid, r.id)); }} />
      {rules && rules.length === 0 && <p className="mt-4 text-lg">No warranty rules yet.{admin ? " Import a CSV above, or add one below." : ""}</p>}
      {rules && rules.length > 0 && (
        <div className="mt-4 overflow-x-auto bg-surface">
          <table className="w-full min-w-[640px] border-collapse">
            <thead><tr>
              <th className="th" scope="col">Component</th><th className="th" scope="col">Job type code</th>
              <th className="th text-right" scope="col">Months</th><th className="th text-right" scope="col">Miles</th><th className="th" scope="col">Covers</th>
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
                      <td className="td">
                        <select aria-label={`Covers for ${r.component}`} className="field min-h-[40px] w-[170px]" value={r.covers}
                          onChange={(e) => act(() => api.updateWarrantyRule(cid, r.id, { covers: e.target.value as Covers }))}>
                          {(Object.keys(COVERS) as Covers[]).map((c) => <option key={c} value={c}>{COVERS[c]}</option>)}
                        </select>
                      </td>
                      <td className="td text-right"><button className="btn-secondary" aria-label={`Delete rule for ${r.component}`} onClick={() => setAskDelete(r)}>Delete</button></td>
                    </>
                  ) : (
                    <>
                      <td className="td font-medium">{r.component}</td><td className="td num">{r.vmrs_code}</td>
                      <td className="td num text-right">{r.months}</td><td className="td num text-right">{r.miles == null ? "No limit" : r.miles.toLocaleString("en-US")}</td><td className="td">{COVERS[r.covers] ?? r.covers}</td>
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
            await api.addWarrantyRule(cid, { vmrs_code: draft.vmrs_code.trim(), component: draft.component.trim(), months: Number(draft.months), miles: num(draft.miles), covers: draft.covers });
            setDraft({ vmrs_code: "", component: "", months: "", miles: "", covers: "parts+labour" });
            markStale?.(cid);
          });
        }}>
          {([["component", "Component", "w-[220px]"], ["vmrs_code", "Job type code", "w-[160px]"], ["months", "Months", "w-[110px]"], ["miles", "Miles (optional)", "w-[150px]"]] as const).map(([k, l, w]) => (
            <div key={k}>
              <label htmlFor={`wr-${k}`} className="mb-1 block text-sm font-medium">{l}</label>
              <input id={`wr-${k}`} className={`field ${w}`} value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} list={k === "vmrs_code" ? "job-codes" : undefined} autoComplete="off" />
            </div>
          ))}
          <div>
            <label htmlFor="wr-covers" className="mb-1 block text-sm font-medium">Covers</label>
            <select id="wr-covers" className="field w-[180px]" value={draft.covers} onChange={(e) => setDraft({ ...draft, covers: e.target.value as Covers })}>
              {(Object.keys(COVERS) as Covers[]).map((c) => <option key={c} value={c}>{COVERS[c]}</option>)}
            </select>
          </div>
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
  const markStale = useProgress()?.markChecksStale;
  const [rows, setRows] = useState<Benchmark[] | null>(null);
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const [draft, setDraft] = useState({ vmrs_code: "", vehicle_class: "", hours: "" });
  const [clearAll, setClearAll] = useState(false);
  const load = useCallback(() => api.benchmarks(cid).then(setRows).catch((e) => setMsg({ text: e.message, error: true })), [cid]);
  useEffect(() => { load(); }, [load]);

  async function pick(f: File | undefined) {
    if (!f) return;
    setMsg(null);
    try {
      const r = await api.importBenchmarks(cid, f);
      setMsg({ text: `Imported ${r.imported} ${r.imported === 1 ? "benchmark" : "benchmarks"}.` });
      markStale?.(cid);
      await load();
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : "The import didn't work. Check the file and try again.", error: true }); }
  }

  async function importJobs(f: File) {
    const r = await api.importBenchmarkJobs(cid, f);
    await load();
    markStale?.(cid);
    return {
      message: `Read ${r.rows} ${r.rows === 1 ? "row" : "rows"}: ${r.imported} benchmarks imported${r.merged.length ? `, ${r.merged.length} merged` : ""}${r.skipped.length ? `, ${r.skipped.length} skipped` : ""}.`,
      details: [
        { title: "Skipped, so add these by hand if you need them", items: r.skipped.map((x) => `Row ${x.row} (${x.job}): ${x.reason}`) },
        { title: "Merged", items: r.merged.map((x) => `Row ${x.row} (${x.job}) joined ${x.into}: ${x.reason}`) },
      ],
    };
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    try {
      await api.addBenchmark(cid, { vmrs_code: draft.vmrs_code.trim(), benchmark_hours: Number(draft.hours), vehicle_class: draft.vehicle_class.trim() || null });
      setDraft({ vmrs_code: "", vehicle_class: "", hours: "" });
      markStale?.(cid);
      await load();
    } catch (err) { setMsg({ text: err instanceof Error ? err.message : "That didn't save. Try again.", error: true }); }
  }

  async function removeOne(b: Benchmark) {
    setMsg(null);
    try { await api.deleteBenchmark(cid, b.id); markStale?.(cid); await load(); }
    catch (err) { setMsg({ text: err instanceof Error ? err.message : "That didn't remove. Try again.", error: true }); }
  }

  const removable = (rows ?? []).filter((b) => b.source !== "client_median").length;
  const sourceName = (s: string) => (s === "client_median" ? "Worked out from this client's invoices" : s === "manual" ? "Typed in" : "Imported");

  return (
    <section className="mt-14" aria-labelledby="bench-h" id="benchmarks">
      <h2 id="bench-h" className="text-lg">Labour benchmarks</h2>
      <p className="mt-1 max-w-prose text-muted">
        Typical hours for each job type. Labour above these hours is flagged. Add your own, optionally for one vehicle class, or import them. Where there is none, the checks work one out from this client&apos;s own invoices.
      </p>
      {admin && (
        <>
          <ImportPanel testId="benchmark-jobs-import" label="Import benchmarks by vehicle class (CSV)" onImport={importJobs}
            help={<>Columns: <b>vehicle_class</b>, <b>benchmark_hours</b>, and the job named in <b>description</b> (or <b>job_key</b>, or the app&apos;s own <b>vmrs_code</b>). Each job is matched to the job code the app gives invoice lines with that name. Importing again replaces the earlier import; typed-in values stay.</>} />
          <div className="mt-5">
            <label htmlFor="bench-file" className="mb-1 block font-medium">Import benchmarks by job code (CSV)</label>
            <input id="bench-file" type="file" accept=".csv,text/csv" className="block text-base" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
            <p className="mt-1 text-sm text-muted">Columns: vmrs_code, benchmark_hours</p>
          </div>
          <form className="mt-6 flex flex-wrap items-end gap-4" noValidate onSubmit={add} data-testid="benchmark-add">
            <div>
              <label htmlFor="bm-code" className="mb-1 block text-sm font-medium">Job type code</label>
              <input id="bm-code" className="field w-[160px]" list="job-codes" autoComplete="off" value={draft.vmrs_code} onChange={(e) => setDraft({ ...draft, vmrs_code: e.target.value })} />
            </div>
            <div>
              <label htmlFor="bm-class" className="mb-1 block text-sm font-medium">Vehicle class (optional)</label>
              <input id="bm-class" className="field w-[190px]" placeholder="all vehicles" autoComplete="off" value={draft.vehicle_class} onChange={(e) => setDraft({ ...draft, vehicle_class: e.target.value })} />
            </div>
            <div>
              <label htmlFor="bm-hours" className="mb-1 block text-sm font-medium">Typical hours</label>
              <input id="bm-hours" type="number" step="0.1" min="0" className="field num w-[130px]" value={draft.hours} onChange={(e) => setDraft({ ...draft, hours: e.target.value })} />
            </div>
            <button type="submit" className="btn-secondary" disabled={!draft.vmrs_code.trim() || !draft.hours.trim()}>Add benchmark</button>
          </form>
        </>
      )}
      <p role={msg?.error ? "alert" : "status"} className={`mt-3 ${msg?.error ? "text-danger" : "text-confirmed"}`}>{msg?.text}</p>
      {rows && rows.length === 0 && <p className="mt-4 text-lg">No benchmarks yet.{admin ? " Add one or import a CSV." : ""}</p>}
      {admin && removable > 0 && (
        <div className="mt-4 flex justify-end"><button className="btn-danger btn-sm" onClick={() => setClearAll(true)}>Remove all typed-in and imported ({removable})</button></div>
      )}
      <ConfirmDialog open={clearAll} danger title={`Remove ${removable} benchmarks?`} confirmWord="REMOVE" actionLabel="Remove them"
        body="This removes every benchmark that was typed in or imported. The ones worked out from this client's invoices stay, and the checks use those."
        onClose={() => setClearAll(false)} onConfirm={async () => { await api.deleteAllBenchmarks(cid); setClearAll(false); markStale?.(cid); await load(); }} />
      {rows && rows.length > 0 && (
        <div className="mt-4 max-h-[420px] overflow-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[760px] border-collapse">
            <thead className="sticky top-0 bg-surface"><tr>
              <th className="th" scope="col">Code</th><th className="th" scope="col">Job type</th><th className="th" scope="col">Vehicle class</th>
              <th className="th text-right" scope="col">Typical hours</th><th className="th" scope="col">Source</th><th className="th text-right" scope="col">Samples</th>
              {admin && <th className="th" scope="col"><span className="sr-only">Action</span></th>}
            </tr></thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id} className="tr">
                  <td className="td num">{b.vmrs_code}</td><td className="td">{b.component}</td>
                  <td className="td capitalize">{b.vehicle_class ? b.vehicle_class.replace(/_/g, " ") : "All vehicles"}</td>
                  <td className="td num text-right">{b.hours.toFixed(1)}</td><td className="td">{sourceName(b.source)}</td>
                  <td className="td num text-right">{b.sample_count ?? ""}</td>
                  {admin && (
                    <td className="td text-right">
                      {b.source !== "client_median" && <button className="btn-danger btn-sm" onClick={() => removeOne(b)} aria-label={`Remove benchmark for ${b.component}${b.vehicle_class ? `, ${b.vehicle_class}` : ""}`}>Remove</button>}
                    </td>
                  )}
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
  const [dialog, setDialog] = useState<null | "raw" | "all" | "complete">(null);
  const load = useCallback(() => api.client(cid).then(setInfo).catch(() => undefined), [cid]);
  useEffect(() => { load(); }, [load]);

  async function complete() {
    setMsg(null);
    try { await api.auditComplete(cid); await load(); setMsg({ text: "Audit marked complete." }); }
    catch (e) { setMsg({ text: e instanceof Error ? e.message : "Couldn't mark the audit complete.", error: true }); }
  }

  return (
    <section className="mt-14" aria-labelledby="audit-h" id="audit">
      <h2 id="audit-h" className="text-lg">Audit and data</h2>
      <p className="mt-3" data-testid="audit-state">Audit marked complete: <span className="num font-medium">{info?.audit_completed_at ? dateTime(info.audit_completed_at) : "not yet"}</span></p>
      <p className="mt-1 max-w-prose text-muted">Raw invoice files are deleted automatically <span className="num">{info?.raw_retention_days ?? "a set number of"}</span> days after the audit is marked complete.</p>
      {info?.raw_files_deleted_at && <p className="mt-1 font-medium">Raw files deleted on <span className="num">{dateTime(info.raw_files_deleted_at)}</span></p>}
      {msg && <p role={msg.error ? "alert" : "status"} className={`mt-3 ${msg.error ? "text-danger" : "text-confirmed"}`}>{msg.text}</p>}
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="btn-secondary" onClick={() => setDialog("complete")}>Mark audit complete</button>
        <button className="btn-secondary" onClick={() => setDialog("raw")}>Delete raw files now</button>
      </div>

      <div className="mt-10 max-w-prose border border-danger p-5">
        <h3 className="text-lg text-danger">Delete everything for this client</h3>
        <p className="mt-1">This removes the client with all its invoices, flags and reports. It cannot be undone.</p>
        <button className="btn-secondary mt-4 border-danger text-danger" onClick={() => setDialog("all")}>Delete everything for this client</button>
      </div>

      <ConfirmDialog open={dialog === "complete"} title="Mark this audit complete?" actionLabel="Mark complete"
        body={`This starts the countdown: the original invoice files for ${client.name} are deleted automatically ${info?.raw_retention_days ?? "a set number of"} days from now. Extracted data and reports are kept.`}
        onClose={() => setDialog(null)} onConfirm={async () => { setDialog(null); await complete(); }} />
      <ConfirmDialog open={dialog === "raw"} title="Delete raw files now" confirmWord="DELETE" actionLabel="Delete raw files"
        body={`This deletes the original invoice files and page images for ${client.name}. Extracted data and reports are kept. This cannot be undone.`}
        onClose={() => setDialog(null)} onConfirm={async () => { await api.deleteRaw(cid); setDialog(null); await load(); setMsg({ text: "Raw files deleted." }); }} />
      <ConfirmDialog open={dialog === "all"} title="Delete everything for this client" confirmWord={client.name} actionLabel="Delete everything"
        body={`This deletes ${client.name} and every invoice, flag and report that belongs to it. This cannot be undone.`}
        onClose={() => setDialog(null)} onConfirm={async () => { await api.deleteEverything(cid, client.name); await refreshClients(); router.push("/clients"); }} />
    </section>
  );
}
