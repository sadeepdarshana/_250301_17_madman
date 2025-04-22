"""Madman – Git pull/deploy helper (client + server)"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

# Color codes
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"

# YAML config paths on client
SYSTEM_CONFIG = Path.home() / "madman.yaml"
PROJECT_CONFIG = Path("madman.yaml")

# Path to projects on server
PROJECTS_ROOT = Path.home() / "madman" / "projects"

def print_info(message: str) -> None:
    print(f"{BLUE}[INFO]{RESET} {message}", flush=True)

def print_success(message: str) -> None:
    print(f"{GREEN}[OK]{RESET} {message}", flush=True)

def print_error(message: str) -> None:
    print(f"{RED}[ERROR]{RESET} {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge b into a (b wins)."""
    result = a.copy()
    for key, val in b.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config() -> Dict[str, Any]:
    """Merge system + project YAML with deep override."""
    sys_cfg = yaml.safe_load(SYSTEM_CONFIG.read_text()) or {} if SYSTEM_CONFIG.exists() else {}
    proj_cfg = yaml.safe_load(PROJECT_CONFIG.read_text()) or {} if PROJECT_CONFIG.exists() else {}
    return deep_merge(sys_cfg, proj_cfg)


def get_ssh_credentials(cfg: Dict[str, Any]) -> tuple[str, str]:
    """Extract ssh_user and host from config or exit."""
    server = cfg.get("server") or {}
    user = server.get("ssh_user")
    host = server.get("host")
    if not user or not host:
        print_error("Missing server.ssh_user or server.host in config")
    return user, host

# SSH helper
def run_ssh(user: str, host: str, command: str) -> int:
    target = f"{user}@{host}"
    print_info(f"Running on {target}: {command}")
    return subprocess.run(["ssh", target, command]).returncode

# Print latest commit info
def show_latest(repo_path: Path) -> None:
    def git_cmd(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo_path, text=True).strip()

    branch = git_cmd("branch", "--show-current")
    commit = git_cmd("rev-parse", "--short", "HEAD")
    message = git_cmd("log", "-1", "--pretty=%s")
    print_success(f"branch: {branch} | commit: {commit} | message: {message}")

def get_project_credentials(cfg: Dict[str, Any]) -> tuple[str, str, str, str]:
    project = cfg.get("project") or {}
    try:
        return project["id"], project["ssh_git_user"], project["git_repo"], project["git_branch"]
    except KeyError as e:
        print_error(f"Missing project config key: {e}")

# Client-side: clone
def client_clone() -> None:
    cfg = load_config()
    user, host = get_ssh_credentials(cfg)
    pid, git_user, git_repo, git_branch = get_project_credentials(cfg)

    url = f"{git_user}/{git_repo}.git"
    cmd = f"python3 ~/madman/madman.py clone-server {pid} {url} {git_branch}"
    sys.exit(run_ssh(user, host, cmd))

# Client-side: pull
def client_pull(project_override: str | None) -> None:
    cfg = load_config()
    user, host = get_ssh_credentials(cfg)

    if project_override:
        cmd = f"python3 ~/madman/madman.py pull-server {project_override}"
        sys.exit(run_ssh(user, host, cmd))

    pid, git_user, git_repo, git_branch = get_project_credentials(cfg)

    cmd = f"python3 ~/madman/madman.py pull-server {pid} {git_user} {git_repo} {git_branch}"
    sys.exit(run_ssh(user, host, cmd))

# Client-side: status
def client_status(project_override: str | None) -> None:
    cfg = load_config()
    user, host = get_ssh_credentials(cfg)

    pid = project_override or cfg.get("project", {}).get("id")
    if not pid:
        print_error("Project ID not provided and not in project config")

    cmd = f"python3 ~/madman/madman.py status-server {pid}"
    sys.exit(run_ssh(user, host, cmd))

# Server-side: clone-server
def server_clone(args: List[str]) -> None:
    if len(args) != 3:
        print_error("Usage: clone-server <project_id> <git_url> <git_branch>")
    pid, git_repo, git_branch = args

    repo = PROJECTS_ROOT / pid
    if repo.exists():
        print_error(f"Repository '{pid}' already exists")
    repo.parent.mkdir(parents=True, exist_ok=True)

    print_info(f"Git URI:  {git_repo}. Branch: {git_branch}")
    subprocess.run(["git", "clone", "-b", git_branch, git_repo, str(repo)], check=True)
    show_latest(repo)

# Server-side: pull-server
def server_pull(args: List[str]) -> None:
    if len(args) not in (1, 4):
        print_error("Usage: pull-server <project_id> [ssh_git_user git_repo git_branch]")

    pid = args[0]
    repo_path = PROJECTS_ROOT / pid
    repo_path.parent.mkdir(parents=True, exist_ok=True)

    if len(args) == 4:
        _, git_user, git_repo, git_branch = args
        url = f"{git_user}/{git_repo}.git"
        if not repo_path.exists():
            print_info(f"Cloning into {repo_path} …")
            subprocess.run(["git", "clone", "-b", git_branch, url, str(repo_path)], check=True)
        else:
            # Already cloned; assume correct remote and branch
            pass
    else:
        if not (repo_path / ".git").exists():
            print_error("Repository not found; run full pull first")
        git_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo_path, text=True).strip()

    print_info(f"Synchronizing to origin/{git_branch} …")
    subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True)
    subprocess.run(["git", "reset", "--quiet", "--hard", f"origin/{git_branch}"], cwd=repo_path, check=True)
    show_latest(repo_path)

# Server-side: status-server
def server_status(args: List[str]) -> None:
    if len(args) != 1:
        print_error("Usage: status-server <project_id>")

    pid = args[0]
    repo_path = PROJECTS_ROOT / pid
    if not repo_path.exists():
        print_error(f"Repository '{pid}' not found")

    show_latest(repo_path)

# Main entry
def main() -> None:
    parser = argparse.ArgumentParser("madman")
    parser.add_argument("command", choices=["clone", "pull", "status", "clone-server", "pull-server", "status-server"] )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()

    if opts.command == "clone":
        client_clone()
    elif opts.command == "pull":
        client_pull(opts.args[0] if opts.args else None)
    elif opts.command == "status":
        client_status(opts.args[0] if opts.args else None)
    elif opts.command == "clone-server":
        server_clone(opts.args)
    elif opts.command == "pull-server":
        server_pull(opts.args)
    elif opts.command == "status-server":
        server_status(opts.args)

if __name__ == "__main__":
    main()
