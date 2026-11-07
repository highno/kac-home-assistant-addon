"""Read entity states from Home Assistant through the Supervisor proxy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    def states(self, aliases: dict[str, str]) -> dict[str, HAState]:
        try:
            response = self.session.get(f"{self.base_url}/states", timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HomeAssistantError(f"cannot read Home Assistant states: {exc}") from exc
        if not isinstance(body, list):
            raise HomeAssistantError("Home Assistant returned an unexpected states response")
        by_id = {
            item.get("entity_id"): item
            for item in body
            if isinstance(item, dict) and isinstance(item.get("entity_id"), str)
        }
        result: dict[str, HAState] = {}
        for alias, entity_id in aliases.items():
            item = by_id.get(entity_id)
            if item is None:
                result[alias] = HAState(entity_id, "unavailable", {})
                continue
            attributes = item.get("attributes")
            result[alias] = HAState(
                entity_id=entity_id,
                state=str(item.get("state", "unavailable")),
                attributes=attributes if isinstance(attributes, dict) else {},
                last_changed=item.get("last_changed"),
                last_updated=item.get("last_updated"),
            )
        return result
