"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Thresholds } from "@/lib/api";
import { useProgress } from "@/lib/progress";
import ImportPanel from "./ImportPanel";

/** Form fields. Parts price is shown as a multiplier (1.5 = 50% above the usual price) but stored as a percentage. */
type FormKey = Exclude<keyof Thresholds, "parts_outlier_pct" | "repeat_condition"> | "parts_multiplier";
interface Field { key: FormKey; label: string; hint: string; step?: string; unit?: string }

const GROUPS: { title: string; fields: Field[] }[] = [
  { title: "Labour", fields: [
    { key: "labour_over_benchmark_pct", label: "Over the typical hours by", unit: "%", hint: "Flag labour billed more than this far above the typical hours for the job." },
    { key: "labour_min_samples", label: "Jobs needed for a typical time", hint: "How many past jobs of one type are needed before its typical time is trusted." },
  ] },
  { title: "Repeat repairs", fields: [
    { key: "repeat_repair_days", label: "Within days", hint: "The same part repaired again on the same unit within this many days." },
    { key: "repeat_repair_miles", label: "Within miles", hint: "Or within this many miles. Trailers have no odometer, so they are checked by days only." },
  ] },
  { title: "Parts prices", fields: [
    { key: "parts_multiplier", label: "Price multiplier", unit: "×", step: "0.01", hint: "Flag a part billed above this many times its usual price (1.5 means 50% above)." },
    { key: "parts_single_shop_multiple", label: "Multiplier when one shop sells it", unit: "×", step: "0.01", hint: "The same, for a part that only one shop has billed so far." },
    { key: "parts_min_samples", label: "Sales needed for a usual price", hint: "How many sales of a part number are needed before its usual price is trusted." },
  ] },
  { title: "Maths and duplicates", fields: [
    { key: "math_tolerance", label: "Maths tolerance", unit: "$", step: "0.01", hint: "Ignore differences up to this amount when an invoice is added up." },
    { key: "duplicate_window_days", label: "Duplicate window (days)", hint: "0 means the dates must match. 10 means the same shop, unit and total within 10 days is a duplicate." },
  ] },
];

type Values = Record<FormKey | "repeat_condition", string>;
const round = (n: number, dp = 2) => Math.round(n * 10 ** dp) / 10 ** dp;

function toValues(t: Thresholds): Values {
  const s = (n: number) => String(n);
  return {
    labour_over_benchmark_pct: s(t.labour_over_benchmark_pct), labour_min_samples: s(t.labour_min_samples),
    repeat_repair_days: s(t.repeat_repair_days), repeat_repair_miles: s(t.repeat_repair_miles), repeat_condition: t.repeat_condition,
    parts_multiplier: s(round(1 + t.parts_outlier_pct / 100)), parts_single_shop_multiple: s(t.parts_single_shop_multiple),
    parts_min_samples: s(t.parts_min_samples), math_tolerance: s(t.math_tolerance), duplicate_window_days: s(t.duplicate_window_days),
  };
}

/** Throws a plain sentence when a box doesn't hold a number. The server checks the ranges. */
function toPayload(v: Values): Partial<Thresholds> {
  const num = (k: FormKey, label: string) => {
    const n = Number(v[k]);
    if (v[k].trim() === "" || !Number.isFinite(n)) throw new Error(`"${label}" needs a number.`);
    return n;
  };
  const label = (k: FormKey) => GROUPS.flatMap((g) => g.fields).find((f) => f.key === k)!.label;
  return {
    labour_over_benchmark_pct: num("labour_over_benchmark_pct", label("labour_over_benchmark_pct")),
    labour_min_samples: num("labour_min_samples", label("labour_min_samples")),
    repeat_repair_days: num("repeat_repair_days", label("repeat_repair_days")),
    repeat_repair_miles: num("repeat_repair_miles", label("repeat_repair_miles")),
    repeat_condition: v.repeat_condition === "and" ? "and" : "or",
    parts_outlier_pct: round((num("parts_multiplier", label("parts_multiplier")) - 1) * 100),
    parts_single_shop_multiple: num("parts_single_shop_multiple", label("parts_single_shop_multiple")),
    parts_min_samples: num("parts_min_samples", label("parts_min_samples")),
    math_tolerance: num("math_tolerance", label("math_tolerance")),
    duplicate_window_days: num("duplicate_window_days", label("duplicate_window_days")),
  };
}

export default function ThresholdsSection({ cid, admin }: { cid: string; admin: boolean }) {
  const markStale = useProgress()?.markChecksStale;
  const [saved, setSaved] = useState<Values | null>(null);
  const [vals, setVals] = useState<Values | null>(null);
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.client(cid).then((c) => {
    if (!c.settings) throw new Error("This client's thresholds couldn't be read.");
    const v = toValues(c.settings);
    setSaved(v); setVals(v);
  }).catch((e) => setMsg({ text: e instanceof Error ? e.message : "Couldn't load the thresholds.", error: true })), [cid]);
  useEffect(() => { load(); }, [load]);

  const changed = (k: keyof Values) => !!vals && !!saved && vals[k] !== saved[k];
  const dirty = !!vals && !!saved && (Object.keys(vals) as (keyof Values)[]).some(changed);
  const set = (k: keyof Values, v: string) => { setMsg(null); setVals((p) => (p ? { ...p, [k]: v } : p)); };

  async function save() {
    if (!vals) return;
    setMsg(null); setBusy(true);
    try {
      const c = await api.updateSettings(cid, toPayload(vals));
      const v = toValues(c.settings!);
      setSaved(v); setVals(v);
      markStale?.(cid);
      setMsg({ text: "Thresholds saved. The checks run again the next time you open Review flags." });
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : "The thresholds didn't save. Try again.", error: true }); }
    finally { setBusy(false); }
  }

  async function fromFile(f: File) {
    const r = await api.importThresholds(cid, f);
    const s = r.settings;
    setMsg(null);
    setVals((p) => {
      if (!p) return p;
      const n = { ...p };
      if (s.labour_over_benchmark_pct !== undefined) n.labour_over_benchmark_pct = String(s.labour_over_benchmark_pct);
      if (s.labour_min_samples !== undefined) n.labour_min_samples = String(s.labour_min_samples);
      if (s.repeat_repair_days !== undefined) n.repeat_repair_days = String(s.repeat_repair_days);
      if (s.repeat_repair_miles !== undefined) n.repeat_repair_miles = String(s.repeat_repair_miles);
      if (s.parts_outlier_pct !== undefined) n.parts_multiplier = String(round(1 + s.parts_outlier_pct / 100));
      if (s.parts_single_shop_multiple !== undefined) n.parts_single_shop_multiple = String(s.parts_single_shop_multiple);
      if (s.parts_min_samples !== undefined) n.parts_min_samples = String(s.parts_min_samples);
      if (s.duplicate_window_days !== undefined) n.duplicate_window_days = String(s.duplicate_window_days);
      return n;
    });
    const n = r.applied.length;
    return {
      message: `Read ${n} ${n === 1 ? "value" : "values"} from the file into the form below. Look them over, then press Save thresholds.`,
      details: [{ title: "In the file but not used here", items: r.ignored }],
    };
  }

  return (
    <section className="mt-10" aria-labelledby="thr-h" id="thresholds">
      <h3 id="thr-h" className="text-lg">Thresholds</h3>
      <p className="mt-1 max-w-prose text-muted">
        {admin ? "How far from normal a bill has to be before a check flags it. Change a value and save, or read the values from a thresholds file." : "These limits are set by an admin. You can read them here but not change them."}
      </p>
      {admin && (
        <ImportPanel testId="thresholds-import" label="Read values from a file" accept=".json,application/json" onImport={fromFile}
          help={<>Choose a thresholds file (JSON, like <b>thresholds_and_rules.json</b>). Its values fill the form; nothing is saved until you press Save thresholds.</>} />
      )}
      {vals && (
        <form className="mt-6" noValidate onSubmit={(e) => { e.preventDefault(); save(); }} data-testid="thresholds-form">
          <div className="grid gap-x-8 gap-y-8 md:grid-cols-2">
            {GROUPS.map((g) => (
              <fieldset key={g.title} className="min-w-0">
                <legend className="text-base font-bold">{g.title}</legend>
                <div className="mt-3 flex flex-col gap-4">
                  {g.fields.map((f) => (
                    <div key={f.key}>
                      <label htmlFor={`thr-${f.key}`} className="mb-1 block text-sm font-medium">{f.label}</label>
                      <div className="flex items-center gap-2">
                        <input id={`thr-${f.key}`} type="number" inputMode="decimal" step={f.step ?? "1"} disabled={!admin}
                          className={`field num max-w-[160px] ${changed(f.key) ? "border-amber bg-amber-soft" : ""}`}
                          value={vals[f.key]} onChange={(e) => set(f.key, e.target.value)} aria-describedby={`thr-${f.key}-h`} />
                        {f.unit && <span className="text-muted">{f.unit}</span>}
                        {changed(f.key) && <span className="rounded-full bg-amber-soft px-2 py-0.5 text-xs font-medium">changed</span>}
                      </div>
                      <p id={`thr-${f.key}-h`} className="mt-1 text-sm text-muted">{f.hint}</p>
                    </div>
                  ))}
                  {g.title === "Repeat repairs" && (
                    <div>
                      <label htmlFor="thr-repeat_condition" className="mb-1 block text-sm font-medium">Both limits, or either?</label>
                      <select id="thr-repeat_condition" disabled={!admin} className={`field max-w-[320px] ${changed("repeat_condition") ? "border-amber bg-amber-soft" : ""}`}
                        value={vals.repeat_condition} onChange={(e) => set("repeat_condition", e.target.value)} aria-describedby="thr-repeat_condition-h">
                        <option value="or">Days OR miles: either one is enough</option>
                        <option value="and">Days AND miles: both must be inside</option>
                      </select>
                      <p id="thr-repeat_condition-h" className="mt-1 text-sm text-muted">With AND, a unit with no odometer reading is checked by days alone.</p>
                    </div>
                  )}
                </div>
              </fieldset>
            ))}
          </div>
          {admin && (
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button type="submit" className="btn-primary" disabled={!dirty || busy}>{busy ? "Saving…" : "Save thresholds"}</button>
              {dirty && <button type="button" className="btn-secondary" disabled={busy} onClick={() => { setVals(saved); setMsg(null); }}>Discard changes</button>}
              {dirty && <span className="text-sm text-muted">You have changes that are not saved yet.</span>}
            </div>
          )}
        </form>
      )}
      {!vals && !msg && <p className="mt-4 text-muted" role="status">Loading thresholds…</p>}
      {msg && <p role={msg.error ? "alert" : "status"} className={`mt-3 font-medium ${msg.error ? "text-danger" : "text-confirmed"}`}>{msg.text}</p>}
    </section>
  );
}
