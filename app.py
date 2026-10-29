#!/usr/bin/env python3
"""Вариант 26, этап 1: чтение и проверка YAML-конфигурации CLI-прототипа."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Минимальный CLI-прототип (вариант 26, этап 1)")
    parser.add_argument("-c", "--config", default="config.yaml", help="путь к YAML-конфигурации (по умолчанию config.yaml)")
    args = parser.parse_args(argv)
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2
    print_config(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
