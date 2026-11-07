"""Prepare local files for KAC's documented full-screen image slots."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import time
from typing import Any

from PIL import Image, ImageSequence

try:
    from cairosvg import svg2png
except ImportError:  # Covered by the container dependency; keeps errors actionable.
    svg2png = None

from .errors import BridgeError, ImageError
from .ha import HomeAssistantClient
from .kac import KACClient


SIZE = 240
MAX_IMAGE_BYTES = 1024 * 1024
_SVG_ATTRIBUTE_REFERENCE = re.compile(
    rb"(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
)
_SVG_CSS_REFERENCE = re.compile(rb"url\(\s*['\"]?([^)'\"]+)", re.IGNORECASE)


def _is_svg(raw: bytes) -> bool:
    if (
        raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM"))
        or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
    ):
        return False
    prefix = raw[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    return prefix.startswith(b"<") and re.search(rb"<svg(?:\s|>)", prefix) is not None


def _rasterize_svg(raw: bytes, source_name: str) -> bytes:
    if svg2png is None:
        raise ImageError(
            f"cannot rasterize SVG image {source_name}: CairoSVG is not installed"
        )
    if re.search(rb"@import\b", raw, re.IGNORECASE):
        raise ImageError(
            f"SVG image {source_name} contains an unsupported external reference"
        )
    for pattern in (_SVG_ATTRIBUTE_REFERENCE, _SVG_CSS_REFERENCE):
        for match in pattern.finditer(raw):
            target = match.group(1).strip().lower()
            if not (target.startswith(b"#") or target.startswith(b"data:")):
                raise ImageError(
                    f"SVG image {source_name} contains an unsupported external reference"
                )
    try:
        return svg2png(bytestring=raw, output_width=720, unsafe=False)
    except Exception as exc:
        raise ImageError(f"cannot rasterize SVG image {source_name}: {exc}") from exc


def _fit(frame: Image.Image, mode: str) -> Image.Image:
    frame = frame.convert("RGB")
    width, height = frame.size
    if width < 1 or height < 1:
        raise ImageError("image has an invalid size")
    resampling = Image.Resampling.LANCZOS
    if mode == "contain":
        scale = SIZE / max(width, height)
        resized = frame.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            resampling,
        )
        canvas = Image.new("RGB", (SIZE, SIZE), "black")
        canvas.paste(
            resized, ((SIZE - resized.width) // 2, (SIZE - resized.height) // 2)
        )
        return canvas
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return frame.crop((left, top, left + side, top + side)).resize(
        (SIZE, SIZE), resampling
    )


def _jpeg(frame: Image.Image, options: dict[str, Any]) -> bytes:
    """Encode at the highest useful quality that stays below the target size."""
    maximum_quality = int(options.get("quality", 70))
    target_bytes = int(options.get("max_jpeg_kb", 30)) * 1024
    smallest: bytes | None = None
    qualities = list(range(maximum_quality, 19, -5))
    if maximum_quality < 20:
        qualities = [maximum_quality]
    elif qualities[-1] != 20:
        qualities.append(20)
    for quality in qualities:
        output = io.BytesIO()
        frame.save(
            output,
            "JPEG",
            quality=quality,
            progressive=False,
            optimize=True,
            subsampling=2,
        )
        candidate = output.getvalue()
        smallest = candidate
        if len(candidate) <= target_bytes:
            return candidate
    assert smallest is not None
    return smallest


def prepare_image_bytes(
    raw: bytes, source_name: str, options: dict[str, Any]
) -> tuple[bytes, str]:
    if _is_svg(raw):
        raw = _rasterize_svg(raw, source_name)
    try:
        image = Image.open(io.BytesIO(raw))
    except (OSError, Image.UnidentifiedImageError) as exc:
        signature = raw[:12].hex() or "empty"
        raise ImageError(
            f"cannot open image {source_name} ({len(raw)} bytes, signature {signature}): {exc}"
        ) from exc
    frames = (
        [frame.copy() for frame in ImageSequence.Iterator(image)]
        if getattr(image, "is_animated", False)
        else [image.copy()]
    )
    if len(frames) == 1:
        data, extension = _jpeg(_fit(frames[0], options["fit"]), options), "jpg"
    else:
        delays = [
            max(options["gif_min_delay_ms"], int(frame.info.get("duration") or 0))
            for frame in frames
        ]
        rgb_frames = [_fit(frame, options["fit"]) for frame in frames]
        strip = Image.new("RGB", (SIZE, SIZE * len(rgb_frames)))
        for index, frame in enumerate(rgb_frames):
            strip.paste(frame, (0, index * SIZE))
        palette = strip.quantize(
            colors=options["gif_colors"], method=Image.Quantize.MEDIANCUT
        )
        paletted = [
            frame.quantize(palette=palette, dither=Image.Dither.NONE)
            for frame in rgb_frames
        ]
        output = io.BytesIO()
        paletted[0].save(
            output,
            "GIF",
            save_all=True,
            append_images=paletted[1:],
            duration=delays,
            loop=0,
            optimize=True,
            disposal=1,
        )
        data, extension = output.getvalue(), "gif"
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            f"prepared image {source_name} is {len(data)} bytes; KAC accepts at most 1 MB"
        )
    return data, extension


def prepare_image(source: Path, options: dict[str, Any]) -> tuple[bytes, str]:
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ImageError(f"cannot read image {source}: {exc}") from exc
    return prepare_image_bytes(raw, str(source), options)


class ImageSynchronizer:
    def __init__(self, cache_path: str | Path) -> None:
        self.cache_path = Path(cache_path)
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.cache = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self.cache: dict[str, str] = {}
        self.last_entity_fetch: dict[str, float] = {}

    @staticmethod
    def _fingerprint(raw: bytes, image: dict[str, Any]) -> str:
        digest = hashlib.sha256()
        digest.update(raw)
        relevant = {
            key: image[key]
            for key in (
                "fit",
                "quality",
                "max_jpeg_kb",
                "gif_colors",
                "gif_min_delay_ms",
            )
        }
        digest.update(json.dumps(relevant, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    def sync_device(
        self,
        device: dict[str, Any],
        client: KACClient,
        config_dir: str | Path,
        status: dict[str, Any] | None = None,
        ha: HomeAssistantClient | None = None,
    ) -> list[tuple[str, str]]:
        messages: list[tuple[str, str]] = []
        media_status = (
            str((status or {}).get("medien", "")).split(",")
            if (status or {}).get("medien") is not None
            else []
        )
        prepared: list[
            tuple[dict[str, Any], str | None, str, bytes | None, str | None]
        ] = []
        for image in device["images"]:
            slot = image["slot"]
            try:
                if image.get("delete"):
                    prepared.append((image, None, "deleted", None, None))
                    continue
                cache_key = f"{device['name']}:{slot}"
                if image.get("source_type", "file") == "entity":
                    now = time.monotonic()
                    if (
                        cache_key in self.last_entity_fetch
                        and now - self.last_entity_fetch[cache_key]
                        < image["refresh_seconds"]
                    ):
                        continue
                    if ha is None:
                        raise ImageError(
                            f"{device['name']}: Home Assistant image source requires an API client"
                        )
                    source_name = image["entity_id"]
                    raw = ha.entity_image(source_name)
                else:
                    source_path = Path(image["source"])
                    if not source_path.is_absolute():
                        source_path = Path(config_dir) / source_path
                    try:
                        raw = source_path.read_bytes()
                    except OSError as exc:
                        raise ImageError(f"cannot read image {source_path}: {exc}") from exc
                    source_name = str(source_path)
                fingerprint = self._fingerprint(raw, image)
                data, extension = prepare_image_bytes(raw, source_name, image)
                prepared.append((image, source_name, fingerprint, data, extension))
            except BridgeError as exc:
                messages.append(("error", f"image slot {slot} preparation failed: {exc}"))

        # Upload a GIF last because KAC restarts once after receiving its first GIF.
        prepared.sort(key=lambda item: item[4] == "gif")
        gif_seen = False
        for image, source_name, fingerprint, data, extension in prepared:
            slot = image["slot"]
            cache_key = f"{device['name']}:{slot}"
            remote_raw = media_status[slot - 1] if len(media_status) >= slot else None
            remote_type = (
                "blocked" if remote_raw is not None and "!" in remote_raw else remote_raw
            )
            try:
                if image.get("delete"):
                    if (
                        image["upload"] == "on_change"
                        and self.cache.get(cache_key) == fingerprint
                        and remote_type in {None, ""}
                    ):
                        continue
                    client.delete_image(slot)
                    self.cache[cache_key] = fingerprint
                    messages.append(("info", f"deleted image slot {slot}"))
                    continue
                if extension == "gif":
                    if gif_seen:
                        messages.append(
                            (
                                "error",
                                f"image slot {slot} skipped: KAC permits only one GIF across image slots",
                            )
                        )
                        continue
                    gif_seen = True
                if (
                    image["upload"] == "on_change"
                    and self.cache.get(cache_key) == fingerprint
                    and remote_type in {None, extension}
                ):
                    if image.get("source_type") == "entity":
                        self.last_entity_fetch[cache_key] = time.monotonic()
                    continue
                assert data is not None and extension is not None and source_name is not None
                client.upload_image(data, extension, slot)
                self.cache[cache_key] = fingerprint
                if image.get("source_type") == "entity":
                    self.last_entity_fetch[cache_key] = time.monotonic()
                messages.append(
                    (
                        "info",
                        f"uploaded {extension.upper()} from {source_name} to image slot {slot} ({len(data)} bytes)",
                    )
                )
            except BridgeError as exc:
                messages.append(("error", f"image slot {slot} update failed: {exc}"))
        self.save()
        return messages

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.cache, separators=(",", ":")), encoding="utf-8"
        )
        temporary.replace(self.cache_path)
