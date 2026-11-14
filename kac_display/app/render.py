"""Render configured pages into the documented KAC JSON shape."""

from __future__ import annotations

from collections import deque
import json
import logging
from math import isfinite
from pathlib import Path
import unicodedata
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .errors import RenderError
from .ha import HAState


LOGGER = logging.getLogger(__name__)


_TRANSLITERATIONS = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
        "’": "'",
        "“": '"',
        "”": '"',
        "→": ">",
        "←": "<",
    }
)


def sanitize_text(value: Any, max_bytes: int, mode: str) -> str:
    """Return text that KAC can display: printable ASCII plus the degree sign."""
    text = str(value)
    if mode == "transliterate":
        text = text.translate(_TRANSLITERATIONS)
        degree_marker = "\x00DEGREE\x00"
        text = text.replace("°", degree_marker)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = text.replace(degree_marker, "°")
        text = "".join(
            c if c == "°" or 0x20 <= ord(c) <= 0x7E else "?" for c in text
        )
    else:
        invalid = [c for c in text if c != "°" and not 0x20 <= ord(c) <= 0x7E]
        if invalid:
            raise RenderError(
                f"text {text!r} contains characters unsupported by KAC: {invalid!r}"
            )
    result: list[str] = []
    used = 0
    for char in text:
        encoded = char.encode("utf-8")
        if used + len(encoded) > max_bytes:
            break
        result.append(char)
        used += len(encoded)
    return "".join(result)


class TemplateEngine:
    def __init__(self) -> None:
        self.environment = SandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._cache: dict[str, Any] = {}

    def render(self, value: Any, context: dict[str, Any]) -> str:
        if not isinstance(value, str):
            return str(value)
        try:
            template = self._cache.get(value)
            if template is None:
                template = self.environment.from_string(value)
                self._cache[value] = template
            return template.render(context)
        except (TemplateError, ArithmeticError, TypeError, ValueError) as exc:
            raise RenderError(f"template {value!r} failed: {exc}") from exc


class HistoryStore:
    """Small persistent numeric history used for KAC sparkline rows."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.values: dict[str, list[float]] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.values = {
                    str(key): [
                        number for number in map(float, value[-20:]) if isfinite(number)
                    ]
                    for key, value in raw.items()
                    if isinstance(value, list)
                }
        except (OSError, ValueError, TypeError):
            self.values = {}

    def append(self, key: str, value: float, points: int) -> list[float]:
        history = deque(self.values.get(key, []), maxlen=points)
        history.append(float(value))
        self.values[key] = list(history)
        return self.values[key]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.values, separators=(",", ":")), encoding="utf-8"
        )
        temporary.replace(self.path)


def _as_bool(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"", "0", "false", "no", "off", "none", "null"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    raise RenderError(f"{path}: alert template returned non-boolean value {value!r}")


def _number(value: Any, path: str) -> float:
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RenderError(f"{path}: expected a number, got {value!r}") from exc
    if not isfinite(numeric):
        raise RenderError(f"{path}: expected a finite number, got {value!r}")
    return numeric


def _percent(value: Any, path: str) -> int:
    return round(max(0, min(100, _number(value, path))))


class PageRenderer:
    def __init__(
        self,
        formats: dict[str, str],
        text_mode: str,
        history: HistoryStore,
    ) -> None:
        self.formats = formats
        self.text_mode = text_mode
        self.history = history
        self.templates = TemplateEngine()

    @staticmethod
    def _context(
        states: dict[str, HAState], alias: str | None = None
    ) -> dict[str, Any]:
        selected = states.get(alias) if alias else None
        return {
            "entities": states,
            "states": states,
            "entity": selected,
            "value": selected.state if selected else "",
            "attributes": selected.attributes if selected else {},
            "available": selected.available if selected else True,
        }

    def _render_value(
        self, row: dict[str, Any], context: dict[str, Any]
    ) -> str:
        if "format" in row:
            source = self.formats[row["format"]]
        elif "value" in row:
            source = row["value"]
        elif row.get("entity"):
            source = "{{ value }}"
        else:
            source = ""
        return sanitize_text(
            self.templates.render(source, context), 27, self.text_mode
        )

    def _render_row(
        self,
        row: dict[str, Any],
        states: dict[str, HAState],
        history_key: str,
    ) -> dict[str, Any]:
        code = row["type"]
        if code == "-":
            return {"y": "-"}
        alias = row.get("entity")
        context = self._context(states, alias)
        result: dict[str, Any] = {"y": code}
        label = ""
        try:
            if code in {"h", "k", "b", "g", "s"}:
                label_limit = 7 if code == "s" else 27
                # Keep a readable label if its template cannot use the current state.
                label = sanitize_text(alias or "", label_limit, self.text_mode)
                label = sanitize_text(
                    self.templates.render(row["label"], context), label_limit, self.text_mode
                )
                result["l"] = label
            if alias and (
                context["entity"] is None
                or not context["available"]
                or not context["value"].strip()
            ):
                raise RenderError(f"{history_key}: missing state for {alias!r}")
            result["v"] = self._render_value(row, context)
            if "alert" in row:
                rendered = self.templates.render(row["alert"], context)
                result["a"] = int(_as_bool(rendered, f"{history_key}.alert"))
            if code in {"d", "u", "b"}:
                source = (
                    self.templates.render(row["percent"], context)
                    if "percent" in row
                    else context["value"]
                )
                result["p"] = _percent(source, f"{history_key}.percent")
            if code == "s":
                result["w"] = self._sparkline(row, context, history_key)
            return result
        except RenderError as exc:
            LOGGER.debug("%s: displaying N/A: %s", history_key, exc)
            return {"y": "k", "l": label, "v": "N/A"}

    def _sparkline(
        self, row: dict[str, Any], context: dict[str, Any], history_key: str
    ) -> list[int]:
        if "values" in row:
            samples = [float(value) for value in row["values"]][-20:]
        else:
            current = _number(context["value"], history_key)
            samples = self.history.append(history_key, current, row["history_points"])
        low = float(row.get("scale_min", 0))
        high = float(row.get("scale_max", max(samples + [1.0])))
        if high <= low:
            high = low + 1
            if high == low:
                return [100 if sample > low else 0 for sample in samples]
        return [
            round(100 * ((min(high, max(low, sample)) - low) / (high - low)))
            for sample in samples[-20:]
        ]

    def render_device(
        self, device: dict[str, Any], states: dict[str, HAState]
    ) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        global_context = self._context(states)
        for page_index, page in enumerate(device["pages"]):
            title = self.templates.render(page["title"], global_context)
            rows = [
                self._render_row(
                    row,
                    states,
                    f"{device['name']}:{page_index}:{row_index}",
                )
                for row_index, row in enumerate(page["rows"])
            ]
            pages.append(
                {
                    "t": sanitize_text(title, 15, self.text_mode),
                    "z": rows,
                }
            )
        return pages
