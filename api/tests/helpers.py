import io
import json

from PIL import Image, ImageDraw

from app.services.extraction.fake import FakeProvider


def png_bytes(seed: int = 0, size=(900, 1200)) -> bytes:
    """A distinct image per seed (so SHA-256 differs) with some dark text-like marks."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i in range(30):
        d.rectangle([60, 80 + i * 30, 60 + (seed * 37 + i * 53) % 700 + 50, 94 + i * 30], fill="black")
    d.text((10, 10), f"seed {seed}", fill="black")
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def pdf_bytes(n_pages: int, seed: int = 0) -> bytes:
    imgs = [Image.open(io.BytesIO(png_bytes(seed * 100 + i))).convert("RGB") for i in range(n_pages)]
    b = io.BytesIO()
    imgs[0].save(b, "PDF", save_all=True, append_images=imgs[1:], resolution=100)
    return b.getvalue()


def sc(v, c=0.95):
    return {"value": v, "confidence": c}


def page_json(*, inv="48211", shop="Lone Star Truck Repair", date="03/14/2026", unit="T-114", vin="1M8GDM9AXKP042788",
              odo="412,880", lines=None, subtotal="580.00", tax="0.00", total="580.00", page=(None, None), rotation=0, conf=0.95):
    lines = lines if lines is not None else [
        {"description": sc("R&R alternator", conf), "part_number": sc("ALT-8800", conf), "qty": sc(1, conf),
         "parts_price": sc("350.00", conf), "labour_hours": sc(2.0, conf), "labour_rate": sc("115.00", conf), "line_total": sc("580.00", conf)}
    ]
    return json.dumps({
        "is_invoice": True, "page_number": page[0], "page_count": page[1], "rotation_degrees": rotation,
        "header": {"shop_name": sc(shop, conf), "shop_address": sc("1 Main St, Dallas, TX", conf), "invoice_number": sc(inv, conf),
                   "invoice_date": sc(date, conf), "unit_number": sc(unit, conf), "vin": sc(vin, conf), "odometer": sc(odo, conf),
                   "subtotal": sc(subtotal, conf), "tax": sc(tax, conf), "total": sc(total, conf)},
        "lines": lines,
    })


def script(*responses: str) -> None:
    FakeProvider.reset()
    FakeProvider.scripted = list(responses)
