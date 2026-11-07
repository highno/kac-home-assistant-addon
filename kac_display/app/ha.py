"""Read entity states from Home Assistant through the Supervisor proxy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from .errors import HomeAssistantError


@dataclass(frozen=True)
class HAState:
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str | None = None
    last_updated: str | None = None

    @property
    def available(self) -> bool:
        return self.state not in {"unknown", "unavailable"}


class HomeAssistantClient:
    def __init__(
        self,
        token: str,
        timeout: float = 10,
        base_url: str = "http://supervisor/core/api",
        session: requests.Session | None = None,
    ) -> None:
        if not token:
            raise HomeAssistantError("SUPERVISOR_TOKEN is missing")
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.core_url = (
            self.base_url[:-4]
            if self.base_url.endswith("/api")
            else self.base_url
        )
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    def _state_items(self) -> list[dict[str, Any]]:
        try:
            response = self.session.get(f"{self.base_url}/states", timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HomeAssistantError(f"cannot read Home Assistant states: {exc}") from exc
        if not isinstance(body, list):
            raise HomeAssistantError("Home Assistant returned an unexpected states response")
        return [item for item in body if isinstance(item, dict)]

    @staticmethod
    def _as_state(item: dict[str, Any]) -> HAState:
        attributes = item.get("attributes")
        return HAState(
            entity_id=str(item.get("entity_id", "")),
            state=str(item.get("state", "unavailable")),
            attributes=attributes if isinstance(attributes, dict) else {},
            last_changed=item.get("last_changed"),
            last_updated=item.get("last_updated"),
        )

    def states(self, aliases: dict[str, str]) -> dict[str, HAState]:
        body = self._state_items()
        by_id = {
            item.get("entity_id"): item
            for item in body
            if isinstance(item.get("entity_id"), str)
        }
        result: dict[str, HAState] = {}
        for alias, entity_id in aliases.items():
            item = by_id.get(entity_id)
            if item is None:
                result[alias] = HAState(entity_id, "unavailable", {})
                continue
            result[alias] = self._as_state(item)
        return result

    def entity_catalog(self) -> list[dict[str, Any]]:
        """Return the searchable entity list used by the ingress editor."""
        catalog: list[dict[str, Any]] = []
        for item in self._state_items():
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            attributes = item.get("attributes")
            attributes = attributes if isinstance(attributes, dict) else {}
            domain = entity_id.partition(".")[0]
            catalog.append(
                {
                    "entity_id": entity_id,
                    "name": str(attributes.get("friendly_name") or entity_id),
                    "domain": domain,
                    "state": str(item.get("state", "unavailable")),
                    "has_image": bool(
                        domain in {"camera", "image", "media_player"}
                        or attributes.get("entity_picture")
                    ),
                }
            )
        return sorted(catalog, key=lambda item: (item["name"].lower(), item["entity_id"]))

    def entity_image(self, entity_id: str) -> bytes:
        """Fetch a camera snapshot or an entity picture through Home Assistant."""
        encoded_id = quote(entity_id, safe="")
        domain = entity_id.partition(".")[0]
        if domain == "camera":
            url = f"{self.base_url}/camera_proxy/{encoded_id}"
            params: dict[str, Any] | None = {"width": 240, "height": 240}
        elif domain == "image":
            url = f"{self.base_url}/image_proxy/{encoded_id}"
            params = None
        elif domain == "media_player":
            url = f"{self.base_url}/media_player_proxy/{encoded_id}"
            params = None
        else:
            try:
                state_response = self.session.get(
                    f"{self.base_url}/states/{encoded_id}", timeout=self.timeout
                )
                state_response.raise_for_status()
                state = state_response.json()
            except (requests.RequestException, ValueError) as exc:
                raise HomeAssistantError(
                    f"cannot read image source entity {entity_id}: {exc}"
                ) from exc
            attributes = state.get("attributes") if isinstance(state, dict) else None
            picture = attributes.get("entity_picture") if isinstance(attributes, dict) else None
            if not isinstance(picture, str) or not picture.startswith("/api/"):
                raise HomeAssistantError(
                    f"{entity_id} has no Home Assistant-proxied entity_picture"
                )
            url = f"{self.core_url}{picture}"
            params = None
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HomeAssistantError(
                f"cannot fetch image from {entity_id}: {exc}"
            ) from exc
        content_type = response.headers.get("Content-Type", "").partition(";")[0]
        if not content_type.startswith("image/"):
            raise HomeAssistantError(
                f"{entity_id} returned {content_type or 'an unknown content type'}, not an image"
            )
        data = response.content
        if not data or len(data) > 10 * 1024 * 1024:
            raise HomeAssistantError(
                f"image from {entity_id} is empty or larger than 10 MB"
            )
        return data
