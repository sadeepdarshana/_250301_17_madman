import os
import yaml
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

    # Merge with precedence: system < project
    config = merge_configs(system_config, project_config)

    return config

# Example usage
if __name__ == '__main__':
    madman_config = load_config_yaml()
    print("Effective config:")
    print(madman_config)
