"""A clean PDF carries its text, so a VIN does not have to be read from pixels (where S/5, Z/2 and B/8 get mixed up)."""
import io

from app.services.extraction.schema import PageExtraction, Scored

from .helpers import pdf_bytes

GOOD, BAD_CHECK = "1M8GDM9AXKP042788", "1M8GDM9AXKP042789"


def _text_pdf(text: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=f"<html><body><p>{text}</p></body></html>").write_pdf()


def _page(vin):
    p = PageExtraction()
    p.header.vin = Scored(value=vin, confidence=0.9 if vin else 0.0)
    return p


def test_only_vins_that_pass_the_check_digit_and_stand_alone_are_taken_from_text():
    from app.services import textlayer

    text = f"Unit T-9  VIN: {GOOD}  Odometer 412,880  other {BAD_CHECK}  longer X{GOOD}Y  again {GOOD}"
    assert textlayer.valid_vins(text) == [GOOD]


def test_a_pdf_with_text_gives_its_text_and_an_image_only_pdf_gives_none():
    from app.services import textlayer

    assert GOOD in textlayer.page_texts(_text_pdf(f"VIN: {GOOD}"))[0]
    assert textlayer.page_texts(pdf_bytes(1)) == [""]
    assert textlayer.page_texts(b"not a pdf") == []


def test_the_printed_vin_replaces_a_misread_one_and_is_trusted():
    from app.services import textlayer

    page = _page("1M8GDM9AXKP0427B8")                               # a look-alike misread
    assert textlayer.apply_text_vin(page, f"VIN: {GOOD}") is True
    assert page.header.vin.value == GOOD and page.header.vin.confidence >= 0.99


def test_a_missing_vin_is_filled_from_the_text():
    from app.services import textlayer

    page = _page(None)
    assert textlayer.apply_text_vin(page, f"Serial # {GOOD}") is True and page.header.vin.value == GOOD


def test_nothing_changes_without_a_single_clear_vin_in_the_text():
    from app.services import textlayer

    other = "11111111111111111"                       # a second, valid VIN (the standard all-ones test VIN)
    page = _page("1M8GDM9AXKP0427B8")
    assert textlayer.apply_text_vin(page, "no vin here") is False and page.header.vin.value == "1M8GDM9AXKP0427B8"
    assert textlayer.apply_text_vin(page, f"{GOOD} and {other}") is False and page.header.vin.value == "1M8GDM9AXKP0427B8"   # two vehicles: the text cannot say which
    keep = _page(other)
    assert textlayer.apply_text_vin(keep, f"{GOOD} and {other}") is False and keep.header.vin.value == other                 # the model's VIN is one of them: leave it
