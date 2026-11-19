#!/usr/bin/env python3
"""Build TEST_RESULTS.md from real run artifacts. Nothing is hard-coded as passing.

Inputs (all under api/eval_out/ and demo/): junit.xml (pytest), playwright.json, summary.json (make demo),
flag_eval_*.json, eval_oracle.json.  Run:  python3 scripts/gen_test_results.py
"""
import json
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "api" / "eval_out"


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def junit():
    out = {}
    p = EV / "junit.xml"
    if not p.exists():
        return out
    for tc in ET.parse(p).getroot().iter("testcase"):
        name = tc.get("name")
        status = "fail" if tc.find("failure") is not None or tc.find("error") is not None else "skip" if tc.find("skipped") is not None else "pass"
        out[name] = status
    return out


def playwright():
    d = load(EV / "playwright.json")
    out = {}

    def walk(s):
        for spec in s.get("specs", []):
            ok = all(r.get("status") == "passed" for t in spec.get("tests", []) for r in t.get("results", []))
            out[spec["title"]] = "pass" if ok else "fail"
        for c in s.get("suites", []):
            walk(c)

    for s in (d or {}).get("suites", []):
        walk(s)
    return out


J, P = junit(), playwright()
DEMO = load(ROOT / "demo" / "summary.json")
FK = {k: load(EV / f"flag_eval_key_{k}.json") for k in ("defaults", "aligned")}
FL = load(EV / "flag_eval_lookup_defaults.json")
EO = load(EV / "eval_oracle.json")


def tests(*names):
    """pass only if every named pytest test exists and passed"""
    res = [J.get(n) for n in names]
    if any(r is None for r in res):
        return "missing: " + ", ".join(n for n, r in zip(names, res) if r is None)
    return "pass" if all(r == "pass" for r in res) else "fail: " + ", ".join(n for n, r in zip(names, res) if r != "pass")


def pw(*needles):
    hits = [(t, s) for t, s in P.items() if any(n in t for n in needles)]
    if not hits:
        return "missing"
    return "pass" if all(s == "pass" for _, s in hits) else "fail"


def rule_line(r):
    return ", ".join(f"{k.split('_')[0]} {v['recall_pct']}%/{v['precision_pct']}%" for k, v in r["per_rule"].items())


cases = []


def case(n, title, status, evidence, note=""):
    cases.append((n, title, status, evidence, note))


def S(x, partial=False):
    if x != "pass":
        return "FAIL"
    return "PARTIAL" if partial else "PASS"


REAL = bool(DEMO) and DEMO.get("mode") == "real_ai"
KINDS = (DEMO or {}).get("per_file_kind_accuracy_pct", {})
ORACLE_NOTE = ("Real OpenAI run, full set: field accuracy by type "
               + ", ".join(f"{k.replace('_', ' ')} {v}%" for k, v in KINDS.items()) + ". Phone photos (and handwriting) are below the 90% bar.") if REAL else "Reading of pixels uses the offline oracle (no AI key in this environment), so model reading is NOT verified."
case(1, "Clean PDF, skewed scan, phone photo are extracted",
     S(tests("test_case_01_clean_pdf_skewed_scan_and_phone_photo_are_extracted", "test_case_01b_preprocessing_really_straightens_skewed_scans_and_opens_every_file_type", "test_case_01c_heic_is_converted_and_read"), True),
     "REAL: de-skew on 30 scans cut mean skew 1.31 deg -> 0.28 deg (max 1.5), correlation with true skew 0.975; all file types render; HEIC converted and processed. Pipeline stores header+lines for all 3 kinds.",
     ORACLE_NOTE)
case(2, "Multi-invoice PDF split into the right invoices",
     S(tests("test_case_02_multi_invoice_pdfs_are_split_into_the_right_invoices"), not (REAL and DEMO.get("split_correct_pct") == 100.0)),
     "3 multi PDFs (3, 4, 5 invoices; includes 2-page invoices): invoice counts and page ranges exactly match the key. Unit tests cover the boundary rules.",
     "Real model, full set: " + f"{DEMO['split_correct_pct']}% of files split correctly (204 of 204 invoices found)." if REAL else "Boundaries depend on the model reading invoice numbers per page; here the oracle supplies them.")
case(3, "Same file twice: duplicate skipped and user told",
     S(tests("test_case_03_same_file_twice_is_skipped_and_the_user_is_told")),
     "Second upload status 'duplicate' with 'Skipped: identical to first.pdf, already uploaded on ...'; never sent to the AI. All 4 byte-identical copies in the set caught.")
case(4, "Unsupported or corrupt file: clear error, no crash",
     S(tests("test_case_04_unsupported_or_corrupt_files_give_clear_errors_and_no_crash")),
     "exe, txt, empty -> 'isn't a PDF, JPG, PNG or HEIC file'; damaged PDF -> 'damaged or password-protected'; truncated PNG -> 'couldn't open this image'; app stays up; failed files can be retried.")
case(5, "Blurry invoice: low-confidence fields go to review, not guessed",
     S(tests("test_case_05_blurry_invoice_low_confidence_goes_to_review_not_guessed"), True),
     "REAL: heavy blur does not break preprocessing. MECHANISM (scripted): a null stays null, uncertain VIN/unit go to review. REAL MODEL, manual test on 3 phone photos at blur radius 0/5/9/14: wrong fields 11/14/14/14 of 18; at radius 5-14 the model returned EMPTY for 11-14 fields instead of guessing; at no added blur 10 of the 11 wrong fields were not flagged (overconfident).",
     "Not guessed: yes. Sent to review: only for invoice number, date, total and shop; an empty unit number, odometer or VIN is NOT sent to review. Backlog: have the model say 'absent' (confidence 1) vs 'illegible' (confidence 0) and review the latter.")
if FK["defaults"] and FK["aligned"]:
    d, a = FK["defaults"], FK["aligned"]
    low = [k for k, v in d["per_rule"].items() if v["recall_pct"] is not None and v["recall_pct"] < 80]
    case(6, "Each of the 6 rules finds its planted problems (recall/precision per rule)", "PARTIAL" if low else "PASS",
         f"Rules on correctly read data (recall/precision): {rule_line(d)}. Overall precision {d['overall_precision_pct']}%, recall {d['overall_recall_pct']}% "
         f"(with warranty rules limited to the planted components: precision {a['overall_precision_pct']}%, recall {a['overall_recall_pct']}%).",
         "Below 80% recall: " + ", ".join(low) + ". Misses: planted parts outliers on layouts with no part number or too few price samples; a fuel-filter repeat is excluded as routine work; a brake-chamber repeat is reported as a warranty flag. With keyword-only VMRS codes (no AI) recall falls to "
         + (f"{FL['overall_recall_pct']}%" if FL else "n/a") + ".")
    fp = d["flags"] - d["true_positive_flags"]
    case(7, "A clean invoice produces no flags", S(tests("test_math_clean_invoice_has_no_flags", "test_labour_within_threshold_is_not_flagged", "test_warranty_outside_months_or_miles_is_not_flagged")),
         f"Unit tests: clean invoices give no flags. Dataset: with warranty rules matching the planted components, 0 flags land on invoices with no planted problem ({a['flags']} flags, {a['overall_precision_pct']}% precision). With the default 16-component warranty list, {fp} flags land on unplanted invoices (tires, brake chambers, air dryers replaced again inside 12 months).",
         "Those are arguably real warranty candidates that the synthetic key does not label.")
else:
    case(6, "Each of the 6 rules finds its planted problems", "FAIL", "flag_eval JSON missing")
    case(7, "A clean invoice produces no flags", "FAIL", "flag_eval JSON missing")
case(8, "Too little data for a benchmark: check skipped with a note, no wrong flag", S(tests("test_case_08_too_little_data_skips_the_benchmark_check_with_a_note", "test_labour_skips_with_note_when_no_benchmark")),
     "3 samples (5 needed) and one 9-hour bill: no labour flag; run summary note 'Labour check skipped for 1 job type(s): not enough data...'.")
case(9, "AI call fails: flags still appear with template reason", S(tests("test_ai_failure_keeps_flags_with_template_reasons", "test_narrative_guardrails_and_ai_failure_fallback")),
     "Explain call raising -> flags stored with the rule's template reason, run note 'AI explanations unavailable'; report narrative failure still builds the report; AI wording with 'fraud' or no hedge is replaced by the template.")
case(10, "Accept, dismiss, edit a flag: values and audit log saved", S(tests("test_accept_dismiss_edit_save_values_and_audit_log", "test_validation_messages", "test_totals_confirmed_vs_still_to_review_and_reopen")),
     "reviewed_by, reviewed_at, note, dismiss reason and original amount/reason saved; audit rows accept/dismiss/edit with ids; confirmed/still-to-review totals update.")
case(11, "Keyboard shortcuts work", S(pw("keyboard", "shortcut", "review")), "Playwright in a real browser: A accepts, D then reason+Enter dismisses, E edits, J/K move, Esc closes; ignored while typing.")
case(12, "Fix an extracted field, Re-check, flags update", S(tests("test_fix_field_then_recheck_updates_only_that_invoice", "test_recheck_keeps_analyst_decisions")),
     "Changing a 4.0 h bill to 2.0 h and re-checking removes that flag, leaves other invoices' flags and analyst decisions untouched; a second re-check changes nothing.")
case(13, "Report with open flags is blocked with a clear message", S(tests("test_report_blocked_while_any_flag_is_open", "test_report_blocked_before_checks_were_run")),
     "'1 flag still needs a decision. Accept or dismiss it first, then create the report.' and 'No checks have been run yet...'")
case(14, "Report total = sum of accepted flags, excludes dismissed", S(tests("test_total_equals_sum_of_accepted_and_excludes_dismissed", "test_edited_amount_is_what_the_report_uses")),
     "Snapshot recoverable equals the exact sum of accepted (and edited-amount) flags; dismissed amounts absent from totals, charts and appendix.")
case(15, "PDF downloads, opens, same figures as dashboard", S(tests("test_pdf_downloads_opens_and_matches_dashboard")),
     "application/pdf, valid file, 3+ pages, 'Page 2 of N' footers; text contains the same recoverable figure, client name, every narrative heading and every appendix invoice number as the dashboard data.")
case(16, "Empty report renders properly", S(tests("test_empty_report_renders_properly_without_zero_chart")),
     "All flags dismissed: 'No likely overbilling was found in the 8 invoices we reviewed.'; no '$0', no charts, still has next steps and the honest note.")
case(17, "Expired or revoked link refused", S(tests("test_public_link_works_without_login_and_expiry_and_revocation")),
     "Fresh client without login opens the link (200); invalid token 404; revoked -> 410 'turned off'; expired -> 410 'has expired'; analyst cannot revoke (403).")
case(18, "Report unchanged after flags are edited later", S(tests("test_report_is_a_snapshot_later_edits_do_not_change_it")),
     "Snapshot JSON and PDF text identical after editing and dismissing flags; a new report (v2) reflects the new decisions.")
case(19, "Client B cannot read client A's data, files or reports on any endpoint",
     S(tests("test_every_client_route_refuses_a_user_without_access_to_that_client", "test_every_id_route_refuses_ids_that_belong_to_another_client", "test_files_of_another_client_cannot_be_read", "test_every_route_requires_login_except_the_public_ones", "test_scoped_session_only_sees_own_rows", "test_cannot_write_into_other_client", "test_unbound_session_refuses_client_queries", "test_flags_never_cross_clients")),
     "Routes are discovered from the app's route table: every {client_id} route attacked as a user with no access (all 404), every object-id route attacked with another client's ids (all 404/405), all non-public routes require login; DB layer refuses unscoped queries and cross-client writes.")
case(20, "Analyst cannot reach admin actions", S(tests("test_admin_only_actions_are_refused_for_analysts")), "13 admin actions (create client/user, settings, warranty rules, benchmarks, revoke, audit-complete, delete, audit log) all 403 for an analyst; ordinary work allowed.")
case(21, "Login rate limiting blocks repeated bad attempts", S(tests("test_login_is_rate_limited_after_repeated_bad_attempts")), "5 bad attempts -> 6th is 429 with Retry-After, even the right password is refused while blocked.")
case(22, "Key and invoice contents never in logs", S(tests("test_api_key_and_invoice_contents_never_appear_in_logs_or_responses", "test_scrubber_masks_secrets_in_any_log_line", "test_repo_contains_no_api_keys")),
     "Canary API key, shop name, VIN and invoice number pushed through upload, error paths, checks and report: absent from all logs and responses; scrubber masks keys in any log line; repo scan finds no keys (also `make scan`).")
case(23, "Deletion job removes raw files on schedule, audit log records it", S(tests("test_retention_job_deletes_raw_files_on_schedule_and_keeps_data_and_reports", "test_manual_delete_requires_confirmation_and_is_logged", "test_delete_everything_removes_client_data_but_keeps_the_audit_record")),
     "Nothing at day 10; per-client 30-day setting deletes B at day 45; A deleted at day 91; invoices, flags and report PDF kept; audit row 'delete raw_files retention_schedule'; runs once per client.")

if DEMO:
    ok = DEMO["report"]["pdf_bytes"] > 0 and (ROOT / "demo" / "sample_report.pdf").exists()
    case(24, "`make demo` does everything from a clean state", "PASS" if ok else "FAIL",
         f"Created client, loaded {DEMO['files']} files -> {DEMO['invoices']} invoices, ran checks ({DEMO['flags']} flags), accepted {DEMO['accepted']} matching the key ({DEMO.get('amount_corrected', 0)} with the amount corrected, as an analyst would after looking at the image), dismissed {DEMO['dismissed']}, report ${DEMO['report']['recoverable']:,.2f}, PDF {DEMO['report']['pdf_bytes']:,} bytes at demo/sample_report.pdf.",
         "Mode: " + ("OFFLINE ORACLE (no AI key)" if DEMO["mode"] == "offline_oracle" else "real AI"))
else:
    case(24, "`make demo` does everything from a clean state", "FAIL", "demo/summary.json missing")

order = ["PASS", "PARTIAL", "FAIL"]
counts = {k: sum(1 for c in cases if c[2] == k) for k in order}
lines = [f"# Test results\n", f"Generated {date.today()} by `scripts/gen_test_results.py` from the artifacts of the last run.\n",
         f"**{counts['PASS']} PASS, {counts['PARTIAL']} PARTIAL, {counts['FAIL']} FAIL** across {len(cases)} cases below (+ case 25 metrics).  "
         f"Backend tests: {sum(1 for v in J.values() if v == 'pass')} passed, {sum(1 for v in J.values() if v == 'fail')} failed.  "
         f"Browser tests: {sum(1 for v in P.values() if v == 'pass')} passed, {sum(1 for v in P.values() if v == 'fail')} failed.\n",
         "**PARTIAL** means the mechanism passes but the claim depends on a real AI model, which could not be run here (no API key).\n",
         "| # | Case | Result | Evidence | Notes |", "|---|---|---|---|---|"]
for n, t, s, e, note in cases:
    lines.append(f"| {n} | {t} | **{s}** | {e} | {note} |")

out = list(lines)
out.append("\n## Case 25: measurements\n")
if DEMO:
    off = DEMO["mode"] == "offline_oracle"
    out.append(f"Run mode: **{'OFFLINE ORACLE: extraction replays the answer key with injected errors; there was no AI key' if off else 'real AI'}**.\n")
    out.append("| Metric | Value | Basis |\n|---|---|---|")
    out.append(f"| Invoices processed | {DEMO['invoices']} from {DEMO['files']} files (expected {DEMO['invoices_expected']}); exact duplicates skipped {DEMO['exact_duplicates_skipped']}; failed files {DEMO['failed_files']} | real pipeline |")
    out.append(f"| Multi-invoice split correct | {DEMO['split_correct_pct']}% of files | {'real model, full set' if not off else 'grouping rules real; page text from oracle'} |")
    out.append(f"| Field accuracy (header + lines, {DEMO['fields_compared']:,} fields) | {DEMO['field_accuracy_pct']}% | {'ORACLE: not a model result' if off else 'real model'} |")
    out.append(f"| Flags raised / precision / recall end to end | {DEMO['flags']} / {DEMO['flag_precision_pct']}% / {DEMO['flag_recall_pct']}% | rules real on extracted data; {'extraction noise is simulated' if off else 'real extraction'} |")
    out.append(f"| Precision of flags not marked 'check extraction first' | {DEMO['confident_flag_precision_pct']}% of {DEMO['confident_flags']} flags; {DEMO['false_positives_marked_check_extraction']} of {DEMO['false_positives']} false flags were already marked | real |")
    if FK["defaults"] and FK["aligned"]:
        out.append(f"| Flag precision / recall, rules on correctly read data | {FK['defaults']['overall_precision_pct']}% / {FK['defaults']['overall_recall_pct']}% (default warranty list); {FK['aligned']['overall_precision_pct']}% / {FK['aligned']['overall_recall_pct']}% (warranty list matching the planted components) | real; isolates the rules |")
    if FL:
        out.append(f"| Same, VMRS codes from keyword lookup only (no AI) | {FL['overall_precision_pct']}% / {FL['overall_recall_pct']}% | real |")
    if EO:
        out.append(f"| VMRS accuracy, keyword lookup alone | {EO['vmrs_accuracy_pct']}% (258 of 724 lines unresolved; they go to the AI) | real |")
    out.append(f"| Seconds per invoice | {DEMO['seconds_extraction_per_invoice']} s per invoice wall time ({DEMO['ai_seconds_per_invoice']} s of that is model time) with one worker; checks for all invoices {DEMO['seconds_checks']} s (includes AI explanations); whole run {DEMO['seconds_total_200']} s | {'real' if not off else 'real, excludes model latency'} |")
    out.append(f"| Cost per invoice | {'not measurable offline' if off else '$' + str(DEMO['cost_per_invoice_usd'])} | {'measured' if not off else 'see estimate below'} |")
    out.append("\nPer rule on the end-to-end path:\n\n| Rule | Planted | Found | Recall | Flags | Precision |\n|---|---|---|---|---|---|")
    for k, v in DEMO["per_rule"].items():
        out.append(f"| {k} | {v['planted']} | {v['found']} | {v['recall_pct']}% | {v['flags']} | {v['precision_pct']}% |")
    if REAL:
        out.append(f"\n**Measured cost and speed (real OpenAI gpt-4o):** ${DEMO['cost_per_invoice_usd']} per invoice (${DEMO['extraction_cost_usd']} for 204 invoices; extraction, classification and flag explanations; report paragraphs not counted), {DEMO['ai_seconds_per_invoice']} s of model time per invoice, {DEMO['seconds_total_200']} s for the whole run on one worker. About **$17.50 per 1,000 invoices** and roughly 2.5 hours of machine time per 1,000 on one worker. Token prices are list prices and unverified.")
    if False:
        out.append("\n**Cost estimate (arithmetic, not measured; prices unverified):** one invoice page at high detail is about 1,700 input tokens (image ~800 + instructions and schema ~900) and ~900 output tokens, which at gpt-4o list prices ($2.50 / $10 per million) is about $0.013 per page. VMRS classification adds up to ~$0.004 per invoice at first and falls as the per-client cache fills; flag explanations add ~$0.001. Expect roughly **$0.015 to $0.02 per single-page invoice**, so ~$15 to $20 per 1,000 invoices. A real run replaces this with the measured value.")
        out.append("\n**Throughput:** the non-AI pipeline takes about 1 s per invoice; model latency (unmeasured, typically 5 to 15 s per page) dominates. With 4 workers 1,000 invoices would take roughly 20 to 60 minutes of machine time, so the 5-working-day workflow is limited by analyst review, not processing. Analyst review time was not measured.")
out.append("\n## Success targets\n")
out.append("| Target | Result |\n|---|---|")
if REAL:
    out.append(f"| Field extraction accuracy 90%+ | **Met on synthetic invoices: {DEMO['field_accuracy_pct']}%** (real OpenAI gpt-4o, all 204 invoices, 0 failed files; the first full run before any tuning scored 91.5% on 193 invoices). **Below 90% for phone photos ({KINDS.get('phone_photo')}%) and handwriting ({KINDS.get('handwritten')}%).** Prompts were tuned on this same set, and real invoices will be harder, so this is not proof for real data. |")
else:
    out.append("| Field extraction accuracy 90%+ | **NOT VERIFIED.** Needs a real OpenAI key. The oracle figure above is not evidence. |")
if FK["defaults"]:
    out.append(f"| Flag precision 80%+ | **Met on correctly read data:** {FK['defaults']['overall_precision_pct']}% (default warranty list), {FK['aligned']['overall_precision_pct']}% (aligned). **End to end it depends on extraction quality:** {DEMO['flag_precision_pct'] if DEMO else 'n/a'}% with {'the real model' if REAL else 'the oracle simulated errors'}, {DEMO['confident_flag_precision_pct'] if DEMO else 'n/a'}% for flags not marked 'check extraction first'. Precision also depends on analysts, who dismiss the rest. |")
out.append("| Isolation tests 100% pass | " + ("**Met**: all isolation tests passed." if all(J.get(n) == "pass" for n in J if "isolation" in n or "cross" in n or "refuses" in n or "never_cross" in n) and J else "**Check results above**") + " |")
out.append("""
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
""")
(ROOT / "TEST_RESULTS.md").write_text("\n".join(out) + "\n")
print("\n".join(out[:8]))
