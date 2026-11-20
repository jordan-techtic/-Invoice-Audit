from decimal import Decimal as D

import pytest

from app.flags import explain, reference
from app.flags.types import FlagDraft, money, severity, unit_price
from app.models import DEFAULT_CLIENT_SETTINGS

from .flag_helpers import I, L


def test_labour_median_needs_five_samples():
    mk = lambda hrs: [I(f"i{n}", n, lines=[L(f"i{n}", code="031-001-001", hours=h, rate=100)]) for n, h in enumerate(hrs)]
    assert reference.labour_medians(mk([2, 2, 3, 2]), 5) == {}
    m = reference.labour_medians(mk([2, 2, 3, 2, 8]), 5)
    assert m["031-001-001"] == (D("2.00"), 5)  # the median ignores the one inflated bill


def test_parts_baseline_needs_three_samples_and_counts_shops():
    invs = [I(f"i{n}", n, shop=s, lines=[L(f"i{n}", part="p-1", price=p)]) for n, (s, p) in enumerate([("a", 100), ("a", 110), ("b", 90)])]
    b = reference.parts_baselines(invs, 3)["P1"]
    assert (b.median, b.samples, b.shops) == (D("100.00"), 3, 2)
    assert reference.parts_baselines(invs[:2], 3) == {}


def test_unit_price_reads_extended_and_unit():
    assert unit_price(L(qty=4, price=50, total=200)) == D("50")
    assert unit_price(L(qty=4, price=200, total=200)) == D("50")


def test_severity_bands():
    cfg = DEFAULT_CLIENT_SETTINGS
    assert [severity(D(x), cfg) for x in (50, 150, 499, 500)] == ["low", "medium", "medium", "high"]


T = "Billed 8.0 hrs. Possible overbilling of $330."


@pytest.mark.parametrize("ai", [
    "This is clearly fraud by the shop.",                    # accusation word
    "The shop billed 3 extra hours.",                        # not hedged
    "Proof that the shop overcharged you.",
    None, "",
])
def test_sanitize_falls_back_to_template(ai):
    assert explain.sanitize(ai, T) == T


def test_sanitize_keeps_good_text_and_trims_to_two_sentences():
    good = "This is likely an overbilling. The job usually takes 5 hours. Ask the shop to explain."
    assert explain.sanitize(good, T) == "This is likely an overbilling. The job usually takes 5 hours."


def test_evidence_hash_changes_with_evidence_not_with_other_fields():
    a = FlagDraft("math_error", "i", None, D("5"), {"x": 1}, "t", "k")
    b = FlagDraft("math_error", "other", "l", D("5"), {"x": 1}, "t2", "k2")
    c = FlagDraft("math_error", "i", None, D("5"), {"x": 2}, "t", "k")
    assert explain.evidence_hash(a) == explain.evidence_hash(b) != explain.evidence_hash(c)


def test_money_format():
    assert money(330) == "$330" and money(D("12.5")) == "$12.50" and money(1234.5) == "$1,234.50"


# ---- artifact L8: the AI's wording may not contradict the numbers the rule found
def test_sanitize_rejects_a_dollar_figure_that_is_not_in_the_evidence():
    tmpl = "Possible maths error of $15."
    assert explain.sanitize("This invoice is likely overbilled by $9,999 on line 7.", tmpl, allowed=[15.32, 154.0]) == tmpl


def test_sanitize_accepts_figures_that_match_the_evidence_exactly_or_rounded():
    assert explain.sanitize("This is a likely maths error of $15.32.", "t", allowed=[15.32]) == "This is a likely maths error of $15.32."
    assert explain.sanitize("This is a likely maths error of about $15.", "t", allowed=[15.32]) == "This is a likely maths error of about $15."
    assert explain.sanitize("Billed $1,200.50 where $1,000 is typical; this is a possible overcharge.", "t", allowed=[1200.5, 1000.0]).startswith("Billed $1,200.50")


def test_sanitize_without_a_number_list_keeps_the_old_behaviour():
    assert explain.sanitize("This is a likely issue worth $77.", "t") == "This is a likely issue worth $77."


# ---- artifact L4 root cause: the same invoice counted twice, and one invoice's repeated lines counted as many "sightings"
def _inv(i, shop, num, price, n_lines=1, total=None):
    return I(i, int(i[-1]) if i[-1].isdigit() else 0, shop=shop, num=num, total=total, lines=[L(i, n + 1, part="P-1", price=price, qty=1, total=price) for n in range(n_lines)])


def test_a_copy_of_the_same_invoice_is_not_a_second_sighting_of_the_part():
    invs = [_inv("i1", "acme", "A1", 10), _inv("i2", "acme", "A2", 12), _inv("i3", "acme", "A2", 12)]       # i3 is a copy of i2
    assert reference.parts_baselines(invs, min_samples=3) == {}


def test_one_invoice_with_the_part_on_three_lines_is_one_sighting():
    invs = [_inv("i1", "acme", "A1", 10, n_lines=3), _inv("i2", "acme", "A2", 12)]
    assert reference.parts_baselines(invs, min_samples=3) == {}
    three = invs + [_inv("i3", "beta", "B1", 11)]
    assert reference.parts_baselines(three, min_samples=3)["P1"].samples == 3
