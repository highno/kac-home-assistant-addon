"""Prepare local files for KAC's documented full-screen image slots."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageSequence

from .errors import ImageError
from .kac import KACClient


SIZE = 240
MAX_IMAGE_BYTES = 1024 * 1024


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


def prepare_image(source: Path, options: dict[str, Any]) -> tuple[bytes, str]:
    try:
        raw = source.read_bytes()
        image = Image.open(io.BytesIO(raw))
    except (OSError, Image.UnidentifiedImageError) as exc:
        raise ImageError(f"cannot open image {source}: {exc}") from exc
    frames = (
        [frame.copy() for frame in ImageSequence.Iterator(image)]
        if getattr(image, "is_animated", False)
        else [image.copy()]
    )
    if len(frames) == 1:
        output = io.BytesIO()
        _fit(frames[0], options["fit"]).save(
            output,
            "JPEG",
            quality=options["quality"],
            progressive=False,
            optimize=True,
        )
        data, extension = output.getvalue(), "jpg"
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
            f"prepared image {source} is {len(data)} bytes; KAC accepts at most 1 MB"
        )
    return data, extension


class ImageSynchronizer:
    def __init__(self, cache_path: str | Path) -> None:
        self.cache_path = Path(cache_path)
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.cache = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self.cache: dict[str, str] = {}

    @staticmethod
    def _fingerprint(source: Path, image: dict[str, Any]) -> str:
        digest = hashlib.sha256()
        try:
            digest.update(source.read_bytes())
        except OSError as exc:
            raise ImageError(f"cannot read image {source}: {exc}") from exc
        relevant = {
            key: image[key]
            for key in (
                "fit",
                "quality",
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
    ) -> list[str]:
        messages: list[str] = []
        media_status = (
            str((status or {}).get("medien", "")).split(",")
            if (status or {}).get("medien") is not None
            else []
        )
        prepared: list[tuple[dict[str, Any], Path | None, str, bytes | None, str | None]] = []
        for image in device["images"]:
            slot = image["slot"]
            if image.get("delete"):
                prepared.append((image, None, "deleted", None, None))
                continue
            source = Path(image["source"])
            if not source.is_absolute():
                source = Path(config_dir) / source
            fingerprint = self._fingerprint(source, image)
            data, extension = prepare_image(source, image)
            prepared.append((image, source, fingerprint, data, extension))

        if sum(extension == "gif" for _, _, _, _, extension in prepared) > 1:
            raise ImageError(
                f"{device['name']}: KAC permits only one GIF across image slots"
            )

        # Upload a GIF last because KAC restarts once after receiving its first GIF.
        prepared.sort(key=lambda item: item[4] == "gif")
        for image, source, fingerprint, data, extension in prepared:
            slot = image["slot"]
            cache_key = f"{device['name']}:{slot}"
            remote_raw = media_status[slot - 1] if len(media_status) >= slot else None
            remote_type = (
                "blocked" if remote_raw is not None and "!" in remote_raw else remote_raw
            )
            if image.get("delete"):
                if (
                    image["upload"] == "on_change"
                    and self.cache.get(cache_key) == fingerprint
                    and remote_type in {None, ""}
                ):
                    continue
                client.delete_image(slot)
                self.cache[cache_key] = fingerprint
                messages.append(f"deleted image slot {slot}")
                continue
            if (
                image["upload"] == "on_change"
                and self.cache.get(cache_key) == fingerprint
                and remote_type in {None, extension}
            ):
                messages.append(f"image slot {slot} unchanged")
                continue
            assert data is not None and extension is not None and source is not None
            client.upload_image(data, extension, slot)
            self.cache[cache_key] = fingerprint
            messages.append(
                f"uploaded {extension.upper()} to image slot {slot} ({len(data)} bytes)"
            )
        self.save()
        return messages

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.cache, separators=(",", ":")), encoding="utf-8"
        )
        temporary.replace(self.cache_path)
