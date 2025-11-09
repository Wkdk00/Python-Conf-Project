import sys
import os
import toml
import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Tuple

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


def build_dependency_graph(config: Dict[str, Any]) -> Dict[str, List[Tuple[str, str]]]:
    mode = config["repo_mode"]
    start_name = config["package_name"]
    start_version = config["package_version"]
    max_depth = config["max_depth"]
    repo_path = config["repository_url"]

    graph: Dict[str, List[Tuple[str, str]]] = {}
    stack: List[Tuple[str, str, int, List[str]]] = [(start_name, start_version, 0, [start_name])]
    visited_global: set = set()

    def node_key(name: str, version: str) -> str:
        return f"{name}@{version}"

    while stack:
        name, version, depth, path = stack.pop()
        current_key = node_key(name, version)

        if current_key in visited_global:
            continue
        visited_global.add(current_key)

        try:
            if mode == "remote":
                pkg_data = fetch_package_remote(name, version)
            else:
                pkg_data = fetch_package_local(repo_path, name, version)
        except RuntimeError as e:
            print(f"Пропущен пакет {current_key}: {e}", file=sys.stderr)
            continue

        deps = get_dependencies(pkg_data)
        graph[current_key] = [(dep_name, dep_version) for dep_name, dep_version in deps.items()]

        if depth >= max_depth:
            continue

        for dep_name, dep_version in deps.items():
            if dep_name in path:
                print(f"Цикл обнаружен и пропущен: {' → '.join(path + [dep_name])}", file=sys.stderr)
                continue
            stack.append((dep_name, dep_version, depth + 1, path + [dep_name]))

    return graph


def print_graph(graph: Dict[str, List[Tuple[str, str]]]) -> None:
    if not graph:
        print("Граф зависимостей пуст.")
        return
    print("Граф зависимостей:")
    for node in sorted(graph.keys()):
        deps = graph[node]
        if deps:
            dep_str = ", ".join(f"{n}@{v}" for n, v in deps)
            print(f"{node} -> {dep_str}")
        else:
            print(f"{node} -> (нет зависимостей)")


def invert_graph(graph: Dict[str, List[Tuple[str, str]]]) -> Dict[str, List[str]]:
    inv: Dict[str, List[str]] = {}
    for pkg, deps in graph.items():
        for dep_name, dep_ver in deps:
            dep_key = f"{dep_name}@{dep_ver}"
            inv.setdefault(dep_key, []).append(pkg)
    return inv


def print_reverse_deps(graph: Dict[str, List[Tuple[str, str]]], target: str) -> None:
    inv = invert_graph(graph)
    if target in inv:
        print(f"\nОбратные зависимости для {target}:")
        for depender in sorted(inv[target]):
            print(f"  ← {depender}")
    else:
        print(f"\nОбратные зависимости для {target} не найдены.")


def main():
    if len(sys.argv) != 3:
        print("Использование: python depviz.py <путь_к_config.toml> <целевой_пакет_для_обратных_зависимостей>", file=sys.stderr)
        print("Пример целевого пакета: lodash@4.17.21 или D@1.0")
        sys.exit(1)

    config_path = sys.argv[1]
    target_reverse = sys.argv[2]

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
        print_reverse_deps(graph, target_reverse)
    except Exception as e:
        print(f"Критическая ошибка при построении графа: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()