import json

import pytest
from fastapi.testclient import TestClient

from laxthya_ink.capture.server import create_app, resolve_dir
from tests.test_probe import _pen_session


@pytest.fixture
def client_and_dir(config, tmp_path):
    out = tmp_path / "probe"
    return TestClient(create_app(config, probe_dir=out)), out


def test_index_serves_the_probe_page(client_and_dir):
    client, _ = client_and_dir
    r = client.get("/")
    assert r.status_code == 200
    assert "Signal Probe" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_health(client_and_dir):
    assert client_and_dir[0].get("/api/health").json() == {"ok": True}


def test_upload_saves_json_and_report_under_the_probe_dir(client_and_dir):
    client, out = client_and_dir
    r = client.post("/api/probe", content=json.dumps(_pen_session()))
    assert r.status_code == 200
    body = r.json()
    assert "pressure: varies" in body["report"]
    saved = body["saved_as"]
    assert (out / f"{saved}.json").exists() and (out / f"{saved}.txt").exists()
    assert json.loads((out / f"{saved}.json").read_text(encoding="utf-8"))["events"]


def test_invalid_json_is_400(client_and_dir):
    r = client_and_dir[0].post("/api/probe", content="{nope")
    assert r.status_code == 400


def test_bad_events_are_422_and_nothing_is_saved(client_and_dir):
    client, out = client_and_dir
    r = client.post("/api/probe", content=json.dumps({"events": []}))
    assert r.status_code == 422
    assert not out.exists() or not list(out.iterdir())


def test_oversized_upload_is_413(config, tmp_path):
    config["capture"]["max_upload_mb"] = 0.001          # about 1 KB
    client = TestClient(create_app(config, probe_dir=tmp_path))
    r = client.post("/api/probe", content=json.dumps(_pen_session()))
    assert r.status_code == 413


def test_resolve_dir_relative_and_absolute(tmp_path):
    assert resolve_dir(str(tmp_path)) == tmp_path
    assert resolve_dir("data/probe").parts[-2:] == ("data", "probe")
    assert resolve_dir("data/probe").is_absolute()
