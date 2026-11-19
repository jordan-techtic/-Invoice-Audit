"""Rule 2: the same component repaired again on the same unit within X days or X miles."""

from ..types import Context, FlagDraft, money
from .history import history, prior_repair, repair_amount


def run(ctx: Context) -> list[FlagDraft]:
    days_limit = int(ctx.config["repeat_repair_days"])
    miles_limit = int(ctx.config["repeat_repair_miles"])
    exclude = set(ctx.config.get("repeat_exclude_codes", []))
    out: list[FlagDraft] = []
    for (unit, code), entries in history(ctx.invoices).items():
        if code in exclude:
            continue
        seen_repairs: set[str] = set()
        for i, (inv, ln) in enumerate(entries):
            if inv.id in seen_repairs:
                continue  # one flag per repair, however many lines it has
            seen_repairs.add(inv.id)
            ln, total_amount = repair_amount(entries, i)
            p = prior_repair(entries, i)
            if p is None or p.days < 0:
                continue
            within_days = p.days <= days_limit
            within_miles = p.miles is not None and 0 <= p.miles <= miles_limit
            if not (within_days or within_miles):
                continue
            impact = total_amount
            name = ctx.code_names.get(code, "This component")
            when = f"{p.days} days" + (f" and {p.miles:,} miles" if p.miles is not None and p.miles >= 0 else "")
            out.append(FlagDraft(
                type="repeat_repair", invoice_id=inv.id, line_id=ln.id, related_invoice_id=p.invoice.id, impact=impact,
                dedupe_key=f"repeat:{ln.id}",
                evidence={"vmrs_code": code, "job": name, "unit": unit, "days_since_previous": p.days, "miles_since_previous": p.miles,
                          "previous_invoice": p.invoice.invoice_number, "previous_date": str(p.invoice.invoice_date),
                          "limit_days": days_limit, "limit_miles": miles_limit, "line_total": float(impact)},
                template_reason=(f"{name} was likely repaired again on the same unit {when} after the previous repair. "
                                 f"Possible repeat repair worth {money(impact)}."),
            ))
    return out
