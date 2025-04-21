import os
import sys
import subprocess
import argparse
from typing import Dict

import yaml

# ---------------------------------------------------------------------------
# Styling helpers (ANSI colours)
# ---------------------------------------------------------------------------
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"


def _print(tag: str, colour: str, msg: str, file=sys.stdout):
    print(f"{colour}[{tag}]{RESET} {msg}", file=file)


def info(msg: str):
    _print("INFO", BLUE, msg)


def success(msg: str):
    _print("OK", GREEN, msg)


def warn(msg: str):
    _print("WARN", YELLOW, msg)


def error(msg: str):
    _print("ERROR", RED, msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# YAML configuration helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> Dict:
    """Return parsed YAML or empty dict if the file does not exist."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge *override* into *base* (override wins)."""
    merged = base.copy()
    for key, val in override.items():
        if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(val, dict)
        ):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_config() -> Dict:
    """Merge system‑level and project‑level madman.yaml files."""
    system_cfg = _load_yaml(os.path.expanduser("~/madman.yaml"))
    project_cfg = _load_yaml("./madman.yaml")
    return _deep_merge(system_cfg, project_cfg)


# ---------------------------------------------------------------------------
# Client‑side helpers (called from developer laptop)
# ---------------------------------------------------------------------------

def _ssh_run(ssh_user: str, host: str, remote_cmd: str) -> int:
    """Run *remote_cmd* on *ssh_user@host* and stream output."""
    target = f"{ssh_user}@{host}"
    cmd = ["ssh", target, remote_cmd]
    info(f"Running remote command on {target}: {remote_cmd}")
    try:
        return subprocess.run(cmd).returncode
    except Exception as exc:
        error(f"SSH execution failed: {exc}")
        return 1


def client_pull() -> None:
    cfg = load_config()
    try:
        srv = cfg["server"]
        proj = cfg["project"]
        ssh_user, host = srv["ssh_user"], srv["host"]
        project_id = proj["id"]
        git_user = proj["ssh_git_user"]
        git_repo = proj["ssh_git_repo"]
        git_branch = proj["ssh_git_branch"]
    except KeyError as missing:
        error(f"Missing required config key: {missing}")
        sys.exit(1)

    remote_cmd = (
        "python3 ~/madman/madman.py pull-server "
        f"{project_id} {git_user} {git_repo} {git_branch}"
    )
    sys.exit(_ssh_run(ssh_user, host, remote_cmd))


def client_status() -> None:
    cfg = load_config()
    try:
        srv = cfg["server"]
        proj = cfg["project"]
        ssh_user, host = srv["ssh_user"], srv["host"]
        project_id = proj["id"]
    except KeyError as missing:
        error(f"Missing required config key: {missing}")
        sys.exit(1)

    remote_cmd = f"python3 ~/madman/madman.py status-server {project_id}"
    sys.exit(_ssh_run(ssh_user, host, remote_cmd))


# ---------------------------------------------------------------------------
# Server‑side helpers (executed on the VPS)
# ---------------------------------------------------------------------------

def server_pull(args):
    if len(args) != 4:
        error(
            "Usage: pull-server <project_id> <ssh_git_user> <ssh_git_repo> <ssh_git_branch>"
        )
        sys.exit(1)

    project_id, git_user, git_repo, git_branch = args
    home = os.path.expanduser("~")
    proj_root = os.path.join(home, "madman", "projects")
    proj_path = os.path.join(proj_root, project_id)

    os.makedirs(proj_root, exist_ok=True)
    repo_url = f"{git_user}/{git_repo}.git"

    if not os.path.exists(proj_path):
        info(f"Cloning repository into {proj_path}...")
        subprocess.run(["git", "clone", "-b", git_branch, repo_url, proj_path], check=True)
        success("Clone completed.")
    else:
        if not os.path.isdir(os.path.join(proj_path, ".git")):
            error(f"{proj_path} exists but is not a Git repository.")
            sys.exit(1)

        # --- Sanity checks ---------------------------------------------------
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=proj_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != repo_url:
            error(
                "Remote origin URL mismatch. "
                f"Expected '{repo_url}', got '{result.stdout.strip()}'."
            )
            sys.exit(1)

        result = subprocess.run(
            ["git", "show-ref", f"refs/remotes/origin/{git_branch}"],
            cwd=proj_path,
            check=False,
        )
        if result.returncode != 0:
            error(f"Branch 'origin/{git_branch}' not found.")
            sys.exit(1)
        # --------------------------------------------------------------------

        info("Pulling latest changes…")
        subprocess.run(["git", "fetch", "origin"], cwd=proj_path, check=True)
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{git_branch}"],
            cwd=proj_path,
            check=True,
        )
        success("Repo updated successfully.")


def server_status(args):
    if len(args) != 1:
        error("Usage: status-server <project_id>")
        sys.exit(1)

    project_id = args[0]
    proj_path = os.path.join(os.path.expanduser("~"), "madman", "projects", project_id)
    if not os.path.isdir(proj_path):
        error(f"Project '{project_id}' not found at {proj_path}.")
        sys.exit(1)

    info(f"Status for project '{project_id}':")
    subprocess.run(["git", "remote", "get-url", "origin"], cwd=proj_path)
    subprocess.run(["git", "branch", "--show-current"], cwd=proj_path)
    subprocess.run(["git", "log", "-1", "--oneline"], cwd=proj_path)


# ---------------------------------------------------------------------------
# Entry‑point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Madman deployment tool")
    parser.add_argument(
        "command",
        help="pull | status | pull-server | status-server",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()

    cmd = opts.command
    if cmd == "pull":
        client_pull()
    elif cmd == "status":
        client_status()
    elif cmd == "pull-server":
        server_pull(opts.args)
    elif cmd == "status-server":
        server_status(opts.args)
    else:
        error(f"Unknown command '{cmd}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
