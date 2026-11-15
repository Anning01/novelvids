import json
import sqlite3

import pytest
from fastapi import HTTPException

from api import release
from scripts.update import agent
from services.releases import version_key


def test_numeric_version_order():
    assert version_key("1.10.0") > version_key("1.9.9")
    with pytest.raises(ValueError):
        version_key("1.1.0; cmd")


@pytest.mark.asyncio
async def test_reject_update_for_other_version_and_manual_release(monkeypatch):
    from unittest.mock import AsyncMock
    for online, target in [(True, "9.9.9"), (False, "2.0.0")]:
        monkeypatch.setattr(release, "latest_release", AsyncMock(return_value={"version":"2.0.0", "online":online}))
        with pytest.raises(HTTPException, match="409"):
            await release.update(release.UpdateRequest(version=target))


def test_updater_recovers_interrupted_switch_with_original_database_and_images(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "STATE", state)
    calls = []
    monkeypatch.setattr(agent, "compose", lambda *args: calls.append(args))
    monkeypatch.setattr(agent, "healthy", lambda version: version == "1.1.0")
    saved = {"previous":"1.1.0", "version":"1.2.0", "images":{"backend":"old-backend","frontend":"old-frontend"}}
    agent.write(state / "switch.json", saved)
    with sqlite3.connect(state / "previous.db") as db:
        db.execute("create table saved(id integer)")
        db.execute("insert into saved values(7)")
    agent.recover("1.2.0")
    assert agent.state()["phase"] == "rolled_back"
    assert not (state / "switch.json").exists()
    assert calls[0] == ("stop", "frontend", "backend")
    assert json.loads(agent.override().read_text())["services"]["backend"]["image"] == "old-backend"
    with sqlite3.connect(tmp_path / "data/novelvids.db") as db:
        assert db.execute("select id from saved").fetchone() == (7,)


def test_update_host_builds_new_tag_and_finishes_after_health_check(tmp_path, monkeypatch):
    import hashlib
    from io import BytesIO
    root = tmp_path / "project"
    root.mkdir()
    deployment = b"services: {}"
    (root / "docker-compose.yml").write_bytes(deployment)
    (root / "data").mkdir()
    with sqlite3.connect(root / "data/novelvids.db") as db:
        db.execute("create table project(id integer)")
    state = tmp_path / "state"
    state.mkdir()
    (state / "compose.sha256").write_text(hashlib.sha256(deployment).hexdigest())
    monkeypatch.setattr(agent, "ROOT", root)
    monkeypatch.setattr(agent, "STATE", state)
    monkeypatch.setattr(agent.urllib.request, "urlopen", lambda *a, **kw: BytesIO(
        b'{"tag_name":"v1.2.0","draft":false,"prerelease":false}'))
    monkeypatch.setattr(agent, "probe", lambda _: {"data": {"version": "1.1.0", "busy": False}})
    monkeypatch.setattr(agent, "healthy", lambda version: version == "1.2.0")
    monkeypatch.setattr(agent, "current_images", lambda: {"backend":"old-b","frontend":"old-f"})
    settings = {"services":{"backend":{"environment":{"DATABASE_URL":"sqlite:///app/data/novelvids.db"},
        "volumes":[{"source":str(root/"data"), "target":"/app/data"}]}}}
    monkeypatch.setattr(agent, "compose", lambda *args: json.dumps(settings) if args[0] == "config" else "")
    calls = []
    def run(*args):
        calls.append(args)
        if args[:2] == ("git", "clone"):
            path = agent.Path(args[-1])
            (path / "release.json").write_text('{"version":"1.2.0","update_format":1}')
            (path / "docker-compose.yml").write_bytes(deployment)
    monkeypatch.setattr(agent, "run", run)
    agent.LOCK.acquire()
    agent.upgrade("1.2.0")
    assert agent.state() == {"phase":"completed","version":"1.2.0"}
    assert len([args for args in calls if args[:2] == ("docker","build")]) == 2
    assert (state / "previous-novelvids.db").is_file()
    assert not (state / "switch.json").exists()


@pytest.mark.asyncio
async def test_version_manifest_checks_release_tag_and_feature_minimum(monkeypatch):
    import httpx
    from services.releases import status
    latest = {"tag_name":"v2.1.0","draft":False,"prerelease":False}
    manifest = {"version":"2.1.0","update_format":1,"summary":"升级", "summary_en":"Upgrade",
                "minimum":{"images":"2.0.0","text":"1.0.0"}}
    client = httpx.AsyncClient
    monkeypatch.setattr(status.httpx, "AsyncClient", lambda **kw: client(**kw,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=latest if req.url.host == "api.github.com" else manifest))))
    monkeypatch.setattr(status, "_checked", 0)
    monkeypatch.setattr(status, "_latest", None)
    data = await status.latest_release()
    assert data["version"] == "2.1.0" and data["required"] == ["images"] and data["online"]
    manifest["version"] = "3.0.0"
    monkeypatch.setattr(status, "_checked", 0)
    assert await status.latest_release() == data
