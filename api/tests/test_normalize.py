from datetime import date
from decimal import Decimal

import pytest

from app.services import normalize as N


# 1M8GDM9AXKP042788 is the standard textbook VIN with a valid check digit (X)
@pytest.mark.parametrize("vin,ok", [("1M8GDM9AXKP042788", True), ("11111111111111111", True), ("1M8GDM9AXKP042789", False), ("SHORT", False)])
def test_vin_check_digit(vin, ok):
    assert N.vin_check_digit_ok(vin) is ok


def test_vin_normalisation_uppercases_and_strips():
    assert N.normalize_vin(" 1m8gdm9a-xkp 042788 ") == ("1M8GDM9AXKP042788", "ok")


def test_vin_fixes_ocr_o_for_zero():
    # real VIN ...042788; OCR read the 0 as O
    assert N.normalize_vin("1M8GDM9AXKPO42788") == ("1M8GDM9AXKP042788", "fixed")


def test_vin_wrong_length_and_bad_check_and_missing():
    assert N.normalize_vin("1M8GDM9AXKP04278")[1] == "bad_length"
    assert N.normalize_vin("1M8GDM9AXKP042789")[1] == "bad_check"
    assert N.normalize_vin(None) == (None, "missing")
    assert N.normalize_vin("  ") == (None, "missing")


@pytest.mark.parametrize("raw,exp", [("$1,234.50", "1234.50"), ("1234.5", "1234.50"), ("12,50", "12.50"), ("(45.00)", "-45.00"), (12, "12.00"), ("n/a", None)])
def test_money(raw, exp):
    assert N.parse_money(raw) == (Decimal(exp) if exp else None)


@pytest.mark.parametrize("raw", ["2026-03-14", "03/14/2026", "3/14/26", "Mar 14, 2026", "March 14, 2026", "14 Mar 2026", "14-Mar-2026", "2026/03/14", "14-March-2026"])
def test_dates_normalise_to_iso(raw):
    assert N.parse_date(raw) == date(2026, 3, 14)


def test_odometer_integer_miles():
    assert N.parse_odometer("412,880 mi") == 412880
    assert N.parse_odometer("abc") is None
    assert N.parse_odometer("99999999") is None
