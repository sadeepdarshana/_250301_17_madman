from __future__ import annotations
"""Madman: minimal Git pull/deploy helper.

Commands (client side):
  python madman.py pull                # use madman.yaml
  python madman.py pull <project_id>   # quick pull (ID only)
  python madman.py status              # show status on VPS

Server‑side modes are triggered automatically via SSH and rarely
run by humans:
  pull-server          <id> <git_user> <git_repo> <branch>
  pull-server-id       <id>
  status-server        <id>
"""

import os
import sys
import subprocess
import argparse
from typing import Dict

import yaml

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"


def _print(tag: str, colour: str, msg: str, *, stream=sys.stdout) -> None:
    print(f"{colour}[{tag}]{RESET} {msg}", file=stream)


def info(msg: str) -> None:    _print("INFO", BLUE, msg)

def success(msg: str) -> None: _print("OK", GREEN, msg)

def warn(msg: str) -> None:    _print("WARN", YELLOW, msg)

def error(msg: str) -> None:   _print("ERROR", RED, msg, stream=sys.stderr)

# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> Dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _deep_merge(a: Dict, b: Dict) -> Dict:
    out = a.copy()
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> Dict:
    return _deep_merge(
        _load_yaml(os.path.expanduser("~/madman.yaml")),
        _load_yaml("./madman.yaml"),
    )

# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def _ssh_run(user: str, host: str, cmd: str) -> int:
    target = f"{user}@{host}"
    info(f"Running on {target}: {cmd}")
    try:
        return subprocess.run(["ssh", target, cmd]).returncode
    except Exception as exc:
        error(f"SSH failed: {exc}")
        return 1


def client_pull(project_id_override: str | None) -> None:
    cfg = load_config()
    try:
        srv = cfg["server"]
        ssh_user, host = srv["ssh_user"], srv["host"]
    except KeyError as miss:
        error(f"Missing server config key: {miss}")
        sys.exit(1)

    # Quick path: only project ID provided.
    if project_id_override:
        remote_cmd = f"python3 ~/madman/madman.py pull-server {project_id_override}"
        sys.exit(_ssh_run(ssh_user, host, remote_cmd))

    # Full path: need git details from YAML.
    try:
        proj = cfg["project"]
        project_id = proj["id"]
        git_user = proj["ssh_git_user"]
        git_repo = proj["ssh_git_repo"]
        git_branch = proj["ssh_git_branch"]
    except KeyError as miss:
        error(f"Missing project config key: {miss}")
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
    except KeyError as miss:
        error(f"Missing config key: {miss}")
        sys.exit(1)

    remote_cmd = f"python3 ~/madman/madman.py status-server {project_id}"
    sys.exit(_ssh_run(ssh_user, host, remote_cmd))

# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------

def _proj_path(project_id: str) -> str:
    return os.path.join(os.path.expanduser("~"), "madman", "projects", project_id)


def server_pull(args: list[str]) -> None:
    """Unified pull: 4 args → first‑time/forced clone; 1 arg → existing repo.
    Args layouts:
      [id, git_user, git_repo, branch]
      [id]
    Always ends with fetch + hard reset so working tree matches origin/<branch>.
    """
    if len(args) not in (1, 4):
        error("Usage: pull-server <project_id> [<ssh_git_user> <ssh_git_repo> <branch>]")
        sys.exit(1)

    project_id = args[0]
    path = _proj_path(project_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if len(args) == 4:
        _, git_user, git_repo, branch = args
        repo_url = f"{git_user}/{git_repo}.git"
        if not os.path.exists(path):
            info(f"Cloning into {path} …")
            subprocess.run(["git", "clone", "-b", branch, repo_url, path], check=True)
            success("Clone completed.")
        else:
            if not os.path.isdir(os.path.join(path, ".git")):
                error(f"{path} exists but is not a git repo.")
                sys.exit(1)
            ru = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=path, text=True).strip()
            if ru != repo_url:
                error(f"Remote URL mismatch: {ru} != {repo_url}")
                sys.exit(1)
            if subprocess.run(["git", "show-ref", f"refs/remotes/origin/{branch}"], cwd=path).returncode != 0:
                error(f"origin/{branch} not found")
                sys.exit(1)
    else:
        # Only ID; repo must exist.
        if not os.path.isdir(os.path.join(path, ".git")):
            error(f"{path} is not a git repo. Provide Git info for first clone.")
            sys.exit(1)
        # get current branch
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=path, text=True).strip()
        if not branch:
            error("Could not determine current branch.")
            sys.exit(1)

    info(f"Synchronising with origin/{branch} …")
    subprocess.run(["git", "fetch", "origin"], cwd=path, check=True)
    subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd=path, check=True)
    success("Repo updated successfully.")




def server_status(args: list[str]) -> None:
    if len(args) != 1:
        error("Usage: status-server <id>")
        sys.exit(1)
    project_id = args[0]
    path = _proj_path(project_id)
    if not os.path.isdir(path):
        error(f"{path} not found.")
        sys.exit(1)
    info(f"Status for {project_id}:")
    subprocess.run(["git", "remote", "get-url", "origin"], cwd=path)
    subprocess.run(["git", "branch", "--show-current"], cwd=path)
    subprocess.run(["git", "log", "-1", "--oneline"], cwd=path)

# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Madman helper")
    parser.add_argument("command", help="pull | status | pull-server | pull-server-id | status-server")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()

    cmd = opts.command
    if cmd == "pull":
        override = opts.args[0] if opts.args else None
        client_pull(override)
    elif cmd == "status":
        client_status()
    elif cmd == "pull-server":
        server_pull(opts.args)
    elif cmd == "status-server":
        server_status(opts.args)(opts.args)
    else:
        error(f"Unknown command '{cmd}'")
        sys.exit(1)


if __name__ == "__main__":
    main()

