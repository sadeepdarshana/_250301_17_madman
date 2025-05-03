"""Madman – Git pull/deploy helper (client + server)"""

import argparse
import os
import re
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


def fail(message: str) -> None:
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
        fail(f"Project with ID '{project_id}' not found on server")


def assert_project_not_exists(project_id: str):
    repo_path = PROJECTS_ROOT / project_id
    if repo_path.exists():
        fail(f"Project with ID '{project_id}' already exists on server")


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


def get_systemd_id(project_id, config_name):
    return f"{project_id}_{config_name}"


def madman_project_config(project_id, config_name) -> Any | None:
    print_info("Reading project config file")
    try:
        project_config = json.loads((PROJECTS_ROOT / project_id / MADMAN_PROJECT_CONFIG_FILENAME).read_text())
    except:
        fail("Failed to read and parse project file")

    try:
        config = project_config[config_name]
    except:
        fail(f"Config '{config_name}' not found in the project config")
    return config


def validate_madman_client_config() -> None:
    if not MADMAN_CLIENT_CONFIG.exists():
        fail(f"Madman client config not found at {MADMAN_CLIENT_CONFIG}")

    config = madman_client_config()

    if not config:
        fail(f"Madman client config ({MADMAN_CLIENT_CONFIG}) parsing error")

    if not get(config, "host") or not get(config, "username"):
        fail(f"host or username not found in Madman client config ({MADMAN_CLIENT_CONFIG})")


def write_systemd_service_config(project_id: str, config_name: str):
    project_config = madman_project_config(project_id, config_name)

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

    write_systemd_config_to_file(config, f'{SYSTEMD_FILES_ROOT / get_systemd_id(project_id, config_name)}.service')


def write_systemd_timer_config(project_id: str, config_name: str):
    project_config = madman_project_config(project_id, config_name)
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

    write_systemd_config_to_file(config, f'{SYSTEMD_FILES_ROOT / get_systemd_id(project_id, config_name)}.timer')


def convert_git_url(url: str) -> str | None:
    # Convert HTTPS → SSH
    https_pattern = re.compile(r'https://([^/]+)/([^/]+)/(.+?)(\.git)?$')
    match = https_pattern.match(url)
    if match:
        domain, user, repo, _ = match.groups()
        return f'git@{domain}:{user}/{repo}.git'

    # Convert SSH → HTTPS
    ssh_pattern = re.compile(r'git@([^:]+):([^/]+)/(.+?)(\.git)?$')
    match = ssh_pattern.match(url)
    if match:
        domain, user, repo, _ = match.groups()
        return f'https://{domain}/{user}/{repo}.git'

    fail("Invalid git repo URL")


def get_git_remote_url():
    try:
        result = subprocess.run(
            "git remote get-url origin",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
            shell=True
        )
        return result.stdout.strip()
    except:
        fail("Could find git remote url")


def write_systemd_config_to_file(config: dict, path: str):
    with open(path, 'w') as file:
        for section_name, section in config.items():
            file.write(f"[{section_name}]\n")

            for key, value in section.items():
                file.write(f"{key}={value}\n")


def undeploy_timer_and_service(project_id, config_name):
    run_command_line(f"systemctl disable {get_systemd_id(project_id, config_name)}.timer", check=False, no_logs=True)
    run_command_line(f"systemctl disable {get_systemd_id(project_id, config_name)}.service", check=False, no_logs=True)
    run_command_line(f"systemctl stop {get_systemd_id(project_id, config_name)}.timer", check=False, no_logs=True)
    run_command_line(f"systemctl stop {get_systemd_id(project_id, config_name)}.service", check=False, no_logs=True)
    delete_file(SYSTEMD_FILES_ROOT / f"{get_systemd_id(project_id, config_name)}.service")
    delete_file(SYSTEMD_FILES_ROOT / f"{get_systemd_id(project_id, config_name)}.timer")


def run_command_line(command: str, cwd=Path.home(), check=True, no_logs=False) -> CompletedProcess[bytes]:
    return subprocess.run(command, check=check, shell=True, cwd=cwd, stdout=subprocess.DEVNULL if no_logs else None,
                          stderr=subprocess.DEVNULL if no_logs else None)


def delete_file(path):
    if os.path.exists(path):
        os.remove(path)


def run_ssh(user: str, host: str, command: str) -> int:
    target = f"{user}@{host}"
    print_info(f"Running on {target}: {command}")
    return run_command_line(f"ssh {target} {command}", check=False).returncode


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


def client_clone(config: dict, server_command: str, args: List[str]) -> None:
    user, host, command = config["username"], config["host"], config['script_command']

    if args[1] == 'this':
        args[1] = get_git_remote_url()
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
    try:
        run_command_line(f"git clone --quiet {url} {str(repo_path)}")
    except:
        print_error(f"Failed to clone {url}.")
        url = convert_git_url(url)
        print_info(f"Trying to clone {url}.")
        run_command_line(f"git clone --quiet {url} {str(repo_path)}")
    print_success(f'Successful cloned {url}')

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
        fail(f"Failed to delete directory {repo_path}: {e}")


def server_run(project_id: str, config_name: str) -> None:
    assert_project_exists(project_id)
    config = madman_project_config(project_id, config_name)
    repo_path = PROJECTS_ROOT / project_id

    run_command_line(config['run'], repo_path)


def server_deploy(project_id: str, config_name: str) -> None:
    assert_project_exists(project_id)
    config = madman_project_config(project_id, config_name)

    undeploy_timer_and_service(project_id, config_name)
    write_systemd_service_config(project_id, config_name)

    if 'schedule' in config:
        write_systemd_timer_config(project_id, config_name)
        run_command_line("systemctl daemon-reload")
        run_command_line(f"systemctl enable --now {get_systemd_id(project_id, config_name)}.timer")
    else:
        run_command_line("systemctl daemon-reload")
        run_command_line(f"systemctl enable --now {get_systemd_id(project_id, config_name)}.service")


def server_undeploy(project_id: str, config_name: str) -> None:
    undeploy_timer_and_service(project_id, config_name)
    print_info(f"All deployments removed for {project_id} {config_name}")


def server_list() -> None:
    project_ids = [entry for entry in os.listdir(PROJECTS_ROOT) if os.path.isdir(os.path.join(PROJECTS_ROOT, entry))]

    for project_id in project_ids:
        print(project_id)


# ----------------------------------------------------------------------------------------------------------------------

def main() -> None:
    command_configs = [
        ("clone", client_clone, server_clone),
        ("pull", client_default, server_pull),
        ("status", client_default, server_status),
        ("delete", client_default, server_delete),
        ("run", client_default, server_run),
        ("deploy", client_default, server_deploy),
        ("undeploy", client_default, server_undeploy),
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

    fail(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
