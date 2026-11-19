"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setUnauthorizedHandler, type Client, type User } from "./api";

interface Session {
  user: User;
  clients: Client[];
  client: Client | null;
  chooseClient: (c: Client) => void;
  refreshClients: () => Promise<void>;
}

const Ctx = createContext<Session | null>(null);
const KEY = "ia.client";

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside provider");
  return s;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => { window.location.href = "/clients"; });
    let live = true;
    (async () => {
      try {
        const me = await api.me();
        const list = await api.clients();
        if (!live) return;
        let saved: string | null = null;
        try { saved = localStorage.getItem(KEY); } catch { /* storage unavailable */ }
        setClients(list);
        setClientId(list.some((c) => c.id === saved) ? saved : null);
        setUser(me);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : "Could not load session");
      }
    })();
    return () => { live = false; setUnauthorizedHandler(null); };
  }, []);

  const chooseClient = useCallback((c: Client) => {
    setClientId(c.id);
    try { localStorage.setItem(KEY, c.id); } catch { /* ignore */ }
  }, []);
  const refreshClients = useCallback(async () => { setClients(await api.clients()); }, []);

  const value = useMemo<Session | null>(() => user && {
    user, clients, client: clients.find((c) => c.id === clientId) ?? null,
    chooseClient, refreshClients,
  }, [user, clients, clientId, chooseClient, refreshClients]);

  if (error) return <p className="p-10 text-danger" role="alert">{error}</p>;
  if (!value) return <p className="p-10 text-muted" role="status">Loading…</p>;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}