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
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator
from urllib.parse import urlparse, urlunparse


class AptIndexError(RuntimeError):
    """Индекс недоступен, некорректен или не содержит целевой пакет."""


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
    raw = _fetch(url)
    return _find_package(_decoded_lines(raw, url), package_name)


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
    raise AptIndexError(f"Пакет '{package_name}' не найден в компонентах suite: {', '.join(components)}")


def get_package_from_url(repository_url: str, package_name: str) -> PackageInfo:
    """Ищет пакет в прямом Packages index или в URL каталога .../dists/<suite>/."""
    if _is_package_index(repository_url):
        result = _fetch_package_from_index(repository_url, package_name)
        if result is None:
            raise AptIndexError(f"Пакет '{package_name}' не найден в индексе {repository_url}")
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
        raise AptIndexError(f"Пакет '{package_name}' не найден в тестовом APT-индексе {index_path}")
    return result
