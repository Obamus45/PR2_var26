import tempfile
import unittest
from pathlib import Path

from app import ConfigError, load_config


VALID = {
    "package_name": "demo-app",
    "repository": "./test-repository.txt",
    "test_mode": True,
    "output_file": "dependencies.svg",
    "ascii_tree": True,
    "filter_substring": "",
}


class ConfigValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "repo.txt").write_text("# fixture\n", encoding="utf-8")
        self.values = dict(VALID, repository=str(self.root / "repo.txt"))

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, values):
        import yaml
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(values, allow_unicode=True), encoding="utf-8")
        return path

    def test_valid_configuration(self):
        config = load_config(self.write_config(self.values))
        self.assertEqual(config.package_name, "demo-app")
        self.assertTrue(config.test_mode)
        self.assertEqual(config.filter_substring, "")
        self.assertFalse(config.reverse_dependencies)

    def test_package_name_must_be_valid(self):
        values = dict(self.values, package_name="bad package!")
        with self.assertRaisesRegex(ConfigError, "package_name"):
            load_config(self.write_config(values))

    def test_repository_must_exist_in_test_mode(self):
        values = dict(self.values, repository=str(self.root / "missing.txt"))
        with self.assertRaisesRegex(ConfigError, "repository"):
            load_config(self.write_config(values))

    def test_repository_must_be_url_in_normal_mode(self):
        values = dict(self.values, test_mode=False, repository="not-a-url")
        with self.assertRaisesRegex(ConfigError, "repository"):
            load_config(self.write_config(values))

    def test_test_mode_must_be_boolean(self):
        values = dict(self.values, test_mode="yes")
        with self.assertRaisesRegex(ConfigError, "test_mode"):
            load_config(self.write_config(values))

    def test_output_file_must_be_svg_filename(self):
        values = dict(self.values, output_file="graph.png")
        with self.assertRaisesRegex(ConfigError, "output_file"):
            load_config(self.write_config(values))

    def test_ascii_tree_must_be_boolean(self):
        values = dict(self.values, ascii_tree=1)
        with self.assertRaisesRegex(ConfigError, "ascii_tree"):
            load_config(self.write_config(values))

    def test_filter_must_be_string(self):
        values = dict(self.values, filter_substring=23)
        with self.assertRaisesRegex(ConfigError, "filter_substring"):
            load_config(self.write_config(values))

    def test_reverse_dependencies_flag_must_be_boolean(self):
        values = dict(self.values, reverse_dependencies="yes")
        with self.assertRaisesRegex(ConfigError, "reverse_dependencies"):
            load_config(self.write_config(values))

    def test_unknown_and_missing_parameters_are_reported(self):
        values = dict(self.values)
        values.pop("ascii_tree")
        values["typo"] = "x"
        with self.assertRaisesRegex(ConfigError, "Неизвестные параметры"):
            load_config(self.write_config(values))
        values.pop("typo")
        with self.assertRaisesRegex(ConfigError, "Не заданы обязательные"):
            load_config(self.write_config(values))


if __name__ == "__main__":
    unittest.main()
