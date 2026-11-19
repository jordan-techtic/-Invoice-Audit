"use client";

import Link from "next/link";
import { useSession } from "@/lib/session";
import type { Client } from "@/lib/api";

/** Renders children only when a client is chosen; otherwise says what to do. */
export default function NeedClient({ children }: { children: (c: Client) => React.ReactNode }) {
  const { client } = useSession();
  if (!client) {
    return (
      <div className="max-w-prose">
        <h1 className="text-xl">Choose a client first</h1>
        <p className="mt-2 text-muted">Invoices belong to one client. Pick which client you are working on.</p>
        <Link href="/clients" className="btn-primary mt-6">Go to clients</Link>
      </div>
    );
  }
  return <>{children(client)}</>;
}
