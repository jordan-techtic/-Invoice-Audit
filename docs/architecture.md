# Architecture

```
Browser (Next.js)  --/api proxy-->  FastAPI  --> PostgreSQL (all data, client_id on every table)
                                       |------> S3 in prod, Postgres locally  (clients/<id>/ raw files + page images; reports/<id>/ PDFs)
                                       |------> Redis + RQ  (queues: extraction, flags, maintenance)
                                       '------> AI provider (OpenAI default, Claude optional) via ExtractionProvider
Worker (RQ)  : process_upload, run_flags          Maintenance loop : raw-file retention
```

**Pipeline.** Upload (hash, de-duplicate, store) -> queue -> render pages, auto-rotate, de-skew, enhance -> AI reads each page into a strict JSON schema with a confidence per field -> split pages into invoices -> normalise and sanity-check (VIN check digit, date, totals) -> classify lines to VMRS codes (keyword lookup, then AI, cached) -> invoices, lines and field confidence stored; anything under 0.80 goes to review.

**Checks.** Reference data (labour benchmarks, parts baselines) is recomputed from the client's own invoices, then six rule modules run on plain data views, then the AI explains and scores each flag (the AI never creates a flag). Flags are stored with the evidence numbers and the dedupe key, so re-runs update open flags and never touch an analyst's decision.

**Review and report.** An analyst accepts, dismisses or edits each flag. A report can only be created when no flag is open; it is a frozen snapshot of the accepted flags (amounts as edited), rendered as a web page and a PDF from the same data.

**Provider swap.** `ExtractionProvider` has four methods (read a page, classify lines, explain flags, write report paragraphs). `OpenAIVisionProvider` and `ClaudeVisionProvider` implement them; a Textract or Azure Document Intelligence adapter would implement the page-reading method and delegate the text methods. Prompts live in `api/app/prompts/*.txt`.

**Tenancy.** `app/db.py`: client tables inherit `ClientScoped`; a session event adds `client_id = :bound` to every query touching them, and refuses unbound queries. Jobs and admin views use an explicit, greppable `system_session()`.
