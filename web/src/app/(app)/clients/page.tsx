"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type Client } from "@/lib/api";
import { useSession } from "@/lib/session";

interface Counts { total: number; review: number }

export default function ClientsPage() {
  const router = useRouter();
  const { user, clients, client, chooseClient, refreshClients } = useSession();
  const [counts, setCounts] = useState<Record<string, Counts>>({});
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    clients.forEach(async (c) => {
      try {
        const rows = await api.invoices(c.id);
        if (live) setCounts((p) => ({ ...p, [c.id]: { total: rows.length, review: rows.filter((r) => r.review_status === "needs_review").length } }));
      } catch { /* counts are optional */ }
    });
    return () => { live = false; };
  }, [clients]);

  function pick(c: Client) {
    chooseClient(c);
    router.push("/overview");
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.addClient(name.trim());
      await refreshClients();
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add the client. Check the name and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-xl">Clients</h1>
      <p className="mt-1 max-w-prose text-muted">Step 0: choose the client whose invoices you are auditing. Everything after this (upload, review, report) is for that client only.</p>

      {clients.length === 0 ? (
        <p className="mt-8 max-w-prose text-lg">
          {user.role === "admin" ? "No clients yet. Add your first client below to start uploading invoices." : "No clients are assigned to you yet. Ask an admin to give you access."}
        </p>
      ) : (
        <div className="mt-8 overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[560px] border-collapse">
            <thead>
              <tr>
                <th className="th" scope="col">Client</th>
                <th className="th text-right" scope="col">Invoices</th>
                <th className="th text-right" scope="col">To check</th>
                <th className="th" scope="col"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => {
                const n = counts[c.id];
                const active = client?.id === c.id;
                return (
                  <tr key={c.id} className="tr">
                    <th scope="row" className="td text-left text-base font-medium">
                      {c.name}
                      {active && <span className="ml-3 rounded-full bg-confirmed-soft px-2 py-0.5 text-sm font-medium text-confirmed">Active</span>}
                    </th>
                    <td className="td num text-right">{n ? n.total : "…"}</td>
                    <td className="td num text-right">{n ? (n.review ? <span className="font-bold text-money">{n.review}</span> : "0") : "…"}</td>
                    <td className="td whitespace-nowrap">
                      <div className="flex items-center justify-end gap-3">
                        <Link href={`/clients/${c.id}/settings`} className="btn-secondary btn-sm" aria-label={`Settings for ${c.name}`}>Settings</Link>
                        <button className="btn-primary btn-sm min-w-[140px]" onClick={() => pick(c)} aria-label={`Work on ${c.name}`}>
                          {active ? "Continue audit" : "Open audit"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {user.role === "admin" && (
        <form onSubmit={add} className="card mt-10 max-w-[560px]" noValidate>
          <h2 className="text-lg">Add client</h2>
          <label htmlFor="client-name" className="mb-1 mt-3 block font-medium">Client name</label>
          <div className="flex gap-3">
            <input id="client-name" className="field" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error}
              aria-describedby={error ? "client-error" : undefined} />
            <button type="submit" className="btn-primary shrink-0" disabled={busy || !name.trim()}>{busy ? "Adding…" : "Add client"}</button>
          </div>
          {error && <p id="client-error" role="alert" className="mt-2 text-danger">{error}</p>}
        </form>
      )}
    </div>
  );
}
