"""Rule 6: arithmetic that doesn't add up (line maths, lines vs subtotal, subtotal + tax vs total)."""

from decimal import Decimal

from ..types import Context, FlagDraft, money


def _line_gap(ln) -> Decimal | None:
    """How much the printed line total is ABOVE its parts + labour (over-billing), or None when the line can't be checked.

    With both parts and labour visible, a total above what they add up to counts. With only one of them visible the line may
    also carry a charge we can't see (lump-sum labour, shop fees), so only a total that is *lower* than what is visible counts.
    A parts price of 0.0 is read as "no parts price printed": models fill the field with 0.0 on lines that have none.
    Parts price is read as unit or extended, whichever fits better."""
    if ln.line_total is None:
        return None
    price = ln.parts_price if ln.parts_price else None
    lab = ln.labour_hours * ln.labour_rate if ln.labour_hours is not None and ln.labour_rate is not None else None
    if price is None and lab is None:
        return None
    qty = ln.qty if ln.qty and ln.qty > 0 else Decimal(1)
    labv = lab or Decimal(0)
    cands = [qty * price + labv, price + labv] if price is not None else [labv]
    if price is not None and lab is not None:
        if any(abs(c - ln.line_total) <= Decimal("0.005") for c in cands):
            return Decimal(0)
        return max(ln.line_total - max(cands), Decimal(0))      # over-billing only: a total below the expected amount is not money owed back
    short = [c - ln.line_total for c in cands if c - ln.line_total > 0]
    return min(short) if len(short) == len(cands) else Decimal(0)


def run(ctx: Context) -> list[FlagDraft]:
    tol = Decimal(str(ctx.config["math_tolerance"]))
    out: list[FlagDraft] = []
    line_gaps: dict[str, list[Decimal]] = {}
    for inv in ctx.invoices:
        for ln in inv.lines:
            gap = _line_gap(ln)
            if gap is not None and gap > tol:
                line_gaps.setdefault(inv.id, []).append(gap)
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
        lines_known = bool(inv.lines) and all(t is not None for t in lts)
        line_sum = sum(lts, Decimal(0)) if lines_known else None
        # Most shops print "Parts / Labor / Tax / TOTAL DUE" and no Subtotal row, so a stored subtotal can really be one of those footer
        # rows. When the lines plus tax already equal the total, the invoice adds up and the subtotal is the doubtful number, not the shop.
        consistent = lines_known and inv.total is not None and abs(line_sum + (inv.tax or Decimal(0)) - inv.total) <= tol
        if not consistent:
            if inv.subtotal is not None:
                if lines_known and inv.subtotal - line_sum > tol:
                    findings.append(("lines_vs_subtotal", inv.subtotal - line_sum, "the lines don't add up to the subtotal"))
                if inv.total is not None and inv.tax is not None and inv.total - (inv.subtotal + inv.tax) > tol:
                    findings.append(("subtotal_tax_vs_total", inv.total - (inv.subtotal + inv.tax), "the subtotal plus tax doesn't equal the total"))
            elif lines_known and inv.total is not None and inv.tax is not None and inv.total - (line_sum + inv.tax) > tol:
                findings.append(("lines_tax_vs_total", inv.total - (line_sum + inv.tax), "the lines plus tax don't equal the total"))
        if findings:
            covered = sum((g for g in line_gaps.get(inv.id, [])), Decimal(0))                 # dollars a line flag on this invoice already reports
            impact = (max(f[1] for f in findings) - covered).quantize(Decimal("0.01"))      # one flag per invoice; don't stack overlapping gaps
            if impact <= tol:
                continue
            what = " and ".join(f[2] for f in findings)
            out.append(FlagDraft(
                type="math_error", invoice_id=inv.id, line_id=None, impact=impact, dedupe_key=f"math_hdr:{inv.id}",
                evidence={"check": "totals", "findings": [{"check": c, "difference": float(d)} for c, d, _ in findings],
                          "subtotal": float(inv.subtotal) if inv.subtotal is not None else None, "tax": float(inv.tax) if inv.tax is not None else None,
                          "total": float(inv.total) if inv.total is not None else None},
                template_reason=f"On this invoice {what}. Possible maths error of {money(impact)}.",
            ))
    return out
