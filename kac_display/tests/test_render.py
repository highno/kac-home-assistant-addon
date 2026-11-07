from pathlib import Path
import tempfile
import unittest

from app.ha import HAState
from app.render import HistoryStore, PageRenderer, RenderError, sanitize_text


class RenderTests(unittest.TestCase):
    def test_transliterates_and_truncates_by_bytes(self):
        self.assertEqual(sanitize_text("Küche 21°", 27, "transliterate"), "Kueche 21°")
        self.assertEqual(sanitize_text("12345678901234°", 15, "transliterate"), "12345678901234")
        with self.assertRaises(RenderError):
            sanitize_text("Küche", 27, "strict")

    def test_renders_documented_shape_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            history = HistoryStore(Path(directory) / "history.json")
            renderer = PageRenderer(
                {"temperature": "{{ value | float | round(1) }} °C"},
                "transliterate",
                history,
            )
            device = {
                "name": "test",
                "pages": [
                    {
                        "title": "Küche",
                        "rows": [
                            {
                                "type": "g",
                                "label": "Temperatur",
                                "entity": "temp",
                                "format": "temperature",
                                "alert": "{{ value | float > 25 }}",
                            },
                            {
                                "type": "s",
                                "label": "Temp",
                                "entity": "temp",
                                "value": "{{ value }} °C",
                                "history_points": 20,
                                "scale_min": 0,
                                "scale_max": 40,
                            },
                        ],
                    }
                ],
            }
            states = {"temp": HAState("sensor.temp", "26.5", {})}
            pages = renderer.render_device(device, states)
        self.assertEqual(pages[0]["t"], "Kueche")
        self.assertEqual(pages[0]["z"][0]["y"], "g")
        self.assertEqual(pages[0]["z"][0]["a"], 1)
        self.assertEqual(pages[0]["z"][1]["w"], [66])


if __name__ == "__main__":
    unittest.main()
