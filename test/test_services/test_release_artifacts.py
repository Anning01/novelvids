import hashlib
import io
import json
import subprocess
import tarfile

import pytest

from scripts.update import agent
from scripts.update import install_docker
from scripts.update.prepare_release import next_version, prepare


@pytest.mark.parametrize("current,latest,expected", [
    ("1.1.0", "", "1.2.0"), ("1.1.0", "1.9.0", "1.10.0"), ("2.0.0", "1.9.0", "2.1.0"),
])
def test_release_increments_minor_without_manual_version_edit(current, latest, expected):
    assert next_version(current, latest) == expected


def test_release_packages_only_committed_files_and_does_not_modify_branch(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Release test")
    git("config", "user.email", "release@example.invalid")
    original = json.dumps({"version": "1.1.0", "minimum": {}, "update_format": 1})
    (root / "release.json").write_text(original)
    git("add", "release.json")
    git("commit", "-qm", "fixture")
    (root / "private.txt").write_text("untracked local file")
    sha = git("rev-parse", "HEAD")
    output = tmp_path / "release"
    assert prepare(root, output, "1.2.0") == "1.3.0"
    assert git("rev-parse", "HEAD") == sha
    assert (root / "release.json").read_text() == original
    manifest = json.loads((output / "release.json").read_text())
    bundle = output / manifest["source_archive"]["name"]
    assert manifest["source_archive"]["sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    with tarfile.open(bundle) as archive:
        assert "private.txt" not in archive.getnames()
        packaged = json.load(archive.extractfile("release.json"))
    assert packaged["version"] == "1.3.0" and packaged["source_commit"] == sha


def test_updater_verifies_archive_before_extracting(tmp_path, monkeypatch):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        payload = b'{"version":"1.2.0"}'
        member = tarfile.TarInfo("release.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    bundle = data.getvalue()
    manifest = {"version": "1.2.0", "update_format": 1,
                "source_archive": {"name": "source.tar.gz", "sha256": hashlib.sha256(bundle).hexdigest()}}
    release = {"assets": [{"name": name, "browser_download_url": name} for name in ("release.json", "source.tar.gz")]}
    monkeypatch.setattr(agent.urllib.request, "urlopen", lambda url, **kwargs:
                        io.BytesIO(json.dumps(manifest).encode() if url == "release.json" else bundle))
    agent.release_source(release, "1.2.0", tmp_path / "valid")
    assert json.loads((tmp_path / "valid/release.json").read_text())["version"] == "1.2.0"
    manifest["source_archive"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        agent.release_source(release, "1.2.0", tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_container_install_keeps_custom_compose_and_uses_shared_socket_volume(tmp_path, monkeypatch):
    root = tmp_path / "studio"
    root.mkdir()
    compose = root / "docker-compose.yml"
    compose.write_text("services: {}")
    local = root / "compose.local.yaml"
    original = "services: {frontend: {ports: ['127.0.0.1:8080:80']}}"
    local.write_text(original)
    monkeypatch.setattr(install_docker, "installation", lambda _: ("studio", [str(compose), str(local)]))
    calls = []
    config = {"services": {"backend": {"environment": {"DATABASE_URL": "sqlite:///app/data/novelvids.db"},
              "volumes": [{"source": str(root / "data"), "target": "/app/data"}]}}}
    def run(*args):
        calls.append(args)
        return json.dumps(config) if args[-3:] == ("config", "--format", "json") else ""
    monkeypatch.setattr(install_docker, "run", run)
    install_docker.install(root)
    assert local.read_text() == original
    launch = next(call for call in calls if call[:3] == ("docker", "run", "-d"))
    assert "COMPOSE_FILE=" + ":".join([str(compose), str(local), str(root / ".novelvids-update/compose.json")]) in launch
    assert "studio_update_runtime:/run/novelvids-update" in launch
    assert calls[-1][-4:] == ("-d", "--no-build", "--no-deps", "backend")
    assert not any(call[:3] == ("docker", "compose", "down") for call in calls)


def test_container_activation_preserves_shared_socket_volume(tmp_path, monkeypatch):
    overlay = tmp_path / "compose.json"
    monkeypatch.setenv("NOVELVIDS_UPDATE_OVERRIDE", str(overlay))
    monkeypatch.setenv("NOVELVIDS_UPDATE_VOLUME", "studio_update_runtime")
    monkeypatch.setattr(agent, "compose", lambda *args: "")
    agent.activate({"backend": "new-backend", "frontend": "new-frontend"})
    config = json.loads(overlay.read_text())
    assert config["volumes"] == {"studio_update_runtime": {"external": True}}
    assert config["services"]["backend"]["volumes"] == ["studio_update_runtime:/run/novelvids-update:ro"]


@pytest.mark.asyncio
async def test_release_status_uses_stamped_asset_instead_of_main_version(monkeypatch):
    import httpx
    from services.releases import status
    latest = {"tag_name": "v1.2.0", "draft": False, "prerelease": False,
              "assets": [{"name": "release.json", "browser_download_url": "https://github.com/release.json"}]}
    manifest = {"version": "1.2.0", "minimum": {}, "summary": "更新", "summary_en": "Update", "update_format": 1}
    urls = []
    def respond(request):
        urls.append(str(request.url))
        return httpx.Response(200, json=latest if request.url.host == "api.github.com" else manifest)
    client = httpx.AsyncClient
    monkeypatch.setattr(status.httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(status, "_checked", 0)
    monkeypatch.setattr(status, "_latest", None)
    assert (await status.latest_release())["version"] == "1.2.0"
    assert urls[-1] == "https://github.com/release.json"
