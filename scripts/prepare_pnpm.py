"""Install the project's pinned pnpm without global npm/Corepack or expiring caches."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def download(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def extract_verified_package(payload: bytes, integrity: str, destination: Path) -> None:
    algorithm, digest = integrity.split("-", 1)
    if algorithm != "sha512" or base64.b64encode(hashlib.sha512(payload).digest()).decode() != digest:
        raise ValueError("pnpm archive SHA-512 verification failed")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        # Only unpack regular files/directories beneath package/. No links or devices.
        for member in archive.getmembers():
            path = (destination / member.name).resolve()
            if not path.is_relative_to((destination / "package").resolve()):
                raise ValueError("pnpm archive contains an unsafe path")
            if not member.isfile() and not member.isdir():
                raise ValueError("pnpm archive contains an unsupported entry")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)


def prepare(version: str, output_dir: Path) -> Path:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("An exact pnpm version is required")
    metadata = json.loads(download(f"https://registry.npmjs.org/pnpm/{version}"))
    tarball_url = metadata["dist"]["tarball"]
    if urllib.parse.urlparse(tarball_url).hostname != "registry.npmjs.org":
        raise ValueError("Unexpected pnpm archive host")
    payload = download(tarball_url)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pnpm-", dir=output_dir) as temporary:
        staging = Path(temporary)
        extract_verified_package(payload, metadata["dist"]["integrity"], staging)
        cli = staging / "package" / "bin" / "pnpm.cjs"
        if not cli.is_file():
            raise ValueError("pnpm archive has no CLI entry point")
        package = output_dir / "package"
        if package.exists():
            package.rename(output_dir / f"package.invalid-{uuid.uuid4().hex}")
        (staging / "package").rename(package)
    return output_dir / "package" / "bin" / "pnpm.cjs"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.version, args.output_dir))
