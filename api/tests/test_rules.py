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


# ---------------------------------------------------------------- rule 6: maths, subtotal read from a footer row (artifact X1, L2, X4)
# Most shops print "Parts / Labor / Tax / TOTAL DUE" and no Subtotal row, so a stored subtotal may really be one of those footer rows.
def test_math_subtotal_that_is_the_parts_row_is_not_an_error_when_lines_plus_tax_equal_the_total():
    inv = I(lines=[L(n=1, total=372.87), L(n=2, hours=3.5, rate=111, total=388.50)], subtotal=372.87, tax=31.69, total=793.06)   # invoice 37911
    assert math_errors.run(ctx([inv])) == []


def test_math_subtotal_that_is_the_total_due_row_is_not_an_error_when_lines_plus_tax_equal_the_total():
    inv = I(lines=[L(n=1, total=49.74), L(n=2, total=43.00)], subtotal=96.83, tax=4.09, total=96.83)                              # PE-56950
    assert math_errors.run(ctx([inv])) == []


def test_math_without_a_subtotal_compares_lines_plus_tax_with_the_total():
    wrong = I(lines=[L(n=1, total=100), L(n=2, total=100)], subtotal=None, tax=10, total=260)
    f = math_errors.run(ctx([wrong]))
    assert len(f) == 1 and f[0].line_id is None and f[0].impact == D("50.00")
    assert math_errors.run(ctx([I(lines=[L(n=1, total=100), L(n=2, total=100)], subtotal=None, tax=10, total=210)])) == []


def test_math_under_billing_is_not_recoverable_money():
    under = I(lines=[L(total=100)], subtotal=100, tax=8.25, total=100)            # the shop charged LESS than its own subtotal + tax
    assert math_errors.run(ctx([under])) == []
    over = I(lines=[L(total=100)], subtotal=100, tax=8.25, total=120)
    assert [f.impact for f in math_errors.run(ctx([over]))] == [D("11.75")]


def test_math_missing_tax_is_not_assumed_to_be_zero():
    assert math_errors.run(ctx([I(lines=[L(total=100)], subtotal=100, tax=None, total=108.25)])) == []


def test_math_both_visible_line_printed_below_its_parts_and_labour_is_not_over_billing():
    assert math_errors.run(ctx([I(lines=[L(qty=2, price=50, hours=1, rate=100, total=120)], subtotal=120, tax=0, total=120)])) == []   # 150 or 200 expected, 120 printed


def test_math_zero_parts_price_is_treated_as_not_printed():
    # 'Annual DOT insp' has no parts price on the page; a stored 0.0 must not make the line look like "parts and labour both visible"
    line = L(qty=2.8, price=0.0, hours=2.8, rate=140, total=520)
    assert math_errors.run(ctx([I(lines=[line], subtotal=None, tax=0, total=520)])) == []


def test_math_header_gap_already_explained_by_line_flags_is_not_counted_twice():
    inv = I(lines=[L(n=1, qty=1, price=70, hours=1, rate=100, total=200)], subtotal=230, tax=0, total=230)   # the line is 30 over (170 expected); the subtotal repeats that 30
    f = math_errors.run(ctx([inv]))
    assert [(x.line_id, x.impact) for x in f] == [("i1-l1", D("30.00"))]


# ---------------------------------------------------------------- artifact L1: one set of dollars, counted once
def test_a_duplicate_invoice_does_not_also_carry_its_own_line_flags():
    mk = lambda i, order: I(i, order, num="77", dt=d(2026, 1, 5), lines=[L(i, 1, qty=1, price=70, hours=1, rate=100, total=200)], subtotal=200, tax=0, total=200)   # line is 30 over
    drafts = run_rules(ctx([mk("a", 0), mk("b", 1)]))
    assert [x.type for x in drafts if x.invoice_id == "b"] == ["duplicate"]       # the copy is flagged once, for its whole total
    assert [x.type for x in drafts if x.invoice_id == "a"] == ["math_error"]      # the original keeps its own finding


def test_annual_inspections_and_trailer_pm_are_routine_work_not_repeat_repairs_by_default():
    from app.models import DEFAULT_CLIENT_SETTINGS

    assert {"000-001-001", "000-001-002", "045-001-009"} <= set(DEFAULT_CLIENT_SETTINGS["repeat_exclude_codes"])


# ---------------------------------------------------------------- artifact L3 root cause: a part has a POSITION, and "inspect" is not a replacement
from app.flags.rules import history as _history  # noqa: E402


def test_left_front_and_right_front_are_different_positions_but_unknown_is_not_a_conflict():
    assert _history.positions_conflict("R&R brake chamber LF", "R&R brake chamber RF")
    assert _history.positions_conflict("R/R BRK CHMBR - DRVR FRT", "R/R BRK CHMBR - PASS FRT")
    assert _history.positions_conflict("Brake chamber front", "Brake chamber rear")
    assert not _history.positions_conflict("Brake chamber LF", "Brake chamber left front")
    assert not _history.positions_conflict("Brake chamber", "Brake chamber LF")          # one side unknown: still the same job as far as we can tell
    assert not _history.positions_conflict("R&R alternator", "RPLC ALT")                 # "R&R" is remove-and-replace, not a position


def test_inspecting_is_not_replacing():
    h = _history.is_replacement
    assert h("R&R brake chamber") and h("Replace alternator") and h("RPLC ALT") and h("Brake chamber")
    assert not h("Inspect brake chambers") and not h("Check alternator output") and not h("Adjust brakes")
    assert h("Inspect and replace brake chamber")


def _pair_desc(d1, d2, days=30):
    a = I("a", 0, num="1", dt=d(2025, 3, 1), odo=100000, lines=[L("a", code="013-001-007", desc=d1, total=300)])
    b = I("b", 1, num="2", dt=d(2025, 3, 1 + days), odo=101000, lines=[L("b", code="013-001-007", desc=d2, total=300)])
    return [a, b]


def test_the_same_job_on_a_different_wheel_position_is_not_a_repeat_repair():
    assert repeat.run(ctx(_pair_desc("R&R brake chamber LF", "R&R brake chamber RF"))) == []
    assert len(repeat.run(ctx(_pair_desc("R&R brake chamber LF", "R&R brake chamber left front")))) == 1
    assert len(repeat.run(ctx(_pair_desc("R&R brake chamber", "R&R brake chamber")))) == 1       # no position printed: unchanged


def test_an_inspection_followed_by_a_replacement_is_not_a_repeat_repair():
    assert repeat.run(ctx(_pair_desc("Inspect brake chambers", "R&R brake chamber"))) == []


def test_two_invoices_for_the_same_job_on_the_same_day_are_not_a_repeat_repair():
    assert repeat.run(ctx(_pair_desc("R&R brake chamber", "R&R brake chamber", days=0))) == []      # same day: a continuation or a re-bill, which the duplicate rule covers


# ---------------------------------------------------------------- artifact L10 root cause: a shop number alone does not make a duplicate
def test_the_same_invoice_number_with_nothing_else_in_common_is_not_a_duplicate():
    a = I("a", 0, num="7", dt=d(2026, 1, 5), unit="U1", total=100, lines=[L("a", total=100)])
    b = I("b", 1, num="7", dt=d(2026, 5, 20), unit="U2", total=250, lines=[L("b", total=250)])     # a shop that restarted its numbering
    assert duplicate.run(ctx([a, b])) == []


def test_the_same_number_and_the_same_total_is_a_duplicate():
    a = I("a", 0, num="7", dt=d(2026, 1, 5), unit="U1", total=100, lines=[L("a", total=100)])
    b = I("b", 1, num="7", dt=d(2026, 1, 9), unit="U1", total=100, lines=[L("b", total=100)])     # re-dated copy
    assert [f.impact for f in duplicate.run(ctx([a, b]))] == [D("100")]


def test_a_duplicate_with_no_amount_does_not_create_a_zero_dollar_flag():
    a = I("a", 0, num="7", dt=d(2026, 1, 5), unit="U1", total=None, lines=[L("a", total=None)])
    b = I("b", 1, num="7", dt=d(2026, 1, 5), unit="U1", total=None, lines=[L("b", total=None)])
    assert [f for f in duplicate.run(ctx([a, b])) if f.impact == 0] == []
