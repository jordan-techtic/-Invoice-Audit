"""Rule 5: the same invoice billed twice, or the same line twice on one invoice."""

from __future__ import annotations

from decimal import Decimal

from ..types import Context, FlagDraft, InvoiceView, line_amount, money


def _num(s: str | None) -> str | None:
    return "".join(ch for ch in s.upper() if ch.isalnum()) if s else None


def run(ctx: Context) -> list[FlagDraft]:
    out: list[FlagDraft] = []
    invs = sorted(ctx.invoices, key=lambda i: i.order)
    flagged: set[str] = set()

    def group_by(keyfn) -> None:
        groups: dict[tuple, list[InvoiceView]] = {}
        for inv in invs:
            k = keyfn(inv)
            if k:
                groups.setdefault(k, []).append(inv)
        for members in groups.values():
            first = members[0]
            for dup in members[1:]:
                if dup.id in flagged:
                    continue
                flagged.add(dup.id)
                amt = dup.total if dup.total is not None else Decimal(0)
                how = keyfn.__name__
                out.append(FlagDraft(
                    type="duplicate", invoice_id=dup.id, line_id=None, related_invoice_id=first.id, impact=amt,
                    dedupe_key=f"dup_invoice:{dup.id}",
                    evidence={"match": how, "invoice_number": dup.invoice_number, "original_invoice_number": first.invoice_number,
                              "date": str(dup.invoice_date), "total": float(amt)},
                    template_reason=(f"Invoice {dup.invoice_number or ''} looks like a likely duplicate of an invoice already processed "
                                     f"({'same shop and invoice number' if how == 'same_number' else 'same shop, unit, date and total'}). "
                                     f"Possible double billing of {money(amt)}.").replace("Invoice  looks", "This invoice looks"),
                ))

    def same_number(i: InvoiceView):
        return (i.shop_key, _num(i.invoice_number)) if i.shop_key and _num(i.invoice_number) else None

    def same_job(i: InvoiceView):
        return (i.shop_key, i.unit_key, i.invoice_date, i.total) if i.shop_key and i.unit_key and i.invoice_date and i.total else None

    group_by(same_number)
    group_by(same_job)

    for inv in invs:
        if inv.id in flagged:
            continue
        seen: dict[tuple, str] = {}
        for ln in inv.lines:
            amt = line_amount(ln)
            if amt <= 0 or not ln.description:
                continue
            k = (ln.description.strip().lower(), _num(ln.part_number), ln.qty, ln.parts_price, ln.labour_hours, ln.labour_rate, ln.line_total)
            if k in seen:
                out.append(FlagDraft(
                    type="duplicate", invoice_id=inv.id, line_id=ln.id, impact=amt, dedupe_key=f"dup_line:{ln.id}",
                    evidence={"match": "identical_line", "description": ln.description, "amount": float(amt), "first_line_no": seen[k]},
                    template_reason=f"This line appears twice with identical details, so it is a likely duplicate. Possible double billing of {money(amt)}.",
                ))
            else:
                seen[k] = ln.line_no
    return out
