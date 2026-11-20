"""The extraction prompt is the contract with the model. These pin the rules that stop the false maths flags (artifact X1, X2, X3)."""
import re

from app.prompts import PROMPT_VERSION, load
from app.services.extraction.schema import Line


def _text() -> str:
    return load("extraction_system").lower()


def test_subtotal_is_filled_only_from_a_row_labelled_subtotal():
    t = _text()
    assert re.search(r"subtotal[^.]*only[^.]*(labelled|labeled)[^.]*subtotal|only[^.]*(labelled|labeled)[^.]*subtotal", t), "say when subtotal may be filled"
    assert "parts / labor / tax / total due" in t or "parts, labor, tax" in t, "name the footer layout that has no subtotal row"
    assert re.search(r"null", t[t.index("subtotal"):]), "and say what to return otherwise"


def test_footer_rows_are_not_line_items():
    t = _text()
    for word in ("parts", "labor", "sales tax", "total due"):
        assert word in t.split("rules:")[1]
    assert re.search(r"(footer|summary)[^.]*not[^.]*line|never[^.]*(footer|summary)[^.]*line", t)


def test_one_entry_per_printed_row_and_parts_price_is_the_unit_price():
    t = _text()
    assert "one entry in lines per printed row" in t
    assert "never merge" in t or "do not merge" in t
    assert "unit price" in t and "parts_price" in t
    assert "may be on the same line" not in t, "the old wording invited merging two rows"


def test_schema_and_prompt_agree_that_parts_price_is_the_unit_price():
    from pathlib import Path
    import app.services.extraction.schema as schema_module
    assert "unit price" in Path(schema_module.__file__).read_text().lower()


def test_prompt_version_was_bumped_so_cached_explanations_are_not_reused():
    assert PROMPT_VERSION != "p3-2"
