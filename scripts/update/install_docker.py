"""Install the updater beside an existing Compose app, preserving its overrides."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def installation(root):
    identifiers = run("docker", "ps", "-q", "--filter", "label=com.docker.compose.service=backend",
                      "--filter", f"label=com.docker.compose.project.working_dir={root}").splitlines()
    if len(identifiers) != 1:
        raise ValueError("Expected one running backend in this installation directory")
    labels = json.loads(run("docker", "inspect", "--format", "{{json .Config.Labels}}", identifiers[0]))
    project = labels["com.docker.compose.project"]
    files = labels["com.docker.compose.project.config_files"].split(",")
    return project, files


def install(root):
    project, files = installation(root)
    state = root / ".novelvids-update/state"
    override = root / ".novelvids-update/compose.json"
    if (state / "status.json").exists():
        phase = json.loads((state / "status.json").read_text())["phase"]
        if phase in {"preparing", "draining", "installing", "rolling_back", "recovery_needed"}:
            raise ValueError("An unfinished update must be recovered first")
    # An old host updater needs explicit migration to avoid two update owners.
    if any("/run/novelvids-update" in Path(file).read_text() for file in files if Path(file) != override):
        raise ValueError("An existing host updater must be stopped and migrated first")
    command = ["docker", "compose", "--project-name", project]
    for file in files:
        command.extend(["--file", file])
    config = json.loads(run(*command, "config", "--format", "json"))
    backend = config["services"]["backend"]
    if backend["environment"].get("DATABASE_URL") != "sqlite:///app/data/novelvids.db":
        raise ValueError("This updater currently supports the standard SQLite installation")
    if not any(v.get("source") == str(root / "data") and v["target"] == "/app/data" for v in backend["volumes"]):
        raise ValueError("Expected the installation's data directory to be mounted")
    state.mkdir(parents=True, exist_ok=True)
    (state / "compose.sha256").write_text(hashlib.sha256((root / "docker-compose.yml").read_bytes()).hexdigest())
    volume = project + "_update_runtime"
    run("docker", "volume", "create", volume)
    if not override.exists():
        override.write_text(json.dumps({"services": {"backend": {"volumes": [f"{volume}:/run/novelvids-update:ro"]}},
                                       "volumes": {volume: {"external": True}}}))
    if str(override) not in files:
        files.append(str(override))
        command.extend(["--file", str(override)])
    name = project + "-updater"
    existing = run("docker", "ps", "-aq", "--filter", f"name=^/{name}$")
    if existing:
        owner = run("docker", "inspect", "--format", '{{index .Config.Labels "novelvids.update.root"}}', existing)
        if owner != str(root):
            raise ValueError("The updater container name belongs to another installation")
        run("docker", "rm", "-f", name)
    run("docker", "run", "-d", "--name", name, "--restart", "unless-stopped",
        "--label", f"novelvids.update.root={root}",
        "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{root}:{root}",
        "-v", f"{volume}:/run/novelvids-update", "-w", str(root),
        "-e", f"COMPOSE_PROJECT_NAME={project}", "-e", "COMPOSE_FILE=" + ":".join(files),
        "-e", f"NOVELVIDS_UPDATE_STATE={state}", "-e", f"NOVELVIDS_UPDATE_OVERRIDE={override}",
        "-e", f"NOVELVIDS_UPDATE_VOLUME={volume}", "novelvids-updater:local", str(root))
    # Recreate only the backend to attach the shared socket, keeping the current image.
    run(*command, "up", "-d", "--no-build", "--no-deps", "backend")
    print("Docker updater installed. The studio will offer newer published releases.")


if __name__ == "__main__":
    install(Path(sys.argv[1]).resolve())
