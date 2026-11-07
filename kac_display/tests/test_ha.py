import unittest

from app.ha import HomeAssistantClient


class Response:
    def __init__(self, body=None, content=b"", content_type="application/json"):
        self.body = body
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class Session:
    def __init__(self):
        self.headers = {}
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append((url, kwargs))
        if url.endswith("/states"):
            return Response(
                [
                    {
                        "entity_id": "camera.garden",
                        "state": "streaming",
                        "attributes": {"friendly_name": "Garden"},
                    },
                    {
                        "entity_id": "media_player.living",
                        "state": "playing",
                        "attributes": {"friendly_name": "Living room"},
                    },
                ]
            )
        return Response(content=b"image", content_type="image/jpeg")


class HomeAssistantTests(unittest.TestCase):
    def test_catalog_and_camera_image_use_core_proxy(self):
        session = Session()
        client = HomeAssistantClient("token", session=session)
        catalog = client.entity_catalog()
        self.assertEqual([item["entity_id"] for item in catalog], ["camera.garden", "media_player.living"])
        self.assertTrue(all(item["has_image"] for item in catalog))

        self.assertEqual(client.entity_image("camera.garden"), b"image")
        url, kwargs = session.urls[-1]
        self.assertEqual(url, "http://supervisor/core/api/camera_proxy/camera.garden")
        self.assertEqual(kwargs["params"], {"width": 240, "height": 240})

    def test_media_player_uses_documented_proxy(self):
        session = Session()
        client = HomeAssistantClient("token", session=session)
        self.assertEqual(client.entity_image("media_player.living"), b"image")
        self.assertEqual(
            session.urls[-1][0],
            "http://supervisor/core/api/media_player_proxy/media_player.living",
        )

    def test_other_entity_uses_relative_entity_picture(self):
        class PictureSession(Session):
            def get(self, url, **kwargs):
                self.urls.append((url, kwargs))
                if "/states/" in url:
                    return Response(
                        {
                            "entity_id": "image.weather",
                            "state": "2026-11-07T18:00:00Z",
                            "attributes": {
                                "entity_picture": "/api/image/serve/weather/original"
                            },
                        }
                    )
                return Response(content=b"weather", content_type="image/png")

        session = PictureSession()
        client = HomeAssistantClient("token", session=session)
        self.assertEqual(client.entity_image("image.weather"), b"weather")
        self.assertEqual(
            session.urls[-1][0],
            "http://supervisor/core/api/image/serve/weather/original",
        )


if __name__ == "__main__":
    unittest.main()
