export type Role = "admin" | "analyst" | string;
export interface User { id: string; email: string; name: string; role: Role }
export interface Client {
  id: string; name: string; slug: string;
  raw_retention_days?: number; raw_files_deleted_at?: string | null; audit_completed_at?: string | null;
}
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

export type FlagType = "labour_over_benchmark" | "repeat_repair" | "warranty_eligible" | "parts_price_outlier" | "duplicate" | "math_error";
export interface Flag {
  id: string; type: FlagType; severity: string | null; impact: number; reason: string; status: string;
  shop: string | null; unit: string | null; invoice_id: string; invoice_number: string | null; line_description: string | null;
}
export type FlagStatus = "open" | "accepted" | "edited" | "dismissed";
export type DismissReason = "wrong_extraction" | "valid_reason" | "not_real_issue" | "other";
export interface FlagList {
  total_possible_recoverable: number; confirmed_total: number; open_total: number; count: number; flags: Flag[];
}
export interface FlagDetail {
  id: string; type: FlagType; severity: string | null; impact: number; original_impact: number;
  reason: string; original_reason: string; status: FlagStatus; dismiss_reason: DismissReason | null; note: string | null;
  reviewed_by: string | null; reviewed_at: string | null; evidence_lines: string[];
  invoice: { id: string; invoice_number: string | null; invoice_date: string | null; shop: string | null; unit: string | null;
    vin: string | null; odometer: number | string | null; total: number | string | null; pages: { n: number; url: string }[]; flagged_page: number | null };
  line: { id: string; line_no: number; description: string | null; y_center: number | null } | null;
  lines: { id: string; line_no: number; description: string | null; part_number: string | null; qty: number | string | null;
    parts_price: number | string | null; labour_hours: number | string | null; labour_rate: number | string | null;
    line_total: number | string | null; flagged: boolean }[];
}
export interface Breakdown { key?: string; label: string; count: number; amount: number }
export interface Snapshot {
  id: string; version: number; empty: boolean;
  branding: { company_name: string; tagline?: string; accent?: string; ink?: string; money?: string; footer?: string };
  cover: { client_name: string; audit_date: string; invoices_reviewed: number; period?: string };
  summary: { total_spend: number; recoverable: number; pct_of_spend: number; flag_count: number; headline: string; top_findings: { sentence: string; amount: number }[] };
  breakdown: { by_type: Breakdown[]; by_shop: Breakdown[]; by_vehicle: Breakdown[] };
  narratives: { type: string; label: string; count: number; amount: number; paragraph: string }[];
  appendix: { invoice_number: string | null; date: string | null; shop: string | null; unit: string | null; reason: string; amount: number; type_label: string }[];
  next_steps: { text: string }; note: string; expires_at: string | null;
}
export interface ReportItem {
  id: string; version: number; generated_at: string; recoverable: number; flag_count: number;
  expires_at: string | null; revoked: boolean; expired: boolean; share_url: string | null;
}
export interface AuditRow {
  id: string; created_at: string; user_name: string | null; client_name: string | null; action: string;
  object_type: string | null; object_id: string | null; detail: unknown; ip: string | null;
}
export interface FlagRun {
  id: string; status: "queued" | "running" | "done" | "failed"; started_at: string | null; finished_at: string | null;
  summary: { flags: number; by_type: Record<string, number>; notes: string[] } | null; error: string | null;
}
export interface WarrantyRule { id: string; vmrs_code: string; component: string; months: number; miles: number | null }
export interface Benchmark { vmrs_code: string; component: string; hours: number; source: string; sample_count: number | null }

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
      headers: init.body && typeof init.body === "string" ? { "Content-Type": "application/json", ...init.headers } : init.headers,
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
  runFlags: (cid: string) => request<{ job_id: string; status: string }>(`/clients/${cid}/run-flags`, { method: "POST" }),
  flagRun: (cid: string, job: string) => request<FlagRun>(`/clients/${cid}/flag-runs/${job}`),
  flags: (cid: string, q: { type?: string; status?: string; shop?: string; unit?: string; sort?: string }) => {
    const sp = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => { if (v) sp.set(k, v); });
    return request<FlagList>(`/clients/${cid}/flags?${sp}`);
  },
  flagFilters: (cid: string) => request<{ shops: string[]; units: string[] }>(`/clients/${cid}/flags/filters`),
  flag: (cid: string, fid: string) => request<FlagDetail>(`/clients/${cid}/flags/${fid}`),
  flagAction: (cid: string, fid: string, action: "accept" | "dismiss" | "edit" | "reopen", body: object = {}) =>
    request<FlagDetail>(`/clients/${cid}/flags/${fid}/${action}`, json("POST", body)),
  recheck: (cid: string, iid: string) => request<{ flags: number; added: number; removed: number }>(`/clients/${cid}/invoices/${iid}/recheck`, { method: "POST" }),
  client: (cid: string) => request<Client>(`/clients/${cid}`),
  reportSettings: (cid: string) => request<{ default_offer_text: string; company_name: string }>(`/clients/${cid}/report-settings`),
  createReport: (cid: string, body: { expires_days: number; offer_text: string }) => request<ReportItem>(`/clients/${cid}/reports`, json("POST", body)),
  reports: (cid: string) => request<ReportItem[]>(`/clients/${cid}/reports`),
  report: (cid: string, rid: string) => request<Snapshot>(`/clients/${cid}/reports/${rid}`),
  revokeReport: (cid: string, rid: string) => request<unknown>(`/clients/${cid}/reports/${rid}/revoke`, { method: "POST" }),
  publicReport: (token: string) => request<Snapshot>(`/public/reports/${token}`),
  auditLog: (q: { client_id?: string; action?: string; limit: number; offset: number }) => {
    const sp = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => { if (v !== undefined && v !== "") sp.set(k, String(v)); });
    return request<{ total: number; rows: AuditRow[] }>(`/admin/audit-log?${sp}`);
  },
  auditComplete: (cid: string) => request<unknown>(`/clients/${cid}/audit-complete`, { method: "POST" }),
  deleteRaw: (cid: string) => request<unknown>(`/clients/${cid}/delete-raw-files`, json("POST", { confirm: "DELETE" })),
  deleteEverything: (cid: string, name: string) => request<unknown>(`/clients/${cid}/delete-everything`, json("POST", { confirm: name })),
  warrantyRules: (cid: string) => request<WarrantyRule[]>(`/clients/${cid}/warranty-rules`),
  addWarrantyRule: (cid: string, r: Omit<WarrantyRule, "id">) => request<unknown>(`/clients/${cid}/warranty-rules`, json("POST", r)),
  updateWarrantyRule: (cid: string, id: string, r: Partial<Omit<WarrantyRule, "id" | "vmrs_code">>) =>
    request<unknown>(`/clients/${cid}/warranty-rules/${id}`, json("PUT", r)),
  deleteWarrantyRule: (cid: string, id: string) => request<unknown>(`/clients/${cid}/warranty-rules/${id}`, { method: "DELETE" }),
  benchmarks: (cid: string) => request<Benchmark[]>(`/clients/${cid}/benchmarks`),
  importBenchmarks: (cid: string, file: File) => {
    const f = new FormData(); f.append("file", file);
    return request<{ imported: number }>(`/clients/${cid}/benchmarks/import`, { method: "POST", body: f });
  },
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

export const STATUS_WORD: Record<string, string> = { open: "Open", accepted: "Accepted", edited: "Accepted (edited)", dismissed: "Dismissed" };
export const DISMISS_WORD: Record<string, string> = {
  wrong_extraction: "Wrong extraction", valid_reason: "Shop had a valid reason", not_real_issue: "Not a real issue", other: "Other",
};
export const TYPE_NAME: Record<FlagType, string> = {
  labour_over_benchmark: "Labour hours above typical",
  repeat_repair: "Repeat repair",
  warranty_eligible: "Possibly under warranty",
  parts_price_outlier: "Parts price above typical",
  duplicate: "Possible duplicate",
  math_error: "Totals don't add up",
};

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export const REVIEW_QUERY_KEY = "ia.reviewQuery";
export const REVIEW_IDS_KEY = "ia.reviewIds";
