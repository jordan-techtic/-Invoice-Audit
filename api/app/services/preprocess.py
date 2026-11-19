"""Turn an uploaded original into clean page images for the AI. The original is never modified."""

from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image, ImageFile, ImageOps

MAX_SIDE = 2000
JPEG_QUALITY = 88


class UnreadableFile(Exception):
    """Message is safe to show to the user."""


def sniff_type(data: bytes) -> str | None:
    """Return 'pdf', 'jpeg', 'png' or 'heic' from magic bytes, or None."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
        return "heic"
    return None


def _register_heif() -> None:
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:  # pragma: no cover
        pass


def render_pages(data: bytes, kind: str, max_pages: int = 100) -> list[Image.Image]:
    """Original bytes -> list of RGB PIL images (EXIF-rotated for photos)."""
    if kind == "pdf":
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(data)
        except Exception as e:
            raise UnreadableFile("This PDF is damaged or password-protected. Re-export it and upload again.") from e
        if len(pdf) > max_pages:
            raise UnreadableFile(f"This PDF has {len(pdf)} pages; the limit is {max_pages}. Split it and upload the parts.")
        out = []
        for page in pdf:
            # ~200 dpi; letter page => ~1700x2200
            out.append(page.render(scale=200 / 72).to_pil().convert("RGB"))
        return out
    if kind == "heic":
        _register_heif()
    ImageFile.LOAD_TRUNCATED_IMAGES = False  # WeasyPrint turns this on globally; a cut-off upload must fail, not load half a page
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise UnreadableFile("We couldn't open this image. Check that it isn't corrupted and upload it again.") from e
    return [ImageOps.exif_transpose(img).convert("RGB")]


def _deskew_angle(gray: np.ndarray) -> float:
    """Estimate the text skew in degrees (positive = counter-clockwise tilt). 0 if unsure."""
    small = gray
    h, w = small.shape
    if max(h, w) > 1400:
        f = 1400 / max(h, w)
        small = cv2.resize(small, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    blur = cv2.GaussianBlur(small, (3, 3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # Join characters into horizontal runs so line direction dominates.
    bw = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1)))
    lines = cv2.HoughLinesP(bw, 1, np.pi / 720, threshold=120, minLineLength=small.shape[1] // 5, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        a = math.degrees(math.atan2(y1 - y2, x2 - x1))
        if abs(a) <= 15:
            angles.append(a)
    if len(angles) < 5:
        return 0.0
    return float(np.median(angles))


def deskew(img: Image.Image) -> Image.Image:
    arr = np.array(img.convert("L"))
    angle = _deskew_angle(arr)
    if abs(angle) < 0.4:
        return img
    return img.rotate(-angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))


def enhance(img: Image.Image) -> Image.Image:
    """CLAHE on lightness: lifts faint print and evens out shadows without blowing out colour."""
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)
    return Image.fromarray(out)


def prepare_page(img: Image.Image, rotate_cw: int = 0) -> bytes:
    """Auto-rotate (if told), de-skew, enhance, downsize, encode as JPEG."""
    if rotate_cw % 360:
        img = img.rotate(-rotate_cw, expand=True)  # PIL rotates counter-clockwise for positive angles
    img = deskew(img)
    img = enhance(img)
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()
