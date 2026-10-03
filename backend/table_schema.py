"""Read bundled or upstream versioned RPFM schemas for the selected game."""

from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

SCHEMA_NAMES = {
    "warhammer3": "wh3",
    "warhammer2": "wh2",
    "warhammer": "wh",
    "three_kingdoms": "3k",
    "pharaoh_dynasties": "ph_dyn",
    "pharaoh": "ph",
    "troy": "troy",
    "thrones_of_britannia": "tob",
    "attila": "att",
    "rome2": "rom2",
    "shogun2": "sho2",
}
SCHEMA_BASE_URL = "https://raw.githubusercontent.com/Frodo45127/rpfm-schemas/master/"
BUNDLED_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
MAX_SCHEMA_BYTES = 64 * 1024 * 1024
_TOKEN = re.compile(
    r'\s+|//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"|'
    r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*|[()\[\]{},:]",
    re.S,
)


class _RonReader:
    """The data-only RON subset used by RPFM schemas; never executes input."""

    def __init__(self, source: str):
        self.source = source
        self.cursor = 0
        self.current = self._next()

    def _next(self) -> str:
        while self.cursor < len(self.source):
            match = _TOKEN.match(self.source, self.cursor)
            if not match:
                raise ValueError("schemaUpdate.invalidSchema")
            self.cursor = match.end()
            token = match.group()
            if token.isspace() or token.startswith(("//", "/*")):
                continue
            return token
        return ""

    def take(self, expected: str | None = None) -> str:
        token = self.current
        if not token or (expected is not None and token != expected):
            raise ValueError("schemaUpdate.invalidSchema")
        self.current = self._next()
        return token

    def value(self):
        token = self.current
        if token in {"(", "[", "{"}:
            opener = self.take()
            closer = {"(": ")", "[": "]", "{": "}"}[opener]
            items, mapping = [], {}
            is_map = opener == "{"
            while self.current != closer:
                key = self.value()
                if self.current == ":":
                    is_map = True
                    self.take(":")
                    mapping[key] = self.value()
                else:
                    items.append(key)
                if self.current != closer:
                    self.take(",")
            self.take(closer)
            return mapping if is_map else items
        token = self.take()
        if token.startswith('"'):
            # RON unicode escapes use \u{...}, unlike JSON's \uXXXX.
            token = re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda m: chr(int(m[1], 16)), token)
            token = token.replace("\\'", "'").replace("\\0", "\\u0000")
            return json.loads(token)
        if token == "true":
            return True
        if token == "false":
            return False
        if token == "None":
            return None
        if re.fullmatch(r"-?\d+", token):
            return int(token)
        if token[0].isdigit() or token[0] == "-":
            return float(token)
        if self.current == "(":
            args = self.value()
            if token == "Some" and isinstance(args, list) and len(args) == 1:
                return args[0]
            return {"kind": token, "definition": args[0] if len(args) == 1 else args}
        return token


def parse_schema(source: str) -> dict:
    reader = _RonReader(source)
    root = reader.value()
    if reader.current or not isinstance(root, dict) or root.get("version") != 5:
        raise ValueError("schemaUpdate.invalidSchema")
    definitions = root.get("definitions")
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError("schemaUpdate.invalidSchema")
    result = {}
    patches = root.get("patches") or {}

    def compact(definition, table_patches):
        fields = []
        for field in definition["fields"]:
            field_type = field["field_type"]
            if isinstance(field_type, dict):
                field_type = {"kind": field_type["kind"], "definition": compact(field_type["definition"], {})}
            fields.append(
                {
                    "name": field["name"],
                    "type": field_type,
                    "default": table_patches.get(field["name"], {}).get(
                        "default_value", field.get("default_value")
                    ),
                    "bitwise": field.get("is_bitwise", 0),
                    "enum": field.get("enum_values", {}),
                    "colour": field.get("is_part_of_colour"),
                }
            )
        return {"version": definition["version"], "fields": fields}

    try:
        for name, versions in definitions.items():
            result[name] = [compact(item, patches.get(name, {})) for item in versions]
            if not result[name]:
                raise ValueError("schemaUpdate.invalidSchema")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("schemaUpdate.invalidSchema") from exc
    return result


def load_latest_schema(game_id: str, cache_dir: Path, *, prefer_bundled: bool = False) -> tuple[dict, dict]:
    """Use bundled definitions without network, or revalidate the upstream cache."""
    if game_id not in SCHEMA_NAMES:
        raise ValueError("schemaUpdate.unsupportedGame")
    name = f"schema_{SCHEMA_NAMES[game_id]}.ron"
    if prefer_bundled:
        try:
            with gzip.open(BUNDLED_SCHEMA_DIR / f"{name}.gz", "rb") as stream:
                raw = stream.read(MAX_SCHEMA_BYTES + 1)
            if len(raw) > MAX_SCHEMA_BYTES:
                raise ValueError("schemaUpdate.invalidSchema")
            schemas = parse_schema(raw.decode("utf-8"))
        except (OSError, EOFError, UnicodeError) as exc:
            raise ValueError("schemaUpdate.invalidSchema") from exc
        return schemas, {"source_url": SCHEMA_BASE_URL + name, "cached": False, "bundled": True}
    path = cache_dir / name
    metadata_path = path.with_suffix(".json")
    metadata = {}
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    headers = {"User-Agent": "wyccc-mod-manager", "Accept": "text/plain"}
    if path.is_file() and metadata.get("etag"):
        headers["If-None-Match"] = metadata["etag"]
    try:
        with urlopen(Request(SCHEMA_BASE_URL + name, headers=headers), timeout=30) as response:
            raw = response.read(MAX_SCHEMA_BYTES + 1)
            if len(raw) > MAX_SCHEMA_BYTES:
                raise ValueError("schemaUpdate.invalidSchema")
            schemas = parse_schema(raw.decode("utf-8"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
            temporary = Path(temporary_name)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(raw)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            metadata_path.write_text(json.dumps({"etag": response.headers.get("ETag", "")}), encoding="utf-8")
            return schemas, {"source_url": SCHEMA_BASE_URL + name, "cached": False}
    except (URLError, OSError) as exc:
        # 304 means a verified current cache. Network failures mean an explicitly
        # labelled cached definition, never silently claim it is the newest.
        if path.is_file():
            try:
                schemas = parse_schema(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise ValueError("schemaUpdate.downloadFailed") from exc
            return schemas, {
                "source_url": SCHEMA_BASE_URL + name,
                "cached": getattr(exc, "code", None) != 304,
            }
        raise ValueError("schemaUpdate.downloadFailed") from exc
