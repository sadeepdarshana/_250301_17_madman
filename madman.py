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

MADMAN_CLIENT_CONFIG = Path.home() / ".madman-client-config.yaml"
PROJECT_CONFIG = Path("madman.yaml")

SCRIPT_DEFAULT_COMMAND = "python3 ~/madman/madman.py"

CLIENT_COMMANDS = ["clone", "pull", "status"]
SERVER_COMMANDS = ["server-clone", "server-pull", "server-status"]

# Path to projects on server
PROJECTS_ROOT = Path.home() / "madman" / "projects"


def print_info(message: str) -> None:
    print(f"{BLUE}[INFO]{RESET} {message}", flush=True)


def print_success(message: str) -> None:
    print(f"{GREEN}[OK]{RESET} {message}", flush=True)


def print_error(message: str) -> None:
    print(f"{RED}[ERROR]{RESET} {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def assert_project_exists(project_id):
    if not (PROJECTS_ROOT / project_id / ".git").exists():
        print_error(f"Project with ID '{project_id}' not found on server")


def assert_project_not_exists(project_id):
    repo_path = PROJECTS_ROOT / project_id
    if repo_path.exists():
        print_error(f"Project with ID '{project_id}' already exists on server")


def get(d, path, default=None):
    keys = path.split(".")
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, default)
        else:
            return default
    return d


def madman_client_config() -> Any | None:
    if not MADMAN_CLIENT_CONFIG.exists():
        return None

    config = yaml.safe_load(MADMAN_CLIENT_CONFIG.read_text())

    if not get(config, 'server.script_command'):
        config['server']['script_command'] = SCRIPT_DEFAULT_COMMAND

    return config


def validate_madman_client_config() -> None:
    if not MADMAN_CLIENT_CONFIG.exists():
        print_error("Madman client config not found at ~/.madman-client-config.yaml")

    config = madman_client_config()

    if not config:
        print_error("Madman client config (~/.madman-client-config.yaml) parsing error")

    if not get(config, "server.host") or not get(config, "server.username"):
        print_error("server.host or server.username not found in Madman client config (~/.madman-client-config.yaml)")


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
    print_info(f"branch: {branch} | commit: {commit} | message: {message}")


def get_project_credentials(cfg: Dict[str, Any]) -> tuple[str, str, str, str]:
    project = cfg.get("project") or {}
    try:
        return project["id"], project["ssh_git_user"], project["git_repo"], project["git_branch"]
    except KeyError as e:
        print_error(f"Missing project config key: {e}")


# Server and client commands -------------------------------------------------------------------------------------------
# --------- Clone -----------
def client_clone(project_id, url) -> None:
    config = madman_client_config()
    user, host, command = config["server"]["username"], config["server"]["host"], config['server']['script_command']

    cmd = f"{command} server-clone {project_id} {url}"
    sys.exit(run_ssh(user, host, cmd))


def server_clone(project_id, url) -> None:
    assert_project_not_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id
    repo_path.parent.mkdir(parents=True, exist_ok=True)

    print_info(f"Cloning {url} into {repo_path}")
    subprocess.run(["git", "clone", "--quiet", url, str(repo_path)], check=True)
    print_success('Clone successful')

    show_latest(repo_path)


# --------- Pull ----------
def client_pull(project_id) -> None:
    config = madman_client_config()
    user, host, command = config["server"]["username"], config["server"]["host"], config['server']['script_command']

    cmd = f"{command} server-pull {project_id}"
    sys.exit(run_ssh(user, host, cmd))


def server_pull(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)

    git_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo_path, text=True).strip()
    print_info(f"Synchronizing to origin/{git_branch} …")
    subprocess.run(["git", "fetch", "--quiet", "origin"], cwd=repo_path, check=True)
    subprocess.run(["git", "reset", "--quiet", "--hard", f"origin/{git_branch}"], cwd=repo_path, check=True)
    print_success('Pull successful')

    show_latest(repo_path)


# --------- Status ---------
def client_status(project_id: str) -> None:
    config = madman_client_config()
    user, host, command = config["server"]["username"], config["server"]["host"], config['server']['script_command']

    cmd = f"{command} server-status {project_id}"
    sys.exit(run_ssh(user, host, cmd))


def server_status(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)


# ----------------------------------------------------------------------------------------------------------------------

# Main entry
def main() -> None:
    parser = argparse.ArgumentParser("madman")
    parser.add_argument("command", choices=CLIENT_COMMANDS + SERVER_COMMANDS)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()

    if options.command in CLIENT_COMMANDS:
        validate_madman_client_config()

    if options.command == "clone":
        client_clone(*options.args)
    elif options.command == "pull":
        client_pull(*options.args)
    elif options.command == "status":
        client_status(*options.args)
    elif options.command == "server-clone":
        server_clone(*options.args)
    elif options.command == "server-pull":
        server_pull(*options.args)
    elif options.command == "server-status":
        server_status(*options.args)


if __name__ == "__main__":
    main()
