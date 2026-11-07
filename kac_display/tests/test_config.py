from pathlib import Path
import tempfile
import unittest

from app.config import config_from_options, kac_settings, load_config, options_from_config
from app.errors import ConfigurationError


VALID = """
version: 1
entities:
  temp: sensor.temperature
formats:
  temp: "{{ value }} °C"
devices:
  - name: test
    host: 192.168.1.50
    key: abc123
    settings:
      rotation_seconds: 20
    pages:
      - title: Home
        rows:
          - type: big
            label: Temp
            entity: temp
            format: temp
    images: []
"""


class ConfigTests(unittest.TestCase):
    def test_loads_and_normalizes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kac.yaml"
            path.write_text(VALID, encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config["devices"][0]["pages"][0]["rows"][0]["type"], "g")
        self.assertEqual(kac_settings(config["devices"][0]["settings"]), {"rot": 20})

    def test_rejects_more_than_eight_rows(self):
        rows = "\n".join("          - type: empty" for _ in range(9))
        text = VALID.replace(
            "          - type: big\n            label: Temp\n            entity: temp\n            format: temp",
            rows,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kac.yaml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_config(path)

    def test_graphical_options_are_converted(self):
        options = {
            "update_interval_seconds": 15,
            "text_mode": "transliterate",
            "home_assistant_timeout_seconds": 9,
            "entities": [
                {"alias": "temp", "entity_id": "sensor.temperature"}
            ],
            "formats": [
                {"name": "temp", "template": "{{ value }} °C"}
            ],
            "devices": [
                {
                    "name": "living",
                    "host": "192.168.1.50",
                    "key": "abc123",
                    "timeout_seconds": 10,
                    "rotation_seconds": 20,
                    "brightness_enabled": True,
                    "brightness": 75,
                    "brightness_schedule_enabled": False,
                    "pages": [
                        {
                            "title": "Home",
                            "rows": [
                                {
                                    "type": "big",
                                    "label": "Temp",
                                    "entity": "temp",
                                    "format": "temp",
                                }
                            ],
                        }
                    ],
                    "images": [],
                }
            ],
        }
        config = config_from_options(options)
        self.assertEqual(config["update_interval_seconds"], 15)
        self.assertEqual(config["devices"][0]["pages"][0]["rows"][0]["type"], "g")
        self.assertEqual(config["devices"][0]["settings"]["brightness"], 75)

    def test_graphical_camera_image_source_is_converted(self):
        options = {
            "entities": [],
            "formats": [],
            "devices": [
                {
                    "name": "living",
                    "host": "192.168.1.50",
                    "key": "abc123",
                    "pages": [{"title": "Home", "rows": []}],
                    "images": [
                        {
                            "slot": 1,
                            "source_type": "entity",
                            "entity_id": "camera.garden",
                            "refresh_seconds": 120,
                            "max_jpeg_kb": 30,
                        }
                    ],
                }
            ],
        }
        image = config_from_options(options)["devices"][0]["images"][0]
        self.assertEqual(image["source_type"], "entity")
        self.assertEqual(image["entity_id"], "camera.garden")
        self.assertEqual(image["refresh_seconds"], 120)

    def test_legacy_configuration_can_be_migrated_to_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kac.yaml"
            path.write_text(VALID, encoding="utf-8")
            legacy = load_config(path)
        options = options_from_config(legacy, {"dry_run": False})
        self.assertEqual(options["entities"][0]["alias"], "temp")
        self.assertEqual(options["devices"][0]["pages"][0]["rows"][0]["type"], "big")
        converted = config_from_options(options)
        self.assertEqual(converted["devices"][0]["pages"][0]["rows"][0]["type"], "g")


if __name__ == "__main__":
    unittest.main()
