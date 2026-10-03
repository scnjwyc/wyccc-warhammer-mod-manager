import base64
import hashlib
import io
import tarfile

import pytest

from scripts.prepare_pnpm import extract_verified_package


def archive(name="package/bin/pnpm.cjs"):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        payload = b"console.log('11.7.0')"
        member = tarfile.TarInfo(name)
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))
    data = output.getvalue()
    return data, "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def test_extracts_integrity_checked_cli(tmp_path):
    data, integrity = archive()
    extract_verified_package(data, integrity, tmp_path)
    assert (tmp_path / "package/bin/pnpm.cjs").read_bytes() == b"console.log('11.7.0')"


def test_rejects_corrupted_download_before_writing(tmp_path):
    data, integrity = archive()
    with pytest.raises(ValueError, match="SHA-512"):
        extract_verified_package(data + b"corruption", integrity, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["../outside.txt", "package/../../outside.txt"])
def test_rejects_archive_path_escape(tmp_path, name):
    data, integrity = archive(name)
    with pytest.raises(ValueError, match="unsafe path"):
        extract_verified_package(data, integrity, tmp_path)
