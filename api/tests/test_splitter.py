import json

from app.services.extraction.schema import PageExtraction
from app.services.splitter import merge_group, split_pages

from .helpers import page_json


def P(**kw):
    return PageExtraction.model_validate(json.loads(page_json(**kw)))


def test_single_invoice_single_page():
    assert split_pages([P()]) == [[0]]


def test_different_invoice_numbers_split():
    assert split_pages([P(inv="1"), P(inv="2"), P(inv="3")]) == [[0], [1], [2]]


def test_same_invoice_number_continues():
    assert split_pages([P(inv="1", page=(1, 2)), P(inv="1", page=(2, 2))]) == [[0, 1]]


def test_continuation_page_without_number():
    p2 = P(inv=None, page=(2, 2), subtotal="9.00")
    p2.header.invoice_number.value = None
    assert split_pages([P(inv="1", page=(1, 2)), p2]) == [[0, 1]]


def test_page_one_of_n_starts_new_invoice_even_without_number():
    nxt = P(inv=None, page=(1, 2))
    nxt.header.invoice_number.value = None
    assert split_pages([P(inv="1", page=(1, 1)), nxt]) == [[0], [1]]


def test_non_invoice_pages_are_dropped():
    blank = PageExtraction(is_invoice=False)
    assert split_pages([P(inv="1"), blank, P(inv="2")]) == [[0], [2]]


def test_invoice_number_formatting_differences_do_not_split():
    assert split_pages([P(inv="INV-0042"), P(inv="inv 0042")]) == [[0, 1]]


def test_merge_takes_totals_from_last_page_and_concats_lines():
    a = P(inv="1", page=(1, 2), subtotal="100.00", total="100.00")
    b = P(inv="1", page=(2, 2), subtotal="250.00", total="250.00")
    m = merge_group([a, b], [0, 1])
    assert (m.page_start, m.page_end) == (1, 2)
    assert m.header["total"]["value"] == "250.00" and len(m.lines) == 2
