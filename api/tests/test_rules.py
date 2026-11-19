from decimal import Decimal as D

from app.flags.engine import run_rules
from app.flags.rules import duplicate, labour, math_errors, parts_price, repeat, warranty
from app.flags.types import Baseline

from .flag_helpers import I, L, ctx, d, rule

ALT, PUMP, PM = "031-001-001", "042-001-002", "045-001-001"


# ---------------------------------------------------------------- rule 1: labour
def test_labour_flags_when_over_threshold_with_impact():
    c = ctx([I(lines=[L(code=ALT, hours=8, rate=110)])], benchmarks={ALT: D("5.0")})
    f = labour.run(c)
    assert len(f) == 1 and f[0].impact == D("330.00") and f[0].type == "labour_over_benchmark"
    assert f[0].template_reason == "Billed 8.0 hrs for a job that typically takes 5.0 hrs. Possible overbilling of 3.0 hrs x $110 = $330."


def test_labour_within_threshold_is_not_flagged():
    assert labour.run(ctx([I(lines=[L(code=ALT, hours=5.9, rate=110)])], benchmarks={ALT: D("5.0")})) == []  # 18% over < 20%


def test_labour_threshold_is_configurable_per_client():
    c = ctx([I(lines=[L(code=ALT, hours=5.6, rate=100)])], benchmarks={ALT: D("5.0")}, cfg={"labour_over_benchmark_pct": 10})
    assert len(labour.run(c)) == 1


def test_labour_skips_with_note_when_no_benchmark():
    c = ctx([I(lines=[L(code=ALT, hours=8, rate=110)])])
    assert labour.run(c) == [] and "not enough data" in c.notes[0]


# ---------------------------------------------------------------- rule 2: repeat
def _two(code, d1, d2, o1=None, o2=None, **kw):
    return [I("a", 0, num="1", dt=d1, odo=o1, lines=[L("a", code=code, total=300)]),
            I("b", 1, num="2", dt=d2, odo=o2, lines=[L("b", code=code, total=450, **kw)])]


def test_repeat_within_days_flags_the_later_repair_with_its_total():
    f = repeat.run(ctx(_two(PUMP, d(2026, 1, 1), d(2026, 2, 15))))
    assert len(f) == 1 and f[0].invoice_id == "b" and f[0].impact == D("450") and f[0].related_invoice_id == "a"


def test_repeat_within_miles_flags_even_if_days_are_long():
    assert len(repeat.run(ctx(_two(PUMP, d(2026, 1, 1), d(2026, 9, 1), 100000, 107000)))) == 1


def test_repeat_outside_both_limits_is_not_flagged():
    assert repeat.run(ctx(_two(PUMP, d(2026, 1, 1), d(2026, 9, 1), 100000, 125000))) == []


def test_repeat_ignores_routine_work_like_pm_service():
    assert repeat.run(ctx(_two(PM, d(2026, 1, 1), d(2026, 2, 1)))) == []


def test_repeat_gives_one_flag_per_repair_with_the_combined_amount():
    later = I("b", 1, num="2", dt=d(2026, 2, 1), lines=[L("b", 1, code=PUMP, total=100), L("b", 2, code=PUMP, total=50)])
    f = repeat.run(ctx([I("a", 0, num="1", dt=d(2026, 1, 1), lines=[L("a", code=PUMP, total=100)]), later]))
    assert len(f) == 1 and f[0].impact == D("150") and f[0].line_id == "b-l1"


def test_repeat_ignores_two_lines_on_the_same_invoice_and_other_units():
    same = I("a", 0, num="1", dt=d(2026, 1, 1), lines=[L("a", 1, code=PUMP, total=100), L("a", 2, code=PUMP, total=100)])
    assert repeat.run(ctx([same])) == []
    other = [_two(PUMP, d(2026, 1, 1), d(2026, 1, 20))[0], I("b", 1, num="2", dt=d(2026, 1, 20), unit="T2", lines=[L("b", code=PUMP, total=1)])]
    assert repeat.run(ctx(other)) == []


# ---------------------------------------------------------------- rule 3: warranty
def test_warranty_inside_window_flags_with_claimable_amount():
    f = warranty.run(ctx(_two(ALT, d(2026, 1, 1), d(2026, 7, 20), 100000, 140000), warranty=rule()))
    assert len(f) == 1 and f[0].impact == D("450") and f[0].evidence["warranty_months"] == 12


def test_warranty_outside_months_or_miles_is_not_flagged():
    assert warranty.run(ctx(_two(ALT, d(2025, 1, 1), d(2026, 7, 20)), warranty=rule())) == []                       # 18 months
    assert warranty.run(ctx(_two(ALT, d(2026, 1, 1), d(2026, 7, 20), 100000, 230000), warranty=rule())) == []       # 130k miles


def test_warranty_needs_a_rule_for_that_component():
    assert warranty.run(ctx(_two(PUMP, d(2026, 1, 1), d(2026, 3, 1)), warranty=rule())) == []


def test_warranty_supersedes_repeat_so_dollars_are_not_double_counted():
    c = ctx(_two(ALT, d(2026, 1, 1), d(2026, 2, 1)), warranty=rule())
    assert [x.type for x in run_rules(c)] == ["warranty_eligible"]


# ---------------------------------------------------------------- rule 4: parts price
BASE = {"ABC123": Baseline(D("100.00"), 5, 2)}


def _part(price, qty=1, total=None, **kw):
    return ctx([I(lines=[L(part="abc-123", price=price, qty=qty, total=total, **kw)])], baselines=BASE)


def test_parts_outlier_flags_over_25_percent_with_impact_times_qty():
    f = parts_price.run(_part(130, qty=2, total=260))
    assert len(f) == 1 and f[0].impact == D("60.00")


def test_parts_within_25_percent_is_not_flagged():
    assert parts_price.run(_part(124)) == []


def test_parts_single_shop_needs_1_5x():
    one = {"ABC123": Baseline(D("100.00"), 5, 1)}
    mk = lambda p: ctx([I(lines=[L(part="ABC123", price=p)])], baselines=one)
    assert parts_price.run(mk(140)) == [] and len(parts_price.run(mk(160))) == 1


def test_parts_extended_price_is_read_as_unit_price_using_the_line_total():
    f = parts_price.run(_part(520, qty=4, total=520))  # 4 x $130 printed as the extended $520
    assert len(f) == 1 and f[0].impact == D("120.00") and f[0].evidence["unit_price"] == 130.0


def test_parts_ambiguous_unit_or_extended_gets_benefit_of_the_doubt():
    # qty 2, price 220, line total 400 (lump labour hides which reading is right): 220 each would be an outlier, 110 each is fine
    assert parts_price.run(_part(220, qty=2, total=400)) == []
    # both readings are outliers (400 each or 200 each vs $100): flag at the lower reading
    f = parts_price.run(_part(400, qty=2, total=900))
    assert len(f) == 1 and f[0].evidence["unit_price"] == 200.0


def test_parts_without_baseline_is_skipped():
    assert parts_price.run(ctx([I(lines=[L(part="ZZZ", price=999)])], baselines=BASE)) == []


# ---------------------------------------------------------------- rule 5: duplicates
def test_duplicate_same_shop_and_number():
    invs = [I("a", 0, num="48211", total=500), I("b", 1, num="48-211", total=500)]
    f = duplicate.run(ctx(invs))
    assert len(f) == 1 and f[0].invoice_id == "b" and f[0].related_invoice_id == "a" and f[0].impact == D("500")


def test_same_number_at_different_shops_is_not_a_duplicate():
    assert duplicate.run(ctx([I("a", 0, shop="x", num="1", total=5), I("b", 1, shop="y", num="1", total=5)])) == []


def test_duplicate_same_shop_unit_date_total_with_different_numbers():
    invs = [I("a", 0, num="1", dt=d(2026, 3, 1), total=800), I("b", 1, num="2", dt=d(2026, 3, 1), total=800)]
    assert len(duplicate.run(ctx(invs))) == 1


def test_duplicate_identical_lines_within_an_invoice():
    inv = I("a", 0, num="1", lines=[L("a", 1, desc="Air dryer", price=200, total=200), L("a", 2, desc="Air dryer", price=200, total=200)])
    f = duplicate.run(ctx([inv]))
    assert len(f) == 1 and f[0].line_id == "a-l2" and f[0].impact == D("200")
    ok = I("a", 0, num="1", lines=[L("a", 1, desc="Air dryer", price=200, total=200), L("a", 2, desc="Air dryer", price=210, total=210)])
    assert duplicate.run(ctx([ok])) == []


# ---------------------------------------------------------------- rule 6: maths
def test_math_clean_invoice_has_no_flags():
    inv = I(lines=[L(qty=2, price=50, total=100), L(n=2, hours=2, rate=100, total=200)], subtotal=300, tax=24, total=324)
    assert math_errors.run(ctx([inv])) == []


def test_math_line_total_wrong_when_parts_and_labour_are_both_visible():
    f = math_errors.run(ctx([I(lines=[L(qty=2, price=50, hours=1, rate=100, total=230)], subtotal=230, total=230)]))  # 100 + 100 = 200, printed 230
    assert len(f) == 1 and f[0].line_id == "i1-l1" and f[0].impact == D("30.00")


def test_math_total_below_visible_parts_is_flagged():
    f = math_errors.run(ctx([I(lines=[L(qty=2, price=50, total=30)], subtotal=30, total=30)]))  # lower than either reading of the parts price
    assert len(f) == 1 and f[0].impact == D("20.00")


def test_math_lump_sum_labour_is_not_an_error():
    # parts $500 but line total $940: labour billed as a lump sum with no hours/rate printed -> cannot be checked
    assert math_errors.run(ctx([I(lines=[L(qty=1, price=500, total=940)], subtotal=940, total=940)])) == []


def test_math_extended_parts_price_is_not_an_error():
    assert math_errors.run(ctx([I(lines=[L(qty=4, price=200, total=200)], subtotal=200, total=200)])) == []


def test_math_subtotal_and_total_errors_make_one_invoice_flag():
    inv = I(lines=[L(total=100), L(n=2, total=100)], subtotal=250, tax=10, total=300)  # lines sum 200 vs 250; 250+10 vs 300
    f = math_errors.run(ctx([inv]))
    assert len(f) == 1 and f[0].line_id is None and f[0].impact == D("50.00") and len(f[0].evidence["findings"]) == 2


def test_math_tolerance_allows_rounding():
    assert math_errors.run(ctx([I(lines=[L(total=100.00)], subtotal=100.00, tax=8.25, total=108.74)])) == []
