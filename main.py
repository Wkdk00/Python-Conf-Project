import sys
import os
import toml
import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Tuple, Set

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


def fetch_package_remote(package_name: str, version: str) -> Dict[str, Any]:
    url = f"https://registry.npmjs.org/{package_name}/{version}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP ошибка для {package_name}@{version}: {e}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Сетевая ошибка для {package_name}@{version}: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Некорректный JSON для {package_name}@{version}: {e}")
    except Exception as e:
        raise RuntimeError(f"Неизвестная ошибка при загрузке {package_name}@{version}: {e}")


def fetch_package_local(local_repo_path: str, package_name: str, version: str) -> Dict[str, Any]:
    if not os.path.isfile(local_repo_path):
        raise RuntimeError(f"Локальный файл репозитория не найден: {local_repo_path}")
    try:
        with open(local_repo_path, "r", encoding="utf-8") as f:
            repo_data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Ошибка чтения локального репозитория: {e}")

    key = f"{package_name}@{version}"
    if key not in repo_data:
        raise RuntimeError(f"Пакет {key} отсутствует в локальном репозитории")
    return repo_data[key]


def get_dependencies(pkg_data: Dict[str, Any]) -> Dict[str, str]:
    return pkg_data.get("dependencies", {})


def build_dependency_graph(
    config: Dict[str, Any]
) -> Dict[str, List[Tuple[str, str]]]:
    mode = config["repo_mode"]
    start_name = config["package_name"]
    start_version = config["package_version"]
    max_depth = config["max_depth"]

    # Словарь для хранения графа: узел -> список (зависимость, версия)
    graph: Dict[str, List[Tuple[str, str]]] = {}
    # Стек для DFS: (package_name, version, depth, path)
    stack: List[Tuple[str, str, int, List[str]]] = [(start_name, start_version, 0, [start_name])]
    visited_global: Set[str] = set()  # для избежания повторной загрузки одного и того же узла

    def node_key(name: str, version: str) -> str:
        return f"{name}@{version}"

    while stack:
        name, version, depth, path = stack.pop()
        current_key = node_key(name, version)

        # Пропускаем, если уже обработали этот узел на этой или меньшей глубине
        if current_key in visited_global:
            continue
        visited_global.add(current_key)

        # Загружаем метаданные пакета
        try:
            if mode == "remote":
                pkg_data = fetch_package_remote(name, version)
            else:  # local
                pkg_data = fetch_package_local(config["repository_url"], name, version)
        except RuntimeError as e:
            print(f"Предупреждение: пропущен пакет {current_key}: {e}", file=sys.stderr)
            continue

        deps = get_dependencies(pkg_data)
        graph[current_key] = [(dep_name, dep_version) for dep_name, dep_version in deps.items()]

        # Если достигли макс. глубины — не добавляем зависимости в стек
        if depth >= max_depth:
            continue

        # Проверяем циклы и добавляем в стек
        for dep_name, dep_version in deps.items():
            if dep_name in path:
                # Цикл обнаружен — пропускаем
                print(f"Циклическая зависимость обнаружена и пропущена: {' → '.join(path + [dep_name])}", file=sys.stderr)
                continue
            stack.append((dep_name, dep_version, depth + 1, path + [dep_name]))

    return graph


def print_graph(graph: Dict[str, List[Tuple[str, str]]]) -> None:
    if not graph:
        print("Граф зависимостей пуст.")
        return
    print("Граф зависимостей:")
    for node, deps in graph.items():
        if deps:
            print(f"{node} -> " + ", ".join(f"{n}@{v}" for n, v in deps))
        else:
            print(f"{node} -> (нет зависимостей)")


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

    try:
        graph = build_dependency_graph(config)
        print_graph(graph)
    except Exception as e:
        print(f"Критическая ошибка при построении графа: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()