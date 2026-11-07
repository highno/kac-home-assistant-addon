from pathlib import Path
import tempfile
import unittest

from PIL import Image

from app.images import prepare_image


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


if __name__ == "__main__":
    unittest.main()
