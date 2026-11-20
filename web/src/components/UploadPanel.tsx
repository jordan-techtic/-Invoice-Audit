"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, shortDate, uploadFile, type UploadRow } from "@/lib/api";
import { IconFile } from "@/components/Icons";
import { useProgress } from "@/lib/progress";

const MAX_BYTES = 25 * 1024 * 1024;
const EXT = ["pdf", "jpg", "jpeg", "png", "heic", "heif"];

interface Local { key: string; name: string; progress: number; error?: string }

function checkFile(f: File): string | null {
  const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
  if (!EXT.includes(ext)) return `${f.name} is not a supported file type. Convert it to PDF, JPG, PNG or HEIC and add it again.`;
  if (f.size > MAX_BYTES) return `${f.name} is ${(f.size / 1048576).toFixed(0)} MB, over the 25 MB limit. Compress or split it and add it again.`;
  return null;
}

const STATUS: Record<UploadRow["status"], string> = {
  queued: "Queued", reading: "Reading", needs_review: "Needs review", done: "Done", failed: "Failed", duplicate: "Skipped (duplicate)",
};

const PILL: Record<UploadRow["status"], string> = {
  queued: "bg-sunken text-muted", reading: "bg-sunken text-ink", needs_review: "bg-amber-soft text-ink", done: "bg-confirmed-soft text-confirmed",
  failed: "bg-[#fdecea] text-danger", duplicate: "bg-dismissed-soft text-dismissed",
};

/** Drop zone, upload summary and file list. `header` is shown at the left of the upload button. `onChange` fires when the set of files or their statuses changes,
 *  so the invoice list next to it can reload. */
export default function UploadPanel({ cid, onChange, header }: { cid: string; onChange?: () => void; header?: React.ReactNode }) {
  const [rows, setRows] = useState<UploadRow[] | null>(null);
  const [local, setLocal] = useState<Local[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const refreshProgress = useProgress()?.refresh;
  const signature = useRef<string | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; });

  const reload = useCallback(async () => {
    try {
      const next = await api.uploads(cid);
      setRows(next); setLoadError(null); refreshProgress?.();
      const sig = next.map((r) => `${r.id}:${r.status}:${r.invoice_count ?? ""}`).join("|");
      if (signature.current !== null && signature.current !== sig) onChangeRef.current?.();
      signature.current = sig;
    } catch (e) { setLoadError(e instanceof Error ? e.message : "Couldn't load your files. Refresh the page."); }
  }, [cid, refreshProgress]);

  useEffect(() => { setRows(null); signature.current = null; reload(); }, [reload]);

  const active = (rows ?? []).some((r) => r.status === "queued" || r.status === "reading");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(reload, 2000);
    return () => clearInterval(t);
  }, [active, reload]);

  async function addFiles(list: FileList | File[]) {
    const files = Array.from(list);
    const ok: { f: File; key: string }[] = [];
    const next: Local[] = [];
    files.forEach((f, i) => {
      const key = `${Date.now()}-${i}-${f.name}`;
      const err = checkFile(f);
      next.push({ key, name: f.name, progress: 0, error: err ?? undefined });
      if (!err) ok.push({ f, key });
    });
    setLocal((p) => [...next, ...p]);
    const queue = [...ok];
    const worker = async () => {
      for (let item = queue.shift(); item; item = queue.shift()) {
        const res = await uploadFile(cid, item.f, (p) =>
          setLocal((l) => l.map((x) => (x.key === item.key ? { ...x, progress: p } : x))));
        if (res.ok) {
          await reload();
          setLocal((l) => l.filter((x) => x.key !== item.key));
        } else {
          setLocal((l) => l.map((x) => (x.key === item.key ? { ...x, error: res.error } : x)));
        }
      }
    };
    await Promise.all([worker(), worker(), worker()]);
  }

  async function retry(id: string) {
    setRowError((p) => { const { [id]: _drop, ...rest } = p; void _drop; return rest; });
    try { await api.retryUpload(cid, id); await reload(); }
    catch (e) { setRowError((p) => ({ ...p, [id]: e instanceof Error ? e.message : "Retry didn't start. Try again." })); }
  }

  const all = rows ?? [];
  // The file list only appears when something needs attention: an upload in flight, or a file that failed (so it can be retried).
  const trouble = local.length > 0 || all.some((r) => r.status === "failed");
  const count = (st: UploadRow["status"][]) => all.filter((r) => st.includes(r.status)).length;
  const invoicesFound = all.reduce((n, r) => n + (r.invoice_count ?? 0), 0);
  const summary = [
    { label: "Files", value: all.length },
    { label: "Being read", value: count(["queued", "reading"]) },
    { label: "Read", value: count(["done", "needs_review"]) },
    { label: "Invoices found", value: invoicesFound },
    { label: "Duplicates skipped", value: count(["duplicate"]) },
    { label: "Failed", value: count(["failed"]) },
  ];

  return (
    <section
      aria-label="Upload invoices"
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false); }}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-prose">{header}</div>
        <div className="w-full shrink-0 sm:w-auto sm:text-right">
          <input
            ref={input} id="file-input" type="file" multiple className="peer sr-only"
            accept=".pdf,.jpg,.jpeg,.png,.heic,.heif,application/pdf,image/jpeg,image/png,image/heic"
            onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ""; }}
          />
          <label htmlFor="file-input" className="btn-primary btn-lg w-full cursor-pointer peer-focus-visible:outline peer-focus-visible:outline-[3px] peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary sm:w-auto">
            <IconFile />Upload invoices
          </label>
          <p className="mt-2 text-sm text-muted">{over ? "Drop to upload" : "PDF, JPG, PNG or HEIC · up to 25 MB each"}</p>
        </div>
      </div>

      {loadError && <p role="alert" className="mt-4 text-danger">{loadError}</p>}

      {all.length > 0 && (
        <dl className={`mt-5 grid grid-cols-3 gap-2 rounded-lg border-2 p-3 sm:grid-cols-6 sm:p-4 ${over ? "border-dashed border-primary bg-sunken" : "border-line bg-surface"}`} aria-label="Upload summary">
          {summary.map((x) => {
            const bad = x.label === "Failed" && x.value > 0;
            return (
              <div key={x.label} className={`rounded-md border px-3 py-2 ${bad ? "border-danger bg-surface" : "border-line bg-bg"}`}>
                <dt className="text-xs leading-tight text-muted">{x.label}</dt>
                <dd className={`num mt-0.5 text-xl font-bold ${bad ? "text-danger" : ""}`}>{x.value}</dd>
              </div>
            );
          })}
        </dl>
      )}

      {trouble && (
        <div className="mt-4">
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[640px] border-collapse">
              <caption className="sr-only">Uploaded files</caption>
              <thead>
                <tr>
                  <th scope="col" className="th">File</th>
                  <th scope="col" className="th text-right">Pages</th>
                  <th scope="col" className="th text-right">Invoices</th>
                  <th scope="col" className="th">Status</th>
                  <th scope="col" className="th"><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {local.map((l) => (
                  <tr key={l.key} className="tr">
                    <td className="td font-medium break-all">{l.name}</td>
                    <td className="td" />
                    <td className="td" />
                    <td className="td" colSpan={2}>
                      {l.error ? (
                        <div className="flex items-start justify-between gap-4">
                          <p className="text-danger" role="alert"><span className="font-medium">Not uploaded.</span> {l.error}</p>
                          <button className="btn-secondary btn-sm shrink-0" onClick={() => setLocal((p) => p.filter((x) => x.key !== l.key))}>Dismiss</button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-3">
                          <span className="w-24 shrink-0">Uploading</span>
                          <div className="h-2 w-full max-w-[240px] bg-sunken" role="progressbar" aria-label={`Uploading ${l.name}`}
                            aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(l.progress * 100)}>
                            <div className="h-2 bg-primary transition-[width] duration-200" style={{ width: `${Math.round(l.progress * 100)}%` }} />
                          </div>
                          <span className="num text-sm text-muted">{Math.round(l.progress * 100)}%</span>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {all.filter((r) => r.status === "failed").map((r) => (
                  <tr key={r.id} className="tr" data-status={r.status}>
                    <td className="td font-medium break-all">
                      {r.filename}
                      <span className="block text-sm font-normal text-muted">Added {shortDate(r.created_at)}</span>
                    </td>
                    <td className="td num text-right">{r.page_count ?? ""}</td>
                    <td className="td num text-right">{r.invoice_count ?? ""}</td>
                    <td className="td">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-sm font-medium ${PILL[r.status]}`}>{STATUS[r.status]}</span>
                      {r.status_detail && <span className={`block text-sm ${r.status === "failed" ? "text-danger" : "text-muted"}`}>{r.status_detail}</span>}
                      {rowError[r.id] && <span role="alert" className="block text-sm text-danger">{rowError[r.id]}</span>}
                    </td>
                    <td className="td whitespace-nowrap text-right">
                      {r.status === "failed" && <button className="btn-secondary btn-sm" onClick={() => retry(r.id)}>Retry</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
