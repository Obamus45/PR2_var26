import gzip
import tempfile
import unittest
from pathlib import Path

from apt_index import AptIndexError, _dependency_groups, get_package_from_file


FIXTURE = """Package: demo-app
Version: 1.2.3-1
Architecture: amd64
Pre-Depends: init-system-helpers (>= 1.60)
Depends: libc6 (>= 2.35), demo-core (>= 1.0) | demo-core-compat,
 demo-data (= 1.2.3-1) [amd64]
Description: package description
 more description text

Package: demo-core
Version: 1.4-2
Depends: libgcc-s1
"""


class AptIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "Packages"
        self.path.write_text(FIXTURE, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_package_and_direct_dependencies(self):
        package = get_package_from_file(self.path, "demo-app")
        self.assertEqual(package.version, "1.2.3-1")
        self.assertEqual(package.pre_depends, ("init-system-helpers",))
        self.assertEqual(package.depends, (
            "libc6",
            "demo-core | demo-core-compat",
            "demo-data",
        ))

    def test_absent_package_is_a_clear_error(self):
        with self.assertRaisesRegex(AptIndexError, "не найден"):
            get_package_from_file(self.path, "missing-package")

    def test_splits_only_top_level_commas_and_preserves_alternatives(self):
        groups = _dependency_groups("a (>= 1, << 3), b | c (>= 2), d [amd64]")
        self.assertEqual(groups, ("a", "b | c", "d"))

    def test_gzip_index_is_supported(self):
        compressed_path = Path(self.temp.name) / "Packages.gz"
        compressed_path.write_bytes(gzip.compress(FIXTURE.encode("utf-8")))
        package = get_package_from_file(compressed_path, "demo-app")
        self.assertEqual(package.name, "demo-app")


if __name__ == "__main__":
    unittest.main()
