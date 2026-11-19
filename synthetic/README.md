# Synthetic repair-invoice generator

Test data for a US fleet repair-invoice audit tool (no real invoices exist). Everything is fictional.

## Run
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python generate.py --out out --count 200 --seed 7           # ~1 min on 8 cores (~7 CPU-minutes total; use --workers N)
.venv/bin/python verify.py --out out                                  # consistency checks + summary table
```
Needs `pdftoppm`/`pdftotext` (poppler) on PATH. Output is deterministic for a given seed
(byte-identical, independent of `--workers`).

## Output (`--out`)
- `pdf/` clean text-layer PDFs; `scans/` raster-only PDFs (grey, low contrast, skew -3..3 deg);
  `photos/` phone-style JPEGs (perspective, uneven light/shadow, blur, noise, JPEG artefacts,
  some rotated 90/180/270 in pixels, ~1-1.9 MP and ~2.8-4 MP); `multi/` 3 PDFs holding 3-5 consecutive
  invoices of one shop each, some invoices spanning 2 pages ("Page 1 of 2").
- ~20 handwritten-style invoices (kind `handwritten`, split between `scans/` and `photos/`).
- `answer_key.json` (schema as specified), plus `generation_meta.json` (extra: layout id, tax rate,
  skew/rotation/MP per file, which fields are handwritten) which is not part of the key.

## Key semantics
- Header and line values are what is PRINTED, including planted errors. For `math_error` the note says
  `field=...; printed X, correct Y`. `line_no` is null for header-level problems.
- `parts_price` = extended parts amount printed (qty x unit price). Labour on a "lump" layout has no hours/rate,
  so `labour_hours`/`labour_rate` are null and `line_total` includes the lump. Fee lines (shop supplies,
  environmental) have `vmrs_code` null. Fields a layout does not print are null (VIN, part no., qty).
- `vin_check_digit_valid` is null when the layout prints no VIN, false for the 3 planted bad check digits.
- Exact byte duplicates: `exact_duplicate_of` names the original; they carry the same `key_id`s.
  `duplicate_invoice` = same shop/number/date/unit/jobs re-rendered with another layout and medium
  (new `key_id`, planted note names the original).
- Planted events are consistent across the set (repeat/warranty rows reference an earlier invoice
  of the same unit in the note). Trailers have `odometer` null.

## Handwriting
No handwriting TTF exists on this host (`fc-list`). Handwriting is simulated with the script font
URW Z003 (Zapf Chancery clone) drawn glyph by glyph with random rotation, baseline wobble, spacing and
ink colour jitter, over blank fields (unit, odometer, labour hours, grand total). It is legible but more
regular than real handwriting.
