"use client";

import { useEffect, useState } from "react";
import { api, dateTime, type AuditRow } from "@/lib/api";
import { useSession } from "@/lib/session";

const PAGE = 50;
const ACTIONS = ["login", "logout", "upload", "view", "edit", "accept", "dismiss", "reopen", "report_create", "report_revoke", "audit_complete", "delete_raw_files", "delete_everything"];

export default function AuditPage() {
  const { user, clients } = useSession();
  const [action, setAction] = useState("");
  const [clientId, setClientId] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; rows: AuditRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const admin = user.role === "admin";

  useEffect(() => {
    if (!admin) return;
    api.auditLog({ client_id: clientId, action, limit: PAGE, offset }).then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load the audit log."));
  }, [admin, action, clientId, offset]);

  if (!admin) return <div><h1 className="text-xl">Audit log</h1><p className="mt-3 text-lg">Only admins can see the audit log.</p></div>;
  const total = data?.total ?? 0;
  const actions = Array.from(new Set([...ACTIONS, ...(data?.rows.map((r) => r.action) ?? [])]));

  return (
    <div>
      <h1 className="text-xl">Audit log</h1>
      <p className="mt-1 max-w-prose text-muted">Who did what, and when. Newest first.</p>
      <div className="mt-6 flex flex-wrap gap-4">
        <div>
          <label htmlFor="a-action" className="mb-1 block text-sm font-medium">Action</label>
          <select id="a-action" className="field min-w-[200px]" value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }}>
            <option value="">All actions</option>{actions.map((a) => <option key={a} value={a}>{a.replace(/_/g, " ")}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="a-client" className="mb-1 block text-sm font-medium">Client</label>
          <select id="a-client" className="field min-w-[220px]" value={clientId} onChange={(e) => { setClientId(e.target.value); setOffset(0); }}>
            <option value="">All clients</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>
      {error && <p role="alert" className="mt-6 text-danger">{error}</p>}
      {data && data.rows.length === 0 && <p className="mt-8 text-lg">Nothing recorded for these filters.</p>}
      {data && data.rows.length > 0 && (
        <>
          <div className="mt-6 overflow-x-auto bg-surface">
            <table className="w-full min-w-[900px] border-collapse">
              <caption className="sr-only">Audit log</caption>
              <thead><tr>{["When", "Who", "Client", "Action", "Object", "Details"].map((h) => <th key={h} scope="col" className="th">{h}</th>)}</tr></thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id} className="tr align-top">
                    <td className="td num whitespace-nowrap">{dateTime(r.created_at)}</td>
                    <td className="td">{r.user_name}</td>
                    <td className="td">{r.client_name}</td>
                    <td className="td whitespace-nowrap font-medium">{r.action.replace(/_/g, " ")}</td>
                    <td className="td">{r.object_type?.replace(/_/g, " ")}</td>
                    <td className="td max-w-[40ch] break-words text-sm text-muted">{r.detail ? JSON.stringify(r.detail) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center gap-4">
            <button className="btn-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous page</button>
            <span className="num text-muted">Showing {offset + 1} to {Math.min(offset + PAGE, total)} of {total}</span>
            <button className="btn-secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next page</button>
          </div>
        </>
      )}
    </div>
  );
}
