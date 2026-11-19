"""Rule 4: unit price well above the usual price for the same part number."""

from decimal import Decimal

from ..types import Context, FlagDraft, money, norm_part, unit_price_candidates


def run(ctx: Context) -> list[FlagDraft]:
    pct = Decimal(str(ctx.config["parts_outlier_pct"]))
    single_mult = Decimal(str(ctx.config["parts_single_shop_multiple"]))
    out: list[FlagDraft] = []
    for inv in ctx.invoices:
        for ln in inv.lines:
            key = norm_part(ln.part_number)
            base = ctx.baselines.get(key) if key else None
            cands = unit_price_candidates(ln)
            if base is None or not cands:
                continue
            price = min(cands, key=lambda c: abs(c - base.median))  # ambiguous unit/extended price: give the shop the benefit of the doubt
            limit = base.median * (single_mult if base.shops <= 1 else 1 + pct / 100)
            if price <= limit:
                continue
            qty = ln.qty if ln.qty and ln.qty > 0 else Decimal(1)
            impact = ((price - base.median) * qty).quantize(Decimal("0.01"))
            over = (price / base.median - 1) * 100
            out.append(FlagDraft(
                type="parts_price_outlier", invoice_id=inv.id, line_id=ln.id, impact=impact, dedupe_key=f"parts:{ln.id}",
                evidence={"part_number": ln.part_number, "unit_price": float(price.quantize(Decimal("0.01"))), "median_price": float(base.median),
                          "over_pct": round(float(over), 1), "qty": float(qty), "samples": base.samples, "shops_selling": base.shops},
                template_reason=(f"Part {ln.part_number} was billed at {money(price)} each; it usually costs about {money(base.median)}. "
                                 f"Possible overpricing of {money(impact)}."),
            ))
    return out
