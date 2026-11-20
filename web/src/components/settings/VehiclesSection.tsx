"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Vehicle } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import { IconPlus } from "@/components/Icons";
import { useProgress } from "@/lib/progress";
import ImportPanel from "./ImportPanel";

const label = (c: string | null) => (c ? c.replace(/_/g, " ") : "not set");
const EMPTY = { unit_number: "", vehicle_class: "", vin: "", year: "", make: "", model: "", start_odometer: "" };
type Draft = typeof EMPTY;

export default function VehiclesSection({ cid, admin }: { cid: string; admin: boolean }) {
  const markStale = useProgress()?.markChecksStale;
  const [rows, setRows] = useState<Vehicle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Vehicle | null>(null);   // null while adding a new one
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [remove, setRemove] = useState<null | Vehicle | "all">(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  const load = useCallback(() => api.vehicles(cid).then((r) => { setRows(r); setError(null); }).catch((e) => setError(e instanceof Error ? e.message : "Couldn't load the vehicles.")), [cid]);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    (rows ?? []).forEach((v) => m.set(label(v.vehicle_class), (m.get(label(v.vehicle_class)) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [rows]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter((v) => !needle || [v.unit_number, v.vin, v.vehicle_class, v.make, v.model].some((x) => x?.toLowerCase().includes(needle)));
  }, [rows, q]);

  async function importFile(f: File) {
    const r = await api.importVehicles(cid, f);
    await load();
    markStale?.(cid);
    return {
      message: `Imported ${r.rows} ${r.rows === 1 ? "vehicle" : "vehicles"}: ${r.added} added, ${r.updated} updated. ${r.total_vehicles} on the list now.`,
      details: [{ title: "Worth a look", items: r.warnings.map((w) => `Row ${w.row}: ${w.message}`) }],
    };
  }

  function openForm(v: Vehicle | null) {
    setEditing(v);
    setFormError(null);
    setDraft(v ? { unit_number: v.unit_number, vehicle_class: v.vehicle_class ?? "", vin: v.vin ?? "", year: v.year?.toString() ?? "", make: v.make ?? "", model: v.model ?? "", start_odometer: v.start_odometer?.toString() ?? "" } : EMPTY);
    dialog.current?.showModal();
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const num = (s: string, name: string) => {
      if (!s.trim()) return null;
      const n = Number(s);
      if (!Number.isFinite(n)) throw new Error(`${name} needs a number.`);
      return n;
    };
    setBusy(true); setFormError(null);
    try {
      const body = { unit_number: draft.unit_number, vehicle_class: draft.vehicle_class, vin: draft.vin.trim() || null, year: num(draft.year, "Year"),
        make: draft.make.trim() || null, model: draft.model.trim() || null, start_odometer: num(draft.start_odometer, "Start odometer") };
      if (editing) await api.updateVehicle(cid, editing.id, body); else await api.addVehicle(cid, body);
      dialog.current?.close();
      markStale?.(cid);
      await load();
      setNotice(editing ? `Saved ${draft.unit_number}.` : `Added ${draft.unit_number}.`);
    } catch (err) { setFormError(err instanceof Error ? err.message : "That didn't save. Try again."); }
    finally { setBusy(false); }
  }

  async function doRemove() {
    let said = "";
    if (remove === "all") { const r = await api.deleteAllVehicles(cid); said = `Removed ${r.removed} ${r.removed === 1 ? "vehicle" : "vehicles"}.`; }
    else if (remove) { await api.deleteVehicle(cid, remove.id); said = `Removed ${remove.unit_number}.`; }
    setRemove(null);
    markStale?.(cid);
    await load();
    setNotice(said);
  }

  const field = (k: keyof Draft, text: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <div>
      <label htmlFor={`veh-${k}`} className="mb-1 block text-sm font-medium">{text}</label>
      <input id={`veh-${k}`} className="field" value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} {...extra} />
    </div>
  );

  return (
    <section className="mt-14" aria-labelledby="veh-h" id="vehicles">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <h3 id="veh-h" className="text-lg">Vehicles</h3>
          <p className="mt-1 max-w-prose text-muted">
            The fleet list. The checks use each unit&apos;s class to compare labour with the same kind of vehicle and to check trailers for repeats by days only,
            and the VIN to find the unit on an invoice that prints only the VIN.
          </p>
        </div>
        {admin && <button className="btn-primary" onClick={() => openForm(null)} aria-haspopup="dialog"><IconPlus />Add vehicle</button>}
      </div>
      {admin && (
        <ImportPanel testId="vehicles-import" label="Import vehicles (CSV)" onImport={importFile}
          help={<>Columns: <b>unit</b>, <b>vehicle_class</b> (required); <b>vin</b>, <b>year</b>, <b>make</b>, <b>model</b>, <b>start_odometer</b> (optional). Units already on the list are updated; none are removed.</>} />
      )}
      {error && <p role="alert" className="mt-3 text-danger">{error}</p>}
      {notice && <p role="status" className="mt-3 font-medium text-confirmed">{notice}</p>}
      {rows && rows.length === 0 && <p className="mt-4 text-lg">No vehicles yet.{admin ? " Add one, or import a CSV." : ""}</p>}
      {rows && rows.length > 0 && (
        <>
          <p className="mt-5 font-medium" data-testid="vehicle-summary">
            {rows.length} {rows.length === 1 ? "vehicle" : "vehicles"}
            <span className="font-normal text-muted"> · {counts.map(([c, n]) => `${n} ${c}`).join(" · ")}</span>
          </p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="w-full sm:w-[320px]">
              <label htmlFor="veh-search" className="sr-only">Search vehicles</label>
              <input id="veh-search" type="search" className="field" placeholder="Search unit, VIN, class or make" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {admin && <button className="btn-danger btn-sm" onClick={() => setRemove("all")}>Remove all vehicles</button>}
          </div>
          <div className="mt-3 max-h-[420px] overflow-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[820px] border-collapse" data-testid="vehicle-table">
              <caption className="sr-only">Vehicles</caption>
              <thead className="sticky top-0 bg-surface">
                <tr>
                  <th className="th" scope="col">Unit</th><th className="th" scope="col">Class</th><th className="th" scope="col">VIN</th>
                  <th className="th text-right" scope="col">Year</th><th className="th" scope="col">Make and model</th><th className="th text-right" scope="col">Start odometer</th>
                  {admin && <th className="th" scope="col"><span className="sr-only">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {shown.map((v) => (
                  <tr key={v.id} className="tr">
                    <td className="td num font-medium">{v.unit_number}</td>
                    <td className="td capitalize">{label(v.vehicle_class)}</td>
                    <td className="td num">{v.vin ?? ""}</td>
                    <td className="td num text-right">{v.year ?? ""}</td>
                    <td className="td">{[v.make, v.model].filter(Boolean).join(" ")}</td>
                    <td className="td num text-right">{v.start_odometer == null ? "" : v.start_odometer.toLocaleString("en-US")}</td>
                    {admin && (
                      <td className="td whitespace-nowrap text-right">
                        <button className="btn-secondary btn-sm mr-2" onClick={() => openForm(v)} aria-label={`Edit ${v.unit_number}`}>Edit</button>
                        <button className="btn-danger btn-sm" onClick={() => setRemove(v)} aria-label={`Remove ${v.unit_number}`}>Remove</button>
                      </td>
                    )}
                  </tr>
                ))}
                {shown.length === 0 && <tr><td className="td text-muted" colSpan={admin ? 7 : 6}>No vehicle matches that search.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}

      <dialog ref={dialog} aria-labelledby="veh-dialog-h" className="w-[min(560px,94vw)] rounded-lg border border-line-strong bg-surface p-0 text-ink backdrop:bg-ink/40"
        onClick={(e) => { if (e.target === dialog.current) dialog.current?.close(); }}>
        <form onSubmit={save} className="p-6" noValidate>
          <h2 id="veh-dialog-h" className="text-lg">{editing ? `Edit ${editing.unit_number}` : "Add vehicle"}</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {field("unit_number", "Unit number", { autoFocus: true, autoComplete: "off" })}
            {field("vehicle_class", "Vehicle class", { placeholder: "tractor, trailer, box_truck, van", list: "veh-classes", autoComplete: "off" })}
            {field("vin", "VIN (optional)", { autoComplete: "off", maxLength: 17 })}
            {field("year", "Year (optional)", { inputMode: "numeric" })}
            {field("make", "Make (optional)")}
            {field("model", "Model (optional)")}
            {field("start_odometer", "Start odometer (optional)", { inputMode: "numeric" })}
          </div>
          <datalist id="veh-classes">{[...new Set((rows ?? []).map((v) => v.vehicle_class).filter(Boolean))].map((c) => <option key={c} value={c!} />)}</datalist>
          {formError && <p role="alert" className="mt-3 text-danger">{formError}</p>}
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button type="button" className="btn-secondary" onClick={() => dialog.current?.close()}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={busy || !draft.unit_number.trim() || !draft.vehicle_class.trim()}>{busy ? "Saving…" : editing ? "Save" : "Add vehicle"}</button>
          </div>
        </form>
      </dialog>

      <ConfirmDialog open={remove !== null} danger
        title={remove === "all" ? `Remove all ${rows?.length ?? 0} vehicles?` : `Remove ${remove?.unit_number ?? ""}?`}
        body={remove === "all" ? "This empties the fleet list. Invoices keep the unit numbers printed on them. You can import or add vehicles again at any time."
          : "This takes the vehicle off the fleet list. Invoices keep the unit number printed on them."}
        confirmWord={remove === "all" ? "REMOVE" : undefined} actionLabel={remove === "all" ? "Remove all" : "Remove"} onConfirm={doRemove} onClose={() => setRemove(null)} />
    </section>
  );
}
