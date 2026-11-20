"use client";

import { useState } from "react";
import { ApiError, type ImportProblem } from "@/lib/api";

/** What a finished import tells the person: one line, plus optional lists (rows skipped, warnings). */
export interface ImportOutcome { message: string; details?: { title: string; items: string[] }[] }

/** A file picker for a CSV import, with the result or every row problem shown right under it. Nothing here knows what is imported. */
export default function ImportPanel({ label, help, accept = ".csv,text/csv", onImport, testId, children }: {
  label: string; help: React.ReactNode; accept?: string; testId: string;
  onImport: (file: File) => Promise<ImportOutcome>; children?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null);
  const [failure, setFailure] = useState<{ message: string; problems: ImportProblem[] } | null>(null);

  async function pick(f: File | undefined) {
    if (!f) return;
    setBusy(true); setOutcome(null); setFailure(null);
    try { setOutcome(await onImport(f)); }
    catch (e) {
      setFailure({ message: e instanceof Error ? e.message : "The import didn't work. Check the file and try again.", problems: e instanceof ApiError ? e.errors : [] });
    } finally { setBusy(false); }
  }

  return (
    <div className="mt-4" data-testid={testId}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <label className={`btn-secondary cursor-pointer focus-within:outline focus-within:outline-[3px] focus-within:outline-offset-2 focus-within:outline-primary ${busy ? "pointer-events-none opacity-60" : ""}`}>
          {busy ? "Importing…" : label}
          <input type="file" accept={accept} className="sr-only" disabled={busy} data-testid={`${testId}-file`}
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        {children}
      </div>
      <p className="mt-2 max-w-prose text-sm text-muted">{help}</p>
      {outcome && (
        <div role="status" className="mt-3 max-w-prose rounded-md border border-confirmed bg-confirmed-soft p-4" data-testid={`${testId}-result`}>
          <p className="font-medium text-confirmed">{outcome.message}</p>
          {outcome.details?.filter((d) => d.items.length).map((d) => (
            <div key={d.title} className="mt-3">
              <p className="text-sm font-medium">{d.title}</p>
              <ul className="mt-1 max-h-40 list-disc overflow-auto pl-5 text-sm">{d.items.map((i, n) => <li key={n}>{i}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
      {failure && (
        <div role="alert" className="mt-3 max-w-prose rounded-md border border-danger bg-[#fdecea] p-4" data-testid={`${testId}-error`}>
          <p className="font-medium text-danger">{failure.message}</p>
          {failure.problems.length > 0 && (
            <ul className="mt-2 max-h-64 list-disc overflow-auto pl-5 text-sm">
              {failure.problems.map((p, n) => <li key={n}>{p.row > 0 ? <b>Row {p.row}: </b> : null}{p.message}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
