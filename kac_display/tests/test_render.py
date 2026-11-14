from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.ha import HAState
from app.main import Bridge
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

    def test_missing_numbers_do_not_interrupt_text_page_updates(self):
        chart = {"type": "s", "label": "Verlauf", "entity": "sensor", "history_points": 20}
        device = {
            "name": "test",
            "host": "kac.test",
            "key": "test",
            "timeout_seconds": 1,
            "settings": {},
            "images": [],
            "pages": [
                {
                    "title": "Messwerte",
                    "rows": [
                        {"type": "b", "label": "Balken", "entity": "sensor"},
                        {"type": "u", "percent": "{{ entities.sensor.state }}"},
                        chart,
                        {
                            "type": "g",
                            "label": "Formel",
                            "entity": "sensor",
                            "value": "{{ 10 / (value | float(0)) }}",
                        },
                        {"type": "k", "label": "Status", "entity": "status"},
                    ],
                },
                {
                    "title": "Weitere Seite",
                    "rows": [{"type": "k", "label": "Text", "value": "OK"}],
                },
            ],
        }
        client = Mock()
        client.send_pages.return_value = {}
        ha = Mock()
        config = {
            "formats": {},
            "text_mode": "transliterate",
            "devices": [device],
            "config_dir": "/config",
            "entities": {"sensor": "sensor.level", "status": "binary_sensor.door"},
            "home_assistant": {"timeout_seconds": 1},
        }
        with (
            patch("app.main.HomeAssistantClient", return_value=ha),
            patch("app.main.KACClient", return_value=client),
            patch("app.main.ImageSynchronizer"),
            patch.object(HistoryStore, "save"),
        ):
            bridge = Bridge(config, dry_run=False)
            bridge.history.values = {"test:0:2": [25]}
            ha.states.return_value = {"status": HAState("binary_sensor.door", "on", {})}
            for state in ("unavailable", "unknown", "", "offline", "NaN", "inf"):
                with self.subTest(state=state):
                    ha.states.return_value["sensor"] = HAState("sensor.level", state, {})
                    bridge.run_once()
                    pages = client.send_pages.call_args.args[0]
                    self.assertEqual(
                        pages[0]["z"][:3],
                        [
                            {"y": "k", "l": "Balken", "v": "N/A"},
                            {"y": "k", "l": "", "v": "N/A"},
                            {"y": "k", "l": "Verlauf", "v": "N/A"},
                        ],
                    )
                    self.assertEqual(pages[0]["z"][4]["v"], "on")
                    self.assertEqual(pages[1]["z"][0]["v"], "OK")
                    if state == "offline":
                        self.assertEqual(pages[0]["z"][3]["v"], "N/A")
                    self.assertEqual(bridge.history.values["test:0:2"], [25])

            ha.states.return_value["sensor"] = HAState("sensor.level", "50", {})
            bridge.run_once()
            self.assertEqual(client.send_pages.call_count, 7)
            pages = client.send_pages.call_args.args[0]
            self.assertEqual(pages[0]["z"][0]["p"], 50)
            self.assertEqual(pages[0]["z"][2]["w"], [50, 100])
            self.assertEqual(bridge.history.values["test:0:2"], [25, 50])


if __name__ == "__main__":
    unittest.main()
