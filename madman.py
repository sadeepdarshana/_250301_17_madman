import os
import sys
import yaml
import subprocess
import argparse
from typing import Dict

RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"


def info(msg):
    print(f"{BLUE}[INFO]{RESET} {msg}")

def success(msg):
    print(f"{GREEN}[OK]{RESET} {msg}")

def warn(msg):
    print(f"{YELLOW}[WARN]{RESET} {msg}")

def error(msg):
    print(f"{RED}[ERROR]{RESET} {msg}", file=sys.stderr)

def load_yaml_config(path: str) -> Dict:
    if os.path.exists(path):
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def merge_configs(base: Dict, override: Dict) -> Dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result

def load_config_yaml() -> Dict:
    system_config_path = os.path.expanduser('~/madman.yaml')
    project_config_path = './madman.yaml'

    system_config = load_yaml_config(system_config_path)
    project_config = load_yaml_config(project_config_path)

    config = merge_configs(system_config, project_config)
    return config

def run_client_deploy():
    config = load_config_yaml()

    try:
        ssh_user = config['server']['ssh_user']
        host = config['server']['host']
        project = config['project']
        project_id = project['id']
        git_user = project['ssh_git_user']
        git_repo = project['ssh_git_repo']
        git_branch = project['ssh_git_branch']
    except KeyError as e:
        error(f"Missing required config field: {e}")
        sys.exit(1)

    ssh_target = f"{ssh_user}@{host}"
    remote_cmd = f"python3 ~/madman/madman.py deploy-server {project_id} {git_user} {git_repo} {git_branch}"
    full_cmd = ["ssh", ssh_target, remote_cmd]

    info(f"Running remote deployment on {ssh_target}...\n")
    try:
        result = subprocess.run(full_cmd)
        sys.exit(result.returncode)
    except Exception as e:
        error(f"Failed to run SSH command: {e}")
        sys.exit(1)

def run_server_deploy(args):
    if len(args) != 4:
        error("Usage: deploy-server <project_id> <ssh_git_user> <ssh_git_repo> <ssh_git_branch>")
        sys.exit(1)

    project_id, git_user, git_repo, git_branch = args
    home = os.path.expanduser("~")
    project_root = os.path.join(home, "madman", "projects")
    project_path = os.path.join(project_root, project_id)

    os.makedirs(project_root, exist_ok=True)

    if not os.path.exists(project_path):
        info(f"Cloning repository into {project_path}...")
        repo_url = f"{git_user}/{git_repo}.git"
        subprocess.run(["git", "clone", "-b", git_branch, repo_url, project_path], check=True)
        success("Clone completed.")
    else:
        git_dir = os.path.join(project_path, ".git")
        if not os.path.isdir(git_dir):
            error(f"{project_path} exists but is not a git repository.")
            sys.exit(1)

        # Sanity check 1: remote URL matches
        result = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=project_path, capture_output=True, text=True)
        expected_url = f"{git_user}/{git_repo}.git"
        if result.returncode != 0 or result.stdout.strip() != expected_url:
            error(f"Remote origin URL mismatch. Expected '{expected_url}', got '{result.stdout.strip()}'.")
            sys.exit(1)

        # Sanity check 2: branch exists on origin
        result = subprocess.run(["git", "show-ref", f"refs/remotes/origin/{git_branch}"], cwd=project_path)
        if result.returncode != 0:
            error(f"Branch 'origin/{git_branch}' not found.")
            sys.exit(1)

        info(f"Pulling latest changes in {project_path}...")
        subprocess.run(["git", "fetch", "origin"], cwd=project_path, check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{git_branch}"], cwd=project_path, check=True)
        success("Pull and reset completed.")

def run_server_status(args):
    if len(args) != 1:
        error("Usage: status-server <project_id>")
        sys.exit(1)

    project_id = args[0]
    project_path = os.path.join(os.path.expanduser("~"), "madman", "projects", project_id)
    if not os.path.isdir(project_path):
        error(f"Project '{project_id}' not found at {project_path}.")
        sys.exit(1)

    info(f"Status for project: {project_id}")
    subprocess.run(["git", "remote", "get-url", "origin"], cwd=project_path)
    subprocess.run(["git", "branch", "--show-current"], cwd=project_path)
    subprocess.run(["git", "log", "-1", "--oneline"], cwd=project_path)

def main():
    parser = argparse.ArgumentParser(description="Madman deployment tool")
    parser.add_argument("command", help="Command to run: deploy, deploy-server, or status-server")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()

    if parsed.command == "deploy":
        run_client_deploy()
    elif parsed.command == "deploy-server":
        run_server_deploy(parsed.args)
    elif parsed.command == "status-server":
        run_server_status(parsed.args)
    else:
        error(f"Unknown command: {parsed.command}")
        sys.exit(1)

if __name__ == '__main__':
    main()
