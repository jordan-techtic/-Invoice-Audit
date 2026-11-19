export type Role = "admin" | "analyst" | string;
export interface User { id: string; email: string; name: string; role: Role }
export interface Client { id: string; name: string; slug: string }
export type UploadStatus = "queued" | "reading" | "needs_review" | "done" | "failed" | "duplicate";
export interface UploadRow {
  id: string; filename: string; status: UploadStatus; status_detail: string | null;
  source: string | null; size_bytes: number | null; page_count: number | null;
  invoice_count: number | null; created_at: string; duplicate_of: string | null;
}
export type UploadResult =
  | { ok: true; upload: UploadRow }
  | { ok: false; filename: string; error: string };
export type ReviewStatus = "needs_review" | "ready" | "reviewed";
export interface InvoiceSummary {
  id: string; shop: string | null; invoice_number: string | null; invoice_date: string | null;
  unit_number: string | null; total: number | string | null; review_status: ReviewStatus; fields_to_check: number;
}
export interface FieldState {
  value: string | number | null; confidence: number | null; needs_review: boolean;
  note: string | null; corrected: boolean;
}
export interface InvoiceLine { id: string; line_no: number; [field: string]: FieldState | string | number }
export interface InvoiceDetail {
  id: string; review_status: ReviewStatus; source_filename: string | null;
  pages: { n: number; url: string }[];
  header: Record<string, FieldState>;
  lines: InvoiceLine[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) { onUnauthorized = fn; }

export const apiUrl = (path: string) => `/api${path}`;

export function errorText(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length && typeof d[0]?.msg === "string") return d[0].msg;
  }
  if (status >= 500) return "The server hit a problem. Wait a moment and try again.";
  return "That request didn't work. Check the details and try again.";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      credentials: "include",
      ...init,
      headers: init.body ? { "Content-Type": "application/json", ...init.headers } : init.headers,
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/login")) onUnauthorized?.();
    throw new ApiError(res.status, res.status === 401 && path.startsWith("/auth/login")
      ? "That email and password don't match. Check both and try again."
      : errorText(body, res.status));
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({ method, body: data === undefined ? undefined : JSON.stringify(data) });

export const api = {
  login: (email: string, password: string) => request<User>("/auth/login", json("POST", { email, password })),
  logout: () => request<unknown>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  clients: () => request<Client[]>("/clients"),
  addClient: (name: string) => request<Client>("/clients", json("POST", { name })),
  uploads: (cid: string) => request<UploadRow[]>(`/clients/${cid}/uploads`),
  retryUpload: (cid: string, id: string) => request<unknown>(`/clients/${cid}/uploads/${id}/retry`, { method: "POST" }),
  invoices: (cid: string, status?: ReviewStatus) =>
    request<InvoiceSummary[]>(`/clients/${cid}/invoices${status ? `?status=${status}` : ""}`),
  invoice: (cid: string, id: string) => request<InvoiceDetail>(`/clients/${cid}/invoices/${id}`),
  editField: (cid: string, id: string, field: string, value: string | null, lineId?: string) =>
    request<unknown>(`/clients/${cid}/invoices/${id}/fields`, json("PATCH", { field, value, line_id: lineId })),
  markChecked: (cid: string, id: string) => request<unknown>(`/clients/${cid}/invoices/${id}/mark-checked`, { method: "POST" }),
};

/** Upload one file with real progress. Resolves with the per-file result from the API. */
export function uploadFile(cid: string, file: File, onProgress: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve) => {
    const fail = (error: string) => resolve({ ok: false, filename: file.name, error });
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl(`/clients/${cid}/uploads`));
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onerror = () => fail("Can't reach the server. Check your connection and try again.");
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* handled below */ }
      if (xhr.status === 401) { onUnauthorized?.(); return fail("You're signed out. Sign in again and retry."); }
      if (xhr.status >= 200 && xhr.status < 300 && Array.isArray(body) && body[0]) return resolve(body[0] as UploadResult);
      fail(errorText(body, xhr.status));
    };
    const form = new FormData();
    form.append("files", file);
    xhr.send(form);
  });
}

export const STATUS_LABEL: Record<ReviewStatus, string> = { needs_review: "Needs review", ready: "Ready", reviewed: "Checked" };

export function money(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const n = typeof v === "number" ? v : parseFloat(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
