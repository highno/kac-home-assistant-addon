import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from app.errors import ImageError
from app.images import ImageSynchronizer, prepare_image, prepare_image_bytes


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

    def test_png_with_embedded_svg_metadata_stays_a_png(self):
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Source", "<svg>original vector metadata</svg>")
        raw = io.BytesIO()
        Image.new("RGB", (320, 180), "purple").save(raw, "PNG", pnginfo=metadata)
        self.assertIn(b"<svg>", raw.getvalue()[:4096])
        data, extension = prepare_image_bytes(
            raw.getvalue(),
            "uploaded.png",
            {
                "fit": "contain",
                "quality": 70,
                "max_jpeg_kb": 30,
                "gif_colors": 64,
                "gif_min_delay_ms": 100,
            },
        )
        self.assertEqual(extension, "jpg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

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

    def test_svg_external_references_are_rejected(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="http://device/private.png"/></svg>'
        with self.assertRaises(ImageError):
            prepare_image_bytes(
                svg,
                "unsafe.svg",
                {
                    "fit": "contain",
                    "quality": 70,
                    "max_jpeg_kb": 30,
                    "gif_colors": 64,
                    "gif_min_delay_ms": 100,
                },
            )

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

    def test_svg_map_is_rasterized_to_jpeg(self):
        svg = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
        <rect width="400" height="200" fill="#202020"/>
        <path d="M20 20h360v160H20z" fill="#40a0ff"/>
        </svg>"""
        raster = io.BytesIO()
        Image.new("RGB", (400, 200), "blue").save(raster, "PNG")
        with patch("app.images.svg2png", return_value=raster.getvalue()) as renderer:
            data, extension = prepare_image_bytes(
                svg,
                "image.saugi_karte",
                {
                    "fit": "contain",
                    "quality": 70,
                    "max_jpeg_kb": 30,
                    "gif_colors": 64,
                    "gif_min_delay_ms": 100,
                },
            )
        renderer.assert_called_once()
        self.assertEqual(extension, "jpg")
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.size, (240, 240))

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

    def test_bad_slot_does_not_block_following_entity_image(self):
        raw = io.BytesIO()
        Image.new("RGB", (100, 100), "green").save(raw, "PNG")

        class HA:
            def entity_image(self, entity_id):
                return raw.getvalue()

        class KAC:
            def __init__(self):
                self.slots = []

            def upload_image(self, data, extension, slot):
                self.slots.append(slot)

        common = {
            "refresh_seconds": 60,
            "fit": "cover",
            "upload": "on_change",
            "delete": False,
            "quality": 70,
            "max_jpeg_kb": 30,
            "gif_colors": 64,
            "gif_min_delay_ms": 100,
        }
        device = {
            "name": "test",
            "images": [
                dict(common, slot=1, source_type="file", source="broken.png"),
                dict(
                    common,
                    slot=2,
                    source_type="entity",
                    entity_id="image.saugi_karte",
                ),
            ],
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            Path(directory, "broken.png").write_bytes(b"not an image")
            kac = KAC()
            messages = ImageSynchronizer(Path(directory) / "cache.json").sync_device(
                device, kac, directory, ha=HA()
            )
        self.assertEqual(kac.slots, [2])
        self.assertTrue(
            any(level == "error" and "slot 1" in message for level, message in messages)
        )


if __name__ == "__main__":
    unittest.main()
