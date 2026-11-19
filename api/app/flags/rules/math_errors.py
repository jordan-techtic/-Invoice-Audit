"""Rule 6: arithmetic that doesn't add up (line maths, lines vs subtotal, subtotal + tax vs total)."""

from decimal import Decimal

from ..types import Context, FlagDraft, money


def _line_gap(ln) -> Decimal | None:
    """Gap between the printed line total and its parts + labour, or None when the line can't be checked.

    With both parts and labour visible, any mismatch counts. With only one of them visible the line may also carry a
    charge we can't see (lump-sum labour, shop fees), so only a total that is *lower* than what is visible counts.
    Parts price is read as unit or extended, whichever fits better."""
    if ln.line_total is None:
        return None
    lab = ln.labour_hours * ln.labour_rate if ln.labour_hours is not None and ln.labour_rate is not None else None
    if ln.parts_price is None and lab is None:
        return None
    qty = ln.qty if ln.qty and ln.qty > 0 else Decimal(1)
    labv = lab or Decimal(0)
    cands = [qty * ln.parts_price + labv, ln.parts_price + labv] if ln.parts_price is not None else [labv]
    if ln.parts_price is not None and lab is not None:
        return min(abs(c - ln.line_total) for c in cands)
    short = [c - ln.line_total for c in cands if c - ln.line_total > 0]
    return min(short) if len(short) == len(cands) else Decimal(0)


def run(ctx: Context) -> list[FlagDraft]:
    tol = Decimal(str(ctx.config["math_tolerance"]))
    out: list[FlagDraft] = []
    for inv in ctx.invoices:
        for ln in inv.lines:
            gap = _line_gap(ln)
            if gap is not None and gap > tol:
                out.append(FlagDraft(
                    type="math_error", invoice_id=inv.id, line_id=ln.id, impact=gap.quantize(Decimal("0.01")), dedupe_key=f"math_line:{ln.id}",
                    evidence={"check": "line_total", "printed_total": float(ln.line_total), "qty": float(ln.qty) if ln.qty is not None else None,
                              "parts_price": float(ln.parts_price) if ln.parts_price is not None else None,
                              "labour_hours": float(ln.labour_hours) if ln.labour_hours is not None else None,
                              "labour_rate": float(ln.labour_rate) if ln.labour_rate is not None else None, "difference": float(gap)},
                    template_reason=f"The quantity, price and hours on this line don't add up to the printed total. Possible maths error of {money(gap)}.",
                ))
        findings: list[tuple[str, Decimal, str]] = []
        lts = [ln.line_total for ln in inv.lines]
        if inv.subtotal is not None and inv.lines and all(t is not None for t in lts):
            diff = abs(sum(lts, Decimal(0)) - inv.subtotal)
            if diff > tol:
                findings.append(("lines_vs_subtotal", diff, "the lines don't add up to the subtotal"))
        if inv.subtotal is not None and inv.total is not None:
            diff = abs(inv.subtotal + (inv.tax or Decimal(0)) - inv.total)
            if diff > tol:
                findings.append(("subtotal_tax_vs_total", diff, "the subtotal plus tax doesn't equal the total"))
        if findings:
            impact = max(f[1] for f in findings).quantize(Decimal("0.01"))  # one flag per invoice; don't stack overlapping gaps
            what = " and ".join(f[2] for f in findings)
            out.append(FlagDraft(
                type="math_error", invoice_id=inv.id, line_id=None, impact=impact, dedupe_key=f"math_hdr:{inv.id}",
                evidence={"check": "totals", "findings": [{"check": c, "difference": float(d)} for c, d, _ in findings],
                          "subtotal": float(inv.subtotal) if inv.subtotal is not None else None, "tax": float(inv.tax) if inv.tax is not None else None,
                          "total": float(inv.total) if inv.total is not None else None},
                template_reason=f"On this invoice {what}. Possible maths error of {money(impact)}.",
            ))
    return out
