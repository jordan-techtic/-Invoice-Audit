"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, shortDate, uploadFile, type UploadRow } from "@/lib/api";
import NeedClient from "@/components/NeedClient";
import { IconFile } from "@/components/Icons";

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

export default function UploadPage() {
  return <NeedClient>{(c) => <Upload cid={c.id} />}</NeedClient>;
}

function Upload({ cid }: { cid: string }) {
  const [rows, setRows] = useState<UploadRow[] | null>(null);
  const [local, setLocal] = useState<Local[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try { setRows(await api.uploads(cid)); setLoadError(null); }
    catch (e) { setLoadError(e instanceof Error ? e.message : "Couldn't load your files. Refresh the page."); }
  }, [cid]);

  useEffect(() => { setRows(null); reload(); }, [reload]);

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

  const empty = rows !== null && rows.length === 0 && local.length === 0;

  return (
    <div>
      <h1 className="text-xl">Upload invoices</h1>

      <div
        className={`relative mt-6 ${over ? "bg-sunken" : "bg-surface"} border-2 border-dashed border-line-strong`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}
      >
        <input
          ref={input} id="file-input" type="file" multiple className="peer sr-only"
          accept=".pdf,.jpg,.jpeg,.png,.heic,.heif,application/pdf,image/jpeg,image/png,image/heic"
          onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ""; }}
        />
        <label htmlFor="file-input" className="flex min-h-[220px] cursor-pointer flex-col items-center justify-center gap-3 px-6 py-10 text-center peer-focus-visible:outline peer-focus-visible:outline-[3px] peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary">
          <span className="text-primary"><IconFile /></span>
          <span className="text-lg font-bold text-primary">Drop invoices here, or choose files</span>
          <span className="text-sm text-muted">PDF, JPG, PNG or HEIC. Up to 25 MB each. You can add several at once.</span>
        </label>
      </div>

      {loadError && <p role="alert" className="mt-6 text-danger">{loadError}</p>}

      {empty ? (
        <p className="mt-8 max-w-prose text-lg">No invoices yet. Drop files here to start the audit.</p>
      ) : (
        rows !== null && (
          <div className="mt-8 overflow-x-auto bg-surface">
            <table className="w-full min-w-[640px] border-collapse">
              <caption className="sr-only">Uploaded files</caption>
              <thead>
                <tr>
                  <th scope="col" className="th">File</th>
                  <th scope="col" className="th text-right">Pages</th>
                  <th scope="col" className="th">Status</th>
                  <th scope="col" className="th"><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {local.map((l) => (
                  <tr key={l.key} className="tr">
                    <td className="td font-medium break-all">{l.name}</td>
                    <td className="td" />
                    <td className="td" colSpan={2}>
                      {l.error ? (
                        <div className="flex items-start justify-between gap-4">
                          <p className="text-danger" role="alert"><span className="font-medium">Not uploaded.</span> {l.error}</p>
                          <button className="btn-secondary shrink-0" onClick={() => setLocal((p) => p.filter((x) => x.key !== l.key))}>Dismiss</button>
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
                {(rows ?? []).map((r) => (
                  <tr key={r.id} className="tr" data-status={r.status}>
                    <td className="td font-medium break-all">
                      {r.filename}
                      <span className="block text-sm font-normal text-muted">Added {shortDate(r.created_at)}</span>
                    </td>
                    <td className="td num text-right">{r.page_count ?? ""}</td>
                    <td className="td">
                      <span className={`font-medium ${r.status === "failed" ? "text-danger" : ""}`}>{STATUS[r.status]}</span>
                      {r.status === "needs_review" && r.invoice_count ? <span className="num text-muted"> ({r.invoice_count} {r.invoice_count === 1 ? "invoice" : "invoices"})</span> : null}
                      {r.status_detail && <span className={`block text-sm ${r.status === "failed" ? "text-danger" : "text-muted"}`}>{r.status_detail}</span>}
                      {rowError[r.id] && <span role="alert" className="block text-sm text-danger">{rowError[r.id]}</span>}
                    </td>
                    <td className="td text-right">
                      {r.status === "failed" && <button className="btn-secondary" onClick={() => retry(r.id)}>Retry</button>}
                      {r.status === "needs_review" && <Link href="/invoices?status=needs_review" className="font-medium text-primary underline underline-offset-4">Review invoices</Link>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  );
}
