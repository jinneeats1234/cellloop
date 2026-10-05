"""Error handling: consistent shape, request IDs, no leaked internals, friendly failures."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.main import app
from app.services import llm as llm_module
from app.services.storage import get_storage
from tests.conftest import NORTHGATE, SCIENTIST


@app.get("/api/_test/crash", include_in_schema=False)
def _crash() -> None:
    raise RuntimeError("secret internal detail: db password is hunter2")


def test_error_shape_and_request_id(client, login):
    r = client.get("/api/experiments/does-not-exist", headers=login(SCIENTIST))
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert body["request_id"] == r.headers["X-Request-ID"]


def test_incoming_request_id_is_propagated(client, login):
    r = client.get("/api/auth/me", headers={**login(SCIENTIST), "X-Request-ID": "trace-abc12345"})
    assert r.headers["X-Request-ID"] == "trace-abc12345"


def test_validation_errors_have_readable_message(client, login):
    r = client.post("/api/recommendations", headers=login(SCIENTIST), json={"n": 99})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert "n:" in body["message"] and "12" in body["message"]


def test_unexpected_errors_hide_internals(client):
    r = client.get("/api/_test/crash")
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "internal_error"
    assert "hunter2" not in r.text and "RuntimeError" not in r.text
    assert body["request_id"] in body["detail"]


def test_health_reports_database(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_missing_stored_file_returns_404(client, login):
    sci = login(SCIENTIST)
    r = client.post("/api/documents", headers=login(NORTHGATE),
                    files={"file": ("gone.txt", b"Cell ID: G-1\nAnode: Ni-YSZ\nCathode: LSCF", "text/plain")})
    doc = r.json()
    path = get_storage()._path(f"northgate-univ/{doc['id']}/gone.txt")  # type: ignore[attr-defined]
    path.unlink()
    r = client.get(f"/api/documents/{doc['id']}/file", headers=sci)
    assert r.status_code == 404
    assert r.json()["code"] == "file_missing"


def test_ai_outage_is_reported_as_retryable(client, login, monkeypatch):
    def boom(question, sources):
        raise UpstreamError("Couldn't reach the AI service (answering your question). Please try again.", code="ai_unreachable")

    monkeypatch.setattr(llm_module.get_llm(), "answer", boom)
    r = client.post("/api/qa", headers=login(SCIENTIST), json={"question": "What sintering temperature window gave the lowest ASR?"})
    assert r.status_code == 502
    assert r.json()["code"] == "ai_unreachable"


def test_corrupt_pdf_fails_with_friendly_message(client, login):
    r = client.post("/api/documents", headers=login(NORTHGATE),
                    files={"file": ("broken.pdf", b"%PDF-1.7 this is not really a pdf", "application/pdf")})
    assert r.status_code == 201
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=login(SCIENTIST)).json()
    assert doc["status"] == "failed"
    assert "Couldn't read this PDF" in doc["error"]
    assert "Traceback" not in doc["error"]


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"auth_mode": "cognito"}, "COGNITO_USER_POOL_ID"),
        ({"storage_backend": "s3"}, "S3_BUCKET"),
        ({"app_env": "prod"}, "AUTH_MODE=dev is not allowed"),
        ({"database_url": "mysql://x"}, "DATABASE_URL"),
        ({"dev_jwt_secret": "short"}, "at least 32"),
    ],
)
def test_invalid_configuration_is_rejected(overrides, expected):
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, **overrides)
    assert expected in str(exc.value)
