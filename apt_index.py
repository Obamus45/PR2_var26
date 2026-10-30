"""Получение прямых зависимостей из индексов Ubuntu APT без менеджера пакетов.

Поддерживаются обычный Packages index (plain/gzip/xz/bzip2) и URL каталога
конкретного suite, например .../dists/noble/. Для suite читается Release,
затем проверяются его component/binary-amd64 Packages indexes.
"""
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator
from urllib.parse import urlparse, urlunparse


class AptIndexError(RuntimeError):
    """Индекс недоступен или некорректен."""


class PackageNotFoundError(AptIndexError):
    """Индекс был прочитан, но в нём нет указанного имени пакета."""


@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str
    pre_depends: tuple[str, ...]
    depends: tuple[str, ...]


def _field_paragraphs(lines: Iterable[str]) -> Iterator[dict[str, str]]:
    fields: dict[str, str] = {}
    current: str | None = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if fields:
                yield fields
            fields, current = {}, None
        elif line[:1].isspace():
            if current is not None:
                fields[current] += " " + line.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            current = key
            fields[key] = value.strip()
    if fields:
        yield fields


def _dependency_groups(value: str) -> tuple[str, ...]:
    """Разделяет Depends по запятым, сохраняя альтернативы A | B одной группой."""
    groups: list[str] = []
    start = 0
    round_depth = square_depth = 0
    for i, char in enumerate(value):
        if char == "(":
            round_depth += 1
        elif char == ")":
            round_depth = max(0, round_depth - 1)
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        # Не считаем < и > скобками: в версиях Debian это операторы << и >>.
        elif char == "," and not (round_depth or square_depth):
            piece = value[start:i].strip()
            if piece:
                groups.append(piece)
            start = i + 1
    last = value[start:].strip()
    if last:
        groups.append(last)

    result: list[str] = []
    for group in groups:
        alternatives = []
        for alternative in group.split("|"):
            match = re.match(r"\s*([a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?)", alternative)
            if match:
                alternatives.append(match.group(1))
        if alternatives:
            result.append(" | ".join(alternatives))
    return tuple(result)


def _find_package(stream: Iterable[str], package_name: str) -> PackageInfo | None:
    for fields in _field_paragraphs(stream):
        if fields.get("Package") != package_name:
            continue
        return PackageInfo(
            name=package_name,
            version=fields.get("Version", "не указана"),
            pre_depends=_dependency_groups(fields.get("Pre-Depends", "")),
            depends=_dependency_groups(fields.get("Depends", "")),
        )
    return None


@lru_cache(maxsize=3)
def _package_map(url: str) -> dict[str, PackageInfo]:
    """Загружает и разбирает индекс один раз; пригодится при транзитивном обходе."""
    raw = _fetch(url)
    packages: dict[str, PackageInfo] = {}
    for fields in _field_paragraphs(_decoded_lines(raw, url)):
        name = fields.get("Package")
        if not name or name in packages:
            continue
        packages[name] = PackageInfo(
            name=name,
            version=fields.get("Version", "не указана"),
            pre_depends=_dependency_groups(fields.get("Pre-Depends", "")),
            depends=_dependency_groups(fields.get("Depends", "")),
        )
    return packages


def _decoded_lines(raw: bytes, source_name: str) -> Iterable[str]:
    # Определяем compression по сигнатуре, чтобы URL без расширения тоже работал.
    buffer = io.BytesIO(raw)
    try:
        if raw.startswith(b"\x1f\x8b") or source_name.endswith(".gz"):
            source: BinaryIO = gzip.GzipFile(fileobj=buffer)
        elif raw.startswith(b"\xfd7zXZ\x00") or source_name.endswith(".xz"):
            source = lzma.LZMAFile(buffer)
        elif raw.startswith(b"BZh") or source_name.endswith(".bz2"):
            source = bz2.BZ2File(buffer)
        else:
            source = buffer
        for line in source:
            yield line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
    except (OSError, EOFError, lzma.LZMAError) as exc:
        raise AptIndexError(f"Не удалось распаковать индекс {source_name}: {exc}") from exc


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "variant26-dependency-prototype/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AptIndexError(f"Не удалось получить {url}: {exc}") from exc


def _fetch_package_from_index(url: str, package_name: str) -> PackageInfo | None:
    return _package_map(url).get(package_name)


def _is_package_index(url: str) -> bool:
    leaf = urlparse(url).path.rsplit("/", 1)[-1]
    return leaf == "Packages" or leaf.startswith("Packages.")


def _suite_root(url: str) -> str | None:
    parsed = urlparse(url)
    match = re.search(r"/dists/[^/]+/?$", parsed.path)
    if not match:
        return None
    return urlunparse(parsed._replace(path=parsed.path.rstrip("/") + "/", params="", query="", fragment=""))


def _release_fields(release_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in release_text.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    return fields


def _try_suite_indexes(suite_root: str, package_name: str) -> PackageInfo:
    release_url = suite_root + "Release"
    release = _fetch(release_url).decode("utf-8", errors="replace")
    fields = _release_fields(release)
    components = fields.get("Components", "main universe restricted multiverse").split()
    architectures = fields.get("Architectures", "amd64").split()
    architecture = "amd64" if "amd64" in architectures else (architectures[0] if architectures else "amd64")

    failures: list[str] = []
    loaded_any_index = False
    for component in components:
        base = f"{suite_root}{component}/binary-{architecture}/Packages"
        for suffix in (".xz", ".gz", ".bz2", ""):
            url = base + suffix
            try:
                result = _fetch_package_from_index(url, package_name)
            except AptIndexError as exc:
                failures.append(str(exc))
                continue
            loaded_any_index = True
            if result is not None:
                return result
            break

    if not loaded_any_index:
        detail = "; ".join(failures[-3:])
        raise AptIndexError(f"Не удалось получить ни один Packages index для {suite_root}. {detail}")
    raise PackageNotFoundError(f"Пакет '{package_name}' не найден в компонентах suite: {', '.join(components)}")


def build_reverse_index(packages: Iterable[PackageInfo]) -> dict[str, tuple[str, ...]]:
    """Инвертирует прямые ребра: для каждого пакета перечисляет зависящие от него."""
    reverse: dict[str, list[str]] = {}
    for package in packages:
        reverse.setdefault(package.name, [])
        groups = (*package.pre_depends, *package.depends)
        for group in groups:
            for alternative in group.split("|"):
                dependency = alternative.strip()
                if dependency:
                    dependents = reverse.setdefault(dependency, [])
                    if package.name not in dependents:
                        dependents.append(package.name)
    return {name: tuple(dependents) for name, dependents in reverse.items()}


def get_reverse_dependencies_from_url(repository_url: str, package_name: str) -> dict[str, tuple[str, ...]]:
    """Читает индексы APT и возвращает обратный список смежности для всех их пакетов."""
    if _is_package_index(repository_url):
        package_maps = [_package_map(repository_url)]
    else:
        suite_root = _suite_root(repository_url)
        if not suite_root:
            raise AptIndexError(
                "Для обратных зависимостей укажите Packages index или URL suite вида .../dists/noble/"
            )
        release = _fetch(suite_root + "Release").decode("utf-8", errors="replace")
        fields = _release_fields(release)
        components = fields.get("Components", "main universe restricted multiverse").split()
        architectures = fields.get("Architectures", "amd64").split()
        architecture = "amd64" if "amd64" in architectures else (architectures[0] if architectures else "amd64")
        package_maps = []
        errors: list[str] = []
        for component in components:
            base = f"{suite_root}{component}/binary-{architecture}/Packages"
            for suffix in (".xz", ".gz", ".bz2", ""):
                try:
                    package_map = _package_map(base + suffix)
                except AptIndexError as exc:
                    errors.append(str(exc))
                    continue
                package_maps.append(package_map)
                break
        if not package_maps:
            raise AptIndexError(
                f"Не удалось получить индексы компонентов suite {suite_root}: " + "; ".join(errors[-3:])
            )

    packages: dict[str, PackageInfo] = {}
    for package_map in package_maps:
        for name, info in package_map.items():
            packages.setdefault(name, info)
    reverse = build_reverse_index(packages.values())
    if package_name not in reverse:
        raise PackageNotFoundError(f"Пакет '{package_name}' не найден в доступных APT-индексах")
    return reverse


def get_package_from_url(repository_url: str, package_name: str) -> PackageInfo:
    """Ищет пакет в прямом Packages index или в URL каталога .../dists/<suite>/."""
    if _is_package_index(repository_url):
        result = _fetch_package_from_index(repository_url, package_name)
        if result is None:
            raise PackageNotFoundError(f"Пакет '{package_name}' не найден в индексе {repository_url}")
        return result

    suite_root = _suite_root(repository_url)
    if suite_root:
        try:
            return _try_suite_indexes(suite_root, package_name)
        except AptIndexError:
            raise
        except (UnicodeError, OSError) as exc:
            raise AptIndexError(f"Не удалось прочитать метаданные suite {suite_root}: {exc}") from exc

    raise AptIndexError(
        "URL должен указывать на файл Packages (например, Packages.gz) "
        "или на каталог конкретного Ubuntu suite вида .../dists/noble/; "
        "URL корня зеркала не задаёт выпуск Ubuntu и компонент."
    )


def get_package_from_file(index_path: Path, package_name: str) -> PackageInfo:
    """Читает локальный Packages-файл (тестовый режим), plain или сжатый."""
    try:
        raw = index_path.read_bytes()
    except OSError as exc:
        raise AptIndexError(f"Не удалось прочитать тестовый APT-индекс {index_path}: {exc}") from exc
    result = _find_package(_decoded_lines(raw, str(index_path)), package_name)
    if result is None:
        raise PackageNotFoundError(f"Пакет '{package_name}' не найден в тестовом APT-индексе {index_path}")
    return result
