# Test results

Generated 2026-11-19 by `scripts/gen_test_results.py` from the artifacts of the last run.

**20 PASS, 4 PARTIAL, 0 FAIL** across 24 cases below (+ case 25 metrics).  Backend tests: 186 passed, 0 failed.  Browser tests: 4 passed, 0 failed.

**PARTIAL** means the mechanism passes but the claim depends on a real AI model, which could not be run here (no API key).

| # | Case | Result | Evidence | Notes |
|---|---|---|---|---|
| 1 | Clean PDF, skewed scan, phone photo are extracted | **PARTIAL** | REAL: de-skew on 30 scans cut mean skew 1.31 deg -> 0.28 deg (max 1.5), correlation with true skew 0.975; all file types render; HEIC converted and processed. Pipeline stores header+lines for all 3 kinds. | Reading of pixels uses the offline oracle (no AI key in this environment), so model reading is NOT verified. |
| 2 | Multi-invoice PDF split into the right invoices | **PARTIAL** | 3 multi PDFs (3, 4, 5 invoices; includes 2-page invoices): invoice counts and page ranges exactly match the key. Unit tests cover the boundary rules. | Boundaries depend on the model reading invoice numbers per page; here the oracle supplies them. |
| 3 | Same file twice: duplicate skipped and user told | **PASS** | Second upload status 'duplicate' with 'Skipped: identical to first.pdf, already uploaded on ...'; never sent to the AI. All 4 byte-identical copies in the set caught. |  |
| 4 | Unsupported or corrupt file: clear error, no crash | **PASS** | exe, txt, empty -> 'isn't a PDF, JPG, PNG or HEIC file'; damaged PDF -> 'damaged or password-protected'; truncated PNG -> 'couldn't open this image'; app stays up; failed files can be retried. |  |
| 5 | Blurry invoice: low-confidence fields go to review, not guessed | **PARTIAL** | REAL: heavy blur does not break preprocessing. MECHANISM: a null stays null, uncertain VIN/unit go to review with 'Check this: hard to read'. | Whether a real model reports uncertainty on blur this way is untested. |
| 6 | Each of the 6 rules finds its planted problems (recall/precision per rule) | **PARTIAL** | Rules on correctly read data (recall/precision): labour 91.7%/100.0%, repeat 77.8%/100.0%, warranty 100.0%/50.0%, parts 70.0%/100.0%, duplicate 100.0%/100.0%, math 100.0%/100.0%. Overall precision 87.5%, recall 88.9% (with warranty rules limited to the planted components: precision 100.0%, recall 90.7%). | Below 80% recall: repeat_repair, parts_price_outlier. Misses: planted parts outliers on layouts with no part number or too few price samples; a fuel-filter repeat is excluded as routine work; a brake-chamber repeat is reported as a warranty flag. With keyword-only VMRS codes (no AI) recall falls to 79.6%. |
| 7 | A clean invoice produces no flags | **PASS** | Unit tests: clean invoices give no flags. Dataset: with warranty rules matching the planted components, 0 flags land on invoices with no planted problem (50 flags, 100.0% precision). With the default 16-component warranty list, 7 flags land on unplanted invoices (tires, brake chambers, air dryers replaced again inside 12 months). | Those are arguably real warranty candidates that the synthetic key does not label. |
| 8 | Too little data for a benchmark: check skipped with a note, no wrong flag | **PASS** | 3 samples (5 needed) and one 9-hour bill: no labour flag; run summary note 'Labour check skipped for 1 job type(s): not enough data...'. |  |
| 9 | AI call fails: flags still appear with template reason | **PASS** | Explain call raising -> flags stored with the rule's template reason, run note 'AI explanations unavailable'; report narrative failure still builds the report; AI wording with 'fraud' or no hedge is replaced by the template. |  |
| 10 | Accept, dismiss, edit a flag: values and audit log saved | **PASS** | reviewed_by, reviewed_at, note, dismiss reason and original amount/reason saved; audit rows accept/dismiss/edit with ids; confirmed/still-to-review totals update. |  |
| 11 | Keyboard shortcuts work | **PASS** | Playwright in a real browser: A accepts, D then reason+Enter dismisses, E edits, J/K move, Esc closes; ignored while typing. |  |
| 12 | Fix an extracted field, Re-check, flags update | **PASS** | Changing a 4.0 h bill to 2.0 h and re-checking removes that flag, leaves other invoices' flags and analyst decisions untouched; a second re-check changes nothing. |  |
| 13 | Report with open flags is blocked with a clear message | **PASS** | '1 flag still needs a decision. Accept or dismiss it first, then create the report.' and 'No checks have been run yet...' |  |
| 14 | Report total = sum of accepted flags, excludes dismissed | **PASS** | Snapshot recoverable equals the exact sum of accepted (and edited-amount) flags; dismissed amounts absent from totals, charts and appendix. |  |
| 15 | PDF downloads, opens, same figures as dashboard | **PASS** | application/pdf, valid file, 3+ pages, 'Page 2 of N' footers; text contains the same recoverable figure, client name, every narrative heading and every appendix invoice number as the dashboard data. |  |
| 16 | Empty report renders properly | **PASS** | All flags dismissed: 'No likely overbilling was found in the 8 invoices we reviewed.'; no '$0', no charts, still has next steps and the honest note. |  |
| 17 | Expired or revoked link refused | **PASS** | Fresh client without login opens the link (200); invalid token 404; revoked -> 410 'turned off'; expired -> 410 'has expired'; analyst cannot revoke (403). |  |
| 18 | Report unchanged after flags are edited later | **PASS** | Snapshot JSON and PDF text identical after editing and dismissing flags; a new report (v2) reflects the new decisions. |  |
| 19 | Client B cannot read client A's data, files or reports on any endpoint | **PASS** | Routes are discovered from the app's route table: every {client_id} route attacked as a user with no access (all 404), every object-id route attacked with another client's ids (all 404/405), all non-public routes require login; DB layer refuses unscoped queries and cross-client writes. |  |
| 20 | Analyst cannot reach admin actions | **PASS** | 13 admin actions (create client/user, settings, warranty rules, benchmarks, revoke, audit-complete, delete, audit log) all 403 for an analyst; ordinary work allowed. |  |
| 21 | Login rate limiting blocks repeated bad attempts | **PASS** | 5 bad attempts -> 6th is 429 with Retry-After, even the right password is refused while blocked. |  |
| 22 | Key and invoice contents never in logs | **PASS** | Canary API key, shop name, VIN and invoice number pushed through upload, error paths, checks and report: absent from all logs and responses; scrubber masks keys in any log line; repo scan finds no keys (also `make scan`). |  |
| 23 | Deletion job removes raw files on schedule, audit log records it | **PASS** | Nothing at day 10; per-client 30-day setting deletes B at day 45; A deleted at day 91; invoices, flags and report PDF kept; audit row 'delete raw_files retention_schedule'; runs once per client. |  |
| 24 | `make demo` does everything from a clean state | **PASS** | Created client, loaded 199 files -> 204 invoices, ran checks (176 flags), accepted 44 matching the key (6 with the amount corrected, as an analyst would after looking at the image), dismissed 132, report $9,156.69, PDF 36,437 bytes at demo/sample_report.pdf. | Mode: OFFLINE ORACLE (no AI key) |

## Case 25: measurements

Run mode: **OFFLINE ORACLE: extraction replays the answer key with injected errors; there was no AI key**.

| Metric | Value | Basis |
|---|---|---|
| Invoices processed | 204 from 199 files (expected 204); exact duplicates skipped 4/4; failed files 0 | real pipeline |
| Multi-invoice split correct | 100.0% of files | grouping rules real; page text from oracle |
| Field accuracy (header + lines, 7,108 fields) | 96.29% | ORACLE: not a model result |
| Flags raised / precision / recall end to end | 176 / 25.0% / 72.22% | rules real on extracted data; extraction noise is simulated |
| Precision of flags not marked 'check extraction first' | 77.27% of 22 flags; 127 of 132 false flags were already marked | real |
| Flag precision / recall, rules on correctly read data | 87.5% / 88.9% (default warranty list); 100.0% / 90.7% (warranty list matching the planted components) | real; isolates the rules |
| Same, VMRS codes from keyword lookup only (no AI) | 84.6% / 79.6% | real |
| VMRS accuracy, keyword lookup alone | 87.85% (258 of 724 lines unresolved; they go to the AI) | real |
| Seconds per invoice | 1.014 s pipeline time excluding the AI call; checks for all invoices 0.46 s; whole demo 215.0 s | real, excludes model latency |
| Cost per invoice | not measurable offline | see estimate below |

Per rule on the end-to-end path:

| Rule | Planted | Found | Recall | Flags | Precision |
|---|---|---|---|---|---|
| labour_over_benchmark | 12 | 10 | 83.33% | 24 | 41.67% |
| repeat_repair | 9 | 4 | 44.44% | 4 | 100.0% |
| warranty_eligible | 7 | 4 | 57.14% | 13 | 30.77% |
| parts_price_outlier | 10 | 6 | 60.0% | 12 | 50.0% |
| duplicate | 4 | 3 | 75.0% | 3 | 100.0% |
| math_error | 12 | 12 | 100.0% | 120 | 14.17% |

**Cost estimate (arithmetic, not measured; prices unverified):** one invoice page at high detail is about 1,700 input tokens (image ~800 + instructions and schema ~900) and ~900 output tokens, which at gpt-4o list prices ($2.50 / $10 per million) is about $0.013 per page. VMRS classification adds up to ~$0.004 per invoice at first and falls as the per-client cache fills; flag explanations add ~$0.001. Expect roughly **$0.015 to $0.02 per single-page invoice**, so ~$15 to $20 per 1,000 invoices. A real run replaces this with the measured value.

**Throughput:** the non-AI pipeline takes about 1 s per invoice; model latency (unmeasured, typically 5 to 15 s per page) dominates. With 4 workers 1,000 invoices would take roughly 20 to 60 minutes of machine time, so the 5-working-day workflow is limited by analyst review, not processing. Analyst review time was not measured.

## Success targets

| Target | Result |
|---|---|
| Field extraction accuracy 90%+ | **NOT VERIFIED.** Needs a real OpenAI key. The harness is ready (`python -m eval.run_eval --provider openai`); the oracle figure above is not evidence. |
| Flag precision 80%+ | **Met on correctly read data:** 87.5% (default warranty list), 100.0% (aligned). **End to end it depends on extraction quality:** 25.0% with the oracle's simulated errors, 77.27% for flags not marked 'check extraction first'. Precision also depends on analysts, who dismiss the rest. |
| Isolation tests 100% pass | **Met**: all isolation tests passed. |

## Known limitations
- **No real AI run.** No API key was available, so real extraction accuracy, real cost per invoice, real model latency, model calibration of confidence, and behaviour on rotated, warped, blurry or truly handwritten pages are all unmeasured. Synthetic handwriting is a script font with jitter and is easier than real handwriting.
- **The oracle is not a model.** It replays the answer key with injected errors and made-up confidence calibration. Accuracy and review-rate figures from it only exercise the plumbing.
- **Synthetic data is cleaner than real data.** Planted problems are well separated from normal variation; real invoices will produce more borderline flags. Planted counts: 12 inflated hours, 9 repeat repairs, 7 warranty cases, 10 parts outliers, 4 duplicates, 12 maths errors (the brief asked for about 10 of each).
- **Flagged-line marker.** The review screen shows a callout and a highlighted row; the picture band only appears when the model supplies a line position (`y_center`), which is untested with a real model.
- **Rule weaknesses.** Parts-price checks need a part number and at least 3 samples; repeat repair excludes routine work (PM, filters, diagnostics) by default; benchmarks and baselines come from the client's own invoices and need at least 5 / 3 samples; a repair with two lines for the same component is one flag.
- **Perspective-warped photos** are not corrected (de-skew handles rotation only); page rotation of 90/180 degrees relies on the model reporting it and is tested only with scripted responses.
- **Security is prototype-grade** (see `docs/security-overview.md`): in-memory rate limiter, shared-secret inbound email, no MFA/SSO, no virus scan, no backups, zero data retention at the provider is an agreement not verified here, TLS config not exercised.
- **PDF** uses a server template with the same data as the dashboard, not a browser render of the dashboard page.
- **Parts-of-spend metrics** use invoice totals as read; misread totals change the 'spend reviewed' figure until fixed.
- **Not built:** client portal, Fleetio/telematics, detention recovery, disputing invoices, mobile app.

