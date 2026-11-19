# Data handling policy

Applies to client invoice data processed by the Repair Invoice Audit tool. Short on purpose: it says what we do, and where the prototype does not yet do it (see the security overview).

## What data we hold
- **Raw files:** the invoices a client sends (PDF, scan, photo) and the page images we make from them.
- **Extracted data:** shop, invoice number, date, unit, VIN, odometer, line items, totals, with a confidence score per field.
- **Findings:** flags, analyst decisions and notes; **reports** (a frozen copy of each report and its PDF).
- **Staff data:** staff names, emails, password hashes, an audit log of who viewed, edited, accepted, dismissed, exported or deleted what.

## Rules
1. **Separation.** Each client's data is stored and queried separately. Every query is scoped to one client by a single shared data layer, and tests try to cross the boundary on every endpoint.
2. **Access.** Only Techtic staff with an account can open client data, and only the clients they are assigned to (admins see all). Clients do not log in. A client sees a report only through a read-only link that is long and unguessable, expires (default 30 days) and can be turned off by an admin.
3. **Where data goes.** Client data is sent only to our storage (US region, encrypted) and to the AI provider we use to read and describe invoices. The AI provider must run under zero data retention or equivalent, with no training on our data; the app will not call the provider until that has been confirmed in configuration. Nothing else receives client data.
4. **Minimising what the AI sees.** The AI receives page images and, for later steps, short text (line descriptions, numbers). An optional setting masks VINs and phone numbers in text. Page images are sent as they are.
5. **Retention and deletion.** Original files and page images are deleted automatically 90 days after the audit is marked complete (configurable per client). An admin can delete them sooner, or delete everything for a client, after a confirmation. Extracted data and reports are kept until an admin deletes them. Every deletion is recorded in the audit log.
6. **Secrets.** API keys and encryption keys come from the environment, never from the code or repository, and are masked in logs.
7. **Logging.** Logs hold ids, statuses and counts. They never hold invoice contents, extracted values or keys.
8. **Incidents.** Suspected unauthorised access is reported to the security owner immediately and to affected clients within 72 hours of confirmation.
9. **Synthetic data.** Demos and tests use synthetic invoices only. Never put real client data into a demo, test or screenshot.

## Responsibilities
The security owner reviews the audit log monthly, confirms deletions ran, and re-checks the configuration list (`make config-check`) before each new client.
