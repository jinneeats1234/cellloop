"""Security and robustness: injection, traversal, spoofing, weird input. Nothing here may 500."""

import time

import jwt
import pytest

from app.core.config import get_settings
from tests.conftest import LEAD, NORTHGATE, RIDGELINE, SCIENTIST

WEIRD_STRINGS = [
    "",
    "   ",
    "' OR 1=1 --",
    "\"; DROP TABLE experiments; --",
    "%",
    "_",
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "../../../../etc/passwd",
    "null",
    "NaN",
    "Infinity",
    "1e309",
    "-1e309",
    "😀🔬 Ni–YSZ µm Ω·cm²",
    "a" * 5000,
    "line1\nline2\r\n\t",
    "‮RTL override",
]


def _no_500(r):
    assert r.status_code < 500, f"{r.request.method} {r.request.url} -> {r.status_code}: {r.text[:300]}"


# --- SQL injection & LIKE wildcards ---------------------------------------------------

@pytest.mark.parametrize("q", WEIRD_STRINGS)
def test_registry_search_handles_any_input(client, login, q):
    r = client.get("/api/experiments", params={"q": q[:200]}, headers=login(SCIENTIST))
    _no_500(r)


def test_sql_injection_does_not_widen_results(client, login):
    ng = login(NORTHGATE)
    for q in ["' OR 1=1 --", "x' OR organization='ridgeline-lab", "%' OR '1'='1"]:
        r = client.get("/api/experiments", params={"q": q, "status": ""}, headers=ng)
        assert r.status_code == 200
        assert all(e["organization"] == "northgate-univ" for e in r.json()["items"])
        assert r.json()["total"] == 0


def test_like_wildcards_are_literal(client, login):
    # '%' and '_' are search characters, not "match everything".
    sci = login(SCIENTIST)
    everything = client.get("/api/experiments", params={"status": ""}, headers=sci).json()["total"]
    percent = client.get("/api/experiments", params={"q": "%", "status": "", "limit": 1000}, headers=sci).json()
    # Only records that literally contain '%' (e.g. "Ni-YSZ 60:40 wt%") match; unescaped, '%' would match all.
    assert 0 < percent["total"] < everything
    assert all("%" in " ".join(str(v) for v in e["fields"].values()) for e in percent["items"])
    assert client.get("/api/experiments", params={"q": "_", "status": ""}, headers=sci).json()["total"] == 0


@pytest.mark.parametrize("bad", ["' OR 1=1 --", "%", "<b>x</b>", "a" * 100])
def test_recommender_filters_handle_any_input(client, login, bad):
    r = client.post("/api/recommendations", headers=login(SCIENTIST), json={"n": 2, "filters": {"cathode_composition": bad}})
    _no_500(r)


# --- Path traversal & tenant spoofing -------------------------------------------------

@pytest.mark.parametrize("org", ["../../etc", "../internal", "internal", "nonexistent-lab", "Ridgeline Lab", "a" * 300])
def test_internal_upload_rejects_unknown_or_malicious_org(client, login, org):
    r = client.post("/api/documents", headers=login(SCIENTIST), data={"organization": org},
                    files={"file": ("t.txt", f"Cell ID: T-{org[:20]}".encode(), "text/plain")})
    _no_500(r)
    assert r.status_code in (400, 422)


def test_manual_experiment_rejects_unknown_org(client, login):
    r = client.post("/api/experiments", headers=login(SCIENTIST), json={"organization": "../../x", "values": {}})
    _no_500(r)
    assert r.status_code in (400, 422)


@pytest.mark.parametrize("name", ["../../evil.txt", "..\\..\\evil.txt", "evil.txt\x00.pdf", "CON.txt", ".txt", "🔥.txt"])
def test_weird_filenames_are_sanitised(client, login, name):
    r = client.post("/api/documents", headers=login(NORTHGATE),
                    files={"file": (name, f"Cell ID: {time.time()}".encode(), "text/plain")})
    _no_500(r)
    if r.status_code == 201:
        fn = r.json()["filename"]
        assert "/" not in fn and "\\" not in fn and "\x00" not in fn and ".." not in fn


# --- Content-type spoofing (stored XSS through downloads) -------------------------------

def test_download_never_serves_client_supplied_html(client, login):
    html = b"<html><script>alert(document.cookie)</script></html>"
    r = client.post("/api/documents", headers=login(NORTHGATE), files={"file": ("x.txt", html, "text/html")})
    assert r.status_code == 201
    d = client.get(f"/api/documents/{r.json()['id']}/file", headers=login(SCIENTIST))
    assert d.status_code == 200
    ctype = d.headers["content-type"]
    assert "html" not in ctype and ctype.startswith("text/plain")
    assert d.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in d.headers["content-disposition"]


def test_fake_pdf_is_not_served_as_pdf(client, login):
    r = client.post("/api/documents", headers=login(NORTHGATE),
                    files={"file": ("fake.pdf", b"<html><script>alert(1)</script>", "application/pdf")})
    assert r.status_code in (201, 415, 422)
    if r.status_code == 201:
        d = client.get(f"/api/documents/{r.json()['id']}/file", headers=login(SCIENTIST))
        assert "pdf" not in d.headers["content-type"]


# --- Numbers: NaN / Infinity / overflow ------------------------------------------------

def _pending(client, login):
    items = client.get("/api/experiments", params={"status": "pending_review"}, headers=login(SCIENTIST)).json()["items"]
    return items[0]["id"]


@pytest.mark.parametrize("value", ["NaN", "nan", "inf", "-Infinity", "1e309", 1e300, "1e30", 10**30])
def test_non_finite_and_absurd_numbers_rejected(client, login, value):
    eid = _pending(client, login)
    for field in ("ocv_v", "thermal_cycles"):
        r = client.patch(f"/api/experiments/{eid}", headers=login(SCIENTIST), json={"values": {field: value}})
        _no_500(r)
        assert r.status_code == 422, (field, value, r.status_code)


def test_raw_json_nan_is_rejected(client, login):
    eid = _pending(client, login)
    r = client.patch(f"/api/experiments/{eid}", headers={**login(SCIENTIST), "Content-Type": "application/json"},
                     content=b'{"values": {"ocv_v": NaN}}')
    _no_500(r)
    assert r.status_code == 422


@pytest.mark.parametrize("value", WEIRD_STRINGS)
def test_text_fields_accept_or_reject_cleanly(client, login, value):
    eid = _pending(client, login)
    r = client.patch(f"/api/experiments/{eid}", headers=login(SCIENTIST), json={"values": {"notes": value}})
    _no_500(r)


def test_nul_bytes_rejected(client, login):
    eid = _pending(client, login)
    r = client.patch(f"/api/experiments/{eid}", headers=login(SCIENTIST), json={"values": {"notes": "a\x00b"}})
    assert r.status_code == 422
    r = client.get("/api/experiments", params={"q": "a\x00b"}, headers=login(SCIENTIST))
    assert r.status_code == 422


# --- Whitespace-only input -------------------------------------------------------------

def test_whitespace_only_text_is_rejected(client, login):
    sci = login(SCIENTIST)
    assert client.post("/api/qa", headers=sci, json={"question": "        "}).status_code == 422
    eid = _pending(client, login)
    assert client.post(f"/api/experiments/{eid}/reject", headers=sci, json={"reason": "     "}).status_code == 422


# --- Query parameters ------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/documents?limit=-5", "/api/documents?limit=abc", "/api/audit?limit=-1",
                                  "/api/audit?offset=-1", "/api/experiments?limit=0", "/api/experiments?min_temp=abc",
                                  "/api/experiments/similar?params=sintering_temp_c:abc&params=x:1&params=y:2"])
def test_bad_query_parameters_are_400s_not_500s(client, login, path):
    r = client.get(path, headers=login(SCIENTIST))
    _no_500(r)
    assert r.status_code == 422


# --- Authentication --------------------------------------------------------------------

def test_tampered_tokens_rejected(client, login):
    s = get_settings()
    good = login(SCIENTIST)["Authorization"].split()[1]
    claims = jwt.decode(good, s.dev_jwt_secret, algorithms=["HS256"], issuer="cellloop-dev")
    forged_admin = jwt.encode({**claims, "sub": "dev|admin@cellloop.dev"}, "wrong-secret-wrong-secret-wrong-secret!", algorithm="HS256")
    none_alg = jwt.encode({**claims}, key="", algorithm="none")
    expired = jwt.encode({**claims, "exp": int(time.time()) - 10}, s.dev_jwt_secret, algorithm="HS256")
    for tok in [forged_admin, none_alg, expired, good + "x", "a.b.c", ""]:
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, tok
        assert s.dev_jwt_secret not in r.text


def test_partner_cannot_read_other_orgs_via_any_endpoint(client, login):
    rl = login(RIDGELINE)
    ng_docs = client.get("/api/documents", headers=login(NORTHGATE)).json()
    ng_exps = client.get("/api/experiments", params={"status": ""}, headers=login(NORTHGATE)).json()["items"]
    for d in ng_docs[:3]:
        for suffix in ("", "/file"):
            assert client.get(f"/api/documents/{d['id']}{suffix}", headers=rl).status_code == 404
        assert client.post(f"/api/documents/{d['id']}/reextract", headers=rl).status_code == 403
    for e in ng_exps[:3]:
        assert client.get(f"/api/experiments/{e['id']}", headers=rl).status_code == 404
        assert client.patch(f"/api/experiments/{e['id']}", headers=rl, json={"values": {}}).status_code == 403
    # organization filter is ignored for partners
    r = client.get("/api/experiments", params={"organization": "northgate-univ", "status": ""}, headers=rl)
    assert {e["organization"] for e in r.json()["items"]} <= {"ridgeline-lab"}


def test_partners_do_not_see_internal_reviewer_emails(client, login):
    items = client.get("/api/experiments", params={"status": "approved"}, headers=login(NORTHGATE)).json()["items"]
    assert items and all(e["reviewed_by"] in (None, "CellLoop team") for e in items)


def test_leadership_is_read_only(client, login):
    lead = login(LEAD)
    eid = _pending(client, login)
    assert client.patch(f"/api/experiments/{eid}", headers=lead, json={"values": {}}).status_code == 403
    assert client.post(f"/api/experiments/{eid}/reject", headers=lead, json={"reason": "nope nope"}).status_code == 403
    r = client.post("/api/documents", headers=lead, files={"file": ("l.txt", b"Cell ID: L", "text/plain")})
    assert r.status_code == 403


# --- Response hardening ----------------------------------------------------------------

def test_security_headers_on_api_responses(client, login):
    r = client.get("/api/experiments", headers=login(SCIENTIST))
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["referrer-policy"] == "no-referrer"


def test_oversized_request_rejected_early(client, login):
    big = b"x" * (get_settings().max_upload_mb * 1024 * 1024 + 2048)
    r = client.post("/api/documents", headers=login(NORTHGATE), files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413


def test_rate_limit_on_expensive_endpoints(client, login, monkeypatch):
    from app.core import ratelimit

    monkeypatch.setattr(ratelimit, "ENABLED", True)
    ratelimit.reset()
    sci = login(SCIENTIST)
    codes = [client.post("/api/qa", headers=sci, json={"question": "What is the ASR target?"}).status_code for _ in range(25)]
    assert 429 in codes
    ratelimit.reset()
