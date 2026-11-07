"""Service entry point for the Home Assistant add-on."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import threading
from typing import Any

from .config import kac_settings, load_config
from .errors import BridgeError, ConfigurationError
from .ha import HomeAssistantClient
from .images import ImageSynchronizer
from .kac import KACClient
from .render import HistoryStore, PageRenderer


LOGGER = logging.getLogger("kac_bridge")
OPTIONS_PATH = Path("/data/options.json")
EXAMPLE_PATH = Path("/app/example-kac.yaml")


def _load_options() -> dict[str, Any]:
    defaults = {
        "config_file": "/config/kac.yaml",
        "log_level": "info",
        "dry_run": False,
    }
    try:
        raw = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    except OSError:
        return defaults
    except ValueError as exc:
        raise ConfigurationError(f"invalid {OPTIONS_PATH}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"{OPTIONS_PATH} must contain a JSON object")
    return dict(defaults, **raw)


def _copy_example(config_path: Path) -> bool:
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(EXAMPLE_PATH, config_path)
    except OSError as exc:
        raise ConfigurationError(
            f"configuration is missing and example could not be created at {config_path}: {exc}"
        ) from exc
    return True


def _version_tuple(value: Any) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


class Bridge:
    def __init__(self, config: dict[str, Any], dry_run: bool) -> None:
        self.config = config
        self.dry_run = dry_run
        self.stop_event = threading.Event()
        self.history = HistoryStore("/data/sparkline-history.json")
        self.renderer = PageRenderer(
            config["formats"], config["text_mode"], self.history
        )
        self.image_sync = ImageSynchronizer("/data/image-cache.json")
        self.clients = {
            device["name"]: KACClient(
                device["host"], device["key"], device["timeout_seconds"]
            )
            for device in config["devices"]
        }
        self.ha = HomeAssistantClient(
            os.environ.get("SUPERVISOR_TOKEN", ""),
            config["home_assistant"]["timeout_seconds"],
        )

    def stop(self, *_: Any) -> None:
        self.stop_event.set()

    @staticmethod
    def _uses_modern_features(device: dict[str, Any]) -> bool:
        return bool(device["images"]) or any(
            row["type"] in {"g", "s"}
            for page in device["pages"]
            for row in page["rows"]
        )

    def initialize_devices(self) -> None:
        for device in self.config["devices"]:
            name = device["name"]
            client = self.clients[name]
            if self.dry_run:
                LOGGER.info("%s: dry run; status check and image synchronization skipped", name)
                continue
            try:
                status = client.status()
                firmware = status.get("version", "unknown")
                LOGGER.info(
                    "%s: connected to %s, firmware %s, max pages %s",
                    name,
                    status.get("name", device["host"]),
                    firmware,
                    status.get("max_seiten", "unknown"),
                )
                version = _version_tuple(firmware)
                if self._uses_modern_features(device) and version and version < (0, 8, 10):
                    LOGGER.warning(
                        "%s: firmware %s is older than 0.8.10; image slots, big values, or sparklines may be unavailable",
                        name,
                        firmware,
                    )
                for message in self.image_sync.sync_device(
                    device, client, self.config["config_dir"], status
                ):
                    LOGGER.info("%s: %s", name, message)
            except BridgeError as exc:
                LOGGER.error("%s: initialization failed: %s", name, exc)

    def run_once(self) -> None:
        states = self.ha.states(self.config["entities"])
        for alias, state in states.items():
            if not state.available:
                LOGGER.warning("%s (%s) is %s", alias, state.entity_id, state.state)
        for device in self.config["devices"]:
            name = device["name"]
            try:
                pages = self.renderer.render_device(device, states)
                if self.dry_run:
                    LOGGER.info(
                        "%s: dry-run pages: %s",
                        name,
                        json.dumps(pages, ensure_ascii=False, separators=(",", ":")),
                    )
                    continue
                answer = self.clients[name].send_pages(
                    pages, kac_settings(device["settings"])
                )
                if answer.get("voll"):
                    LOGGER.warning(
                        "%s: KAC memory is full; only %s page(s) were kept",
                        name,
                        answer.get("seiten", "some"),
                    )
                else:
                    LOGGER.info(
                        "%s: sent %d page(s); KAC stores %s",
                        name,
                        len(pages),
                        answer.get("seiten", len(pages)),
                    )
            except BridgeError as exc:
                LOGGER.error("%s: update failed: %s", name, exc)
        self.history.save()

    def run(self) -> None:
        self.initialize_devices()
        interval = self.config["update_interval_seconds"]
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except BridgeError as exc:
                LOGGER.error("update cycle failed: %s", exc)
            except Exception:
                LOGGER.exception("unexpected update-cycle failure")
            self.stop_event.wait(interval)


def main() -> int:
    try:
        options = _load_options()
        logging.basicConfig(
            level=getattr(logging, str(options["log_level"]).upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(message)s",
        )
        config_path = Path(str(options["config_file"]))
        if _copy_example(config_path):
            LOGGER.error(
                "created example configuration at %s; edit it, set the KAC host/key and entity IDs, then restart the add-on",
                config_path,
            )
            return 2
        config = load_config(config_path)
        bridge = Bridge(config, bool(options["dry_run"]))
        signal.signal(signal.SIGTERM, bridge.stop)
        signal.signal(signal.SIGINT, bridge.stop)
        bridge.run()
        return 0
    except ConfigurationError as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("configuration error: %s", exc)
        return 2
    except BridgeError as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("startup failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
