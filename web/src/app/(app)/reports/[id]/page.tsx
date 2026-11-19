"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, apiUrl, type Snapshot } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import ReportView from "@/components/ReportView";

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <NeedClient>{(c) => <Staff cid={c.id} id={id} />}</NeedClient>;
}

function Staff({ cid, id }: { cid: string; id: string }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.report(cid, id).then(setSnap).catch((e) => setError(e instanceof Error ? e.message : "Couldn't load this report.")); }, [cid, id]);
  if (error) return <p role="alert" className="text-danger">{error} <Link href="/reports" className="btn-link">Back to reports</Link></p>;
  if (!snap) return <p className="text-muted" role="status">Loading report…</p>;
  return (
    <div>
      <div className="no-print mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link href="/reports" className="btn-link">← Back to reports</Link>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => window.print()}>Print</button>
          <a className="btn-primary" href={apiUrl(`/clients/${cid}/reports/${id}/pdf`)} download>Download PDF</a>
        </div>
      </div>
      <ReportView snapshot={snap} />
    </div>
  );
}
