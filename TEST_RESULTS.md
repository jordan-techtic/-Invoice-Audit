# Test results

Generated 2026-11-19 by `scripts/gen_test_results.py` from the artifacts of the last run.

**21 PASS, 3 PARTIAL, 0 FAIL** across 24 cases below (+ case 25 metrics).  Backend tests: 209 passed, 0 failed.  Browser tests: 5 passed, 0 failed.

**PARTIAL** means the mechanism passes but the claim depends on a real AI model, which could not be run here (no API key).

| # | Case | Result | Evidence | Notes |
|---|---|---|---|---|
| 1 | Clean PDF, skewed scan, phone photo are extracted | **PARTIAL** | REAL: de-skew on 30 scans cut mean skew 1.31 deg -> 0.28 deg (max 1.5), correlation with true skew 0.975; all file types render; HEIC converted and processed. Pipeline stores header+lines for all 3 kinds. | Real OpenAI run, full set: field accuracy by type multi pdf 99.55%, clean pdf 98.67%, phone photo 75.15%, handwritten 87.66%, skewed scan 98.65%. Phone photos (and handwriting) are below the 90% bar. |
| 2 | Multi-invoice PDF split into the right invoices | **PASS** | 3 multi PDFs (3, 4, 5 invoices; includes 2-page invoices): invoice counts and page ranges exactly match the key. Unit tests cover the boundary rules. | Real model, full set: 100.0% of files split correctly (204 of 204 invoices found). |
| 3 | Same file twice: duplicate skipped and user told | **PASS** | Second upload status 'duplicate' with 'Skipped: identical to first.pdf, already uploaded on ...'; never sent to the AI. All 4 byte-identical copies in the set caught. |  |
| 4 | Unsupported or corrupt file: clear error, no crash | **PASS** | exe, txt, empty -> 'isn't a PDF, JPG, PNG or HEIC file'; damaged PDF -> 'damaged or password-protected'; truncated PNG -> 'couldn't open this image'; app stays up; failed files can be retried. |  |
| 5 | Blurry invoice: low-confidence fields go to review, not guessed | **PARTIAL** | REAL: heavy blur does not break preprocessing. MECHANISM (scripted): a null stays null, uncertain VIN/unit go to review. REAL MODEL, manual test on 3 phone photos at blur radius 0/5/9/14: wrong fields 11/14/14/14 of 18; at radius 5-14 the model returned EMPTY for 11-14 fields instead of guessing; at no added blur 10 of the 11 wrong fields were not flagged (overconfident). | Not guessed: yes. Sent to review: only for invoice number, date, total and shop; an empty unit number, odometer or VIN is NOT sent to review. Backlog: have the model say 'absent' (confidence 1) vs 'illegible' (confidence 0) and review the latter. |
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
| 24 | `make demo` does everything from a clean state | **PASS** | Created client, loaded 199 files -> 204 invoices, ran checks (105 flags), accepted 40 matching the key (5 with the amount corrected, as an analyst would after looking at the image), dismissed 65, report $13,639.73, PDF 39,541 bytes at demo/sample_report.pdf. | Mode: real AI |

## Case 25: measurements

Run mode: **real AI**.

| Metric | Value | Basis |
|---|---|---|
| Invoices processed | 204 from 199 files (expected 204); exact duplicates skipped 4/4; failed files 0 | real pipeline |
| Multi-invoice split correct | 100.0% of files | real model, full set |
| Field accuracy (header + lines, 7,108 fields) | 92.05% | real model |
| Flags raised / precision / recall end to end | 105 / 38.1% / 70.37% | rules real on extracted data; real extraction |
| Precision of flags not marked 'check extraction first' | 53.49% of 43 flags; 45 of 65 false flags were already marked | real |
| Flag precision / recall, rules on correctly read data | 87.5% / 88.9% (default warranty list); 100.0% / 90.7% (warranty list matching the planted components) | real; isolates the rules |
| Same, VMRS codes from keyword lookup only (no AI) | 84.6% / 79.6% | real |
| VMRS accuracy, keyword lookup alone | 87.85% (258 of 724 lines unresolved; they go to the AI) | real |
| Seconds per invoice | 9.913 s per invoice wall time (8.7 s of that is model time) with one worker; checks for all invoices 59.78 s (includes AI explanations); whole run 2092.2 s | real |
| Cost per invoice | $0.01754 | measured |

Per rule on the end-to-end path:

| Rule | Planted | Found | Recall | Flags | Precision |
|---|---|---|---|---|---|
| labour_over_benchmark | 12 | 11 | 91.67% | 15 | 73.33% |
| repeat_repair | 9 | 2 | 22.22% | 2 | 100.0% |
| warranty_eligible | 7 | 4 | 57.14% | 9 | 44.44% |
| parts_price_outlier | 10 | 6 | 60.0% | 9 | 66.67% |
| duplicate | 4 | 4 | 100.0% | 4 | 100.0% |
| math_error | 12 | 11 | 91.67% | 66 | 19.7% |

**Measured cost and speed (real OpenAI gpt-4o):** $0.01754 per invoice ($3.4997 for 204 invoices; extraction, classification and flag explanations; report paragraphs not counted), 8.7 s of model time per invoice, 2092.2 s for the whole run on one worker. About **$17.50 per 1,000 invoices** and roughly 2.5 hours of machine time per 1,000 on one worker. Token prices are list prices and unverified.

## Success targets

| Target | Result |
|---|---|
| Field extraction accuracy 90%+ | **Met on synthetic invoices: 92.05%** (real OpenAI gpt-4o, all 204 invoices, 0 failed files; the first full run before any tuning scored 91.5% on 193 invoices). **Below 90% for phone photos (75.15%) and handwriting (87.66%).** Prompts were tuned on this same set, and real invoices will be harder, so this is not proof for real data. |
| Flag precision 80%+ | **Met on correctly read data:** 87.5% (default warranty list), 100.0% (aligned). **End to end it depends on extraction quality:** 38.1% with the real model, 53.49% for flags not marked 'check extraction first'. Precision also depends on analysts, who dismiss the rest. |
| Isolation tests 100% pass | **Met**: all isolation tests passed. |

## Known limitations
- **Measured with a real model only on synthetic invoices.** Real invoices will be harder. Synthetic handwriting is a script font with jitter and is easier than real handwriting. Rotated (90/180 degree) and perspective-warped pages are still unmeasured with the real model.
- **The model is overconfident.** In the first real runs only about 16% of wrong fields had low confidence, so the review queue alone misses most misreads; sanity checks and the "check extraction first" marker on flags help (the marker was on 83% to 69% of false flags) but do not close the gap.
- **Flags built on misread numbers dominate false positives.** End to end with the real model, 105 flags gave 38% precision (66 maths-error flags, 20% precise); flags not marked "check extraction first" were 53% precise. The scope's 80% is measured after analyst review, which has not been done by a real analyst.
- **A rate-limit episode at the AI provider** failed 45 files in one run; retries and clearer messages were added afterwards and the final run had no failures, but this is not tested at scale. (The offline oracle, used when no key is set, is not a model; its figures only exercise the plumbing.)
- **Synthetic data is cleaner than real data.** Planted problems are well separated from normal variation; real invoices will produce more borderline flags. Planted counts: 12 inflated hours, 9 repeat repairs, 7 warranty cases, 10 parts outliers, 4 duplicates, 12 maths errors (the brief asked for about 10 of each).
- **Flagged-line marker.** The review screen shows a callout and a highlighted row; the picture band only appears when the model supplies a line position (`y_center`), which is untested with a real model.
- **Rule weaknesses.** Parts-price checks need a part number and at least 3 samples; repeat repair excludes routine work (PM, filters, diagnostics) by default; benchmarks and baselines come from the client's own invoices and need at least 5 / 3 samples; a repair with two lines for the same component is one flag.
- **Perspective-warped photos** are not corrected (de-skew handles rotation only); page rotation of 90/180 degrees relies on the model reporting it and is tested only with scripted responses.
- **Security is prototype-grade** (see `docs/security-overview.md`): in-memory rate limiter, shared-secret inbound email, no MFA/SSO, no virus scan, no backups, zero data retention at the provider is an agreement not verified here, TLS config not exercised.
- **PDF** uses a server template with the same data as the dashboard, not a browser render of the dashboard page.
- **Parts-of-spend metrics** use invoice totals as read; misread totals change the 'spend reviewed' figure until fixed.
- **Not built:** client portal, Fleetio/telematics, detention recovery, disputing invoices, mobile app.

