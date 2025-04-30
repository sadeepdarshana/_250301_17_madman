"""Madman – Git pull/deploy helper (client + server)"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, List
import json

MADMAN_CLIENT_CONFIG = Path.home() / "madman-client-config.json"
MADMAN_PROJECT_CONFIG_FILENAME = Path("madman.json")

SCRIPT_DEFAULT_COMMAND = "python3 ~/madman/madman.py"

SERVER_COMMAND_PREFIX = "server"

PROJECTS_ROOT = Path.home() / "madman" / "projects"

SYSTEMD_FILES_ROOT = Path('/etc/systemd/system')


def print_info(message: str) -> None:
    print(f"\033[94m[INFO]\033[0m {message}", flush=True)


def print_success(message: str) -> None:
    print(f"\033[92m[OK]\033[0m {message}", flush=True)


def print_error(message: str) -> None:
    print(f"\033[91m[ERROR]\033[0m {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def parse_args(all_commands):
    parser = argparse.ArgumentParser("madman")
    parser.add_argument("command", choices=all_commands)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    return options.command, options.args


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


def get_server_command(client_command):
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


def write_systemd_service_config(project_id: str):
    project_config = madman_project_config(project_id)

    run = project_config['run']
    is_scheduled_task = 'schedule' in project_config

    work_directory = PROJECTS_ROOT / project_id
    service_type = 'oneshot' if is_scheduled_task else 'simple'
    restart = 'no' if is_scheduled_task else 'always'

    config = {
        "Unit": {},
        "Service": {
            "Type": service_type,
            "WorkingDirectory": work_directory,
            "ExecStart": run,
            "Restart": restart
        }
    }

    if not is_scheduled_task:
        config['Install'] = {
            "WantedBy": "multi-user.target"
        }

    write_systemd_config_to_file(config, f'{SYSTEMD_FILES_ROOT / project_id}.service')


def write_systemd_timer_config(project_id: str):
    project_config = madman_project_config(project_id)
    schedule = project_config['schedule']

    config = {
        "Unit": {},
        "Timer": {
            "OnCalendar": schedule,
            "Persistent": "true"
        },
        "Install": {
            "WantedBy": "timers.target"
        }
    }

    write_systemd_config_to_file(config, f'{SYSTEMD_FILES_ROOT / project_id}.timer')


def write_systemd_config_to_file(config: dict, path: str):
    with open(path, 'w') as file:
        for section_name, section in config.items():
            file.write(f"[{section_name}]\n")

            for key, value in section.items():
                file.write(f"{key}={value}\n")


def undeploy_timer_and_service(project_id):
    run_command_line(f"systemctl disable {project_id}.timer", check=False, no_logs=True)
    run_command_line(f"systemctl disable {project_id}.service", check=False, no_logs=True)
    run_command_line(f"systemctl stop {project_id}.timer", check=False, no_logs=True)
    run_command_line(f"systemctl stop {project_id}.service", check=False, no_logs=True)
    delete_file(SYSTEMD_FILES_ROOT / f"{project_id}.service")
    delete_file(SYSTEMD_FILES_ROOT / f"{project_id}.timer")


def run_command_line(command: str, cwd=Path.home(), check=True, no_logs=False) -> CompletedProcess[bytes]:
    return subprocess.run(command, check=check, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def delete_file(path):
    if os.path.exists(path):
        os.remove(path)


def run_ssh(user: str, host: str, command: str) -> int:
    target = f"{user}@{host}"
    print_info(f"Running on {target}: {command}")
    return run_command_line(f"ssh {target} {command}").returncode


# Print latest commit info
def show_latest(repo_path: Path) -> None:
    def git_cmd(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo_path, text=True).strip()

    branch = git_cmd("branch", "--show-current")
    commit = git_cmd("rev-parse", "--short", "HEAD")
    message = git_cmd("log", "-1", "--pretty=%s")
    print_info(f"branch: {branch}  |  commit: {commit}  |  message: {message}  |  path: {repo_path}")


# Server and client commands -------------------------------------------------------------------------------------------
# --------- Client -----------
def client_default(config: dict, server_command: str, args: List[str]) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    cmd = f"{command} {server_command} {' '.join(args)}"
    sys.exit(run_ssh(user, host, cmd))


def client_ssh(config: dict, server_command: str, args: List[str]) -> None:
    user, host, command = config["username"], config["host"], config['script_command']
    sys.exit(run_ssh(user, host, ''))


# --------- Server -----------
def server_clone(project_id: str, url: str) -> None:
    assert_project_not_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id
    repo_path.parent.mkdir(parents=True, exist_ok=True)

    print_info(f"Cloning {url} into {repo_path}")
    run_command_line(f"git clone --quiet {url} {str(repo_path)}")
    print_success('Clone successful')

    show_latest(repo_path)


def server_pull(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)

    git_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo_path, text=True).strip()
    print_info(f"Synchronizing to origin/{git_branch} …")
    run_command_line(f"git fetch --quiet origin", repo_path)
    run_command_line(f"git reset --quiet --hard origin/{git_branch}", repo_path)
    print_success('Pull successful')

    show_latest(repo_path)


def server_status(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)


def server_delete(project_id: str) -> None:
    assert_project_exists(project_id)
    repo_path = PROJECTS_ROOT / project_id

    show_latest(repo_path)

    try:
        shutil.rmtree(repo_path)
        print_success(f"Successfully deleted project")
    except Exception as e:
        print_error(f"Failed to delete directory {repo_path}: {e}")


def server_run(project_id: str) -> None:
    assert_project_exists(project_id)
    config = madman_project_config(project_id)
    repo_path = PROJECTS_ROOT / project_id

    run_command_line(config['run'], repo_path)


def server_deploy(project_id: str) -> None:
    assert_project_exists(project_id)
    config = madman_project_config(project_id)

    undeploy_timer_and_service(project_id)
    write_systemd_service_config(project_id)

    if 'schedule' in config:
        write_systemd_timer_config(project_id)
        run_command_line("systemctl daemon-reload")
        run_command_line(f"systemctl enable --now {project_id}.timer")
    else:
        run_command_line("systemctl daemon-reload")
        run_command_line(f"systemctl enable --now {project_id}.service")


def server_list() -> None:
    project_ids = [entry for entry in os.listdir(PROJECTS_ROOT) if os.path.isdir(os.path.join(PROJECTS_ROOT, entry))]

    for project_id in project_ids:
        print(project_id)


# ----------------------------------------------------------------------------------------------------------------------

def main() -> None:
    command_configs = [
        ("clone", client_default, server_clone),
        ("pull", client_default, server_pull),
        ("status", client_default, server_status),
        ("delete", client_default, server_delete),
        ("run", client_default, server_run),
        ("deploy", client_default, server_deploy),
        ("ssh", client_ssh, None),
        ("list", client_default, server_list)
    ]

    client_commands = [i[0] for i in command_configs]
    server_commands = [get_server_command(i) for i in client_commands]

    command, command_args = parse_args(client_commands + server_commands)

    for config in command_configs:
        client_command, client_function, server_function = config
        server_command = get_server_command(client_command)

        if command == client_command and client_function:
            validate_madman_client_config()
            client_function(madman_client_config(), server_command, command_args)
            return

        if command == server_command and server_function:
            server_function(*command_args)
            return

    print_error(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
