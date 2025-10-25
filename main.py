import sys
import os
import toml
from typing import Any, Dict

REQUIRED_PARAMS = {
    "package_name": str,
    "repository_url": str,
    "repo_mode": str,
    "package_version": str,
    "max_depth": int,
}

ALLOWED_REPO_MODES = {"local", "remote"}

def validate_config(config: Dict[str, Any]) -> None:
    missing = []
    for key, expected_type in REQUIRED_PARAMS.items():
        if key not in config:
            missing.append(key)
        elif not isinstance(config[key], expected_type):
            raise TypeError(f"Параметр '{key}' должен быть типа {expected_type.__name__}, "
                            f"получен {type(config[key]).__name__}")
    if missing:
        raise KeyError(f"Отсутствуют обязательные параметры: {', '.join(missing)}")

    mode = config["repo_mode"]
    if mode not in ALLOWED_REPO_MODES:
        raise ValueError(f"Недопустимое значение repo_mode: '{mode}'. "
                         f"Допустимые значения: {', '.join(ALLOWED_REPO_MODES)}")

    if config["max_depth"] < 0:
        raise ValueError("max_depth не может быть отрицательным")

def main():
    if len(sys.argv) != 2:
        print("Использование: python depviz.py <путь_к_config.toml>", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]

    if not os.path.isfile(config_path):
        print(f"Ошибка: файл конфигурации не найден: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = toml.load(f)
    except toml.TomlDecodeError as e:
        print(f"Ошибка разбора TOML: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Ошибка чтения файла: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        validate_config(config)
    except (KeyError, TypeError, ValueError) as e:
        print(f"Ошибка в конфигурации: {e}", file=sys.stderr)
        sys.exit(1)

    for key in REQUIRED_PARAMS:
        print(f"{key} = {config[key]}")

if __name__ == "__main__":
    main()