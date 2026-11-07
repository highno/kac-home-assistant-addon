from pathlib import Path
import tempfile
import unittest

from app.config import kac_settings, load_config
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


if __name__ == "__main__":
    unittest.main()
