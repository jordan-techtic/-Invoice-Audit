"""Rule 3: a component replaced again while the earlier replacement should still be under warranty."""

from decimal import Decimal

from ..types import Context, FlagDraft, money, parts_amount
from .history import history, prior_repair, repair_amount, repair_lines

DAYS_PER_MONTH = 30.4375


def run(ctx: Context) -> list[FlagDraft]:
    out: list[FlagDraft] = []
    for (unit, code), entries in history(ctx.invoices).items():
        rule = ctx.warranty.get(code)
        if rule is None:
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
            if p.days > rule.months * DAYS_PER_MONTH:
                continue
            if rule.miles is not None and p.miles is not None and p.miles > rule.miles:
                continue
            impact = total_amount
            if rule.covers == "parts":  # the warranty pays for the parts only, so only the parts are claimable
                impact = sum((parts_amount(l) for l in repair_lines(entries, i)), Decimal(0))
                if impact <= 0:
                    continue
            out.append(FlagDraft(
                type="warranty_eligible", invoice_id=inv.id, line_id=ln.id, related_invoice_id=p.invoice.id, impact=impact,
                dedupe_key=f"warranty:{ln.id}",
                evidence={"vmrs_code": code, "component": rule.component, "unit": unit, "warranty_months": rule.months, "warranty_miles": rule.miles,
                          "days_since_previous": p.days, "miles_since_previous": p.miles, "previous_invoice": p.invoice.invoice_number,
                          "previous_date": str(p.invoice.invoice_date), "claimable": float(impact), "covers": rule.covers},
                template_reason=(f"The {rule.component.lower()} was likely replaced again {p.days} days after the previous replacement, "
                                 f"inside a {rule.months}-month warranty. Possible warranty claim of {money(impact)}"
                                 f"{' (parts only)' if rule.covers == 'parts' else ''}."),
            ))
    return out
