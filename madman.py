"""Madman – Git pull/deploy helper (client + server)"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
import json

MADMAN_CLIENT_CONFIG = Path.home() / "madman-client-config.json"
MADMAN_PROJECT_CONFIG_FILENAME = Path("madman.json")

SCRIPT_DEFAULT_COMMAND = "python3 ~/madman/madman.py"

SERVER_COMMAND_PREFIX = "server"

PROJECTS_ROOT = Path.home() / "madman" / "projects"


def print_info(message: str) -> None:
    print(f"\033[94m[INFO]\033[0m {message}", flush=True)


def print_success(message: str) -> None:
    print(f"\033[92m[OK]\033[0m {message}", flush=True)


def print_error(message: str) -> None:
    print(f"\033[91m[ERROR]\033[0m {message}", file=sys.stderr, flush=True)
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


def get_server_command_for_client_command(client_command):
    return f"{SERVER_COMMAND_PREFIX}-{client_command}"


def madman_client_config() -> Any | None:
    if not MADMAN_CLIENT_CONFIG.exists():
        return None

    try:
        config = json.loads(MADMAN_CLIENT_CONFIG.read_text())  # Use JSON loader
    except:
        return None

    if not get(config, 'script_command'):
        config['script_command'] = SCRIPT_DEFAULT_COMMAND

    return config


def madman_project_config(project_id) -> Any | None:
    config = json.loads((PROJECTS_ROOT / project_id / MADMAN_PROJECT_CONFIG_FILENAME).read_text())
    return config


def validate_madman_client_config() -> None:
    if not MADMAN_CLIENT_CONFIG.exists():
        print_error(f"Madman client config not found at {MADMAN_CLIENT_CONFIG}")

    config = madman_client_config()

    if not config:
        print_error(f"Madman client config ({MADMAN_CLIENT_CONFIG}) parsing error")

    if not get(config, "host") or not get(config, "username"):
        print_error(f"host or username not found in Madman client config ({MADMAN_CLIENT_CONFIG})")


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
def client_clone(config: dict, server_command: str, project_id: str, url: str) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command} {project_id} {url}"
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
def client_pull(config: dict, server_command: str, project_id: str) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command} {project_id}"
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
def client_status(config: dict, server_command: str, project_id: str) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command} {project_id}"
    sys.exit(run_ssh(user, host, cmd))


def server_status(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)


# --------- Delete ---------
def client_delete(config: dict, server_command: str, project_id: str) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command} {project_id}"
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


# --------- Run ---------
def client_run(config: dict, server_command: str, project_id: str) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command} {project_id}"
    sys.exit(run_ssh(user, host, cmd))


def server_run(project_id: str) -> None:
    config = madman_project_config(project_id)
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)

    subprocess.run(config['run'].split())


# --------- SSH ---------
def client_ssh(config: dict, server_command: str, project_id: str = None) -> None:
    user, host, command = config["username"], config["host"], config['script_command']
    sys.exit(run_ssh(user, host, ''))


# --------- List ---------
def client_list(config: dict, server_command: str) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command}"
    sys.exit(run_ssh(user, host, cmd))


def server_list() -> None:
    project_ids = [entry for entry in os.listdir(PROJECTS_ROOT) if os.path.isdir(os.path.join(PROJECTS_ROOT, entry))]

    for project_id in project_ids:
        print(project_id)


# ----------------------------------------------------------------------------------------------------------------------

def main() -> None:
    client_server_command_map = [
        ("clone", client_clone, server_clone),
        ("pull", client_pull, server_pull),
        ("status", client_status, server_status),
        ("delete", client_delete, server_delete),
        ("run", client_run, server_run),
        ("ssh", client_ssh, None),
        ("list", client_list, server_list)
    ]

    client_commands = [command[0] for command in client_server_command_map]
    server_commands = [get_server_command_for_client_command(command[0]) for command in client_server_command_map]

    parser = argparse.ArgumentParser("madman")
    parser.add_argument("command", choices=client_commands + server_commands)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()

    for command in client_server_command_map:
        client_command, client_function, server_function = command
        server_command = get_server_command_for_client_command(client_command)

        if options.command == client_command and client_function:
            validate_madman_client_config()
            client_function(madman_client_config(), server_command, *options.args)
            return

        if options.command == server_command and server_function:
            server_function(*options.args)
            return

    print_error(f"Unknown command: {options.command}")


if __name__ == "__main__":
    main()
