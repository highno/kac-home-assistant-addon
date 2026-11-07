import io
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image

from app.ui import ConfigurationServer, UIConfigurationStore


OPTIONS = {
    "entities": [],
    "formats": [],
    "devices": [
        {
            "name": "living",
            "host": "192.168.1.50",
            "key": "secret",
            "pages": [{"title": "Home", "rows": []}],
            "images": [],
        }
    ],
}


class UIStoreTests(unittest.TestCase):
    def test_masks_and_preserves_device_key(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            store = UIConfigurationStore(Path(directory) / "config.json", OPTIONS)
            public = store.public()
            self.assertEqual(public["devices"][0]["key"], "")
            self.assertTrue(public["devices"][0]["key_configured"])
            store.save(public)
            self.assertEqual(store.read()["devices"][0]["key"], "secret")

    def test_static_upload(self):
        class HA:
            @staticmethod
            def entity_catalog():
                return [{"entity_id": "camera.garden", "name": "Garden"}]

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            store = UIConfigurationStore(root / "config.json", OPTIONS)
            server = ConfigurationServer(
                store,
                HA(),
                threading.Event(),
                port=0,
                upload_dir=root / "uploads",
            )
            image = io.BytesIO()
            Image.new("RGB", (20, 10), "blue").save(image, "PNG")
            source = server._save_upload("test.png", image.getvalue())
            self.assertTrue(source.startswith("uploads/"))
            self.assertTrue((root / source).is_file())


if __name__ == "__main__":
    unittest.main()
