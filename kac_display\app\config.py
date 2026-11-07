"""Load and validate the detailed YAML configuration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

import yaml

from .errors import ConfigurationError


ROW_TYPES = {
    "heading": "h",
    "value": "k",
    "down": "d",
    "up": "u",
    "bar": "b",
    "big": "g",
    "sparkline": "s",
    "empty": "-",
    "h": "h",
    "k": "k",
    "d": "d",
    "u": "u",
    "b": "b",
    "g": "g",
    "s": "s",
    "-": "-",
}


def _fail(path: str, message: str) -> None:
    raise ConfigurationError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be a mapping")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be a list")
    return value


def _number_in(value: Any, low: float, high: float, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a number")
    if not low <= float(value) <= high:
        _fail(path, f"must be between {low:g} and {high:g}")


def _int_in(value: Any, low: int, high: int, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "must be an integer")
    if not low <= value <= high:
        _fail(path, f"must be between {low} and {high}")


def _read_key(device: dict[str, Any], base_dir: Path, path: str) -> str:
    has_key = "key" in device
    has_file = "key_file" in device
    if has_key == has_file:
        _fail(path, "set exactly one of key or key_file")
    if has_file:
        key_path = Path(str(device["key_file"]))
        if not key_path.is_absolute():
            key_path = base_dir / key_path
        try:
            key = key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            _fail(f"{path}.key_file", f"cannot be read: {exc}")
    else:
        key = str(device["key"])
    if not 1 <= len(key) <= 32 or any(ord(c) < 0x21 or ord(c) > 0x7E for c in key):
        _fail(path, "device key must contain 1–32 printable ASCII characters without spaces")
    return key


def _validate_row(
    row: Any,
    path: str,
    entities: dict[str, str],
    formats: dict[str, str],
) -> dict[str, Any]:
    row = deepcopy(_mapping(row, path))
    kind = row.get("type")
    if kind not in ROW_TYPES:
        _fail(f"{path}.type", f"must be one of {', '.join(sorted(ROW_TYPES))}")
    row["type"] = ROW_TYPES[kind]

    alias = row.get("entity")
    if alias is not None and alias not in entities:
        _fail(f"{path}.entity", f"unknown entity alias {alias!r}")
    format_name = row.get("format")
    if format_name is not None and format_name not in formats:
        _fail(f"{path}.format", f"unknown format {format_name!r}")
    if "format" in row and "value" in row:
        _fail(path, "use either format or value, not both")

    code = row["type"]
    if code in {"h", "k", "b", "g", "s"} and "label" not in row:
        _fail(path, f"row type {kind!r} requires label")
    if code in {"d", "u", "b"} and "percent" not in row and alias is None:
        _fail(path, f"row type {kind!r} requires percent or entity")
    if code == "s":
        has_values = "values" in row
        if (alias is None) == (not has_values):
            _fail(path, "sparkline requires exactly one of entity or values")
        if has_values:
            values = _list(row["values"], f"{path}.values")
            for index, value in enumerate(values):
                _number_in(value, -1e100, 1e100, f"{path}.values[{index}]")
        points = row.get("history_points", 20)
        if isinstance(points, bool) or not isinstance(points, int) or not 1 <= points <= 20:
            _fail(f"{path}.history_points", "must be an integer from 1 to 20")
        row["history_points"] = points
        if "scale_min" in row:
            _number_in(row["scale_min"], -1e100, 1e100, f"{path}.scale_min")
        if "scale_max" in row:
            _number_in(row["scale_max"], -1e100, 1e100, f"{path}.scale_max")
        if "scale_min" in row and "scale_max" in row and row["scale_min"] >= row["scale_max"]:
            _fail(path, "scale_max must be greater than scale_min")
    return row


def _validate_images(images: Any, path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    slots: set[int] = set()
    for index, raw in enumerate(_list(images, path)):
        item_path = f"{path}[{index}]"
        image = deepcopy(_mapping(raw, item_path))
        slot = image.get("slot")
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 5:
            _fail(f"{item_path}.slot", "must be an integer from 1 to 5")
        if slot in slots:
            _fail(f"{item_path}.slot", "is configured more than once")
        slots.add(slot)
        deleting = image.get("delete", False)
        if not isinstance(deleting, bool):
            _fail(f"{item_path}.delete", "must be true or false")
        if deleting:
            if "source" in image:
                _fail(item_path, "delete and source cannot be used together")
        elif not isinstance(image.get("source"), str) or not image["source"]:
            _fail(f"{item_path}.source", "is required unless delete is true")
        if image.get("fit", "cover") not in {"cover", "contain"}:
            _fail(f"{item_path}.fit", "must be cover or contain")
        if image.get("upload", "on_change") not in {"on_change", "startup"}:
            _fail(f"{item_path}.upload", "must be on_change or startup")
        quality = image.get("quality", 90)
        if isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
            _fail(f"{item_path}.quality", "must be an integer from 1 to 100")
        colors = image.get("gif_colors", 64)
        if isinstance(colors, bool) or not isinstance(colors, int) or not 2 <= colors <= 256:
            _fail(f"{item_path}.gif_colors", "must be an integer from 2 to 256")
        delay = image.get("gif_min_delay_ms", 100)
        if isinstance(delay, bool) or not isinstance(delay, int) or not 20 <= delay <= 60000:
            _fail(f"{item_path}.gif_min_delay_ms", "must be an integer from 20 to 60000")
        image.setdefault("fit", "cover")
        image.setdefault("upload", "on_change")
        image.setdefault("quality", 90)
        image.setdefault("gif_colors", 64)
        image.setdefault("gif_min_delay_ms", 100)
        result.append(image)
    return result


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a detailed config and return a normalized, validated mapping."""
    config_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"cannot read {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {config_path}: {exc}") from exc
    config = deepcopy(_mapping(raw, "configuration"))

    if config.get("version") != 1:
        _fail("version", "must be 1")
    interval = config.get("update_interval_seconds", 10)
    _number_in(interval, 1, 3600, "update_interval_seconds")
    config["update_interval_seconds"] = float(interval)
    if config.get("text_mode", "transliterate") not in {"transliterate", "strict"}:
        _fail("text_mode", "must be transliterate or strict")
    config.setdefault("text_mode", "transliterate")

    ha = _mapping(config.get("home_assistant", {}), "home_assistant")
    timeout = ha.get("timeout_seconds", 10)
    _number_in(timeout, 1, 120, "home_assistant.timeout_seconds")
    ha["timeout_seconds"] = float(timeout)
    config["home_assistant"] = ha

    entities = _mapping(config.get("entities", {}), "entities")
    for alias, entity_id in entities.items():
        if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
            _fail("entities", f"invalid alias {alias!r}")
        if not isinstance(entity_id, str) or "." not in entity_id or any(c.isspace() for c in entity_id):
            _fail(f"entities.{alias}", "must be a Home Assistant entity_id")
    config["entities"] = entities

    formats = _mapping(config.get("formats", {}), "formats")
    for name, template in formats.items():
        if not isinstance(name, str) or not isinstance(template, str):
            _fail("formats", "names and templates must be strings")
    config["formats"] = formats

    devices: list[dict[str, Any]] = []
    names: set[str] = set()
    for device_index, raw_device in enumerate(_list(config.get("devices"), "devices")):
        path_prefix = f"devices[{device_index}]"
        device = deepcopy(_mapping(raw_device, path_prefix))
        name = device.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            _fail(f"{path_prefix}.name", "must contain only letters, digits, dot, underscore, or hyphen")
        if name in names:
            _fail(f"{path_prefix}.name", "must be unique")
        names.add(name)
        host = device.get("host")
        if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
            _fail(f"{path_prefix}.host", "must be an IP address or host name without http://, port, or path")
        device["key"] = _read_key(device, config_path.parent, path_prefix)
        device.pop("key_file", None)
        timeout = device.get("timeout_seconds", 10)
        _number_in(timeout, 1, 120, f"{path_prefix}.timeout_seconds")
        device["timeout_seconds"] = float(timeout)

        settings = deepcopy(_mapping(device.get("settings", {}), f"{path_prefix}.settings"))
        allowed_settings = {"rotation_seconds", "brightness", "timezone", "brightness_schedule"}
        unknown_settings = set(settings) - allowed_settings
        if unknown_settings:
            _fail(f"{path_prefix}.settings", f"unknown keys: {', '.join(sorted(unknown_settings))}")
        if "rotation_seconds" in settings:
            _int_in(settings["rotation_seconds"], 5, 255, f"{path_prefix}.settings.rotation_seconds")
        if "brightness" in settings:
            _int_in(settings["brightness"], 0, 100, f"{path_prefix}.settings.brightness")
        if "timezone" in settings:
            timezone = settings["timezone"]
            if (
                not isinstance(timezone, str)
                or not 3 <= len(timezone) <= 47
                or any(ord(char) < 0x20 or ord(char) > 0x7E for char in timezone)
            ):
                _fail(
                    f"{path_prefix}.settings.timezone",
                    "must be a 3–47 character printable ASCII POSIX time-zone string",
                )
        if "brightness_schedule" in settings:
            schedule = _mapping(settings["brightness_schedule"], f"{path_prefix}.settings.brightness_schedule")
            required = {"day", "night", "night_from", "night_until"}
            if set(schedule) != required:
                _fail(f"{path_prefix}.settings.brightness_schedule", f"must contain exactly {', '.join(sorted(required))}")
            _int_in(schedule["day"], 0, 100, f"{path_prefix}.settings.brightness_schedule.day")
            _int_in(schedule["night"], 0, 100, f"{path_prefix}.settings.brightness_schedule.night")
            _int_in(schedule["night_from"], 0, 23, f"{path_prefix}.settings.brightness_schedule.night_from")
            _int_in(schedule["night_until"], 0, 23, f"{path_prefix}.settings.brightness_schedule.night_until")
        device["settings"] = settings

        pages: list[dict[str, Any]] = []
        for page_index, raw_page in enumerate(_list(device.get("pages"), f"{path_prefix}.pages")):
            page_path = f"{path_prefix}.pages[{page_index}]"
            page = deepcopy(_mapping(raw_page, page_path))
            if not isinstance(page.get("title"), str):
                _fail(f"{page_path}.title", "is required and must be a string")
            rows = _list(page.get("rows"), f"{page_path}.rows")
            if len(rows) > 8:
                _fail(f"{page_path}.rows", "KAC supports at most 8 rows per page")
            page["rows"] = [
                _validate_row(row, f"{page_path}.rows[{row_index}]", entities, formats)
                for row_index, row in enumerate(rows)
            ]
            pages.append(page)
        if not pages:
            _fail(f"{path_prefix}.pages", "at least one text page is required")
        device["pages"] = pages
        device["images"] = _validate_images(device.get("images", []), f"{path_prefix}.images")
        devices.append(device)

    if not devices:
        _fail("devices", "at least one device is required")
    config["devices"] = devices
    config["config_dir"] = str(config_path.parent)
    return config


def kac_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Map friendly config names to documented KAC API fields."""
    result: dict[str, Any] = {}
    if "rotation_seconds" in settings:
        result["rot"] = int(settings["rotation_seconds"])
    if "brightness" in settings:
        result["b"] = int(settings["brightness"])
    if "timezone" in settings:
        result["tz"] = settings["timezone"]
    if "brightness_schedule" in settings:
        schedule = settings["brightness_schedule"]
        result.update(
            hell_tag=int(schedule["day"]),
            hell_nacht=int(schedule["night"]),
            nacht_von=int(schedule["night_from"]),
            nacht_bis=int(schedule["night_until"]),
        )
    return result
