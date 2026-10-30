import tempfile
import unittest
from pathlib import Path

from dependency_graph import GraphError, build_bfs_recursive, parse_test_repository


class DependencyGraphTests(unittest.TestCase):
    def test_bfs_order_and_cycle(self):
        adjacency = {
            "A": ("B", "C"),
            "B": ("D",),
            "C": ("D", "E"),
            "D": ("A",),
            "E": (),
        }
        graph = build_bfs_recursive("A", lambda node: adjacency[node])
        self.assertEqual(graph.bfs_order, ("A", "B", "C", "D", "E"))
        self.assertEqual(graph.edges["D"], ("A",))  # цикл отображён, повторного обхода нет
        self.assertEqual(len(graph.edges), 5)

    def test_filter_excludes_matching_nodes_and_their_branches(self):
        adjacency = {"A": ("B", "C"), "B": ("D",), "C": ("E",), "D": (), "E": ()}
        graph = build_bfs_recursive("A", lambda node: adjacency[node], "C")
        self.assertEqual(graph.bfs_order, ("A", "B", "D"))
        self.assertNotIn("C", graph.edges)
        self.assertNotIn("E", graph.edges)

    def test_filtered_root_is_reported(self):
        with self.assertRaisesRegex(GraphError, "исключён фильтром"):
            build_bfs_recursive("ABC", lambda _: (), "B")

    def test_parses_test_repository_and_implicit_leaf_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repo.txt"
            path.write_text("# comment\nA: B, C\nB: D\nC:\n", encoding="utf-8")
            graph = parse_test_repository(path)
        self.assertEqual(graph["A"], ("B", "C"))
        self.assertEqual(graph["C"], ())
        self.assertEqual(graph["D"], ())

    def test_rejects_lowercase_or_malformed_test_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repo.txt"
            path.write_text("A: lower-case\n", encoding="utf-8")
            with self.assertRaisesRegex(GraphError, "Строка 1"):
                parse_test_repository(path)


if __name__ == "__main__":
    unittest.main()
