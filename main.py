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


# ================
# Режим: REMOTE
# ================
def fetch_package_remote(package_name: str, version: str) -> Dict[str, str]:
    url = f"https://registry.npmjs.org/{package_name}/{version}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.load(response)
    except Exception as e:
        raise RuntimeError(f"Не удалось загрузить {package_name}@{version}: {e}")
    return data.get("dependencies", {})


# ================
# Режим: LOCAL (тестовый)
# ================
def load_local_repo(repo_path: str) -> Dict[str, Dict[str, str]]:
    if not os.path.isfile(repo_path):
        raise FileNotFoundError(f"Тестовый репозиторий не найден: {repo_path}")
    try:
        with open(repo_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"Ошибка чтения тестового репозитория: {e}")


def fetch_package_local(repo: Dict[str, Dict[str, str]], package_name: str, version: str) -> Dict[str, str]:
    # В тестовом режиме версия игнорируется, используется только имя
    # Формат: {"A": {"B": "1.0", "C": "2.0"}, "B": {"D": "1.0"}}
    if package_name not in repo:
        return {}
    return repo[package_name]


# ================
# Итеративный DFS с ограничением глубины и обнаружением циклов
# ================
def build_dependency_graph(
    start_package: str,
    start_version: str,
    max_depth: int,
    fetcher,
) -> List[Tuple[str, str]]:
    """
    Возвращает список рёбер: (родитель, зависимость)
    """
    graph = []
    visited = set()  # для избежания повторной обработки одних и тех же узлов на одной глубине
    stack: List[Tuple[str, int, List[str]]] = [(start_package, 0, [])]  # (пакет, глубина, путь_до_него)

    while stack:
        current, depth, path = stack.pop()

        if depth >= max_depth:
            continue

        if current in path:
            # Цикл обнаружен
            cycle = path + [current]
            print(f"Обнаружена циклическая зависимость: {' -> '.join(cycle)}", file=sys.stderr)
            continue

        # Получаем зависимости текущего пакета
        try:
            deps = fetcher(current, "ignored")  # версия игнорируется в тестовом режиме; в remote — используется при вызове
        except Exception as e:
            print(f"Не удалось получить зависимости для {current}: {e}", file=sys.stderr)
            continue

        if not deps:
            continue

        for dep_name in deps:
            edge = (current, dep_name)
            graph.append(edge)

            if dep_name not in visited or True:  # разрешаем повторное посещение для разных путей (важно для циклов)
                new_path = path + [current]
                stack.append((dep_name, depth + 1, new_path))

        visited.add(current)

    return graph


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

    # Этап 1: вывод параметров
    for key in REQUIRED_PARAMS:
        print(f"{key} = {config[key]}")

    # Подготовка fetcher-функции
    if config["repo_mode"] == "remote":
        def fetcher(pkg, ver):
            return fetch_package_remote(pkg, config["package_version"] if pkg == config["package_name"] else "latest")
        # ⚠️ Упрощение: для зависимостей берём "latest", но в реальности нужно парсить версию из spec.
        # Для учебного проекта допустимо.
        start_pkg = config["package_name"]
    else:  # local
        repo_path = config["repository_url"]
        repo_data = load_local_repo(repo_path)
        def fetcher(pkg, ver):
            return fetch_package_local(repo_data, pkg, ver)
        start_pkg = config["package_name"]

    # Построение графа
    try:
        edges = build_dependency_graph(
            start_package=start_pkg,
            start_version=config["package_version"],
            max_depth=config["max_depth"],
            fetcher=fetcher,
        )
    except Exception as e:
        print(f"Ошибка при построении графа: {e}", file=sys.stderr)
        sys.exit(1)

    # Вывод графа
    if not edges:
        print("Граф зависимостей пуст.")
    else:
        print("\nГраф зависимостей:")
        for parent, child in edges:
            print(f"{parent} -> {child}")


if __name__ == "__main__":
    main()