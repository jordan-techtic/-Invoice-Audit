# Client settings and reference data

Everything the audit checks depend on is stored **per client** and is edited under *Clients → (client) → Settings*, not in code.
A new client starts with the thresholds below and **no** warranty rules, vehicles or imported benchmarks: load them from the
client's own documents (see "Loading the documents").

## Thresholds

Stored in `client.settings`; read by the rules in `api/app/flags/rules/`. Defaults live in `DEFAULT_CLIENT_SETTINGS`
(`api/app/models.py`). Changing one affects the **next** run of the checks; open flags are updated, decided flags are never
overwritten (they are marked *inputs changed* / *no longer applies* instead, and a report cannot be created until they are reopened or dismissed).

| Setting | Meaning | Default | `thresholds_and_rules.json` key (conversion) |
|---|---|---|---|
| `labour_over_benchmark_pct` | Flag labour billed more than this many % above the typical hours for the job (and vehicle class) | 20 | `labour_over_benchmark_pct` (a fraction: 0.2 → 20) |
| `labour_min_samples` | Invoices needed before a typical time is worked out from the client's own history | 5 | none |
| `repeat_repair_days` | Same job code on the same unit again within this many days | 90 | `repeat_repair_days` |
| `repeat_repair_miles` | …or within this many miles (trailers have no odometer: days only) | 10,000 | `repeat_repair_miles` |
| `repeat_condition` | `or`: days **or** miles is enough; `and`: both must be inside the limit | `or` | none (the file's rule text is not read) |
| `parts_outlier_pct` | Flag a part priced more than this many % above its median | 25 | `parts_price_outlier_ratio` (1.5 → 50) |
| `parts_single_shop_multiple` | The same test when only one shop sells the part | 1.5 | `parts_price_outlier_ratio` |
| `parts_min_samples` | Sightings of a part number before a median is trusted | 3 | `parts_price_min_observations` |
| `duplicate_window_days` | `0`: a duplicate must carry the same date. `N`: same shop, unit and total within N days (also catches a re-submission with a new number) | 0 | `duplicate_invoice_window_days` |
| `math_tolerance` | Ignore differences up to this many dollars when an invoice is added up | 1.00 | none |
| `confidence_threshold` | A field read below this score goes to review | 0.80 | none |
| `repeat_exclude_codes` | Routine, recurring job codes that are never a "repeat repair" (oil change, annual DOT inspection, trailer PM …) | see code | none |
| `severity_high_dollars` / `severity_medium_dollars` | Flag severity bands | 500 / 150 | none |

## Loading the documents

Admin only. Each import validates the whole file, lists every bad row, and imports nothing unless the file is clean.

| Document | Settings action | Endpoint | What it fills |
|---|---|---|---|
| `thresholds_and_rules.json` | *Import thresholds* (fills the form; review, then save) | `POST /clients/{id}/settings/import-thresholds`, then `PATCH /clients/{id}` | the thresholds in the table above |
| `warranty_rules.csv` (`component, warranty_months, warranty_miles, covers`) | *Import warranty rules* (`merge` or `replace`) | `POST /clients/{id}/warranty-rules/import` | one rule per job code; `covers` is `parts` or `parts+labour`, and a `parts` rule claims the parts only |
| `vehicles.csv` (`unit, vehicle_class`, optional `vin`) | *Import vehicles* | `POST /clients/{id}/vehicles/import` | the fleet list: gives each unit its class, names the unit for a VIN, and lets a unit read as `1026` join `T-1026` |
| `jobs_vmrs.csv` (`description` or `job_key`, `vehicle_class`, `benchmark_hours`) | *Import jobs* | `POST /clients/{id}/benchmarks/import-jobs` | typical labour hours **per job and vehicle class** (a tractor and a trailer inspection are different benchmarks) |

Order of precedence for a labour benchmark: a value typed in for one vehicle class, then an imported value for all vehicles, then the
median worked out from the client's own invoices for that job and class.

## What the checks do with the numbers

* **Subtotal.** Many shops print *Parts / Labor / Tax / TOTAL DUE* and no Subtotal row. The model is told to leave `subtotal` empty
  unless a row is labelled Subtotal. When it fills one anyway, an invoice whose lines plus tax already equal the total is treated as
  adding up. With no subtotal, lines plus tax are compared with the total.
* **Maths flags count over-billing only.** A total that is *lower* than the shop's own figures is not money to recover. A missing tax is
  never assumed to be zero. One maths flag per invoice, and a header flag only reports the part of the gap a line flag does not already cover.
* **Duplicates are counted once.** An invoice flagged as a duplicate carries no other flags of its own.
* **Review.** "Mark as checked" is refused while an arithmetic or VIN check has failed and nobody corrected the field; confirm it as
  printed (`?confirm_as_printed=true`) or correct the number. Correcting a number refreshes the flags that rest on it.
* **Hard to read.** A flag shows *check extraction first* whenever a number it rests on has a stored score below the threshold and nobody
  corrected it, even after the invoice was marked checked. Accepting such a flag needs `extraction_checked: true`.
* **Reports.** A report counts only invoices that are not waiting for review, says "reviewed by an analyst" only when findings were reviewed,
  shows *out of date* when a decision changed after it was created, and a new version turns the older public link off.
