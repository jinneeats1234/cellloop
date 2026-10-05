import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="cellloop-test-")
os.environ.update(
    CELLLOOP_ENV_FILE="",  # ignore the developer's backend/.env so tests are reproducible
    APP_ENV="test",
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    LOCAL_STORAGE_DIR=f"{_tmp}/uploads",
    AUTH_MODE="dev",
    LLM_PROVIDER="mock",
    STORAGE_BACKEND="local",
    RATE_LIMIT_ENABLED="false",  # test_security switches it on for its own test
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.scripts.seed import seed  # noqa: E402

seed(reset=True)


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def login(client):
    cache: dict[str, dict] = {}

    def _login(email: str) -> dict:
        if email not in cache:
            r = client.post("/api/auth/dev-login", json={"email": email})
            assert r.status_code == 200, r.text
            cache[email] = {"Authorization": f"Bearer {r.json()['token']}"}
        return cache[email]

    return _login


SCIENTIST = "scientist@cellloop.dev"
LEAD = "lead@cellloop.dev"
NORTHGATE = "researcher@northgate.edu"
RIDGELINE = "researcher@ridgeline-lab.org"
