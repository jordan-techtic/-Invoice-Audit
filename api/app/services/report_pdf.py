from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..flags.types import money as _money

for _n in ("fontTools", "weasyprint"):
    logging.getLogger(_n).setLevel(logging.ERROR)

_DIR = Path(__file__).parent.parent / "reports"
_env = Environment(loader=FileSystemLoader(str(_DIR)), autoescape=select_autoescape(["html"]))


def money(v) -> str:
    return _money(v)


def render_html(snapshot: dict) -> str:
    return _env.get_template("report.html").render(s=snapshot, money=money, audit_date=f"{date.fromisoformat(snapshot['cover']['audit_date']):%b} {date.fromisoformat(snapshot['cover']['audit_date']).day}, {date.fromisoformat(snapshot['cover']['audit_date']).year}")


def render_pdf(snapshot: dict) -> bytes:
    from weasyprint import HTML

    return HTML(string=render_html(snapshot), base_url=str(_DIR) + "/").write_pdf()
