"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type Client } from "@/lib/api";
import { useSession } from "@/lib/session";
import { IconPlus } from "@/components/Icons";

interface Counts { total: number; review: number }

export default function ClientsPage() {
  const router = useRouter();
  const { user, clients, client, chooseClient, refreshClients } = useSession();
  const [counts, setCounts] = useState<Record<string, Counts>>({});
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);

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

  function openAdd() { setName(""); setError(null); dialog.current?.showModal(); }
  function closeAdd() { setName(""); setError(null); }

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
      dialog.current?.close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add the client. Check the name and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-prose">
          <h1 className="text-xl">Clients</h1>
          <p className="mt-1 text-muted">Choose the client whose invoices you are auditing. Everything after this (upload, review, report) is for that client only.</p>
        </div>
        {user.role === "admin" && (
          <button className="btn-primary btn-lg w-full sm:w-auto" onClick={openAdd} aria-haspopup="dialog">
            <IconPlus />Add client
          </button>
        )}
      </div>

      {clients.length === 0 ? (
        <p className="mt-8 max-w-prose text-lg">
          {user.role === "admin" ? "No clients yet. Use the Add client button to add your first client and start uploading invoices." : "No clients are assigned to you yet. Ask an admin to give you access."}
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
        <dialog ref={dialog} onClose={closeAdd} onClick={(e) => { if (e.target === dialog.current) dialog.current?.close(); }}
          className="w-[min(480px,92vw)] rounded-lg border border-line-strong bg-surface p-0 text-ink backdrop:bg-ink/40" aria-labelledby="add-client-title">
          <form onSubmit={add} className="p-6" noValidate>
            <h2 id="add-client-title" className="text-lg">Add client</h2>
            <p className="mt-1 text-muted">Each client has its own invoices, flags and reports.</p>
            <label htmlFor="client-name" className="mb-1 mt-4 block font-medium">Client name</label>
            <input id="client-name" className="field" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error}
              aria-describedby={error ? "client-error" : undefined} autoComplete="off" autoFocus />
            {error && <p id="client-error" role="alert" className="mt-2 text-danger">{error}</p>}
            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <button type="button" className="btn-secondary" onClick={() => dialog.current?.close()}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={busy || !name.trim()}>{busy ? "Adding…" : "Add client"}</button>
            </div>
          </form>
        </dialog>
      )}
    </div>
  );
}
