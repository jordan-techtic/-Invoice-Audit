"""Rule 1: labour hours billed are well above what this job usually takes."""

from decimal import Decimal

from ..types import Context, FlagDraft, hrs, money


def run(ctx: Context) -> list[FlagDraft]:
    pct = Decimal(str(ctx.config["labour_over_benchmark_pct"]))
    out: list[FlagDraft] = []
    no_data: set[str] = set()
    for inv in ctx.invoices:
        for ln in inv.lines:
            if ln.labour_hours is None or ln.labour_rate is None or not ln.vmrs_code:
                continue
            cls = inv.vehicle_class
            bench = ctx.class_benchmarks.get((ln.vmrs_code, cls)) if cls else None  # same job, same kind of vehicle
            by_class = bench is not None
            if bench is None:
                bench = ctx.benchmarks.get(ln.vmrs_code)
            if bench is None:
                no_data.add(ln.vmrs_code)
                continue
            if ln.labour_hours > bench * (1 + pct / 100):
                extra = ln.labour_hours - bench
                impact = (extra * ln.labour_rate).quantize(Decimal("0.01"))
                over = ((ln.labour_hours / bench) - 1) * 100
                out.append(FlagDraft(
                    type="labour_over_benchmark", invoice_id=inv.id, line_id=ln.id, impact=impact,
                    dedupe_key=f"labour:{ln.id}",
                    evidence={"vmrs_code": ln.vmrs_code, "job": ctx.code_names.get(ln.vmrs_code), "billed_hours": float(ln.labour_hours),
                              "benchmark_hours": float(bench), "over_pct": round(float(over), 1), "labour_rate": float(ln.labour_rate),
                              "threshold_pct": float(pct), **({"vehicle_class": cls} if by_class else {})},
                    template_reason=(f"Billed {hrs(ln.labour_hours)} hrs for a job that typically takes {hrs(bench)} hrs. "
                                     f"Possible overbilling of {hrs(extra)} hrs x {money(ln.labour_rate)} = {money(impact)}."),
                ))
    if no_data:
        ctx.notes.append(f"Labour check skipped for {len(no_data)} job type(s): not enough data to set a typical time.")
    return out
