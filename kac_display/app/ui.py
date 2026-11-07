"""Ingress configuration editor and static-image upload API."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import uuid

from PIL import Image, ImageSequence, UnidentifiedImageError

from .config import config_from_options
from .errors import BridgeError, ConfigurationError
from .ha import HomeAssistantClient


LOGGER = logging.getLogger("kac_bridge.ui")
MAX_REQUEST_BYTES = 10 * 1024 * 1024
STATIC_DIR = Path(__file__).with_name("static")


class UIConfigurationStore:
    """Persist the custom editor model and retain masked device keys."""

    def __init__(self, path: str | Path, initial_options: dict[str, Any]) -> None:
        self.path = Path(path)
        self.initial_options = deepcopy(initial_options)
        self.lock = threading.Lock()

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def read(self) -> dict[str, Any]:
        with self.lock:
            if not self.path.is_file():
                return deepcopy(self.initial_options)
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ConfigurationError(
                    f"cannot read graphical configuration {self.path}: {exc}"
                ) from exc
            if not isinstance(raw, dict):
                raise ConfigurationError(
                    f"graphical configuration {self.path} must contain an object"
                )
            return raw

    def public(self) -> dict[str, Any]:
        result = self.read()
        for device in result.get("devices", []):
            if not isinstance(device, dict):
                continue
            device["key_configured"] = bool(device.get("key"))
            device["key"] = ""
        return result

    def save(self, incoming: Any) -> dict[str, Any]:
        if not isinstance(incoming, dict):
            raise ConfigurationError("configuration must be a JSON object")
        candidate = deepcopy(incoming)
        current = self.read()
        old_keys = {
            device.get("name"): device.get("key")
            for device in current.get("devices", [])
            if isinstance(device, dict) and device.get("name") and device.get("key")
        }
        old_devices = [
            device
            for device in current.get("devices", [])
            if isinstance(device, dict)
        ]
        for index, device in enumerate(candidate.get("devices", [])):
            if not isinstance(device, dict):
                continue
            device.pop("key_configured", None)
            if not device.get("key"):
                old_key = old_keys.get(device.get("name"))
                if old_key is None and index < len(old_devices):
                    old_key = old_devices[index].get("key")
                if old_key:
                    device["key"] = old_key
        config_from_options(candidate)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        return self.public()


class ConfigurationServer:
    def __init__(
        self,
        store: UIConfigurationStore,
        ha: HomeAssistantClient,
        reload_event: threading.Event,
        port: int = 8099,
        upload_dir: str | Path = "/config/uploads",
    ) -> None:
        self.store = store
        self.ha = ha
        self.reload_event = reload_event
        self.port = port
        self.upload_dir = Path(upload_dir)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "KACConfig/1.0"

            def _allowed(self) -> bool:
                return self.client_address[0] in {
                    "127.0.0.1",
                    "::1",
                    "172.30.32.2",
                }

            def _headers(self, status: int, content_type: str, length: int) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                    "connect-src 'self'",
                )
                self.end_headers()

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self._headers(status, content_type, len(body))
                self.wfile.write(body)

            def _json(self, status: int, value: Any) -> None:
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self._send(status, body, "application/json; charset=utf-8")

            def _error(self, status: int, message: str) -> None:
                self._json(status, {"error": message})

            def _body(self) -> bytes:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ConfigurationError("invalid Content-Length") from exc
                if length < 1 or length > MAX_REQUEST_BYTES:
                    raise ConfigurationError("request body is empty or larger than 10 MB")
                return self.rfile.read(length)

            def do_GET(self) -> None:  # noqa: N802
                if not self._allowed():
                    self._error(HTTPStatus.FORBIDDEN, "ingress access required")
                    return
                parsed = urlparse(self.path)
                try:
                    if parsed.path in {"/", "/index.html"}:
                        body = (STATIC_DIR / "index.html").read_bytes()
                        self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")
                    elif parsed.path == "/api/config":
                        self._json(HTTPStatus.OK, parent.store.public())
                    elif parsed.path == "/api/entities":
                        self._json(HTTPStatus.OK, parent.ha.entity_catalog())
                    else:
                        self._error(HTTPStatus.NOT_FOUND, "not found")
                except BridgeError as exc:
                    self._error(HTTPStatus.BAD_GATEWAY, str(exc))
                except OSError as exc:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

            def do_POST(self) -> None:  # noqa: N802
                if not self._allowed():
                    self._error(HTTPStatus.FORBIDDEN, "ingress access required")
                    return
                parsed = urlparse(self.path)
                try:
                    body = self._body()
                    if parsed.path == "/api/config":
                        try:
                            value = json.loads(body.decode("utf-8"))
                        except (UnicodeDecodeError, ValueError) as exc:
                            raise ConfigurationError(f"invalid JSON: {exc}") from exc
                        saved = parent.store.save(value)
                        parent.reload_event.set()
                        self._json(HTTPStatus.OK, saved)
                    elif parsed.path == "/api/upload":
                        query = parse_qs(parsed.query)
                        filename = unquote(query.get("filename", ["image"])[0])
                        source = parent._save_upload(filename, body)
                        self._json(HTTPStatus.CREATED, {"source": source})
                    else:
                        self._error(HTTPStatus.NOT_FOUND, "not found")
                except (ConfigurationError, UnidentifiedImageError) as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc))
                except OSError as exc:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

            def log_message(self, format: str, *args: Any) -> None:
                LOGGER.debug("UI %s - %s", self.client_address[0], format % args)

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, name="kac-config-ui", daemon=True
        )
        self.thread.start()

    def _save_upload(self, filename: str, data: bytes) -> str:
        image = Image.open(io.BytesIO(data))
        image_format = image.format or ""
        if getattr(image, "is_animated", False) or sum(
            1 for _ in ImageSequence.Iterator(image)
        ) != 1:
            raise ConfigurationError("the upload field accepts static images only")
        Image.open(io.BytesIO(data)).verify()
        extension = {
            "JPEG": ".jpg",
            "PNG": ".png",
            "WEBP": ".webp",
            "BMP": ".bmp",
        }.get(image_format)
        if extension is None:
            raise ConfigurationError(
                f"unsupported static image format {image_format or 'unknown'}"
            )
        stem = Path(filename).stem
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-") or "image"
        stored_name = f"{uuid.uuid4().hex[:10]}-{stem[:80]}{extension}"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        destination = self.upload_dir / stored_name
        destination.write_bytes(data)
        return f"uploads/{stored_name}"

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

