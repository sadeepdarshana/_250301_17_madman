import os
import sys
import yaml
import subprocess
import argparse
from typing import Dict

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
        print(f"Missing required config field: {e}", file=sys.stderr)
        sys.exit(1)

    ssh_target = f"{ssh_user}@{host}"
    remote_cmd = f"python3 ~/madman/madman.py deploy-server {project_id} {git_user} {git_repo} {git_branch}"
    full_cmd = ["ssh", ssh_target, remote_cmd]

    print(f"Running remote deployment on {ssh_target}...\n")
    try:
        result = subprocess.run(full_cmd)
        sys.exit(result.returncode)
    except Exception as e:
        print(f"Failed to run SSH command: {e}", file=sys.stderr)
        sys.exit(1)

def run_server_deploy(args):
    if len(args) != 4:
        print("Usage: deploy-server <project_id> <ssh_git_user> <ssh_git_repo> <ssh_git_branch>", file=sys.stderr)
        sys.exit(1)

    project_id, git_user, git_repo, git_branch = args
    home = os.path.expanduser("~")
    project_root = os.path.join(home, "madman", "projects")
    project_path = os.path.join(project_root, project_id)

    os.makedirs(project_root, exist_ok=True)

    if not os.path.exists(project_path):
        print(f"Cloning repository into {project_path}...")
        repo_url = f"{git_user}/{git_repo}.git"
        subprocess.run(["git", "clone", "-b", git_branch, repo_url, project_path], check=True)
    else:
        git_dir = os.path.join(project_path, ".git")
        if not os.path.isdir(git_dir):
            print(f"Error: {project_path} exists but is not a git repository.", file=sys.stderr)
            sys.exit(1)

        print(f"Pulling latest changes in {project_path}...")
        subprocess.run(["git", "fetch", "origin"], cwd=project_path, check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{git_branch}"], cwd=project_path, check=True)

def main():
    parser = argparse.ArgumentParser(description="Madman deployment tool")
    parser.add_argument("command", help="Command to run: deploy or deploy-server")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()

    if parsed.command == "deploy":
        run_client_deploy()
    elif parsed.command == "deploy-server":
        run_server_deploy(parsed.args)
    else:
        print(f"Unknown command: {parsed.command}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
