# Security overview (prototype)

> **Important:** since the team commits of 2026-11-19, `AUTH_DISABLED` defaults to **true** (`api/app/config.py`, `docker-compose.yml`): there is no login and every request acts as an admin. Everything below about accounts, roles and rate limiting describes the code when `AUTH_DISABLED=false`, which is what the tests enforce. See `docs/scope-compliance.md` section 6.

What is done, what is configured but untested, and what is not done. A proof of concept is not a production system.

## Done and tested (automated tests in `api/tests/`)
| Area | What | Test |
|---|---|---|
| Client separation | One shared data layer adds the client filter to every query on client tables, refuses queries with no client bound, and refuses writes into another client. | `test_isolation*.py` |
| Every endpoint | All routes with a client id and all routes with an object id are generated from the app's route table and attacked from the wrong client; none succeed. All routes except the public ones refuse anonymous callers. | `test_security.py` |
| Accounts | Staff-only login, argon2 password hashes, signed session cookie (HttpOnly, SameSite=strict, expires), roles admin and analyst. | `test_security.py`, `test_auth.py` |
| Admin only | Create clients/users, edit settings and warranty rules, import benchmarks, revoke links, mark audit complete, delete data, read the audit log. | `test_security.py` |
| Rate limiting | 5 failed sign-ins per email or address in 15 minutes blocks further attempts (even with the right password). | `test_security.py` |
| Report links | 43-character random token, only a hash is stored for lookup, expiry date, admin revoke; expired and revoked links return 410. | `test_reports.py` |
| Audit log | Views, edits, accepts, dismisses, exports, deletions, logins, with who and when; admin page to browse it. | `test_security.py`, `test_review.py` |
| Deletion | Scheduled raw-file deletion after the retention period, manual deletion, delete-everything; reports and extracted data survive raw deletion. | `test_security.py` |
| Secrets and logs | Keys masked in every log line; test proves an API-key canary and invoice-content canaries never appear in logs or responses; repo scan for keys. | `test_security.py`, `make scan` |
| Model output at rest | Raw model responses are stored encrypted (Fernet). | `test_ingest_pipeline.py` |
| Startup checks | The API refuses to start without the key for the configured AI provider; `make config-check` lists every unset production setting. | `test_security.py` |

## Configured but not verified here
- **Zero data retention / no training** with the AI provider is an agreement, not a switch. `AI_ZDR_CONFIRMED=true` records that it was arranged; until then the AI provider classes refuse to run. Nothing here proves the provider honours it.
- **Encryption at rest:** the S3 bucket must have default encryption (SSE) and `S3_SSE` set; MinIO locally is not encrypted. **TLS:** `docker-compose.prod.yml` puts a TLS-terminating proxy in front; it is validated with `docker compose config` only and has never been deployed.

## Not done
- No SSO, MFA, password reset flow or account lockout beyond the rate limit; the rate limiter is in memory (one API process).
- No malware scanning of uploads (file type is checked by content, not scanned).
- Page images cannot be redacted before they go to the AI (text can).
- The inbound-email webhook uses a shared secret, not provider signature verification.
- No backups, monitoring, or intrusion detection. No penetration test. No formal compliance (SOC 2 etc.).
- Public report links have no per-link rate limit. Anyone holding a link can read the report until it expires or is revoked.
- Deleting data from object storage does not delete provider-side backups or anything the AI provider retains.
