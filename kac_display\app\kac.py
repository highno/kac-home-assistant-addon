"""Client for the documented KAC HTTP API."""

from __future__ import annotations

import json
from typing import Any

import requests

from .errors import KACError


MAX_REQUEST_BYTES = 3800


class KACClient:
    def __init__(
        self,
        host: str,
        key: str,
        timeout: float = 10,
        session: requests.Session | None = None,
    ) -> None:
        self.host = host
        self.timeout = timeout
        self.base_url = f"http://{host}"
        self.session = session or requests.Session()
        self.session.headers.update({"X-Token": key, "Accept": "application/json"})

    @staticmethod
    def _encode(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def _json_response(self, response: requests.Response, action: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:500]}
        if not response.ok:
            hint = " (check the device key)" if response.status_code == 403 else ""
            raise KACError(
                f"{self.host}: {action} failed with HTTP {response.status_code}: {body}{hint}"
            )
        if not isinstance(body, dict):
            raise KACError(f"{self.host}: {action} returned unexpected JSON")
        return body

    def status(self) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{self.base_url}/api/status", timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise KACError(f"{self.host}: status request failed: {exc}") from exc
        return self._json_response(response, "status request")

    def send_pages(
        self, pages: list[dict[str, Any]], settings: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not pages:
            raise KACError("refusing to send an empty page set")
        base = dict(settings or {})
        parts: list[list[dict[str, Any]]] = []
        part: list[dict[str, Any]] = []
        for page in pages:
            probe = dict(base, seiten=part + [page], ab=99, gesamt=99)
            if part and len(self._encode(probe)) > MAX_REQUEST_BYTES:
                parts.append(part)
                part = []
            probe = dict(base, seiten=[page], ab=99, gesamt=99)
            if len(self._encode(probe)) > MAX_REQUEST_BYTES:
                raise KACError("one rendered page exceeds the safe KAC request size")
            part.append(page)
        if part:
            parts.append(part)

        answer: dict[str, Any] = {}
        first = 0
        for current in parts:
            payload = dict(base, seiten=current)
            if len(parts) > 1:
                payload.update(ab=first, gesamt=len(pages))
            data = self._encode(payload)
            try:
                response = self.session.post(
                    f"{self.base_url}/api/seiten",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise KACError(f"{self.host}: page update failed: {exc}") from exc
            answer = self._json_response(response, "page update")
            if answer.get("voll"):
                break
            first += len(current)
        return answer

    def upload_image(
        self, data: bytes, extension: str, slot: int
    ) -> dict[str, Any]:
        content_type = "image/gif" if extension == "gif" else "image/jpeg"
        try:
            response = self.session.post(
                f"{self.base_url}/api/medium",
                params={"nr": slot},
                files={"medium": (f"kac.{extension}", data, content_type)},
                timeout=max(self.timeout, 60),
            )
        except requests.RequestException as exc:
            raise KACError(f"{self.host}: image upload failed: {exc}") from exc
        return self._json_response(response, f"image upload to slot {slot}")

    def delete_image(self, slot: int) -> dict[str, Any]:
        try:
            response = self.session.delete(
                f"{self.base_url}/api/medium",
                params={"nr": slot},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KACError(f"{self.host}: image deletion failed: {exc}") from exc
        return self._json_response(response, f"image deletion in slot {slot}")
