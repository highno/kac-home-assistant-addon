"""Service entry point for the Home Assistant add-on."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import signal
import sys
import threading
from typing import Any

from .config import config_from_options, kac_settings, load_config, options_from_config
from .errors import BridgeError, ConfigurationError
from .ha import HomeAssistantClient
from .images import ImageSynchronizer
from .kac import KACClient
from .render import HistoryStore, PageRenderer
from .ui import ConfigurationServer, UIConfigurationStore


LOGGER = logging.getLogger("kac_bridge")
OPTIONS_PATH = Path("/data/options.json")
UI_CONFIG_PATH = Path("/data/kac-ui-config.json")


def _load_options() -> dict[str, Any]:
    defaults = {
        "config_file": "/config/kac.yaml",
        "log_level": "info",
        "dry_run": False,
        "update_interval_seconds": 10,
        "text_mode": "transliterate",
        "home_assistant_timeout_seconds": 10,
        "entities": [],
        "formats": [],
        "devices": [],
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
                for level, message in self.image_sync.sync_device(
                    device,
                    client,
                    self.config["config_dir"],
                    status,
                    self.ha,
                ):
                    getattr(LOGGER, level)("%s: %s", name, message)
            except BridgeError as exc:
                LOGGER.error("%s: initialization failed: %s", name, exc)

    def run_once(self) -> None:
        states = self.ha.states(self.config["entities"])
        for alias, state in states.items():
            if not state.available:
                LOGGER.warning("%s (%s) is %s", alias, state.entity_id, state.state)
        for device in self.config["devices"]:
            name = device["name"]
            if not self.dry_run:
                try:
                    for level, message in self.image_sync.sync_device(
                        device,
                        self.clients[name],
                        self.config["config_dir"],
                        ha=self.ha,
                    ):
                        getattr(LOGGER, level)("%s: %s", name, message)
                except BridgeError as exc:
                    LOGGER.error("%s: image update failed: %s", name, exc)
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


def _runtime_config(
    options: dict[str, Any], store: UIConfigurationStore
) -> tuple[dict[str, Any], bool]:
    if store.exists:
        ui_options = store.read()
        config = config_from_options(ui_options)
        LOGGER.info(
            "using ingress configuration with %d device(s)", len(config["devices"])
        )
        return config, bool(ui_options.get("dry_run", options["dry_run"]))
    if options.get("devices"):
        config = config_from_options(options)
        LOGGER.warning(
            "using Configuration-tab settings; open the add-on Web UI and save to migrate"
        )
        return config, bool(options["dry_run"])
    config_path = Path(str(options["config_file"]))
    if config_path.is_file():
        config = load_config(config_path)
        LOGGER.warning(
            "using legacy configuration file %s; open the add-on Web UI to migrate",
            config_path,
        )
        return config, bool(options["dry_run"])
    raise ConfigurationError(
        "no device is configured yet; open the add-on Web UI, add a KAC device, "
        "and save the configuration"
    )


def main() -> int:
    server: ConfigurationServer | None = None
    try:
        options = _load_options()
        logging.basicConfig(
            level=getattr(logging, str(options["log_level"]).upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(message)s",
        )
        shutdown_event = threading.Event()
        reload_event = threading.Event()

        def stop(*_: Any) -> None:
            shutdown_event.set()
            reload_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        editor_options = options
        legacy_path = Path(str(options["config_file"]))
        if not options.get("devices") and legacy_path.is_file():
            try:
                editor_options = options_from_config(load_config(legacy_path), options)
                LOGGER.info("prepared legacy configuration for migration in the Web UI")
            except ConfigurationError as exc:
                LOGGER.warning("cannot prepare legacy configuration for Web UI: %s", exc)
        store = UIConfigurationStore(UI_CONFIG_PATH, editor_options)
        editor_ha = HomeAssistantClient(
            os.environ.get("SUPERVISOR_TOKEN", ""),
            float(options["home_assistant_timeout_seconds"]),
        )
        server = ConfigurationServer(store, editor_ha, reload_event)
        server.start()
        LOGGER.info("graphical editor is available through the add-on Web UI")

        while not shutdown_event.is_set():
            reload_event.clear()
            try:
                config, dry_run = _runtime_config(options, store)
            except ConfigurationError as exc:
                LOGGER.error("configuration error: %s", exc)
                reload_event.wait()
                continue

            bridge = Bridge(config, dry_run)
            bridge.initialize_devices()
            interval = config["update_interval_seconds"]
            while not shutdown_event.is_set() and not reload_event.is_set():
                try:
                    bridge.run_once()
                except BridgeError as exc:
                    LOGGER.error("update cycle failed: %s", exc)
                except Exception:
                    LOGGER.exception("unexpected update-cycle failure")
                reload_event.wait(interval)
            if reload_event.is_set() and not shutdown_event.is_set():
                LOGGER.info("configuration changed; reloading bridge")
        return 0
    except OSError as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("cannot start graphical editor: %s", exc)
        return 1
    except ConfigurationError as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("configuration error: %s", exc)
        return 2
    except BridgeError as exc:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        LOGGER.error("startup failed: %s", exc)
        return 1
    finally:
        if server is not None:
            server.stop()


if __name__ == "__main__":
    sys.exit(main())
