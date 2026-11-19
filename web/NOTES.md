# Frontend notes

Assumptions where the design plan was silent (one line each):

- Rail collapses at 1024px and below (Tailwind `lg` is set to 1025px), so a 1024px tablet gets the 72px rail and more room for the invoice view.
- The invoice view is two columns (about 60/40) from 900px wide; below that the image stacks above the fields.
- Review in the rail goes to /invoices (the invoice list); Reports goes to a calm "Coming soon" page.
- The active client is kept in localStorage (`ia.client`) and validated against the clients the user can see.
- Client invoice counts on /clients come from one invoice-list request per client (cheap at demo scale).
- Rows on the upload list are shown from the server; a file being sent or rejected appears as a temporary row above them.
- Up to 3 files are sent at once, each as its own request, so progress is per file.
- Fields save on blur or Enter; a saved field is cleared of its Check marker immediately, then the invoice is re-read to pick up normalised values.
- "Mark as checked" waits for any save still in flight before it posts.
- Lint script is `eslint .` because `next lint` no longer exists in Next 16.
- The API proxy reads API_URL at build time (rewrites are baked into the standalone build); the Dockerfile takes it as a build arg, default http://api:8000.
- `proxyClientMaxBodySize` is raised to 30 MB so 25 MB uploads pass through the /api proxy.
- Flags and Invoices are tabs inside Review; the flags e2e test mocks the flags endpoints, and the settings page is built to the contract but not yet run against the real API.
- Review nav goes to /review (flags, then Invoices tab); /flags redirects there. The open-flag list for J/K and "x of y" reuses the review filters saved in sessionStorage.
- Report percent is read as already a percentage (4.5 means 4.5%).
- Audit log link shows in the rail foot for admins only; the action filter lists common actions plus any seen in the loaded page.
- Deleting dialogs use the native dialog element and require typing the confirm word or the exact client name.
- The review and report e2e specs create their own data through the API and expect the Phase 4 backend.
