"""Serving the built React app from the API process (single-service deployments)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web import install_static_site


def _site(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>CellLoop</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("outside the build")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    assert install_static_site(app, dist)
    return TestClient(app)


def test_app_shell_and_deep_links(tmp_path):
    c = _site(tmp_path)
    for path in ["/", "/dashboard", "/experiments/123e4567-e89b-12d3-a456-426614174000"]:
        r = c.get(path)
        assert r.status_code == 200 and "CellLoop" in r.text, path
        assert r.headers["cache-control"] == "no-cache"
        assert "script-src 'self'" in r.headers["content-security-policy"]


def test_assets_are_cached_and_missing_files_404(tmp_path):
    c = _site(tmp_path)
    r = c.get("/assets/index-abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert c.get("/assets/old-999.js").status_code == 404
    assert c.get("/favicon.png").status_code == 404


def test_api_routes_win_and_unknown_api_is_json_404(tmp_path):
    c = _site(tmp_path)
    assert c.get("/api/health").json() == {"status": "ok"}
    r = c.get("/api/nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_no_path_traversal_out_of_the_build(tmp_path):
    c = _site(tmp_path)
    for path in ["/../secret.txt", "/..%2fsecret.txt", "/assets/..%2f..%2fsecret.txt"]:
        r = c.get(path)
        assert "outside the build" not in r.text, path


def test_missing_build_is_skipped(tmp_path):
    assert install_static_site(FastAPI(), tmp_path / "nothing-here") is False


def test_precompressed_assets_served_to_gzip_clients(tmp_path):
    import gzip

    c = _site(tmp_path)
    js = tmp_path / "dist" / "assets" / "index-abc123.js"
    (js.parent / (js.name + ".gz")).write_bytes(gzip.compress(js.read_bytes()))
    r = c.get("/assets/index-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.text == "console.log('app')"  # client transparently decompresses
    assert "javascript" in r.headers["content-type"] and "immutable" in r.headers["cache-control"]
    plain = c.get("/assets/index-abc123.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.text == "console.log('app')"
