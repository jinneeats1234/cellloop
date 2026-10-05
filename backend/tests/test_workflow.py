"""Upload -> AI extraction -> human review -> approved record -> audit, Q&A and recommender."""

from pathlib import Path

from app.experiment_schema import FIELD_SPECS
from app.services import llm as llm_module
from app.services.extraction import validate_extraction
from tests.conftest import NORTHGATE, SCIENTIST

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "partner_report_northgate.txt"


def test_extraction_review_approve_audit(client, login):
    text = SAMPLE.read_text().replace("NG-MS-118", "NG-MS-201").replace("2026-09-29", "2026-10-02")
    r = client.post("/api/documents", headers=login(NORTHGATE),
                    files={"file": ("ng201.txt", text.encode(), "text/plain")})
    assert r.status_code == 201
    doc_id = r.json()["id"]

    sci = login(SCIENTIST)
    doc = client.get(f"/api/documents/{doc_id}", headers=sci).json()
    assert doc["status"] == "needs_review", doc
    [exp_id] = doc["experiment_ids"]
    exp = client.get(f"/api/experiments/{exp_id}", headers=sci).json()
    assert exp["status"] == "pending_review"
    assert exp["fields"]["cell_id"] == "NG-MS-201"
    assert exp["fields"]["electrolyte_thickness_um"] == 4.5
    assert exp["extraction"]["asr_ohm_cm2"]["evidence_verified"] is True

    # Implausible value needs explicit acknowledgement.
    bad = client.post(f"/api/experiments/{exp_id}/approve", headers=sci, json={"values": {"ocv_v": 1.9}})
    assert bad.status_code == 422

    r = client.post(f"/api/experiments/{exp_id}/approve", headers=sci,
                    json={"values": {"operator": "J. Okafor (verified)"}, "comment": "Checked against PDF"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert client.post(f"/api/experiments/{exp_id}/approve", headers=sci, json={}).status_code == 409

    log = client.get(f"/api/audit?entity_id={exp_id}", headers=sci).json()
    actions = {a["action"] for a in log}
    assert {"ai_extraction", "approve"} <= actions
    approve = next(a for a in log if a["action"] == "approve")
    assert approve["details"]["ai_fields_corrected"] == ["operator"]

    qa = client.post("/api/qa", headers=sci, json={"question": "What was the total ASR of cell NG-MS-201 at 650 °C?"}).json()
    assert qa["answered"] is True
    assert qa["citations"]


def test_hallucinated_evidence_is_flagged():
    raw = {s.key: {"value": None, "confidence": "low", "evidence": None} for s in FIELD_SPECS}
    raw["asr_ohm_cm2"] = {"value": 0.21, "confidence": "high", "evidence": "Total ASR: 0.21 ohm cm2"}
    raw["cathode_composition"] = {"value": "LSCF", "confidence": "high", "evidence": "Cathode: LSCF"}
    values, meta = validate_extraction(raw, "Cathode: LSCF\nTotal ASR was not measured.")
    assert meta["cathode_composition"]["evidence_verified"] is True
    assert meta["asr_ohm_cm2"]["evidence_verified"] is False
    assert meta["asr_ohm_cm2"]["confidence"] == "low"
    assert "not found" in meta["asr_ohm_cm2"]["problem"]


def test_qa_declines_without_sources(client, login):
    r = client.post("/api/qa", headers=login(SCIENTIST), json={"question": "Who won the 1998 World Cup final?"}).json()
    assert r["answered"] is False and r["citations"] == []


def test_qa_declines_uncited_model_answer(client, login, monkeypatch):
    monkeypatch.setattr(llm_module.get_llm(), "answer", lambda q, s: "The best sintering temperature is 1240 °C.")
    r = client.post("/api/qa", headers=login(SCIENTIST),
                    json={"question": "What sintering temperature window gave the lowest ASR?"}).json()
    assert r["answered"] is False
    assert r["reason"] == "answer_had_no_citations"


def test_recommender_returns_uncertainty_and_rationale(client, login):
    r = client.post("/api/recommendations", headers=login(SCIENTIST), json={"n": 4}).json()
    assert r["mode"] == "bayesian_optimization"
    assert len(r["candidates"]) == 4
    for c in r["candidates"]:
        lo, hi = c["ci95"]
        assert lo < c["predicted_asr"] < hi
        assert 0 <= c["p_beats_target"] <= 1
        assert c["rationale"] and c["nearest_experiment"]["code"].startswith("CL-")
    # Batch should not be near-duplicates.
    p0, p1 = r["candidates"][0]["params"], r["candidates"][1]["params"]
    assert p0 != p1


def test_recommender_bootstraps_with_little_data(client, login):
    r = client.post("/api/recommendations", headers=login(SCIENTIST),
                    json={"n": 3, "filters": {"cathode_composition": "no-such-material"}}).json()
    assert r["mode"] == "exploration"
    assert all(c["predicted_asr"] is None for c in r["candidates"])


def test_dashboard_metrics(client, login):
    d = client.get("/api/dashboard", headers=login(SCIENTIST)).json()
    assert d["counts"]["approved"] >= 38
    assert d["progress"]["series"]
    assert 0 <= d["completeness"]["pct_complete"] <= 100
    assert d["turnaround"]["median_hours"] is not None
