"""Raster degradation: scanner look, phone-photo look, handwriting overlay."""
import math
import subprocess
import tempfile
import os
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

HAND_FONT = "/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf"
PH_PT = 792


def rasterize(pdf_path, dpi, first=None, last=None):
    """pdftoppm -> list of PIL RGB images."""
    with tempfile.TemporaryDirectory() as td:
        cmd = ["pdftoppm", "-r", str(dpi), "-png"]
        if first:
            cmd += ["-f", str(first), "-l", str(last or first)]
        subprocess.run(cmd + [pdf_path, os.path.join(td, "p")], check=True)
        out = []
        for f in sorted(os.listdir(td)):
            out.append(Image.open(os.path.join(td, f)).convert("RGB").copy())
    return out


# ------------------------------------------------------------ handwriting
def hand_overlay(img, marks, dpi, rng):
    """Draw handwriting-like text (script font + per-glyph jitter) at mark positions. rng: numpy Generator."""
    if not marks:
        return img
    img = img.convert("RGBA")
    ink_choices = [(18, 28, 120), (25, 25, 30), (15, 40, 140), (40, 20, 90)]
    ink = ink_choices[int(rng.integers(len(ink_choices)))]
    k = dpi / 72.0
    for m in marks:
        size = int(max(18, m["size"] * k * rng.uniform(1.45, 1.75)))
        font = ImageFont.truetype(HAND_FONT, size)
        text = m["text"]
        advs = [font.getlength(ch) * rng.uniform(0.95, 1.12) for ch in text]
        total = sum(advs)
        x = m["x"] * k
        y = (PH_PT - m["y"]) * k            # baseline in px
        if m["align"] == "r":
            x -= total
        elif m["align"] == "c":
            x -= total / 2
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        slope = rng.uniform(-0.04, 0.02)
        cx = x
        for ch, adv in zip(text, advs):
            g = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(g)
            d.text((size * .4, size * .35), ch, font=font, fill=ink + (int(rng.integers(205, 255)),), anchor="ls" if False else None)
            g = g.rotate(rng.uniform(-7, 7), resample=Image.BICUBIC, center=(size * .6, size * 1.0))
            off_y = rng.uniform(-0.07, 0.07) * size + slope * (cx - x)
            layer.alpha_composite(g, (int(cx - size * .4), int(y - size * 1.05 + off_y)))
            cx += adv
        layer = layer.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(0.7))
        img = Image.alpha_composite(img, layer)
    return img.convert("RGB")


# ------------------------------------------------------------ scan
def scan_look(img, rng):
    g = np.asarray(img.convert("L"), dtype=np.float32)
    lo, hi = rng.uniform(35, 85), rng.uniform(190, 232)
    g = lo + g / 255.0 * (hi - lo)
    h, w = g.shape
    # soft gradient + streaks + noise
    gx = np.linspace(0, 1, w, dtype=np.float32)[None, :] * rng.uniform(-10, 10)
    gy = np.linspace(0, 1, h, dtype=np.float32)[:, None] * rng.uniform(-8, 8)
    g = g + gx + gy
    if rng.random() < .5:
        x = int(rng.integers(0, w))
        g[:, max(0, x - 1):x + 1] -= rng.uniform(6, 16)
    g += rng.normal(0, rng.uniform(3, 7), g.shape).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), rng.uniform(0.5, 1.0))
    g = np.clip(g, 0, 255).astype(np.uint8)
    ang = float(rng.uniform(-3, 3))
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    bg = int(rng.integers(150, 215))
    g = cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=bg)
    return Image.fromarray(g, "L"), ang


# ------------------------------------------------------------ photo
def _lowfreq(rng, h, w, scale=48):
    a = rng.random((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    return cv2.resize(a, (w, h), interpolation=cv2.INTER_CUBIC)


def photo_look(img, rng, target_mp_class):
    """img: PIL RGB page at ~200dpi. returns (PIL RGB, info)"""
    sizes_lo = [(960, 1280), (1080, 1440), (1200, 1600), (1050, 1400)]
    sizes_hi = [(1440, 1920), (1536, 2048), (1632, 2176), (1728, 2304)]
    W, H = (sizes_hi if target_mp_class == "hi" else sizes_lo)[int(rng.integers(4))]
    pw = W * rng.uniform(0.80, 0.90)
    ph = pw * 11 / 8.5
    src = np.asarray(img.resize((int(pw), int(ph)), Image.LANCZOS))
    sh, sw = src.shape[:2]
    cx = W / 2 + rng.uniform(-0.03, 0.03) * W
    cy = H / 2 + rng.uniform(-0.025, 0.025) * H
    rot = math.radians(rng.uniform(-6, 6))
    base = np.array([[-sw / 2, -sh / 2], [sw / 2, -sh / 2], [sw / 2, sh / 2], [-sw / 2, sh / 2]], np.float32)
    R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]], np.float32)
    dst = base @ R.T + np.array([cx, cy], np.float32)
    # perspective: keystone + jitter
    key = rng.uniform(-0.05, 0.05) * sw
    dst[0, 0] += key
    dst[1, 0] -= key
    dst += rng.uniform(-0.018, 0.018, dst.shape).astype(np.float32) * np.array([sw, sh], np.float32)
    src_q = np.array([[0, 0], [sw, 0], [sw, sh], [0, sh]], np.float32)
    Mx = cv2.getPerspectiveTransform(src_q, dst.astype(np.float32))
    # background desk
    col = np.array([[88, 66, 48], [70, 72, 76], [120, 100, 80], [55, 55, 58], [140, 135, 125]][int(rng.integers(5))], np.float32)
    bg = np.ones((H, W, 3), np.float32) * col
    bg *= (0.88 + 0.24 * cv2.GaussianBlur(_lowfreq(rng, H, W, 160), (0, 0), W * .02))[..., None]
    stripes = np.sin(np.linspace(0, rng.uniform(60, 140), H, dtype=np.float32))[:, None] * 5
    bg += stripes[..., None] * 0.6 + cv2.GaussianBlur(rng.normal(0, 7, (H, W)).astype(np.float32), (0, 0), 1.2)[..., None]
    mask = cv2.warpPerspective(np.ones((sh, sw), np.float32), Mx, (W, H), flags=cv2.INTER_LINEAR)
    warped = cv2.warpPerspective(src, Mx, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT).astype(np.float32)
    # paper drop shadow
    sm = cv2.GaussianBlur(np.roll(mask, (int(H * .006), int(W * .008)), (0, 1)), (0, 0), W * .008)
    bg *= (1 - 0.45 * sm)[..., None]
    out = warped * mask[..., None] + bg * (1 - mask[..., None])
    # lighting
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    th = rng.uniform(0, 2 * math.pi)
    t = ((xx / W - .5) * math.cos(th) + (yy / H - .5) * math.sin(th))
    light = 0.92 + rng.uniform(0.15, 0.4) * t
    r2 = ((xx / W - .5) ** 2 + (yy / H - .5) ** 2)
    light *= 1 - rng.uniform(0.2, 0.5) * r2
    if rng.random() < .75:      # hand / phone shadow
        pts = np.array([[rng.uniform(0, W), rng.uniform(0, H)] for _ in range(4)], np.float32)
        sm2 = np.zeros((H, W), np.float32)
        cv2.fillConvexPoly(sm2, cv2.convexHull(pts).astype(np.int32), 1.0)
        sm2 = cv2.GaussianBlur(sm2, (0, 0), W * rng.uniform(.03, .08))
        light *= 1 - rng.uniform(.12, .30) * sm2
    out *= light[..., None]
    cast = rng.choice([0, 1, 2])
    out *= [np.array([1.0, .97, .90]), np.array([.96, .98, 1.03]), np.array([1, 1, 1])][int(cast)].astype(np.float32)
    out = np.clip(out * rng.uniform(0.95, 1.12), 0, 255)
    # blur
    if rng.random() < .22:
        k = int(rng.integers(5, 9))
        ker = np.zeros((k, k), np.float32)
        ker[k // 2, :] = 1.0 / k
        Mr = cv2.getRotationMatrix2D((k / 2 - .5, k / 2 - .5), rng.uniform(0, 180), 1)
        ker = cv2.warpAffine(ker, Mr, (k, k))
        ker /= max(ker.sum(), 1e-6)
        out = cv2.filter2D(out, -1, ker)
    else:
        out = cv2.GaussianBlur(out, (0, 0), rng.uniform(0.6, 1.3))
    out += rng.normal(0, rng.uniform(2, 5.5), out.shape).astype(np.float32)
    out = np.clip(out, 0, 255).astype(np.uint8)
    rotk = int(rng.choice([0, 0, 0, 0, 1, 2, 3]))      # 0 none, 1 = 90 cw, 2 = 180, 3 = 270
    if rotk:
        out = np.rot90(out, k=-rotk)
    return Image.fromarray(np.ascontiguousarray(out), "RGB"), dict(rotation=rotk * 90, size=[int(out.shape[1]), int(out.shape[0])],
                                                                   megapixels=round(W * H / 1e6, 2))
