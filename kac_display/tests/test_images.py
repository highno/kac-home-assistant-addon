import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from app.images import ImageSynchronizer, prepare_image


class ImageTests(unittest.TestCase):
    def test_static_image_becomes_baseline_jpg(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (320, 180), "red").save(source)
            data, extension = prepare_image(
                source,
                {
                    "fit": "contain",
                    "quality": 90,
                    "gif_colors": 64,
                    "gif_min_delay_ms": 100,
                },
            )
        self.assertEqual(extension, "jpg")
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertLess(len(data), 1024 * 1024)

    def test_static_image_is_scaled_and_adapted_to_target_size(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "noise.png"
            Image.effect_noise((600, 400), 80).convert("RGB").save(source)
            data, extension = prepare_image(
                source,
                {
                    "fit": "cover",
                    "quality": 95,
                    "max_jpeg_kb": 20,
                    "gif_colors": 64,
                    "gif_min_delay_ms": 100,
                },
            )
        self.assertEqual(extension, "jpg")
        self.assertLessEqual(len(data), 20 * 1024)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.size, (240, 240))

    def test_quality_below_twenty_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (100, 100), "orange").save(source)
            data, extension = prepare_image(
                source,
                {
                    "fit": "cover",
                    "quality": 10,
                    "max_jpeg_kb": 30,
                    "gif_colors": 64,
                    "gif_min_delay_ms": 100,
                },
            )
        self.assertEqual(extension, "jpg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_entity_image_is_fetched_once_per_refresh_interval(self):
        raw = io.BytesIO()
        Image.new("RGB", (320, 180), "green").save(raw, "PNG")

        class HA:
            calls = 0

            def entity_image(self, entity_id):
                self.calls += 1
                return raw.getvalue()

        class KAC:
            uploads = 0

            def upload_image(self, data, extension, slot):
                self.uploads += 1

        device = {
            "name": "test",
            "images": [
                {
                    "slot": 1,
                    "source_type": "entity",
                    "entity_id": "camera.garden",
                    "refresh_seconds": 60,
                    "fit": "cover",
                    "upload": "on_change",
                    "delete": False,
                    "quality": 70,
                    "max_jpeg_kb": 30,
                    "gif_colors": 64,
                    "gif_min_delay_ms": 100,
                }
            ],
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            sync = ImageSynchronizer(Path(directory) / "cache.json")
            ha, kac = HA(), KAC()
            sync.sync_device(device, kac, directory, ha=ha)
            sync.sync_device(device, kac, directory, ha=ha)
        self.assertEqual(ha.calls, 1)
        self.assertEqual(kac.uploads, 1)


if __name__ == "__main__":
    unittest.main()
