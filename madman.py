from __future__ import annotations
"""Madman: minimal Git pull/deploy helper.

Client commands (run on laptop):
  python madman.py pull [project_id]    # sync repo; optional quick‑ID mode
  python madman.py status [project_id]  # show status; optional quick‑ID mode

Server modes (triggered via SSH):
  pull-server   <id> [<git_user> <git_repo> <branch>]
  status-server <id>

Behaviour:
* If Git parameters are supplied the server clones (if needed) then always
  executes `git fetch` + `git reset --hard origin/<branch>` so the working
  copy exactly matches the remote branch.
* With only the project ID the repo must already exist; the server discovers
  the current branch and performs the same hard‑reset sync.
* After every pull/status the server prints the latest branch, commit hash,
  and message for clarity.
"""

import os
import sys
import subprocess
import argparse
from typing import Dict, List

import yaml

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"


def _p(tag: str, colour: str, msg: str, *, stream=sys.stdout) -> None:
    print(f"{colour}[{tag}]{RESET} {msg}", file=stream)


def info(msg: str) -> None:
    _p("INFO", BLUE, msg)

def success(msg: str) -> None:
    _p("OK", GREEN, msg)

def warn(msg: str) -> None:
    _p("WARN", YELLOW, msg)

def error(msg: str) -> None:
    _p("ERROR", RED, msg, stream=sys.stderr)

# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> Dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _merge(a: Dict, b: Dict) -> Dict:
    out = a.copy()
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> Dict:
    return _merge(_load_yaml(os.path.expanduser("~/madman.yaml")), _load_yaml("./madman.yaml"))

# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

def _ssh(user: str, host: str, remote_cmd: str) -> int:
    target = f"{user}@{host}"
    info(f"SSH {target}: {remote_cmd}")
    try:
        return subprocess.run(["ssh", target, remote_cmd]).returncode
    except Exception as exc:
        error(f"SSH failed: {exc}")
        return 1


def client_pull(override_id: str | None) -> None:
    cfg = load_config()
    try:
        ssh_user, host = cfg["server"]["ssh_user"], cfg["server"]["host"]
    except KeyError as miss:
        error(f"Missing server config key: {miss}")
        sys.exit(1)

    if override_id:
        cmd = f"python3 ~/madman/madman.py pull-server {override_id}"
        sys.exit(_ssh(ssh_user, host, cmd))

    try:
        proj = cfg["project"]
        pid = proj["id"]
        git_user = proj["ssh_git_user"]
        git_repo = proj["ssh_git_repo"]
        branch = proj["ssh_git_branch"]
    except KeyError as miss:
        error(f"Missing project config key: {miss}")
        sys.exit(1)

    cmd = f"python3 ~/madman/madman.py pull-server {pid} {git_user} {git_repo} {branch}"
    sys.exit(_ssh(ssh_user, host, cmd))


def client_status(override_id: str | None) -> None:
    cfg = load_config()
    try:
        ssh_user, host = cfg["server"]["ssh_user"], cfg["server"]["host"]
    except KeyError as miss:
        error(f"Missing server config key: {miss}")
        sys.exit(1)

    pid = override_id or cfg.get("project", {}).get("id")
    if pid is None:
        error("Project ID not provided and not found in madman.yaml")
        sys.exit(1)

    cmd = f"python3 ~/madman/madman.py status-server {pid}"
    sys.exit(_ssh(ssh_user, host, cmd))

# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------

def _path(pid: str) -> str:
    return os.path.join(os.path.expanduser("~"), "madman", "projects", pid)


def _print_latest(repo_path: str) -> None:
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=repo_path, text=True
    ).strip()
    commit = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, text=True
    ).strip()
    msg = subprocess.check_output(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo_path, text=True
    ).strip()
    success(f"branch: {branch} | commit: {commit} | message: {msg}")


def server_pull(args: List[str]) -> None:
    if len(args) not in (1, 4):
        error("Usage: pull-server <id> [<git_user> <git_repo> <branch>]")
        sys.exit(1)

    pid = args[0]
    repo_path = _path(pid)
    os.makedirs(os.path.dirname(repo_path), exist_ok=True)

    if len(args) == 4:
        _, git_user, git_repo, branch = args
        repo_url = f"{git_user}/{git_repo}.git"
        if not os.path.exists(repo_path):
            info(f"Cloning into {repo_path} …")
            subprocess.run(["git", "clone", "-b", branch, repo_url, repo_path], check=True)
            success("Clone completed.")
        else:
            if not os.path.isdir(os.path.join(repo_path, ".git")):
                error(f"{repo_path} exists but is not a git repo.")
                sys.exit(1)
            ru = subprocess.check_output([
                "git", "config", "--get", "remote.origin.url"], cwd=repo_path, text=True
            ).strip()
            if ru != repo_url:
                error(f"Remote URL mismatch: {ru} != {repo_url}")
                sys.exit(1)
    else:
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            error(f"{repo_path} is not a git repo. Provide Git info for first clone.")
            sys.exit(1)
        branch = subprocess.check_output([
            "git", "branch", "--show-current"], cwd=repo_path, text=True
        ).strip()
        if not branch:
            error("Could not determine current branch.")
            sys.exit(1)

    info(f"Synchronising to origin/{branch} …")
    subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True)
    subprocess.run(["git", "reset", "--quiet", "--hard", f"origin/{branch}"], cwd=repo_path, check=True)
    _print_latest(repo_path)


def server_status(args: List[str]) -> None:
    if len(args) != 1:
        error("Usage: status-server <id>")
        sys.exit(1)
    pid = args[0]
    repo_path = _path(pid)
    if not os.path.isdir(repo_path):
        error(f"{repo_path} not found.")
        sys.exit(1)
    info(f"Status for {pid}:")
    _print_latest(repo_path)

# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Madman helper")
    parser.add_argument("command", help="pull | status | pull-server | status-server")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()

    cmd = opts.command
    if cmd == "pull":
        override = opts.args[0] if opts.args else None
        client_pull(override)
    elif cmd == "status":
        override = opts.args[0] if opts.args else None
        client_status(override)
    elif cmd == "pull-server":
        server_pull(opts.args)
    elif cmd == "status-server":
        server_status(opts.args)
    else:
        error(f"Unknown command '{cmd}'")
        sys.exit(1)

if __name__ == "__main__":
    main()
