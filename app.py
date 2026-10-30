#!/usr/bin/env python3
"""Вариант 26: YAML CLI, Ubuntu APT и транзитивный граф зависимостей (этап 3)."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apt_index import (
    AptIndexError,
    PackageInfo,
    PackageNotFoundError,
    get_package_from_file,
    get_package_from_url,
)
from dependency_graph import (
    DependencyGraph,
    GraphError,
    build_bfs_recursive,
    flatten_apt_dependencies,
    parse_test_repository,
)

try:
    import yaml
except ImportError:  # Даём понятную ошибку, если зависимости проекта не установлены.
    yaml = None


EXPECTED_KEYS = {
    "package_name",
    "repository",
    "test_mode",
    "output_file",
    "ascii_tree",
    "filter_substring",
}


class ConfigError(ValueError):
    """Ошибка чтения, структуры или значения конфигурации."""


@dataclass(frozen=True)
class Config:
    package_name: str
    repository: str
    test_mode: bool
    output_file: str
    ascii_tree: bool
    filter_substring: str


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"'{key}': требуется строка")
    value = value.strip()
    if not value:
        raise ConfigError(f"'{key}': значение не должно быть пустым")
    return value


def _required_bool(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if type(value) is not bool:
        raise ConfigError(f"'{key}': требуется логическое значение true или false")
    return value


def load_config(path: Path) -> Config:
    if yaml is None:
        raise ConfigError("Не найден PyYAML. Установите зависимости: python -m pip install -r requirements.txt")
    if not path.exists():
        raise ConfigError(f"Файл конфигурации не найден: {path}")
    if not path.is_file():
        raise ConfigError(f"Путь конфигурации не является файлом: {path}")
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Не удалось прочитать конфигурацию: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Некорректный YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Корнем YAML-документа должен быть объект (набор ключей и значений)")
    unknown = sorted(set(data) - EXPECTED_KEYS)
    missing = sorted(EXPECTED_KEYS - set(data))
    if unknown:
        raise ConfigError("Неизвестные параметры: " + ", ".join(map(str, unknown)))
    if missing:
        raise ConfigError("Не заданы обязательные параметры: " + ", ".join(missing))

    package_name = _required_string(data, "package_name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", package_name):
        raise ConfigError("'package_name': допустимы латинские буквы, цифры, '.', '+', '_' и '-'; первый символ — буква или цифра")

    repository = _required_string(data, "repository")
    test_mode = _required_bool(data, "test_mode")
    if test_mode:
        repo_path = Path(repository).expanduser()
        if not repo_path.is_absolute():
            repo_path = path.expanduser().resolve().parent / repo_path
        if not repo_path.is_file():
            raise ConfigError(f"'repository': в тестовом режиме укажите существующий файл; не найден: {repo_path}")
    else:
        parsed = urlparse(repository)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError("'repository': в обычном режиме требуется корректный URL с http:// или https://")

    output_file = _required_string(data, "output_file")
    if Path(output_file).name != output_file or output_file in {".", ".."}:
        raise ConfigError("'output_file': укажите только имя файла, без пути к каталогу")
    if not output_file.lower().endswith(".svg"):
        raise ConfigError("'output_file': имя файла должно иметь расширение .svg")

    ascii_tree = _required_bool(data, "ascii_tree")
    filter_substring = data.get("filter_substring")
    if not isinstance(filter_substring, str):
        raise ConfigError("'filter_substring': требуется строка (пустая строка отключает фильтрацию)")

    return Config(package_name, repository, test_mode, output_file, ascii_tree, filter_substring)


def print_config(config: Config) -> None:
    """Печатает все пользовательские настройки в формате ключ-значение."""
    print(f"package_name: {config.package_name}")
    print(f"repository: {config.repository}")
    print(f"test_mode: {str(config.test_mode).lower()}")
    print(f"output_file: {config.output_file}")
    print(f"ascii_tree: {str(config.ascii_tree).lower()}")
    print(f"filter_substring: {config.filter_substring!r}")


def print_direct_dependencies(package_name: str, dependencies: tuple[str, ...]) -> None:
    print(f"\nПрямые зависимости для пакета {package_name}:")
    if dependencies:
        for dependency in dependencies:
            print(f"  - {dependency}")
    else:
        print("  (нет)")


def print_graph(graph: DependencyGraph) -> None:
    print("\nТранзитивный граф зависимостей (список смежности):")
    for package in graph.bfs_order:
        dependencies = graph.edges[package]
        print(f"  {package} -> {', '.join(dependencies) if dependencies else '(нет зависимостей)'}")
    print("BFS order: " + " -> ".join(graph.bfs_order))


def _build_test_graph(config: Config, config_path: Path) -> tuple[DependencyGraph, tuple[str, ...]]:
    repository_path = Path(config.repository).expanduser()
    if not repository_path.is_absolute():
        repository_path = config_path.resolve().parent / repository_path
    adjacency = parse_test_repository(repository_path)
    if config.package_name not in adjacency:
        raise GraphError(f"Корневой пакет '{config.package_name}' отсутствует в тестовом графе")
    graph = build_bfs_recursive(
        config.package_name,
        lambda package: adjacency.get(package, ()),
        config.filter_substring,
    )
    return graph, graph.edges[config.package_name]


def _build_apt_graph(config: Config) -> tuple[DependencyGraph, tuple[str, ...], tuple[str, ...]]:
    # Проверяем корень отдельно: если его нет, это ошибка конфигурации/выбора пакета,
    # а не обычный неразрешённый виртуальный пакет на одном из нижних уровней.
    root_info = get_package_from_url(config.repository, config.package_name)
    info_cache: dict[str, PackageInfo] = {config.package_name: root_info}
    unresolved: list[str] = []

    def dependencies_for(package_name: str) -> tuple[str, ...]:
        if package_name not in info_cache:
            try:
                info_cache[package_name] = get_package_from_url(config.repository, package_name)
            except PackageNotFoundError:
                # APT может задавать виртуальную зависимость через Provides; без
                # выбора provider оставляем её узлом-листом, а не прерываем обход.
                unresolved.append(package_name)
                return ()
        info = info_cache[package_name]
        return flatten_apt_dependencies(info.pre_depends, info.depends)

    graph = build_bfs_recursive(config.package_name, dependencies_for, config.filter_substring)
    return graph, graph.edges[config.package_name], tuple(dict.fromkeys(unresolved))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Вариант 26: построение графа зависимостей Ubuntu APT")
    parser.add_argument("-c", "--config", default="config.yaml", help="путь к YAML-конфигурации (по умолчанию config.yaml)")
    args = parser.parse_args(argv)
    config_path = Path(args.config).expanduser()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    print_config(config)
    try:
        if config.test_mode:
            graph, direct = _build_test_graph(config, config_path)
            unresolved: tuple[str, ...] = ()
        else:
            graph, direct, unresolved = _build_apt_graph(config)
    except (AptIndexError, GraphError) as exc:
        print(f"Ошибка построения графа: {exc}", file=sys.stderr)
        return 1

    print_direct_dependencies(config.package_name, direct)
    print_graph(graph)
    if unresolved:
        print("\nУзлы без метаданных в выбранном репозитории (возможные виртуальные пакеты): " + ", ".join(unresolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
