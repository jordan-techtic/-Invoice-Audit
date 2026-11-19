"use client";

import { use, useEffect, useState } from "react";
import { api, ApiError, apiUrl, type Snapshot } from "@/lib/api";
import ReportView from "@/components/ReportView";

export default function PublicReport({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    api.publicReport(token).then(setSnap).catch((e) => {
      setProblem(e instanceof ApiError && e.status === 404 ? "This link isn't valid. Check the address, or ask the sender for a new link." : e instanceof Error ? e.message : "This report can't be shown right now.");
    });
  }, [token]);

  return (
    <div className="min-h-screen">
      <header className="no-print flex min-h-[64px] items-center justify-between gap-4 border-b border-line bg-surface px-6 lg:px-10">
        <p className="text-lg font-bold text-primary">{snap?.branding.company_name ?? "Repair invoice audit"}</p>
        {snap && <a href={apiUrl(`/public/reports/${token}/pdf`)} className="btn-secondary">Download PDF</a>}
      </header>
      <main className="mx-auto max-w-page px-4 py-8 sm:px-6 lg:px-10">
        {problem && <div className="max-w-prose py-10"><h1 className="text-xl">Report unavailable</h1><p role="alert" className="mt-3 text-lg">{problem}</p></div>}
        {!problem && !snap && <p className="text-muted" role="status">Loading report…</p>}
        {snap && <ReportView snapshot={snap} />}
      </main>
    </div>
  );
}
