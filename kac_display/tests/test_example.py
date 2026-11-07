from pathlib import Path
import tempfile
import unittest

from app.config import load_config
from app.ha import HAState
from app.render import HistoryStore, PageRenderer


class ExampleTests(unittest.TestCase):
    def test_shipped_example_validates_and_renders_every_row_type(self):
        config = load_config(Path("examples/kac.yaml"))
        values = {
            "living_temperature": "21.4",
            "living_humidity": "43",
            "phone_battery": "75",
            "house_power": "1234",
            "download_rate": "500",
            "upload_rate": "100",
            "front_door": "off",
        }
        states = {
            alias: HAState(
                config["entities"][alias],
                value,
                {"unit_of_measurement": "test"},
            )
            for alias, value in values.items()
        }
        with tempfile.TemporaryDirectory() as directory:
            renderer = PageRenderer(
                config["formats"],
                config["text_mode"],
                HistoryStore(Path(directory) / "history.json"),
            )
            pages = renderer.render_device(config["devices"][0], states)
        row_types = {row["y"] for page in pages for row in page["z"]}
        self.assertEqual(row_types, {"h", "k", "g", "b", "d", "u", "s", "-"})


if __name__ == "__main__":
    unittest.main()
