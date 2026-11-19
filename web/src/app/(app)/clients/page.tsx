"use client";

import { useEffect, useState } from "react";
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
    router.push("/upload");
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
      <p className="mt-1 max-w-prose text-muted">Choose the client whose invoices you are working on.</p>

      {clients.length === 0 ? (
        <p className="mt-8 max-w-prose text-lg">
          {user.role === "admin" ? "No clients yet. Add your first client below to start uploading invoices." : "No clients are assigned to you yet. Ask an admin to give you access."}
        </p>
      ) : (
        <div className="mt-8 overflow-x-auto bg-surface">
          <table className="w-full min-w-[560px] border-collapse">
            <thead>
              <tr>
                <th className="th" scope="col">Client</th>
                <th className="th text-right" scope="col">Invoices</th>
                <th className="th text-right" scope="col">Need review</th>
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
                      {active && <span className="ml-3 text-sm font-normal text-muted">Active client</span>}
                    </th>
                    <td className="td num text-right">{n ? n.total : ""}</td>
                    <td className="td num text-right">{n ? n.review : ""}</td>
                    <td className="td text-right">
                      <button className={active ? "btn-secondary" : "btn-primary"} onClick={() => pick(c)} aria-label={`Work on ${c.name}`}>
                        {active ? "Continue" : "Choose client"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {user.role === "admin" && (
        <form onSubmit={add} className="mt-12 max-w-[520px]" noValidate>
          <h2 className="text-lg">Add client</h2>
          <label htmlFor="client-name" className="mb-1 mt-3 block font-medium">Client name</label>
          <div className="flex gap-3">
            <input id="client-name" className="field" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error}
              aria-describedby={error ? "client-error" : undefined} />
            <button type="submit" className="btn-secondary shrink-0" disabled={busy || !name.trim()}>Add client</button>
          </div>
          {error && <p id="client-error" role="alert" className="mt-2 text-danger">{error}</p>}
        </form>
      )}
    </div>
  );
}
