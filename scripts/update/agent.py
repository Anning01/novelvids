"""Host-side updater for the standard single-host Docker Compose installation."""
import fcntl
import http.server
import json
import os
import re
import logging
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import hashlib
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if __name__ == "__main__" else Path.cwd()
RUNTIME = Path("/run/novelvids-update")
STATE = Path("/var/lib/novelvids-update")
REPO = "Anning01/novelvids"
TAG = re.compile(r"v(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
LOCK = threading.Lock()


def run(*args, timeout=1800):
    return subprocess.check_output(args, cwd=ROOT, timeout=timeout, text=True).strip()


def compose(*args):
    return run("docker", "compose", *args)


def write(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    os.replace(tmp, path)


def state():
    path = STATE / "status.json"
    return json.loads(path.read_text()) if path.exists() else {"phase": "idle"}


def mark(phase, version):
    write(STATE / "status.json", {"phase": phase, "version": version})


def probe(path):
    # Exercise nginx and its backend proxy inside this project's frontend.
    return json.loads(compose("exec", "-T", "frontend", "wget", "-qO-", "-T", "4", "http://127.0.0.1" + path))


def healthy(version):
    for _ in range(30):
        try:
            if probe("/studio-build.json")["version"] == version and probe("/api/release/installed")["data"]["version"] == version:
                return True
        except (subprocess.SubprocessError, KeyError, ValueError):
            pass
        time.sleep(2)
    return False


def compose_bytes(directory):
    # Ignore comments/whitespace so documentation-only changes do not block an upgrade.
    return "\n".join(line.rstrip() for line in (directory / "docker-compose.yml").read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")).encode()


def current_images():
    result = {}
    for service in ("backend", "frontend"):
        cid = compose("ps", "-q", service)
        result[service] = run("docker", "inspect", "--format", "{{.Image}}", cid)
    return result


def override():
    return ROOT / "docker-compose.override.yml"


def activate(images):
    services = {name: {"image": image, "pull_policy": "never"} for name, image in images.items()}
    services["backend"]["volumes"] = [f"{RUNTIME}:/run/novelvids-update:ro"]
    write(override(), {"services": services})
    compose("up", "-d", "--no-build", "--force-recreate", "backend", "frontend")


def rollback(checkpoint):
    version = checkpoint["version"]
    mark("rolling_back", version)
    compose("stop", "frontend", "backend")
    database = ROOT / "data/novelvids.db"
    backups = checkpoint.get("databases", {"novelvids.db": "previous.db"})
    for filename, backup in backups.items():
        with sqlite3.connect(STATE / backup) as source, sqlite3.connect(database.parent / filename) as destination:
            source.backup(destination)
    activate(checkpoint["images"])
    if not healthy(checkpoint["previous"]):
        raise RuntimeError("Rollback health check failed")
    (STATE / "switch.json").unlink()
    mark("rolled_back", version)


def upgrade(version):
    tag = "v" + version
    mark("preparing", version)
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/releases/latest", timeout=10) as response:
            release = json.load(response)
        if release["tag_name"] != tag or release["draft"] or release["prerelease"]:
            raise ValueError("Expected latest stable release")
        previous = probe("/api/release/installed")["data"]["version"]
        if tuple(map(int, version.split("."))) <= tuple(map(int, previous.split("."))):
            raise ValueError("Expected newer release")
        # Only a stock compose topology is supported. Preserve the operator's environment and mounts.
        config = json.loads(compose("config", "--format", "json"))
        backend = config["services"]["backend"]
        if backend["environment"].get("DATABASE_URL") != "sqlite:///app/data/novelvids.db":
            raise ValueError("Unsupported database layout")
        if not any(v.get("source") == str(ROOT / "data") and v["target"] == "/app/data" for v in backend["volumes"]):
            raise ValueError("Unsupported data volume")
        if (STATE / "compose.sha256").read_text().strip() != hashlib.sha256((ROOT / "docker-compose.yml").read_bytes()).hexdigest():
            raise ValueError("Host compose configuration has changed")
        images = {}
        with tempfile.TemporaryDirectory(dir=STATE) as directory:
            run("git", "clone", "--depth", "1", "--branch", tag, "https://github.com/" + REPO + ".git", directory)
            source = Path(directory)
            manifest = json.loads((source / "release.json").read_text())
            if manifest["version"] != version or manifest.get("update_format") != 1:
                raise ValueError("Release manifest mismatch")
            if compose_bytes(source) != compose_bytes(ROOT):
                raise ValueError("This release requires a Compose deployment change")
            for name, dockerfile in (("backend", "Dockerfile"), ("frontend", "web/Dockerfile")):
                image = f"novelvids-release-{name}:{version}"
                run("docker", "build", "--tag", image, "--file", str(source / dockerfile), directory)
                images[name] = image
        checkpoint = {"version": version, "previous": previous, "images": {}}
        for name, image in current_images().items():
            alias = f"novelvids-rollback-{name}:{previous}"
            run("docker", "tag", image, alias)
            checkpoint["images"][name] = alias
        # Re-check active tasks after building (which may take several minutes).
        mark("draining", version)
        for _ in range(1800):
            if probe("/api/release/installed")["data"].get("busy") is False:
                break
            time.sleep(2)
        else:
            raise RuntimeError("Active tasks did not finish before the update window")
        mark("installing", version)
        # Recovery before the checkpoint only needs to restart the original containers.
        compose("stop", "frontend", "backend")
        database = ROOT / "data/novelvids.db"
        if not database.is_file():
            raise ValueError("Missing database")
        checkpoint["databases"] = {}
        for filename in ("novelvids.db", "creation_agent_checkpoints.db"):
            path = database.parent / filename
            if path.is_file():
                backup = "previous-" + filename
                with sqlite3.connect(path) as src, sqlite3.connect(STATE / backup) as dst:
                    src.backup(dst)
                checkpoint["databases"][filename] = backup
        write(STATE / "switch.json", checkpoint)
        activate(images)
        if not healthy(version):
            raise RuntimeError("Release health check failed")
        (STATE / "switch.json").unlink()
        mark("completed", version)
    except Exception:
        logging.exception("Studio update failed for %s", version)
        recover(version)
    finally:
        LOCK.release()


def recover(version):
    try:
        if (STATE / "switch.json").exists():
            rollback(json.loads((STATE / "switch.json").read_text()))
        else:
            if state()["phase"] == "installing":
                compose("start", "backend", "frontend")
            mark("failed", version)
    except Exception:
        logging.exception("Recovery failed for %s", version)
        mark("recovery_needed", version)


class Handler(http.server.BaseHTTPRequestHandler):
    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200, state())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if self.path != "/update" or not 0 < length < 100:
                raise ValueError
            version = json.loads(self.rfile.read(length))["version"]
            if not TAG.fullmatch("v" + version):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {})
        if state()["phase"] == "recovery_needed" or not LOCK.acquire(blocking=False):
            return self.reply(409, state())
        mark("preparing", version)
        threading.Thread(target=upgrade, args=(version,)).start()
        self.reply(202, {"phase": "preparing", "version": version})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_file = (STATE / "lock").open("a")
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (STATE / "switch.json").exists() or state()["phase"] in {"preparing", "draining", "installing", "rolling_back"}:
        recover(state().get("version"))
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    sock = RUNTIME / "control.sock"
    sock.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(sock), Handler) as server:
        sock.chmod(0o600)
        server.serve_forever()
