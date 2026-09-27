"""Lazy, bounded UI-image reads from the same Pack order as the unit catalogue."""
from __future__ import annotations

import base64
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

from .pack_reader import read_pack_index
from .start_options import _decompress_payload, _has_compression_frame

logger = logging.getLogger(__name__)
IMAGE_SUFFIXES = {".png", ".dds", ".tga", ".jpg", ".jpeg"}


def image_path(value: str) -> str:
    normalized = str(value).replace("\\", "/").casefold()
    if not normalized.startswith("ui/") or ".." in normalized.split("/"):
        return ""
    return normalized if Path(normalized).suffix in IMAGE_SUFFIXES else ""


@lru_cache(maxsize=96)
def _pack_image_index(path: str, size: int, mtime: int) -> dict[str, tuple[int, int, bool]]:
    # Read only the index: ui.pack is nearly 1 GB, but its image index is small.
    images = {}
    for entry in read_pack_index(Path(path)):
        name = image_path(entry.name)
        if name:
            images.setdefault(name, (entry.offset, entry.size, entry.compressed))
    return images


@lru_cache(maxsize=768)
def _image_data(path: str, size: int, mtime: int, name: str) -> str:
    offset, length, compressed = _pack_image_index(path, size, mtime)[name]
    if length > 32 * 1024 * 1024:
        return ""
    with Path(path).open("rb") as stream:
        stream.seek(offset)
        payload = stream.read(length)
    if len(payload) != length:
        raise ValueError("UI Pack changed while reading")
    if compressed or _has_compression_frame(payload):
        payload = _decompress_payload(payload, name)
    with Image.open(BytesIO(payload)) as source:
        if source.width * source.height > 32_000_000:
            return ""
        picture = source.convert("RGBA")
        picture.thumbnail((720, 720), Image.Resampling.LANCZOS)
        output = BytesIO()
        picture.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class EncyclopediaAssets:
    def __init__(self, paths: list[Path]):
        self.images: dict[str, tuple[str, int, int]] = {}
        self.warnings: list[str] = []
        for path in dict.fromkeys(paths):
            try:
                stat = path.stat()
                signature = (str(path), stat.st_size, stat.st_mtime_ns)
                for name in _pack_image_index(*signature):
                    # The first Pack wins for the same internal resource path.
                    self.images.setdefault(name, signature)
            except (OSError, ValueError) as exc:
                logger.warning("Cannot index catalogue images in %s: %s", path.name, exc)
                self.warnings.append(path.name)

    def resolve(self, *candidates: str) -> str:
        for candidate in candidates:
            name = image_path(candidate)
            if name in self.images:
                return name
            if name.endswith(".png") and name[:-4] + ".dds" in self.images:
                return name[:-4] + ".dds"
        return ""

    def read(self, names: list[str]) -> dict[str, str]:
        if not isinstance(names, list) or len(names) > 96 or not all(isinstance(n, str) for n in names):
            raise ValueError("Request at most 96 catalogue images at a time")
        result = {}
        for raw in dict.fromkeys(names):
            name = image_path(raw)
            signature = self.images.get(name)
            if not signature:
                result[raw] = ""
                continue
            try:
                stat = Path(signature[0]).stat()
                if (stat.st_size, stat.st_mtime_ns) != signature[1:]:
                    raise ValueError("UI Pack changed; refresh the catalogue")
                result[raw] = _image_data(*signature, name)
            except (OSError, ValueError, KeyError) as exc:
                logger.warning("Cannot read catalogue image %s: %s", name, exc)
                result[raw] = ""
        return result
