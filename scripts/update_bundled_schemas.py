"""Refresh the offline schema snapshot from an explicit rpfm-schemas commit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.table_schema import MAX_SCHEMA_BYTES, SCHEMA_NAMES, parse_schema  # noqa: E402


def refresh(revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full lowercase Git commit SHA")
    base_url = f"https://raw.githubusercontent.com/Frodo45127/rpfm-schemas/{revision}/"

    def download(name: str) -> bytes:
        with urlopen(Request(base_url + name, headers={"User-Agent": "wyccc-mod-manager"}), timeout=30) as response:
            raw = response.read(MAX_SCHEMA_BYTES + 1)
        if len(raw) > MAX_SCHEMA_BYTES:
            raise ValueError(f"schema exceeds size limit: {name}")
        return raw

    def schema(game: str) -> tuple[str, bytes, dict]:
        name = f"schema_{SCHEMA_NAMES[game]}.ron"
        raw = download(name)
        definitions = parse_schema(raw.decode("utf-8"))
        return name, gzip.compress(raw, compresslevel=9, mtime=0), {
            "file": name + ".gz",
            "source_url": base_url + name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "table_count": len(definitions),
        }

    # Validate all downloads before replacing any existing snapshot file.
    license_text = download("LICENSE")
    with ThreadPoolExecutor(max_workers=3) as pool:
        snapshots = list(pool.map(schema, SCHEMA_NAMES))
    destination = ROOT / "backend" / "schemas"
    destination.mkdir(parents=True, exist_ok=True)
    for name, compressed, _info in snapshots:
        (destination / (name + ".gz")).write_bytes(compressed)
        print(f"{name}: {len(compressed):,} compressed bytes", flush=True)
    (destination / "LICENSE.txt").write_bytes(license_text)
    manifest = {
        "repository": "https://github.com/Frodo45127/rpfm-schemas",
        "revision": revision,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "games": {game: info for game, (_name, _raw, info) in zip(SCHEMA_NAMES, snapshots)},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Full upstream Git commit SHA")
    refresh(parser.parse_args().revision)
