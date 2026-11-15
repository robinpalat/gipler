"""Tests de configuración de usuario (tema y preferencias de visualización)."""
import unittest

from gipler.config import get_settings


class ConfigurationTests(unittest.TestCase):
    def test_get_settings_returns_application_settings(self):
        settings = get_settings()
        self.assertEqual(settings.organizationName(), "Gipler")
        self.assertEqual(settings.applicationName(), "Gipler")

    def test_theme_preference_round_trip(self):
        from gipler.gui import theme as th

        previous = th.load_preference()
        try:
            th.save_preference("claro")
            self.assertEqual(th.load_preference(), "claro")
            th.save_preference("oscuro")
            self.assertEqual(th.load_preference(), "oscuro")
        finally:
            th.save_preference(previous)


if __name__ == "__main__":
    unittest.main()
