from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from backend import audio_pool
from backend.app_settings import SettingsService, default_settings
from backend.launcher import forget_launched_game, launch_game, launched_game_exit_code


def fixture_image():
    image = bytearray(0x5000)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x100)
    image[0x100:0x104] = b"PE\0\0"
    struct.pack_into("<H", image, 0x104, 0x8664)
    struct.pack_into("<I", image, 0x108, 12345)
    struct.pack_into("<H", image, 0x118, 0x20B)
    struct.pack_into("<I", image, 0x150, len(image))
    anchor = bytes.fromhex("2500009001480500007002488944246033c04889442478e8c6861d00413bc50f")
    image[0x1000:0x1020] = anchor
    profile = audio_pool.AudioPoolProfile(
        game_version="offline-fixture", exe_sha256=hashlib.sha256(image).hexdigest(),
        exe_bytes=len(image), image_size=len(image), timestamp=12345,
        anchor_rva=0x1000, anchor=anchor, patch_offset=5,
        patch=bytes.fromhex("b80000002090"), region_rva=0x2000,
        capacity_rva=0x2100, pointers_rva=0x2200,
    )
    return image, profile


class ImageMemory:
    base = 0x140000000

    def __init__(self, image):
        self.image = image
        self.writes = []

    def read(self, address, size):
        offset = address - self.base
        result = bytes(self.image[offset:offset + size])
        assert len(result) == size
        return result

    def write(self, address, data):
        offset = address - self.base
        self.image[offset:offset + len(data)] = data
        self.writes.append((offset, data))


def test_audio_pool_setting_defaults_off_and_survives_restart(tmp_path):
    assert default_settings()["enable_audio_pool_expansion"] is False
    service = SettingsService(tmp_path)
    service.save({"enable_audio_pool_expansion": True})
    assert SettingsService(tmp_path).get_public()["enable_audio_pool_expansion"] is True
    service.save({"enable_audio_pool_expansion": False})
    assert SettingsService(tmp_path).get()["enable_audio_pool_expansion"] is False


def test_only_budget_instruction_changes_and_duplicate_is_skipped():
    image, profile = fixture_image()
    before = bytes(image)
    memory = ImageMemory(image)
    assert audio_pool._patch_suspended_image(memory, memory.base, profile) == "applied"
    assert memory.writes == [(0x1005, profile.patch)]
    assert image[:0x1005] == before[:0x1005]
    assert image[0x100B:] == before[0x100B:]
    assert audio_pool._patch_suspended_image(memory, memory.base, profile) == "already_patched"
    assert len(memory.writes) == 1


@pytest.mark.parametrize("offset", range(32))
def test_unknown_instruction_bytes_are_never_overwritten(offset):
    image, profile = fixture_image()
    image[profile.anchor_rva + offset] ^= 1
    memory = ImageMemory(image)
    with pytest.raises(audio_pool.AudioPoolError, match="signatureMismatch"):
        audio_pool._patch_suspended_image(memory, memory.base, profile)
    assert memory.writes == []


@pytest.mark.parametrize("offset", [0x2000, *range(0x2100, 0x2128, 8), *range(0x2200, 0x2228, 8)])
def test_initialized_audio_pool_is_never_resized(offset):
    image, profile = fixture_image()
    image[offset] = 1
    memory = ImageMemory(image)
    with pytest.raises(audio_pool.AudioPoolError, match="alreadyInitialized"):
        audio_pool._patch_suspended_image(memory, memory.base, profile)
    assert memory.writes == []


@pytest.mark.parametrize("offset", [0, 0x100, 0x104, 0x108, 0x118, 0x150])
def test_mismatched_memory_image_is_rejected(offset):
    image, profile = fixture_image()
    image[offset] ^= 1
    memory = ImageMemory(image)
    with pytest.raises(audio_pool.AudioPoolError, match="signatureMismatch"):
        audio_pool._patch_suspended_image(memory, memory.base, profile)
    assert memory.writes == []


def test_budget_write_requires_successful_readback():
    image, profile = fixture_image()
    memory = ImageMemory(image)
    memory.write = Mock()  # A denied/short native write must never be reported as success.
    with pytest.raises(audio_pool.AudioPoolError, match="signatureMismatch"):
        audio_pool._patch_suspended_image(memory, memory.base, profile)


def test_unknown_executable_cannot_create_a_child(tmp_path):
    executable = tmp_path / "Warhammer3.exe"
    executable.write_bytes(b"different game build")
    with patch.object(audio_pool, "_WindowsChild") as child:
        with pytest.raises(audio_pool.AudioPoolError, match="unsupportedVersion"):
            audio_pool._launch_verified_process(executable, [], tmp_path, {}, 0, audio_pool.WH3_AUDIO_PROFILE)
    child.create.assert_not_called()


def test_same_sized_but_different_executable_hash_is_rejected(tmp_path):
    image, profile = fixture_image()
    image[-1] ^= 1
    executable = tmp_path / "audio_pool_fixture.exe"
    executable.write_bytes(image)
    with patch.object(audio_pool._WindowsChild, "create") as create:
        with pytest.raises(audio_pool.AudioPoolError, match="unsupportedVersion"):
            audio_pool._launch_verified_process(executable, [], tmp_path, {}, 0, profile)
    create.assert_not_called()


def test_failed_patch_aborts_only_its_own_suspended_child(tmp_path):
    image, profile = fixture_image()
    executable = tmp_path / "audio_pool_fixture.exe"
    executable.write_bytes(image)
    memory = ImageMemory(image)
    memory.image[0x1001] ^= 1
    child = Mock(pid=42, memory=memory, image_base=memory.base)
    with patch.object(audio_pool._WindowsChild, "create", return_value=child):
        with pytest.raises(audio_pool.AudioPoolError, match="signatureMismatch"):
            audio_pool._launch_verified_process(executable, [], tmp_path, {}, 0, profile)
    child.abort.assert_called_once_with()
    child.resume.assert_not_called()


def test_enabled_launcher_keeps_save_arguments_environment_and_exit_monitor(tmp_path):
    (tmp_path / "Warhammer3.exe").write_bytes(b"fixture, never executed")
    mod_list = tmp_path / "used_mods.txt"
    mod_list.write_text("")
    process = SimpleNamespace(pid=919191, poll=Mock(return_value=None))
    receipt = {"state": "applied", "target_bytes": 512 << 20}
    with (
        patch("backend.launcher.is_game_running", return_value=False),
        patch("backend.launcher.subprocess.Popen") as ordinary,
        patch("backend.launcher.launch_with_audio_pool", return_value=(process, receipt)) as early,
    ):
        try:
            result = launch_game(str(tmp_path), str(mod_list), "my campaign.save",
                                 app_id="1142710", enable_audio_pool_expansion=True)
            assert result["audio_pool"] == receipt
            assert result["pid"] == process.pid
            assert early.call_args.args[1] == ["game_startup_mode", "campaign_load", "my campaign.save", ";", "used_mods.txt;"]
            assert early.call_args.kwargs["env"]["SteamAppId"] == "1142710"
            ordinary.assert_not_called()
            process.poll.return_value = 7
            assert launched_game_exit_code(process.pid) == 7
        finally:
            forget_launched_game(process.pid)


def test_disabled_launcher_keeps_ordinary_startup(tmp_path):
    (tmp_path / "Warhammer3.exe").write_bytes(b"fixture, never executed")
    order = tmp_path / "used_mods.txt"
    order.write_text("")
    with (
        patch("backend.launcher.is_game_running", return_value=False),
        patch("backend.launcher.subprocess.Popen") as ordinary,
        patch("backend.launcher.launch_with_audio_pool") as early,
    ):
        ordinary.return_value.pid = 919192
        ordinary.return_value.poll.return_value = None
        try:
            launch_game(str(tmp_path), str(order))
            early.assert_not_called()
            ordinary.assert_called_once()
        finally:
            forget_launched_game(919192)


@pytest.mark.skipif(os.name != "nt" or struct.calcsize("P") != 8, reason="Windows x64 process API")
def test_real_suspended_fixture_observes_patch_at_entry_without_disk_changes(tmp_path):
    # Run a COPY of Python, never a game or any game launcher. Its DOS stub is
    # unused by Windows, so it provides a safe page for real remote patching.
    fixture_dir = tmp_path / "音频夹具"
    fixture_dir.mkdir()
    executable = fixture_dir / "audio_pool_fixture.exe"
    # The venv redirector cannot run after being copied away from pyvenv.cfg.
    source_executable = Path(sys._base_executable)
    shutil.copyfile(source_executable, executable)
    original = executable.read_bytes()
    pe = struct.unpack_from("<I", original, 0x3C)[0]
    assert struct.unpack_from("<H", original, pe + 4)[0] == 0x8664
    section_alignment = struct.unpack_from("<I", original, pe + 56)[0]
    header_size = struct.unpack_from("<I", original, pe + 84)[0]
    assert header_size < 0x800 and section_alignment >= 0x1000
    _, template = fixture_image()
    profile = replace(template, exe_sha256=hashlib.sha256(original).hexdigest(),
                      exe_bytes=len(original), image_size=struct.unpack_from("<I", original, pe + 80)[0],
                      timestamp=struct.unpack_from("<I", original, pe + 8)[0],
                      anchor_rva=0x40, anchor=original[0x40:0x60],
                      region_rva=0x800, capacity_rva=0x900, pointers_rva=0xA00)
    result_path = fixture_dir / "result.json"
    script = (
        "import ctypes,json,os,sys; k=ctypes.WinDLL('kernel32'); "
        "k.GetModuleHandleW.restype=ctypes.c_void_p; "
        "data={'patch':ctypes.string_at(k.GetModuleHandleW(None)+0x45,6).hex(),"
        "'pid':os.getpid(),'argv':sys.argv[2:],'cwd':os.getcwd(),'env':os.environ['WMM_AUDIO_TEST']}; "
        "open(sys.argv[1],'w',encoding='utf-8').write(json.dumps(data)); sys.exit(17)"
    )
    environment = dict(os.environ, PYTHONHOME=sys.base_prefix, WMM_AUDIO_TEST="测试 value")
    environment["PATH"] = str(source_executable.parent) + os.pathsep + environment.get("PATH", "")
    child, receipt = audio_pool._launch_verified_process(
        executable, ["-S", "-c", script, str(result_path), 'save 名称 "quoted"', "used_mods.txt;"],
        fixture_dir, environment, 0x08000000, profile,
    )
    try:
        deadline = time.monotonic() + 10
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child.poll() == 17
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result == {"patch": profile.patch.hex(), "pid": child.pid,
                          "argv": ['save 名称 "quoted"', "used_mods.txt;"],
                          "cwd": str(fixture_dir), "env": "测试 value"}
        assert receipt["state"] == "applied"
        assert executable.read_bytes() == original
        assert not (fixture_dir / "dinput8.dll").exists()
    finally:
        if child.poll() is None:
            child.abort()
