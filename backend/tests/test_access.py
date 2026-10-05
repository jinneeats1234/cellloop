"""Success metric: zero cross-partner data exposure."""

from tests.conftest import LEAD, NORTHGATE, RIDGELINE, SCIENTIST


def _ids(client, headers, path="/api/experiments"):
    r = client.get(path, headers=headers)
    assert r.status_code == 200
    body = r.json()
    return body["items"] if isinstance(body, dict) else body


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/experiments").status_code == 401
    assert client.get("/api/experiments", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_partner_lists_only_own_org(client, login):
    for email, org in [(NORTHGATE, "northgate-univ"), (RIDGELINE, "ridgeline-lab")]:
        items = _ids(client, login(email))
        assert items, "partner should see its own experiments"
        assert {e["organization"] for e in items} == {org}
        docs = _ids(client, login(email), "/api/documents")
        assert {d["organization"] for d in docs} <= {org}


def test_partner_cannot_fetch_other_org_records_by_id(client, login):
    ridgeline_exp = _ids(client, login(RIDGELINE))[0]
    ridgeline_docs = _ids(client, login(RIDGELINE), "/api/documents")
    ng = login(NORTHGATE)
    assert client.get(f"/api/experiments/{ridgeline_exp['id']}", headers=ng).status_code == 404
    for d in ridgeline_docs:
        assert client.get(f"/api/documents/{d['id']}", headers=ng).status_code == 404
        assert client.get(f"/api/documents/{d['id']}/file", headers=ng).status_code == 404


def test_partner_cannot_see_internal_reports(client, login):
    internal_docs = [d for d in _ids(client, login(SCIENTIST), "/api/documents") if d["kind"] == "internal_report"]
    assert internal_docs
    assert client.get(f"/api/documents/{internal_docs[0]['id']}", headers=login(NORTHGATE)).status_code == 404


def test_internal_endpoints_forbidden_for_partners(client, login):
    ng = login(NORTHGATE)
    assert client.get("/api/dashboard", headers=ng).status_code == 403
    assert client.get("/api/audit", headers=ng).status_code == 403
    assert client.post("/api/qa", json={"question": "best ASR so far?"}, headers=ng).status_code == 403
    assert client.post("/api/recommendations", json={}, headers=ng).status_code == 403


def test_partner_cannot_approve_and_leadership_is_read_only(client, login):
    pending = _ids(client, login(SCIENTIST), "/api/experiments?status=pending_review")
    ng_pending = next(e for e in pending if e["organization"] == "northgate-univ")
    assert client.post(f"/api/experiments/{ng_pending['id']}/approve", json={}, headers=login(NORTHGATE)).status_code == 403
    assert client.post(f"/api/experiments/{ng_pending['id']}/approve", json={}, headers=login(LEAD)).status_code == 403


def test_partner_upload_is_forced_into_own_org(client, login):
    r = client.post(
        "/api/documents",
        headers=login(NORTHGATE),
        files={"file": ("spoof.txt", b"Cell ID: X-1\nAnode: Ni-YSZ\nCathode: LSCF\nTotal ASR: 0.5", "text/plain")},
        data={"organization": "ridgeline-lab", "kind": "internal_report"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["organization"] == "northgate-univ"
    assert r.json()["kind"] == "partner_report"


def test_upload_rejects_bad_types_and_duplicates(client, login):
    ng = login(NORTHGATE)
    assert client.post("/api/documents", headers=ng, files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    payload = {"file": ("dup.txt", b"Cell ID: D-1\nAnode: Ni-YSZ\nCathode: LSCF", "text/plain")}
    assert client.post("/api/documents", headers=ng, files=payload).status_code == 201
    assert client.post("/api/documents", headers=ng, files=payload).status_code == 409


def test_api_rejects_out_of_range_input(client, login):
    sci = login(SCIENTIST)
    assert client.post("/api/recommendations", headers=sci, json={"n": 0}).status_code == 422
    assert client.post("/api/recommendations", headers=sci, json={"target_temp_c": 5000}).status_code == 422
    assert client.post("/api/recommendations", headers=sci, json={"target_asr": -1}).status_code == 422
    assert client.post("/api/qa", headers=sci, json={"question": "hi"}).status_code == 422
    assert client.get("/api/experiments?q=" + "x" * 201, headers=sci).status_code == 422
    r = client.post("/api/documents", headers=login(NORTHGATE), data={"title": "t" * 501},
                    files={"file": ("long.txt", b"Cell ID: L-1\nAnode: Ni-YSZ", "text/plain")})
    assert r.status_code == 422
