"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  open: boolean; title: string; body: string; confirmWord?: string; actionLabel: string; danger?: boolean;
  onConfirm: () => Promise<void>; onClose: () => void;
}

export default function ConfirmDialog({ open, title, body, confirmWord, actionLabel, danger, onConfirm, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { await onConfirm(); setTyped(""); }
    catch (err) { setError(err instanceof Error ? err.message : "That didn't work. Try again."); }
    finally { setBusy(false); }
  }
  function close() { setTyped(""); setError(null); onClose(); }

  return (
    <dialog ref={ref} onClose={close} className="w-[min(520px,92vw)] border border-line-strong bg-surface p-6 text-ink backdrop:bg-ink/40">
      <form onSubmit={go}>
        <h2 className="text-lg">{title}</h2>
        <p className="mt-2">{body}</p>
        {confirmWord && (
          <>
            <label htmlFor="confirm-word" className="mb-1 mt-4 block text-sm font-medium">Type {confirmWord} to confirm</label>
            <input id="confirm-word" className="field" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </>
        )}
        {error && <p role="alert" className="mt-3 text-danger">{error}</p>}
        <div className="mt-5 flex gap-3">
          <button type="submit" className={danger ? "btn-danger" : "btn-primary"} disabled={(!!confirmWord && typed !== confirmWord) || busy}>{busy ? "Working…" : actionLabel}</button>
          <button type="button" className="btn-secondary" onClick={close}>Cancel</button>
        </div>
      </form>
    </dialog>
  );
}
