import os
import tempfile
import unittest

from gipler.config import configured_paths, default_paths, get_settings, save_paths


class ConfigurationTests(unittest.TestCase):
    def test_default_paths_are_independent_of_install_location(self):
        paths = default_paths()
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(os.path.isabs(path) for path in paths))
        self.assertNotIn("Idiomind", os.path.commonpath(paths))

    def test_configured_paths_round_trip(self):
        settings = get_settings()
        keys = ("paths/dev", "paths/principal", "paths/addons")
        previous = [settings.value(key) for key in keys]
        with tempfile.TemporaryDirectory() as root:
            paths = tuple(os.path.join(root, name) for name in ("source", "main", "addons"))
            try:
                save_paths(*paths)
                self.assertEqual(configured_paths(), paths)
            finally:
                for key, value in zip(keys, previous):
                    if value is None:
                        settings.remove(key)
                    else:
                        settings.setValue(key, value)
                settings.sync()


if __name__ == "__main__":
    unittest.main()
