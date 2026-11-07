import json
import unittest

from app.kac import KACClient


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        data = kwargs.get("data")
        if data:
            payload = json.loads(data)
            return FakeResponse({"ok": True, "seiten": payload.get("gesamt", len(payload["seiten"]))})
        return FakeResponse({"ok": True})


class KACTests(unittest.TestCase):
    def test_sends_large_page_sets_in_documented_parts(self):
        session = FakeSession()
        client = KACClient("192.0.2.1", "key", session=session)
        pages = [
            {
                "t": f"Page {index}",
                "z": [{"y": "k", "l": "Label", "v": "x" * 27} for _ in range(8)],
            }
            for index in range(20)
        ]
        client.send_pages(pages, {"rot": 30})
        self.assertGreater(len(session.posts), 1)
        first = json.loads(session.posts[0][1]["data"])
        second = json.loads(session.posts[1][1]["data"])
        self.assertEqual(first["ab"], 0)
        self.assertEqual(first["gesamt"], 20)
        self.assertEqual(second["ab"], len(first["seiten"]))
        self.assertEqual(second["gesamt"], 20)
        for _, call in session.posts:
            self.assertLessEqual(len(call["data"]), 3800)


if __name__ == "__main__":
    unittest.main()
