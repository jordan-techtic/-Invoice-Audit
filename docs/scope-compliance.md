# Scope compliance review: "Build Scope of Work – Repair Invoice Audit POC"

Compares what is built with each section of the scope document, and lists what remains. Every status below was checked
against the code, the tests or a run artifact on 2026-11-19. **Done** = works and is tested. **Partial** = works but with a
named gap. **Not done** = absent. "Synthetic" means the 204 generated invoices; no real client invoices have been used.

## Verdict
The product the scope describes exists end to end and works on synthetic invoices with a real OpenAI model: upload, read,
check, review, report (web link + PDF), multi-client, staff roles, deletion, audit log. **It is a working POC, not yet
ready for a first real client.** Only the accuracy criterion is met, and only on synthetic invoices; the other three need
real analysts, a 1,000-invoice run, or human readers (section 3). **Login is currently switched off by default (section 6).** The blockers are mostly things only you can
arrange: sample invoices, OpenAI zero-retention confirmation, AWS hosting, an email provider, and the fleet advisor.

Found and fixed during this review: `docker-compose.prod.yml` did not parse (the API still depended on the local MinIO it
had turned off). It is fixed and validated with `docker compose config`; it has not been deployed. (Docker was later removed from the repo on 2026-11-19; there is no deployment config now.)

## 1. Scope (section 2) and modules (section 3)

| Scope item | Status | Evidence / gap |
|---|---|---|
| Bulk upload: PDF, scans, phone photos | **Done** | PDF/JPG/PNG/HEIC, 25 MB, per-file progress; HEIC and de-skew tested on real files. |
| Dedicated email inbox per client | **Partial** | Webhook `POST /inbound/email/<token>` works and is tested with a stub script. No email provider is connected, no address format or domain exists, the address is not shown anywhere in the UI, and the webhook uses a shared secret rather than provider signature checks. |
| AI extraction of header and line items | **Done** | Real OpenAI run: 91.5% field accuracy (run 1). See section 3 for the caveats. |
| Normalised invoice database per client | **Done** | `client_id` on every table, enforced by one shared data layer. |
| Rules + AI flagging engine | **Done** | Six rule modules; AI writes reasons and scores. |
| Analyst review screen | **Partial** | Accept/dismiss/edit, sort by dollars, filters, keyboard shortcuts, side-by-side image and data all work (4 browser tests). The "flagged line marked on the image" draws a band from the line position the model reports (`y_center`). The real model does fill it (725 of 725 lines), but how accurate the position is has not been measured; a text callout and highlighted row are always shown as well. |
| Client report: PDF + web dashboard | **Done** | Same snapshot feeds both; link expires and can be revoked. |
| Multi-client reuse | **Done** | Isolation tested on every route (auto-generated from the route table). |
| 3.1 File type detection, de-duplication, multi-invoice page splitting | **Done** | Content-based type check; SHA-256 de-dup (4/4 planted copies caught); splitting 100% on the 3 multi-invoice PDFs. |
| 3.2 Confidence per field; low-confidence to human review | **Partial** | Built (threshold 0.80, notes in plain words). **But the real model is overconfident: only about 16% of its wrong fields came back with low confidence** (and in a manual blur test, an empty unit number, odometer or VIN is not sent to review at all), so the review queue alone misses most misreads. Sanity checks (VIN check digit, totals, dates) and the "check extraction first" marker on flags catch more (the marker was already on 83% of the false flags in both real-model runs), but field-level protection is weaker than the scope assumes. |
| 3.2 VMRS mapping by AI | **Partial** | Keyword lookup + AI, cached per client: 88–94% accurate. The seed has 112 codes, not the full VMRS list, so real invoices will have more unmapped lines. |
| 3.2 Optional OCR fallback (Textract/Azure) | **Not done** | Only the `ExtractionProvider` interface exists; no adapter. |
| 3.3 Labour benchmarks | **Partial** | Baseline from the client's own invoices (needs 5 samples, per vehicle class) and the job-list CSV import (per job and vehicle class) both work. No licensed dataset has been sourced or loaded. |
| 3.3 Repair history, parts baseline | **Done** | From invoices; median per part number (needs 3 samples). |
| 3.3 Warranty rules per client | **Done** | No built-in defaults any more: an admin imports the client's own `warranty_rules.csv` (or adds rules in the UI). Each rule says whether it covers parts only or parts and labour. See `docs/client-settings.md`. |
| 3.4 Six flag rules, dollar impact, plain-English reason | **Done** | Per-rule unit tests; wording guardrail (no "fraud", must hedge). |
| 3.4 "AI explains and scores each finding" | **Partial** | The score is computed and stored, but nothing shows or uses it: not displayed on the review screen, not used for sorting. |
| 3.5 Sortable by dollars; accept, dismiss, edit | **Done** | Plus dismiss reasons, notes, audit trail, and "report blocked while any flag is open". |
| 3.6 Executive summary, top 5, breakdowns, appendix, next steps, branded PDF | **Done** | The 204-invoice demo PDF is 11 pages; the summary is on page 2. Branding comes from `report_settings.json` (text logo only). The per-client "service offer" field on the client record is not wired into reports (the report takes the text at creation). |

## 2. Tech stack and security (sections 4 and 5)

| Requirement | Status | Evidence / gap |
|---|---|---|
| Next.js, FastAPI, PostgreSQL, S3, HTML-to-PDF | **Done** | Next 16, FastAPI, Postgres 16, MinIO locally / S3 in config, WeasyPrint. |
| Hosting on AWS, US region | **Not done** | Never deployed. There is no deployment config in the repo (Docker was removed on 2026-11-19); S3 settings are in `api/.env.example`. |
| Encrypted at rest | **Partial** | Raw model responses are encrypted by the app (tested). Object storage needs S3 SSE (config exists, not exercised; local MinIO is unencrypted). **Database at-rest encryption is not configured**; it would come from encrypted RDS/volumes. |
| Encrypted in transit | **Partial** | No TLS config in the repo; production needs a TLS reverse proxy in front. Local runs are plain HTTP. |
| Per-client isolation | **Done** | Strongest part: shared data layer, all 35 client routes attacked from the wrong client, cross-client write refusal. |
| Role-based access, staff only | **Partial** | Admin/analyst roles enforced on 13 admin actions. **No UI to create or manage staff accounts** (API only); no MFA, SSO or password reset. Login rate limit is in memory (one process). |
| NDA template and deletion policy | **Done** | `docs/nda-template.md` (needs legal review), `docs/data-handling-policy.md`; automatic raw-file deletion 90 days after audit complete, tested. |
| No training on client data; zero-retention LLM settings | **Partial** | The app refuses to call the AI until `AI_ZDR_CONFIRMED=true`. **Zero retention itself is an agreement with OpenAI that has not been made or verified.** For the synthetic runs I overrode the check in `.env` (test only, labelled). |
| Option to redact (risk table) | **Partial** | Masks VIN and phone numbers in text sent to the AI. Page images cannot be masked. |

## 3. Success criteria (section 8)

| Criterion | Status | Evidence |
|---|---|---|
| Field extraction accuracy 90%+ on test invoices | **Met on synthetic, not proven** | Final full run (real OpenAI gpt-4o, all 204 invoices, 0 failed files): **92.05%**. The earlier untuned run scored 91.5% on 193 invoices, so prompt tuning added about one point. By file type: multi-invoice PDFs 99.6%, skewed scans 98.7%, clean PDFs 98.7%, handwritten 87.7% (**below 90%**), **phone photos 75.2% (well below 90%)**. A middle run reported 84% on photos, but that was only the files that survived a rate-limit episode; on the full set photos did not improve. Prompts were tuned on this same test set and real invoices will be harder, so this needs real samples. |
| Flag precision 80%+ after analyst review | **Cannot be measured yet** | Analyst review is mandatory (report blocked while any flag is open), which is the scope's mitigation. The scope measures precision *after* a human reviews, which needs real analysts. My demo's "analyst" uses the answer key, so its 100% is true by construction and proves nothing. What I can measure is precision *before* review: 87.5% on correctly read data (100% with warranty rules matching the synthetic ones); end to end with real extraction (final run) **38% overall and 53% for flags not marked "check extraction first"** (105 flags, 66 of them maths-error flags at 20% precision). Misreads cause most false flags, which is exactly what review is for, but it means analysts will be dismissing roughly 6 in 10 flags. |
| About 1,000 invoices processed and reported in 5 working days | **Not tested** | Largest run: 204 invoices. Measured on the final run: 9.9 s per invoice wall time (8.7 s of it model time), so about 2.7 hours of machine time per 1,000 on one worker, and **$0.0175 per invoice, about $17.50 per 1,000**. Machine time is not the constraint; analyst review time (not measured) is. One worker process only, and a rate-limit episode cost 45 files in the second run (retries and clearer messages were added; the final run had 0 failures, but this is untested at scale). |
| Report understandable by a fleet manager in under 5 minutes | **Not tested; partly supported** | The summary page is 186 words with one big figure and the top 5 in plain sentences, readable in about 1 minute; the whole body is about 2,500 words (about 12 minutes). No non-expert has read it with a stopwatch. Consider shortening the body or making the summary page the whole point. |

## 4. Key risks table (section 9)

| Risk | Mitigation in scope | Status |
|---|---|---|
| Poor scans / handwriting | Confidence + review queue | **Partial**: handwriting 87.7%, phone photos 75.2%; confidence is poorly calibrated (see 3.2). |
| Benchmark data costly | Dataset baseline + advisor review | **Partial**: baseline built; advisor review and licensing not done. |
| False positives damage credibility | Mandatory analyst review | **Done** in software; precision after review unmeasured. |
| No sample invoices before first client | Anonymised samples or synthetic | **Partial**: synthetic only (204 invoices, 8 layouts, planted problems). |
| Fleets reluctant to share data | NDA, US hosting, redact option | **Partial**: NDA template and redaction exist; US hosting not deployed. |

## 6. Changes by others found in this review (decisions needed)

While running the final checks I found commits and edits by `kuldip jadav` and by you that differ from what the earlier
reports and tests describe. I did not revert any of them.

| Change | Effect | Decision needed |
|---|---|---|
| `auth_disabled` defaults to **true** in `config.py`; every request acts as the seeded admin, role checks and client-access checks are skipped | Scope section 5 ("role-based access for internal staff only") is **not met by default**. Anyone who can reach the API can read, change and delete every client's data. The tests only pass because `conftest.py` forces `AUTH_DISABLED=false`. Nothing in the production config forces it back on. | Decide whether this is a deliberate demo shortcut. For any real deployment set `AUTH_DISABLED=false` and add a production guard that refuses to start with it on. |
| New `STORAGE_BACKEND=postgres` option (invoice files stored in a `stored_objects` table) | Convenient locally. Files are stored unencrypted in database rows, so encryption relies on database at-rest encryption, not S3. **It had a bug**: `delete_prefix` called the wrong `delete`, so the 90-day deletion job, "Delete raw files now" and "Delete everything" all crashed on this backend. | I fixed the bug (one-line import alias) and added a regression test. Decide whether Postgres storage is for local use only. |
| New `api/.env` (for running the API on the host) contains the real OpenAI key, and `api/.dockerignore` did not exclude it | The key was **copied into the API, worker and maintenance Docker images** (found by the repo key-scan test). | I added `.env` to `.dockerignore`, rebuilt the three images and confirmed the key is gone. **Old images may still hold it:** run `docker image prune` for dangling layers, and rotate the key if any image was pushed or shared. Docker has since been removed from the repo. `.env` files are git-ignored and not in git history. |
| `.env.example` removed/changed in commits | New contributors have no template | Restore a template with no values. |


## 7. Detailed module verification (2026-11-19, live stack and real-model demo data)

Each scope module was checked against real output, not just the tests. Results, including problems found:

| Module | What was checked | Result |
|---|---|---|
| 3.1 Ingestion | Email webhook, then Redis queue, then worker, then real OpenAI, on a new file | Works: queued, reading, needs-review in 16 s, $0.0116, source recorded as email. An unchanged file sent by email is skipped as a duplicate. (The earlier demo ran inline and never used the queue.) |
| 3.2 Extraction | Fill rates over 205 invoices; VIN validity; confidence rows; encrypted responses | Shop, address, invoice number, date, totals 100% filled; unit 99%; odometer 82%; VIN 60% (some layouts print none). **Only 56% of stored VINs (69 of 124) have a valid check digit**, so VIN reading is weak. Confidence stored for every field (5,950 rows; 8% below 0.8). All 395 raw responses encrypted; no call needed a retry. |
| 3.2 Review queue size | Why 163 of 204 invoices were "needs review" | **Found and fixed:** 28% of lines are fees (shop supplies, environmental) that legitimately have no job code, and each one sent its invoice to review and was sent to the AI classifier. Exempting them cuts the queue from 163 to 86 invoices (42%) and saves AI tokens; regression test added. 86 invoices is still a heavy load: the remaining causes are VIN check digits (44), line maths (34 invoices) and subtotal/total mismatches. |
| 3.3 Reference data | Tables for the demo client | 27 job-type benchmarks from the client's own data (minimum 5 samples; e.g. oil change 1.6 h from 36 jobs, headlamp 0.5 h from 25), 40 part-price baselines (all across several shops), 16 warranty rules, 39 units with repair history. No licensed benchmark data loaded. |
| 3.4 Flags | Wording, dollars and score over all 105 real-AI flags | All 105 have a dollar impact and a reason; **all hedged, no banned words, two sentences or fewer**. The AI score exists for all but separates real from false only weakly (accepted flags average 0.82, dismissed 0.74) and is not shown in the UI. Large maths flags caused by misread digits still get high scores (0.9). |
| 3.5 Review | Flag detail data for the top accepted flag | Evidence in plain words, page image served (HTTP 200, 505 KB), extracted lines with the flagged one marked, reviewer name and time saved. Header-level flags (duplicates, totals) have no single line to mark. |
| 3.6 Reporting | Public link and PDF without login; every section present | Cover, summary with top 5, breakdown by type (6 rows), shop (9) and vehicle (9), 6 paragraphs, appendix covering all 40 accepted flags, next steps with the service offer, the analyst-review note. PDF is 12 pages. **Reading time:** the summary page is 186 words, but the full body outside the appendix is about 2,500 words (roughly 12 minutes), so the 5-minute goal holds for the summary, not the whole report. **Found and fixed:** the cover period read "Sep 2014 – Sep 2026" because one misread year got through; the period now ignores dates more than 5 years old or in the future. |

## 5. Remaining work

**A. Before any real client data (blockers)**
0. Resolve section 6: turn authentication back on (and refuse to start in production without it), decide on the Postgres storage backend, and rotate the OpenAI key if any image left this machine.
1. Get 50 to 100 anonymised real invoices from a friendly fleet or shop, and re-run the accuracy evaluation on them.
2. Confirm zero data retention with OpenAI, then set `AI_ZDR_CONFIRMED=true` and **restore `AI_ZERO_RETENTION_REQUIRED=true`** in `.env`. Have counsel review the NDA.
3. Deploy to AWS US region: encrypted S3 bucket, encrypted database, TLS, secrets in a secrets manager; make `make config-check --strict` pass; write and test the deployment (TLS proxy, process manager for API, worker and maintenance).
4. Connect a real inbound email provider (Postmark or SES): per-client address, signature verification, and show the address on the client page.
5. Fleet maintenance advisor reviews the rule thresholds, warranty defaults, the "routine work" exclusion list and the benchmark approach; get quotes for licensed labour data.

**B. To prove the success criteria**
6. Measure flag precision after review with two or more real analysts on real invoices, and record review time per invoice.
7. Run a 1,000-invoice test (synthetic is fine, about $17) with several workers (`QUEUE_INLINE=false`, Redis, and `make worker` started 4 times); record total time, cost, failures and rate-limit behaviour.
8. Have 2 or 3 non-expert people read the sample report with a stopwatch; fix what slows them.

**C. Product gaps found in this review**
9. Improve extraction on phone photos (75% vs the 90% bar): a blur check that asks for a re-photo, higher image resolution, and a second read of key fields (invoice number, date, total, VIN) with disagreement sent to review. A Textract/Azure adapter for numbers is the optional fallback the scope names.
10. Fix the overconfidence problem: only 16% of wrong fields are caught by confidence. Use cross-field checks and the second read above; do not rely on the model's own scores.
11. Show the AI score in the review screen and allow sorting or filtering by it (it is stored but unused).
12. Measure how accurate the model's line positions (`y_center`) are on real pages, or take positions from an OCR service.
13. Load the full VMRS code list (or a licensed one) instead of 112 codes.
14. Rule tuning with real data: parts-price recall is 62 to 70% (needs part numbers and 3+ samples), repeat-repair recall 50 to 78%, warranty precision depends on the component list; maths-error false positives come from misread digits.
15. Staff account UI (create, deactivate, assign clients), password reset, MFA or SSO; move the login rate limit to Redis; verify inbound email by provider signature.
16. Wire the per-client service-offer text into reports; logo upload for branding; PDF parity with the dashboard (it is a separate template with the same data).
17. Operations: database backups, monitoring and alerting, log shipping, a runbook, and a penetration test.
18. Mask page images, not just text, if "redact" must cover them.

**D. Later phases (scope section 10, not started)**
Client portal, Fleetio and telematics integrations, ongoing monthly auditing, detention recovery and paperwork automation, commercial model.

**E. Non-software items in the scope**
Team and timeline (sections 6 and 7), the advisor's hours, and benchmark licensing budget (section 11) are project decisions, not code.
