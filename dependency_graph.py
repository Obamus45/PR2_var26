"""Построение графа зависимостей обходом BFS с рекурсивной обработкой очереди."""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


class GraphError(ValueError):
    """Ошибка формата тестового графа или его входных параметров."""


@dataclass(frozen=True)
class DependencyGraph:
    root: str
    edges: dict[str, tuple[str, ...]]
    bfs_order: tuple[str, ...]


def parse_test_repository(path: Path) -> dict[str, tuple[str, ...]]:
    """Читает простое описание графа: PACKAGE: DEP1, DEP2; имена — A-Z."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise GraphError(f"Не удалось прочитать тестовый граф {path}: {exc}") from exc

    graph: dict[str, tuple[str, ...]] = {}
    for line_number, original in enumerate(lines, 1):
        line = original.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Z]+)\s*:\s*(.*)", line)
        if not match:
            raise GraphError(
                f"Строка {line_number}: ожидается формат 'A: B, C' "
                "(имена пакетов — большие латинские буквы)"
            )
        package, raw_dependencies = match.groups()
        if package in graph:
            raise GraphError(f"Строка {line_number}: пакет '{package}' указан повторно")
        dependencies: list[str] = []
        if raw_dependencies.strip():
            for raw_dependency in raw_dependencies.split(","):
                dependency = raw_dependency.strip()
                if not re.fullmatch(r"[A-Z]+", dependency):
                    raise GraphError(f"Строка {line_number}: некорректное имя зависимости '{dependency}'")
                if dependency not in dependencies:
                    dependencies.append(dependency)
        graph[package] = tuple(dependencies)

    # Неописанные справа пакеты считаются узлами без собственных зависимостей.
    for dependencies in tuple(graph.values()):
        for dependency in dependencies:
            graph.setdefault(dependency, ())
    if not graph:
        raise GraphError("Файл тестового графа не содержит ни одной записи")
    return graph


def build_bfs_recursive(
    root: str,
    get_dependencies: Callable[[str], Iterable[str]],
    filter_substring: str = "",
) -> DependencyGraph:
    """Строит граф BFS; очередь обрабатывается рекурсивно, циклы подавляются visited."""
    if filter_substring and filter_substring in root:
        raise GraphError(
            f"Корневой пакет '{root}' исключён фильтром '{filter_substring}'"
        )

    queue: deque[str] = deque([root])
    visited = {root}
    edges: dict[str, tuple[str, ...]] = {root: ()}
    order: list[str] = []

    def visit_next() -> None:
        if not queue:
            return
        package = queue.popleft()
        order.append(package)
        accepted: list[str] = []
        for dependency in get_dependencies(package):
            if filter_substring and filter_substring in dependency:
                continue
            if dependency not in accepted:
                accepted.append(dependency)
            if dependency not in visited:
                visited.add(dependency)
                edges[dependency] = ()
                queue.append(dependency)
        edges[package] = tuple(accepted)
        visit_next()

    visit_next()
    return DependencyGraph(root=root, edges=edges, bfs_order=tuple(order))


def invert_graph(adjacency: dict[str, Iterable[str]]) -> dict[str, tuple[str, ...]]:
    """Строит обратный список смежности, сохраняя изолированные узлы."""
    reverse: dict[str, list[str]] = {node: [] for node in adjacency}
    for package, dependencies in adjacency.items():
        for dependency in dependencies:
            dependents = reverse.setdefault(dependency, [])
            if package not in dependents:
                dependents.append(package)
    return {node: tuple(dependents) for node, dependents in reverse.items()}


def flatten_apt_dependencies(pre_depends: Iterable[str], depends: Iterable[str]) -> tuple[str, ...]:
    """Преобразует группы Depends в имена узлов; альтернативы становятся отдельными рёбрами."""
    names: list[str] = []
    for group in (*pre_depends, *depends):
        for alternative in group.split("|"):
            name = alternative.strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)
