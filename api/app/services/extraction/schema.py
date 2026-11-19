"""Strict schema for what the model must return for one invoice page."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Scored(BaseModel):
    """A value with the model's own confidence that it read it correctly. Null means 'not on the page'."""

    model_config = ConfigDict(extra="forbid")
    value: str | float | int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Header(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_name: Scored = Scored()
    shop_address: Scored = Scored()
    invoice_number: Scored = Scored()
    invoice_date: Scored = Scored()
    unit_number: Scored = Scored()
    vin: Scored = Scored()
    odometer: Scored = Scored()
    subtotal: Scored = Scored()
    tax: Scored = Scored()
    total: Scored = Scored()


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Scored = Scored()
    part_number: Scored = Scored()
    qty: Scored = Scored()
    parts_price: Scored = Scored()  # unit price
    labour_hours: Scored = Scored()
    labour_rate: Scored = Scored()
    line_total: Scored = Scored()


class PageExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_invoice: bool = True
    page_number: int | None = None  # "Page 2 of 3" -> 2
    page_count: int | None = None
    rotation_degrees: int = 0  # clockwise rotation needed to make the text upright: 0, 90, 180 or 270
    header: Header = Header()
    lines: list[Line] = []


HEADER_FIELDS = list(Header.model_fields)
LINE_FIELDS = list(Line.model_fields)


def _inline(node: Any, defs: dict) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items() if k not in ("$defs", "title", "default")}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def tool_input_schema() -> dict:
    raw = PageExtraction.model_json_schema()
    return _inline(raw, raw.get("$defs", {}))
