"use client";

import { useId, useState } from "react";
import type { FieldState } from "@/lib/api";
import { IconAlert, IconCheck } from "./Icons";

const MONEY = new Set(["subtotal", "tax", "total", "parts_price", "labour_rate", "line_total"]);

export function display(field: string, v: FieldState["value"]): string {
  if (v === null || v === undefined) return "";
  if (MONEY.has(field)) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : String(v);
  }
  return String(v);
}

interface Props {
  field: string;
  label: string;
  state: FieldState | undefined;
  onSave: (value: string | null) => Promise<void>;
  /** Shown on a field marked Check: the analyst looked at the image and the value is right as read. */
  onConfirm?: () => Promise<void>;
  compact?: boolean;
  hideLabel?: boolean;
  className?: string;
}

type Phase = "idle" | "saving" | "saved" | "error";

export default function FieldInput({ field, label, state, onSave, onConfirm, compact, hideLabel, className = "" }: Props) {
  const id = useId();
  const shown = display(field, state?.value ?? null);
  const [draft, setDraft] = useState(shown);
  const [editing, setEditing] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const numeric = MONEY.has(field) || ["qty", "labour_hours", "odometer"].includes(field);
  const flagged = !!state?.needs_review;
  const value = editing || phase === "saving" || phase === "error" ? draft : shown;

  async function commit() {
    setEditing(false);
    if (draft.trim() === shown.trim()) { if (phase === "error") { setPhase("idle"); setError(null); } return; }
    setPhase("saving");
    setError(null);
    try {
      await onSave(draft.trim() === "" ? null : draft.trim());
      setPhase("saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save this change. Try again.");
      setPhase("error");
    }
  }

  const noteId = `${id}-note`;
  return (
    <div className={`${flagged ? "rounded-r-md border-l-4 border-danger bg-[#fdecea] py-1 pl-2 pr-1" : ""} ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className={hideLabel ? "sr-only" : "text-sm font-medium"}>{label}</label>
        {flagged && (
          <span className="inline-flex items-center gap-1 text-sm font-bold text-danger"><IconAlert />Check</span>
        )}
      </div>
      <input
        id={id}
        value={value}
        inputMode={numeric ? "decimal" : undefined}
        onChange={(e) => { setDraft(e.target.value); if (phase !== "saving") setPhase("idle"); }}
        onFocus={() => { setDraft(shown); setEditing(true); }}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}
        aria-invalid={phase === "error"}
        aria-describedby={error || flagged ? noteId : undefined}
        className={`field ${compact ? "min-h-[40px] px-2 text-sm" : "mt-1"} ${numeric ? "num text-right" : ""} ${flagged && phase !== "error" ? "border-2 border-danger" : ""}`}
      />
      <div id={noteId} className="min-h-0 text-sm" aria-live="polite">
        {flagged && state?.note && phase !== "error" && <p className="mt-1 text-ink">{state.note}</p>}
        {phase === "error" && <p className="mt-1 text-danger">{error}</p>}
        {phase === "saving" && <p className="mt-1 text-muted">Saving…</p>}
        {phase === "saved" && <p className="mt-1 inline-flex items-center gap-1 text-confirmed"><IconCheck />Saved</p>}
        {flagged && onConfirm && phase !== "saving" && (
          <button type="button" className="btn-link min-h-[32px] text-sm" onClick={async () => {
            setError(null);
            try { await onConfirm(); } catch (e) { setError(e instanceof Error ? e.message : "Couldn't confirm this field. Try again."); setPhase("error"); }
          }} aria-label={`${label} looks right`}>Looks right</button>
        )}
      </div>
    </div>
  );
}
