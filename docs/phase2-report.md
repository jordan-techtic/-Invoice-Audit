# Phase 2 report: ingestion and AI extraction

## Verdict

Phase 2 is built and tested, but **the "90% field accuracy" criterion is not verified**. There is no
`ANTHROPIC_API_KEY` in this environment, so the real model has never been run on the synthetic set.
The accuracy numbers below come from an offline stand-in (the "oracle") that replays the answer key with
injected errors and never looks at an image. They prove the pipeline, matching and metrics work at
scale. They say nothing about how well Claude reads invoices.

To get the real number: put a key in `.env`, set `AI_ZDR_CONFIRMED=true` (the Claude provider refuses to run
without it), then run:

```
docker compose run --rm -v $PWD/api:/app -v $PWD/synthetic:/synthetic api \
  python -m eval.run_eval --synthetic /synthetic/out --provider claude
```

Output goes to `api/eval_out/eval_claude.json`. If it is below 90%, the worst fields are listed in that file
and the next step is prompt and preprocessing changes, as you asked.

## What was measured

| Item | Result | Basis |
|---|---|---|
| Backend tests | 82 passed | real |
| Playwright (upload 3, open, edit, mark as checked) | 1 passed, re-run by me against the live stack | real |
| Frontend `tsc`, `eslint`, `next build` | clean | real |
| Cross-client isolation on every new endpoint | passes (8 endpoints, plus id-swapping and retry across clients) | real |
| Exact duplicates caught | 4 of 4 | real |
| Multi-invoice PDF splitting, page ranges correct | 100% of 199 files (204 invoices) | real splitter on oracle-generated pages, so it tests the grouping rules, not page reading |
| VMRS accuracy by keyword lookup alone, no AI | 87.9% (74.0% before I fixed plural and abbreviation handling) | real; 258 of 724 lines had no lookup hit and would go to the AI |
| Field accuracy overall / header only | 96.3% / 94.3% | **oracle, not a model result** |
| Fields sent to review | 7.3% | oracle; depends on its made-up confidence calibration |
| Wrong fields caught by low confidence | 78.8% | oracle; calibration is invented, so this is not evidence the real model is calibrated |
| Seconds per invoice | 1.04 s of pipeline time with no AI call | real, but excludes model latency |
| Cost per invoice | not measured | needs a key; the `0.0158` in the oracle JSON uses made-up token counts and placeholder prices |

Oracle accuracy by file type (harder files get more injected errors by design): clean PDF 98.9%, multi-invoice
98.0%, skewed scan 96.5%, phone photo 93.4%, handwritten 89.4%.

## Failure patterns found

1. **Keyword lookup missed plurals and shop shorthand.** "wheel seals", "shocks", "steer tires", "PM svc" and
   "DEF fault" did not match, and "wheel seal" lost to the shorter "wheel". Fixed (plural-tolerant matching,
   3-character minimum, more abbreviations). Lookup accuracy went from 74.0% to 87.9%.
2. **Line-total check raised false alarms.** It assumed "parts price" is a unit price. Many shops print the
   extended amount instead. Fixed: a line now passes if it adds up under either reading. Line totals sent to
   review dropped from 29% to 18%.
3. **Remaining VMRS misses are multi-job descriptions**, for example "Oil/filter kit w/ fuel filter" or
   "Replace radiator, hoses & clamps, coolant". One code per line is ambiguous there, so these should be low
   confidence and reviewed by a person. Whether the real model does that is untested.
4. **Totals go to review about 18–20% of the time** although only about 6% are wrong. A single wrong line total
   makes the subtotal check fail too, so errors cascade. This is intended (a person should look), but it adds
   to the review queue. Worth watching on the real model.
5. **Not covered by any test yet:** perspective-warped photos (the de-skew only fixes rotation), pages rotated
   90/180 degrees on real model output (the retry-with-rotation path is unit tested with scripted responses
   only), blur, and real handwriting. The synthetic handwriting is a script font with jitter, so it is easier
   than real handwriting.

## Assumptions made

- MinIO runs from `chainguard/minio`, because the official images could not be pulled here. The API creates
  the bucket at startup. Server-side encryption is left to the S3 bucket in production.
- Zero retention is an agreement with Anthropic, not a request flag. `AI_ZDR_CONFIRMED` records that it was
  confirmed; real client data should not be sent until it is set.
- Token prices (`PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK`) are placeholders; check current pricing.
- `parts_price` is stored as printed, with no assumption about unit versus extended.
- The model is asked to report if a page is sideways or upside down; the page is rotated and read once more.
- Anything the model returns as "not on the page" for the fields every invoice should have (shop, invoice
  number, date, total) goes to review. Other empty fields (VIN, odometer, part number) do not, so a wrongly
  empty optional field is not caught by the review queue.

## Not done in this phase (by design)

Flag rules, the review screen with highlights, reports. Phase 3 has not been started.

## Where things are

- Pipeline: `api/app/services/` (`pipeline.py`, `extraction/`, `checks.py`, `splitter.py`, `vmrs.py`, `preprocess.py`)
- Evaluation: `api/eval/run_eval.py`, results in `api/eval_out/`
- Synthetic data: `synthetic/` (`generate.py`, `verify.py`; 199 files, 204 invoices, answer key)
- Email stub: `scripts/send_test_email.py`
- Frontend notes and screenshots: `web/NOTES.md`, `web/screenshots/`
