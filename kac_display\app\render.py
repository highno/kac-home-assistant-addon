"""Render configured pages into the documented KAC JSON shape."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import unicodedata
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .errors import RenderError
from .ha import HAState


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
        except TemplateError as exc:
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
                    str(key): [float(item) for item in value[-20:]]
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


def _percent(value: Any, path: str) -> int:
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RenderError(f"{path}: expected a number, got {value!r}") from exc
    return max(0, min(100, round(numeric)))


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
        context = self._context(states, row.get("entity"))
        result: dict[str, Any] = {"y": code}
        if code in {"h", "k", "b", "g", "s"}:
            label_limit = 7 if code == "s" else 27
            label = self.templates.render(row["label"], context)
            result["l"] = sanitize_text(label, label_limit, self.text_mode)
        result["v"] = self._render_value(row, context)

        if code in {"d", "u", "b"}:
            source = row.get("percent", context["value"])
            result["p"] = _percent(
                self.templates.render(source, context), f"{history_key}.percent"
            )
        if code == "s":
            if "values" in row:
                samples = [float(value) for value in row["values"]][-20:]
            else:
                try:
                    current = float(context["value"])
                except (TypeError, ValueError) as exc:
                    raise RenderError(
                        f"{history_key}: sparkline entity state is not numeric: {context['value']!r}"
                    ) from exc
                samples = self.history.append(
                    history_key, current, row["history_points"]
                )
            low = float(row.get("scale_min", 0))
            high = float(row.get("scale_max", max(samples + [1.0])))
            if high <= low:
                high = low + 1
            result["w"] = [
                _percent(100 * (sample - low) / (high - low), history_key)
                for sample in samples[-20:]
            ]
        if "alert" in row:
            rendered = self.templates.render(row["alert"], context)
            result["a"] = int(_as_bool(rendered, f"{history_key}.alert"))
        return result

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
