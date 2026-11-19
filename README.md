# Repair invoice audit (proof of concept)

Reads a fleet's outside repair invoices (PDF, scans, phone photos) with AI, flags likely overbilling and missed recoveries,
lets an analyst confirm each finding, and produces a client report (web link + PDF). One deployment, many clients, data
kept separate per client. Internal tool for Techtic Solutions; clients do not log in.

## Quick start
```bash
cp .env.example .env            # add OPENAI_API_KEY and, once confirmed with the provider, AI_ZDR_CONFIRMED=true
docker compose up -d --build    # db, redis, minio, api, worker, maintenance, web
open http://localhost:3000      # sign in: admin@audit-demo.com / admin-password-123  (demo accounts, change them)
```
With no key set, start the stack offline instead: `AI_PROVIDER=fake docker compose up -d --build` (the API refuses to start
with `AI_PROVIDER=openai` and no key, by design).

**One command demo:** `make demo` (or `make demo-clean` to wipe the local volumes first). It generates the 200 synthetic
invoices if needed, loads and reads them, runs the checks, accepts the flags that match the answer key, dismisses the rest,
creates the report and PDF (`demo/sample_report.pdf`) and prints the numbers. With an OpenAI key it uses the real AI.
**Without a key it uses an offline oracle that replays the answer key with injected errors; everything after reading is real,
but the reading accuracy it reports is not a model result.**

## Local without Docker

PostgreSQL, Node.js, and Python 3.11+ on the host. With `QUEUE_INLINE=true` you do not need Redis or an RQ worker. Set
`STORAGE_BACKEND=postgres` in `api/.env` to keep uploaded files in the database (no MinIO).

1. **Database** — create role `audit` / password `audit` and databases `audit` and `audit_test` (see `infra/postgres-init.sql`).
   If port 5433 is in use, point `DATABASE_URL` at 5432 in `api/.env`.
2. **API** — `cp api/.env.example api/.env`, then `./scripts/dev-local.sh` (or follow the manual steps inside the script).
3. **Web** — `cd web && npm install && API_URL=http://127.0.0.1:8000 npm run dev`. With `AUTH_DISABLED=true` in `api/.env`, no sign-in screen (acts as admin).
4. **File storage** — default in `api/.env.example` is `STORAGE_BACKEND=postgres`. Use MinIO only if you set `STORAGE_BACKEND=s3`.

Demo logins: `admin@audit-demo.com` / `admin-password-123`, `analyst@audit-demo.com` / `analyst-password-123`.

## How to run an audit
1. **Create the client.** Admin: *Clients -> Add client*. Open *Settings* to check the warranty rules (defaults for ~16
   components) and, optionally, import licensed labour benchmarks (CSV: `vmrs_code, benchmark_hours`).
2. **Upload invoices.** *Upload*: drop PDFs, JPG, PNG or HEIC files (25 MB max each). Or email them to the client's inbox
   address (webhook `POST /inbound/email/<token>`; test with `scripts/send_test_email.py`). Exact duplicates are skipped and
   listed. Wait until no file says Queued or Reading.
3. **Fix what the AI was unsure of.** *Review -> Invoices*: open invoices marked *Needs review*, compare the fields marked
   "Check" with the image, edit them, then *Mark as checked*. After editing, *Re-check this invoice* refreshes its flags.
4. **Run checks.** *Review -> Flags*: *Run checks*. Reference data is recomputed from the client's invoices, the six rules
   run, and each flag gets a plain-English reason and a dollar impact.
5. **Review every flag.** Open a flag; *Accept flag* (A), *Dismiss flag* (D, pick a reason) or *Edit flag* (E: change the
   amount or reason, add a note). J and K move between flags. Flags marked "hard to read" depend on numbers the AI was unsure
   of: check the image first.
6. **Create the report.** When no flag is open, *Create report* (Reports). It is a frozen copy of the accepted flags. Choose
   the link expiry and edit the service-offer text. Then *Open dashboard*, *Download PDF*, or *Copy link* for the client.
7. **Finish.** Admin: *Settings -> Audit and data -> Mark audit complete*. Raw files are deleted automatically after the
   retention period (90 days by default). *Audit log* (rail foot, admins) shows who did what.

## What is sent to the AI provider
- **Page images** of every uploaded invoice (as they are: names, addresses, phone numbers and VINs on the page are visible).
- **Text:** short line descriptions (to pick a VMRS code), each flag's numbers (to explain it), and per-type totals and
  example sentences (to write report paragraphs). Shop name and invoice numbers can appear in these.
- Never: staff data, passwords, keys, other clients' data, or anything not listed above.
- Settings: `AI_PROVIDER=openai|claude`, `AI_ZDR_CONFIRMED` (the app will not call the provider until zero data retention is
  confirmed), `AI_REDACT_BEFORE_SEND=true` (masks VINs and phone numbers in the text above; images are not masked),
  `AI_ENABLED=false` (no AI calls at all). Raw model responses are stored encrypted for audit; nothing is logged.

## Configuration
`.env` (see `.env.example`): `OPENAI_API_KEY`, `OPENAI_MODEL` (default gpt-4o), `AI_PROVIDER`, `CONFIDENCE_THRESHOLD` (0.80),
`EXTRACTION_RETRIES` (1), `PRICE_INPUT_PER_MTOK` / `PRICE_OUTPUT_PER_MTOK` (cost estimates; check current pricing),
`RAW_FILE_RETENTION_DAYS` (90). Per-client thresholds (labour %, repeat days/miles, parts %, severity bands, retention) are
editable via `PATCH /clients/{id}` settings. Report branding and the default offer text: `api/app/report_settings.json`.
Prompts: `api/app/prompts/*.txt`. Run `make config-check` to list what is not set for production;
`docker-compose.prod.yml` adds TLS. For non-Docker API runs, copy `api/.env.example` to `api/.env`.

## Tests
`make test` runs the backend suite. For the synthetic-data cases mount the set:
`docker compose run --rm -v $PWD/synthetic:/synthetic:ro api python -m pytest -q`.
Browser tests: `cd web && npx playwright test` (stack running with `AI_PROVIDER=fake FAKE_PROVIDER_DEMO=true`).
Measurements: `python -m eval.run_eval` (extraction), `python -m eval.run_flag_eval` (rules), `python -m app.demo` (all).
Results and known limitations: `TEST_RESULTS.md`. More: `docs/` (architecture, data policy, security overview, NDA template,
design plan).

## Known limitations and next steps
See `TEST_RESULTS.md`. Next: client portal, Fleetio and telematics integrations, detention recovery, licensed benchmark data,
Textract/Azure adapters, SSO/MFA, per-link rate limits.