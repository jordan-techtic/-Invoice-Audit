import io
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import select

from app.db import client_session
from app.main import app
from app.models import Flag, Report
from app.services.extraction.fake import FakeProvider

from .test_review import setup_flags


def decide(c, cid, flags, keep):
    """Accept the first `keep` flags, dismiss the rest."""
    for i, f in enumerate(flags):
        if i < keep:
            c.post(f"/clients/{cid}/flags/{f['id']}/accept", json={})
        else:
            c.post(f"/clients/{cid}/flags/{f['id']}/dismiss", json={"reason": "not_real_issue"})


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def make(c, cid, keep=None, **body):
    flags = setup_flags(c, cid)
    decide(c, cid, flags, len(flags) if keep is None else keep)
    r = c.post(f"/clients/{cid}/reports", json=body)
    return flags, r


def test_report_blocked_while_any_flag_is_open(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    decide(admin_client, cid, flags[:-1], len(flags) - 1)       # leave exactly one open
    r = admin_client.post(f"/clients/{cid}/reports", json={})
    assert r.status_code == 409 and "1 flag still needs a decision" in r.json()["detail"]
    assert admin_client.get(f"/clients/{cid}/reports").json() == []


def test_report_blocked_before_checks_were_run(admin_client, world):
    r = admin_client.post(f"/clients/{world['a']}/reports", json={})
    assert r.status_code == 409 and "Run checks" in r.json()["detail"]


def test_total_equals_sum_of_accepted_and_excludes_dismissed(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid, keep=2)
    assert r.status_code == 201
    snap = admin_client.get(f"/clients/{cid}/reports/{r.json()['id']}").json()
    accepted = flags[:2]
    assert round(snap["summary"]["recoverable"], 2) == round(sum(f["impact"] for f in accepted), 2)
    assert snap["summary"]["flag_count"] == 2 and len(snap["appendix"]) == 2
    assert sum(x["amount"] for x in snap["breakdown"]["by_type"]) == snap["summary"]["recoverable"]
    dismissed_amounts = {f["impact"] for f in flags[2:]} - {f["impact"] for f in accepted}
    assert not dismissed_amounts & {a["amount"] for a in snap["appendix"]}
    assert snap["summary"]["total_spend"] > 0 and snap["cover"]["invoices_reviewed"] == 8
    assert 0 < len(snap["summary"]["top_findings"]) <= 5 and snap["note"].startswith("Estimates are based on the invoices provided")


def test_edited_amount_is_what_the_report_uses(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    admin_client.post(f"/clients/{cid}/flags/{flags[0]['id']}/edit", json={"amount": 50.0})
    decide(admin_client, cid, flags[1:], 0)
    for f in flags[1:]:
        pass
    snap = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={}).json()['id']}").json()
    assert snap["summary"]["recoverable"] == 50.0


def test_pdf_downloads_opens_and_matches_dashboard(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    rid = r.json()["id"]
    snap = admin_client.get(f"/clients/{cid}/reports/{rid}").json()
    pdf = admin_client.get(f"/clients/{cid}/reports/{rid}/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:5] == b"%PDF-"
    assert "attachment" in pdf.headers["content-disposition"]
    text = pdf_text(pdf.content)
    n = len(PdfReader(io.BytesIO(pdf.content)).pages)
    assert n >= 3
    money = lambda v: f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"
    assert money(snap["summary"]["recoverable"]) in text
    assert snap["cover"]["client_name"] in text and "Page 2 of" in text
    for t in snap["narratives"]:
        assert t["label"] in text
    for a in snap["appendix"]:
        assert a["invoice_number"] in text
    assert "reviewed by an analyst" in text.replace("\n", " ")           # a report with accepted findings does say each was reviewed


def test_empty_report_renders_properly_without_zero_chart(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid, keep=0)    # every flag dismissed
    assert r.status_code == 201
    rid = r.json()["id"]
    snap = admin_client.get(f"/clients/{cid}/reports/{rid}").json()
    assert snap["empty"] is True and snap["summary"]["recoverable"] == 0
    assert snap["summary"]["headline"].startswith("No likely overbilling was found in the 8 invoices")
    assert snap["breakdown"]["by_type"] == [] and snap["appendix"] == [] and snap["summary"]["top_findings"] == []
    text = pdf_text(admin_client.get(f"/clients/{cid}/reports/{rid}/pdf").content)
    assert "No likely overbilling was found" in text and "$0" not in text and "Where the money is" not in text
    assert "reviewed by an analyst" not in text.replace("\n", " ")        # nothing was reviewed into a finding, so the report does not say so (artifact RP3)
    assert "Estimates are based on the invoices provided" in text.replace("\n", " ")


def public(token_url, **kw):
    token = token_url.rsplit("/r/", 1)[1]
    return token, TestClient(app).get(f"/public/reports/{token}", **kw)   # a fresh client: no login cookie


def test_public_link_works_without_login_and_expiry_and_revocation(admin_client, analyst_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    item = r.json()
    token, resp = public(item["share_url"])
    assert resp.status_code == 200 and resp.json()["cover"]["client_name"].startswith("A ")
    assert len(token) >= 40                                        # unguessable
    assert TestClient(app).get(f"/public/reports/{token}/pdf").headers["content-type"] == "application/pdf"
    assert TestClient(app).get("/public/reports/not-a-real-token").status_code == 404
    # revoke: admin only
    assert analyst_client.post(f"/clients/{cid}/reports/{item['id']}/revoke").status_code == 403
    assert admin_client.post(f"/clients/{cid}/reports/{item['id']}/revoke").json()["revoked"] is True
    gone = TestClient(app).get(f"/public/reports/{token}")
    assert gone.status_code == 410 and "turned off" in gone.json()["detail"]
    assert TestClient(app).get(f"/public/reports/{token}/pdf").status_code == 410
    assert admin_client.get(f"/clients/{cid}/reports").json()[0]["share_url"] is None
    # expiry on a fresh report
    r2 = admin_client.post(f"/clients/{cid}/reports", json={"expires_days": 7}).json()
    token2 = r2["share_url"].rsplit("/r/", 1)[1]
    with client_session(cid) as db:
        row = db.get(Report, r2["id"])
        row.share_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    expired = TestClient(app).get(f"/public/reports/{token2}")
    assert expired.status_code == 410 and "expired" in expired.json()["detail"]
    assert admin_client.get(f"/clients/{cid}/reports").json()[0]["expired"] is True


def test_report_is_a_snapshot_later_edits_do_not_change_it(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    rid = r.json()["id"]
    frozen = lambda r: {k: v for k, v in r.items() if k != "out_of_date"}   # out_of_date is computed from today's decisions; the content is what is frozen
    before = frozen(admin_client.get(f"/clients/{cid}/reports/{rid}").json())
    pdf_before = pdf_text(admin_client.get(f"/clients/{cid}/reports/{rid}/pdf").content)
    admin_client.post(f"/clients/{cid}/flags/{flags[0]['id']}/edit", json={"amount": 1.0, "reason": "Possible tiny issue."})
    admin_client.post(f"/clients/{cid}/flags/{flags[1]['id']}/dismiss", json={"reason": "other"})
    assert frozen(admin_client.get(f"/clients/{cid}/reports/{rid}").json()) == before
    assert pdf_text(admin_client.get(f"/clients/{cid}/reports/{rid}/pdf").content) == pdf_before
    v2 = admin_client.post(f"/clients/{cid}/reports", json={}).json()          # a new report reflects the new decisions
    assert v2["version"] == 2 and v2["recoverable"] != before["summary"]["recoverable"]


def test_narrative_guardrails_and_ai_failure_fallback(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    decide(admin_client, cid, flags, len(flags))
    types = sorted({f["type"] for f in flags})
    FakeProvider.narrative_scripted = [json.dumps({"items": [{"type": t, "paragraph": "This shop committed fraud."} for t in types]})]
    snap = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={}).json()['id']}").json()
    assert snap["narratives"] and all("fraud" not in n["paragraph"].lower() and re.search(r"likely|possible", n["paragraph"], re.I) for n in snap["narratives"])
    FakeProvider.narrative_scripted = []
    FakeProvider.narrative_fail = True
    r = admin_client.post(f"/clients/{cid}/reports", json={})
    assert r.status_code == 201                                                  # AI failure never blocks the report
    FakeProvider.narrative_fail = False
    FakeProvider.narrative_scripted = [json.dumps({"items": [{"type": types[0], "paragraph": "This is a likely issue, so ask the shop to review it."}]})]
    snap = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={}).json()['id']}").json()
    assert next(n for n in snap["narratives"] if n["type"] == types[0])["paragraph"].startswith("This is a likely issue")


def test_offer_text_is_editable_and_defaults_from_settings(admin_client, world):
    cid = world["a"]
    d = admin_client.get(f"/clients/{cid}/report-settings").json()
    assert "Techtic" in d["default_offer_text"]
    flags = setup_flags(admin_client, cid)
    decide(admin_client, cid, flags, len(flags))
    snap = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={'offer_text': 'Call Sam on 555-0100.'}).json()['id']}").json()
    assert snap["next_steps"]["text"] == "Call Sam on 555-0100."


def test_audit_period_ignores_misread_years():
    from datetime import date

    from app.services.report_data import audit_period

    today = date.today()
    good = [date(today.year - 2, 3, 5), date(today.year - 1, 9, 20)]
    assert audit_period(good + [date(2014, 9, 1), date(today.year + 3, 1, 1), None]) == audit_period(good)   # the 2014 and future dates are dropped
    assert audit_period([date(2001, 1, 1)]) is None and audit_period([]) is None


# ---- artifact RP1-RP4: what the client report says must match what was decided, and be safe to read
def test_report_is_marked_out_of_date_when_a_flag_decision_changes_afterwards(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    rid = r.json()["id"]
    assert admin_client.get(f"/clients/{cid}/reports").json()[0]["out_of_date"] is False
    admin_client.post(f"/clients/{cid}/flags/{flags[0]['id']}/dismiss", json={"reason": "other"})
    assert admin_client.get(f"/clients/{cid}/reports").json()[0]["out_of_date"] is True
    assert admin_client.get(f"/clients/{cid}/reports/{rid}").json()["out_of_date"] is True


def test_a_new_version_turns_off_the_older_public_link(admin_client, world):
    cid = world["a"]
    flags, r1 = make(admin_client, cid)
    token1 = r1.json()["share_url"].rsplit("/r/", 1)[1]
    assert TestClient(app).get(f"/public/reports/{token1}").status_code == 200
    r2 = admin_client.post(f"/clients/{cid}/reports", json={})
    token2 = r2.json()["share_url"].rsplit("/r/", 1)[1]
    assert TestClient(app).get(f"/public/reports/{token1}").status_code == 410
    assert TestClient(app).get(f"/public/reports/{token2}").status_code == 200


def test_the_cover_counts_only_invoices_that_are_not_waiting_for_review(admin_client, world):
    from app.models import Invoice, ReviewStatus

    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    with client_session(cid) as db:
        invs = list(db.scalars(select(Invoice)))
        for i, inv in enumerate(invs):
            inv.review_status = ReviewStatus.reviewed if i % 2 == 0 else ReviewStatus.needs_review
        db.commit()
        reviewed = sum(1 for i in invs if i.review_status == ReviewStatus.reviewed)
    decide(admin_client, cid, flags, len(flags))
    snap = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={}).json()['id']}").json()
    assert snap["cover"]["invoices_reviewed"] == reviewed < len(invs)


def test_one_month_is_named_once():
    from datetime import date
    from app.services.report_data import audit_period

    assert audit_period([date.today().replace(day=2), date.today().replace(day=20)]) == f"{date.today():%b %Y}"


def test_the_analyst_review_sentence_is_only_printed_when_there_were_findings(admin_client, world):
    cid = world["a"]
    flags = setup_flags(admin_client, cid)
    decide(admin_client, cid, flags, 0)                                       # everything dismissed: an empty report
    empty = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={}).json()['id']}").json()
    assert empty["empty"] and "reviewed by an analyst" not in empty["note"]
    for f in flags:
        admin_client.post(f"/clients/{cid}/flags/{f['id']}/reopen")
    decide(admin_client, cid, flags, len(flags))
    full = admin_client.get(f"/clients/{cid}/reports/{admin_client.post(f'/clients/{cid}/reports', json={}).json()['id']}").json()
    assert "reviewed by an analyst" in full["note"]


def test_paragraphs_count_invoices_not_flags_and_agree_in_number():
    from app.services.report_data import _paragraphs

    rows = {"math_error": {"count": 3, "invoices": 2, "amount": 120.0, "examples": []}, "duplicate": {"count": 1, "invoices": 1, "amount": 80.0, "examples": []}}
    out = _paragraphs(rows, None)
    assert out["math_error"].startswith("We found 2 invoices ")
    assert out["duplicate"].startswith("We found 1 invoice that looks like ")


def test_a_narrative_with_a_wrong_dollar_figure_falls_back_to_the_template():
    from types import SimpleNamespace as NS
    from app.services.report_data import _paragraphs

    class Provider:
        def narrate(self, payload):
            return NS(items=[NS(type="math_error", paragraph="We found 2 invoices with a possible difference of about $9,999 that is likely worth asking about.")])

    out = _paragraphs({"math_error": {"count": 2, "invoices": 2, "amount": 120.0, "examples": []}}, Provider())
    assert "$9,999" not in out["math_error"] and "$120" in out["math_error"]


def test_the_report_page_never_prints_None_and_keeps_Other_last_and_in_scale(admin_client, world):
    from app.services.report_pdf import render_html

    cid = world["a"]
    flags, r = make(admin_client, cid)
    snap = admin_client.get(f"/clients/{cid}/reports/{r.json()['id']}").json()
    snap["appendix"][0].update(date=None, invoice_number=None, shop=None, unit=None)
    snap["breakdown"]["by_shop"] = [{"label": "Acme", "count": 1, "amount": 100.0}, {"label": "Other", "count": 4, "amount": 400.0}]
    html = render_html(snap)
    assert "None" not in re.sub(r"<[^>]+>", " ", html)
    widths = [float(w) for w in re.findall(r'class="bar[^"]*" style="width: ([\d.]+)%', html.split("By shop")[1].split("By vehicle")[0])]
    assert widths == [100.0, 100.0]        # "Other" is the sum of the tail: it must not shrink the real top shop


# ---- artifact RP4 root cause: three sections each force a new page, so a two-finding report is five mostly empty pages
def test_a_small_report_is_not_spread_over_mostly_empty_pages(admin_client, world):
    cid = world["a"]
    flags, r = make(admin_client, cid)
    pdf = admin_client.get(f"/clients/{cid}/reports/{r.json()['id']}/pdf").content
    pages = [len(p.extract_text().strip()) for p in PdfReader(io.BytesIO(pdf)).pages]
    assert len(flags) == 2 and len(pages) <= 4, pages
