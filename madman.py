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


def print_info(message: str) -> None:
    print(f"{BLUE}[INFO]{RESET} {message}")


def print_success(message: str) -> None:
    print(f"{GREEN}[OK]{RESET} {message}")


def print_error(message: str) -> None:
    print(f"{RED}[ERROR]{RESET} {message}", file=sys.stderr)
    sys.exit(1)

# Load YAML config
SYSTEM_CONFIG = Path.home() / "madman.yaml"
PROJECT_CONFIG = Path("madman.yaml")

def load_config() -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    if SYSTEM_CONFIG.exists():
        config.update(yaml.safe_load(SYSTEM_CONFIG.read_text()) or {})
    if PROJECT_CONFIG.exists():
        config.update(yaml.safe_load(PROJECT_CONFIG.read_text()) or {})
    return config


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

# Path to projects
PROJECTS_ROOT = Path.home() / "madman" / "projects"

# Print latest commit info
def show_latest(repo_path: Path) -> None:
    def git_cmd(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo_path, text=True).strip()

    branch = git_cmd("branch", "--show-current")
    commit = git_cmd("rev-parse", "--short", "HEAD")
    message = git_cmd("log", "-1", "--pretty=%s")
    print_success(f"branch: {branch} | commit: {commit} | message: {message}")

# Client-side: pull
def client_pull(project_override: str | None) -> None:
    cfg = load_config()
    user, host = get_ssh_credentials(cfg)

    if project_override:
        cmd = f"python3 ~/madman/madman.py pull-server {project_override}"
        sys.exit(run_ssh(user, host, cmd))

    project = cfg.get("project") or {}
    try:
        pid = project["id"]
        git_user = project["ssh_git_user"]
        git_repo = project["ssh_git_repo"]
        git_branch = project["ssh_git_branch"]
    except KeyError as e:
        print_error(f"Missing project config key: {e}")

    cmd = (f"python3 ~/madman/madman.py pull-server {pid} "
           f"{git_user} {git_repo} {git_branch}")
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

# Server-side: pull-server
def server_pull(args: List[str]) -> None:
    if len(args) not in (1, 4):
        print_error("Usage: pull-server <project_id> [ssh_git_user ssh_git_repo ssh_git_branch]")

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
    parser.add_argument("command", choices=["pull", "status", "pull-server", "status-server"] )
    parser.add_argument("args", nargs=argparse.REMAINDER)
    opts = parser.parse_args()

    if opts.command == "pull":
        client_pull(opts.args[0] if opts.args else None)
    elif opts.command == "status":
        client_status(opts.args[0] if opts.args else None)
    elif opts.command == "pull-server":
        server_pull(opts.args)
    elif opts.command == "status-server":
        server_status(opts.args)

if __name__ == "__main__":
    main()
