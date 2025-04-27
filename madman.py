"""Madman – Git pull/deploy helper (client + server)"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

MADMAN_CLIENT_CONFIG = Path.home() / ".madman-client-config.yaml"
PROJECT_CONFIG = Path("madman.yaml")

SCRIPT_DEFAULT_COMMAND = "python3 ~/madman/madman.py"

CLIENT_COMMANDS = ["clone", "pull", "status", "delete", "list"]
SERVER_COMMANDS = ["server-clone", "server-pull", "server-status", "server-delete", "server-list"]

PROJECTS_ROOT = Path.home() / "madman" / "projects"


def print_info(message: str) -> None:
    print(f"{"\033[94m"}[INFO]{"\033[0m"} {message}", flush=True)


def print_success(message: str) -> None:
    print(f"{"\033[92m"}[OK]{"\033[0m"} {message}", flush=True)


def print_error(message: str) -> None:
    print(f"{"\033[91m"}[ERROR]{"\033[0m"} {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def assert_project_exists(project_id: str):
    if not (PROJECTS_ROOT / project_id / ".git").exists():
        print_error(f"Project with ID '{project_id}' not found on server")


def assert_project_not_exists(project_id: str):
    repo_path = PROJECTS_ROOT / project_id
    if repo_path.exists():
        print_error(f"Project with ID '{project_id}' already exists on server")


def get(d: dict, path: str, default=None):
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
    print_info(f"branch: {branch}  |  commit: {commit}  |  message: {message}  |  path: {repo_path}")


# Server and client commands -------------------------------------------------------------------------------------------
# --------- Clone -----------
def client_clone(project_id: str, url: str) -> None:
    config = madman_client_config()
    user, host, command = config["server"]["username"], config["server"]["host"], config['server']['script_command']

    cmd = f"{command} server-clone {project_id} {url}"
    sys.exit(run_ssh(user, host, cmd))


def server_clone(project_id: str, url: str) -> None:
    assert_project_not_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id
    repo_path.parent.mkdir(parents=True, exist_ok=True)

    print_info(f"Cloning {url} into {repo_path}")
    subprocess.run(["git", "clone", "--quiet", url, str(repo_path)], check=True)
    print_success('Clone successful')

    show_latest(repo_path)


# --------- Pull ----------
def client_pull(project_id: str) -> None:
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


# --------- Delete ---------
def client_delete(project_id: str) -> None:
    config = madman_client_config()
    user, host, command = config["server"]["username"], config["server"]["host"], config['server']['script_command']

    cmd = f"{command} server-delete {project_id}"
    sys.exit(run_ssh(user, host, cmd))


def server_delete(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)

    try:
        shutil.rmtree(repo_path)
        print_success(f"Successfully deleted project")
    except Exception as e:
        print_error(f"Failed to delete directory {repo_path}: {e}")


# --------- List ---------
def client_list() -> None:
    config = madman_client_config()
    user, host, command = config["server"]["username"], config["server"]["host"], config['server']['script_command']

    cmd = f"{command} server-list"
    sys.exit(run_ssh(user, host, cmd))


def server_list() -> None:
    project_ids = [entry for entry in os.listdir(PROJECTS_ROOT) if os.path.isdir(os.path.join(PROJECTS_ROOT, entry))]

    for project_id in project_ids:
        print(project_id)


# ----------------------------------------------------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser("madman")
    parser.add_argument("command", choices=CLIENT_COMMANDS + SERVER_COMMANDS)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()

    if options.command in CLIENT_COMMANDS:
        validate_madman_client_config()

    commands_map = {
        "clone": client_clone,
        "server-clone": server_clone,
        "pull": client_pull,
        "server-pull": server_pull,
        "status": client_status,
        "server-status": server_status,
        "delete": client_delete,
        "server-delete": server_delete,
        "list": client_list,
        "server-list": server_list,
    }

    if options.command not in commands_map:
        print_error(f"Unknown command: {options.command}")

    commands_map[options.command](*options.args)


if __name__ == "__main__":
    main()
