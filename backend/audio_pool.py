"""Set WH3's audio budget before its first thread runs, without a proxy DLL.

The profile is shared with the tower MOD's audio-pool512-1 fallback. Both
recognize the exact same six-byte replacement; neither adds to an existing pool.
Only the child created by this call is accessed. The executable on disk is read
only, and any validation/write failure aborts that still-suspended child.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import struct
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
TARGET_BYTES = 512 << 20


class AudioPoolError(ValueError):
    """Messages are localization keys, translated by the existing error UI."""


@dataclass(frozen=True)
class AudioPoolProfile:
    game_version: str
    exe_sha256: str
    exe_bytes: int
    image_size: int
    timestamp: int
    anchor_rva: int
    anchor: bytes
    patch_offset: int
    patch: bytes
    region_rva: int
    capacity_rva: int
    pointers_rva: int

    @property
    def patched_anchor(self) -> bytes:
        end = self.patch_offset + len(self.patch)
        return self.anchor[:self.patch_offset] + self.patch + self.anchor[end:]


WH3_AUDIO_PROFILE = AudioPoolProfile(
    game_version="9.0.5.0",
    exe_sha256="d2a8a58288bf8bd86768f21ff6be036cebb1916f9c312999c60afc1abe13789f",
    exe_bytes=237842896, image_size=0xE53A000, timestamp=0x6AE2A00B,
    anchor_rva=0x5A16CA,
    anchor=bytes.fromhex("2500009001480500007002488944246033c04889442478e8c6861d00413bc50f"),
    patch_offset=5, patch=bytes.fromhex("b80000002090"),
    region_rva=0x3F74280, capacity_rva=0x3F742B8, pointers_rva=0x3F742E0,
)


def _verify_executable(executable: Path, profile: AudioPoolProfile) -> None:
    with executable.open("rb") as source:
        if os.fstat(source.fileno()).st_size != profile.exe_bytes:
            raise AudioPoolError("audioPool.unsupportedVersion")
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != profile.exe_sha256:
        raise AudioPoolError("audioPool.unsupportedVersion")


def _verify_image_header(header: bytes, profile: AudioPoolProfile) -> None:
    valid = False
    if header[:2] == b"MZ" and len(header) >= 64:
        pe = struct.unpack_from("<I", header, 0x3C)[0]
        if 64 <= pe <= 2048 and pe + 84 <= len(header):
            valid = (
                header[pe:pe + 4] == b"PE\0\0"
                and struct.unpack_from("<H", header, pe + 4)[0] == 0x8664
                and struct.unpack_from("<I", header, pe + 8)[0] == profile.timestamp
                and struct.unpack_from("<H", header, pe + 24)[0] == 0x20B
                and struct.unpack_from("<I", header, pe + 80)[0] == profile.image_size
            )
    if not valid:
        raise AudioPoolError("audioPool.signatureMismatch")


def _patch_suspended_image(memory: Any, base: int, profile: AudioPoolProfile) -> str:
    _verify_image_header(memory.read(base, 4096), profile)
    anchor = memory.read(base + profile.anchor_rva, len(profile.anchor))
    if anchor not in (profile.anchor, profile.patched_anchor):
        raise AudioPoolError("audioPool.signatureMismatch")
    for rva, size in ((profile.region_rva, 8), (profile.capacity_rva, 40), (profile.pointers_rva, 40)):
        if memory.read(base + rva, size) != bytes(size):
            raise AudioPoolError("audioPool.alreadyInitialized")
    if anchor == profile.patched_anchor:
        return "already_patched"
    memory.write(base + profile.anchor_rva + profile.patch_offset, profile.patch)
    if memory.read(base + profile.anchor_rva, len(profile.anchor)) != profile.patched_anchor:
        raise AudioPoolError("audioPool.signatureMismatch")
    return "applied"


@contextmanager
def _executable_lock(executable: Path):
    # Prevent a concurrent Steam update/replacement between hashing and mapping.
    if os.name != "nt":
        yield
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(executable), 0x80000000, 1, None, 3, 0x80, None)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


class _WindowsChild:
    """Own both CreateProcess handles until patching and ResumeThread finish."""

    def __init__(self, process_handle: int, thread_handle: int, pid: int):
        from ctypes import wintypes
        import _winapi

        self._api = _winapi
        self._process = process_handle
        self._thread = thread_handle
        self.pid = pid
        self._returncode = None
        self._poll_lock = threading.Lock()
        self.memory = self
        self._kernel = kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.ReadProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
        kernel.ReadProcessMemory.restype = wintypes.BOOL
        kernel.WriteProcessMemory.argtypes = kernel.ReadProcessMemory.argtypes
        kernel.WriteProcessMemory.restype = wintypes.BOOL
        kernel.VirtualProtectEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
        kernel.VirtualProtectEx.restype = wintypes.BOOL
        kernel.FlushInstructionCache.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t)
        kernel.FlushInstructionCache.restype = wintypes.BOOL
        kernel.ResumeThread.argtypes = (wintypes.HANDLE,)
        kernel.ResumeThread.restype = wintypes.DWORD

    @classmethod
    def create(cls, executable: Path, arguments: list[str], cwd: Path,
               env: dict[str, str], creationflags: int):
        import _winapi

        process, thread, pid, _tid = _winapi.CreateProcess(
            str(executable), subprocess.list2cmdline([str(executable), *arguments]),
            None, None, False, creationflags | 0x4 | 0x400,  # SUSPENDED | UNICODE_ENVIRONMENT
            env, str(cwd), subprocess.STARTUPINFO(),
        )
        try:
            return cls(process, thread, pid)
        except BaseException:
            try:
                _winapi.TerminateProcess(process, 1)
                _winapi.WaitForSingleObject(process, 5000)
            finally:
                _winapi.CloseHandle(thread)
                _winapi.CloseHandle(process)
            raise

    @property
    def image_base(self) -> int:
        from ctypes import wintypes

        class BasicInformation(ctypes.Structure):
            _fields_ = [("reserved1", ctypes.c_void_p), ("peb", ctypes.c_void_p),
                        ("reserved2", ctypes.c_void_p * 2), ("pid", ctypes.c_size_t),
                        ("reserved3", ctypes.c_void_p)]

        ntdll = ctypes.WinDLL("ntdll")
        query = ntdll.NtQueryInformationProcess
        query.argtypes = (wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                          wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))
        query.restype = wintypes.LONG
        info = BasicInformation()
        length = wintypes.ULONG()
        status = query(self._process, 0, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(length))
        if status < 0 or not info.peb or length.value != ctypes.sizeof(info):
            raise OSError(f"NtQueryInformationProcess failed: 0x{status & 0xFFFFFFFF:08x}")
        # 64-bit PEB's ImageBaseAddress; mapped image identity is checked again.
        base = struct.unpack("<Q", self.read(info.peb + 0x10, 8))[0]
        if not base or base & 0xFFFF:
            raise OSError("Invalid suspended process image base")
        return base

    def read(self, address: int, size: int) -> bytes:
        data = ctypes.create_string_buffer(size)
        done = ctypes.c_size_t()
        if not self._kernel.ReadProcessMemory(self._process, address, data, size, ctypes.byref(done)):
            raise ctypes.WinError(ctypes.get_last_error())
        if done.value != size:
            raise OSError("Short ReadProcessMemory")
        return data.raw

    def write(self, address: int, data: bytes) -> None:
        from ctypes import wintypes

        old = wintypes.DWORD()
        if not self._kernel.VirtualProtectEx(self._process, address, len(data), 0x40, ctypes.byref(old)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            done = ctypes.c_size_t()
            buffer = ctypes.create_string_buffer(data, len(data))
            if not self._kernel.WriteProcessMemory(self._process, address, buffer, len(data), ctypes.byref(done)):
                raise ctypes.WinError(ctypes.get_last_error())
            if done.value != len(data):
                raise OSError("Short WriteProcessMemory")
            if not self._kernel.FlushInstructionCache(self._process, address, len(data)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            unused = wintypes.DWORD()
            if not self._kernel.VirtualProtectEx(self._process, address, len(data), old.value, ctypes.byref(unused)):
                raise ctypes.WinError(ctypes.get_last_error())

    def resume(self) -> None:
        previous = self._kernel.ResumeThread(self._thread)
        if previous == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if previous != 1:
            raise OSError(f"Unexpected primary thread suspend count: {previous}")
        self._api.CloseHandle(self._thread)
        self._thread = None

    def abort(self) -> None:
        try:
            self._api.TerminateProcess(self._process, 1)
            self._api.WaitForSingleObject(self._process, 5000)
        finally:
            self.close()

    def poll(self) -> int | None:
        with self._poll_lock:
            if self._returncode is None and self._process:
                if self._api.WaitForSingleObject(self._process, 0) == 0:
                    self._returncode = self._api.GetExitCodeProcess(self._process)
                    self.close()
            return self._returncode

    def close(self) -> None:
        for attribute in ("_thread", "_process"):
            handle = getattr(self, attribute, None)
            if handle:
                self._api.CloseHandle(handle)
                setattr(self, attribute, None)

    def __del__(self):
        self.close()


def _launch_verified_process(executable: Path, arguments: list[str], cwd: Path,
                             env: dict[str, str], creationflags: int, profile: AudioPoolProfile):
    child = None
    try:
        with _executable_lock(executable):
            _verify_executable(executable, profile)
            child = _WindowsChild.create(executable, arguments, cwd, env, creationflags)
            state = _patch_suspended_image(child.memory, child.image_base, profile)
        # Release our file guard before any game/DRM initialization can run.
        child.resume()
    except BaseException:
        if child is not None:
            child.abort()
        raise
    receipt = {"state": state, "target_bytes": TARGET_BYTES, "game_version": profile.game_version,
               "exe_sha256": profile.exe_sha256, "method": "suspended_process_memory",
               "verification": "instruction_readback_before_initialization"}
    logger.info("Audio pool startup budget pid=%s %s", child.pid, receipt)
    return child, receipt


def launch_with_audio_pool(executable: Path, arguments: list[str], *, cwd: Path,
                          env: dict[str, str], creationflags: int):
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise AudioPoolError("audioPool.unsupportedPlatform")
    if executable.name.casefold() != "warhammer3.exe":
        raise AudioPoolError("audioPool.unsupportedVersion")
    try:
        return _launch_verified_process(executable, arguments, cwd, env, creationflags, WH3_AUDIO_PROFILE)
    except AudioPoolError:
        logger.exception("Audio pool startup rejected")
        raise
    except OSError as error:
        logger.exception("Unable to launch with audio pool expansion")
        raise AudioPoolError("audioPool.launchFailed") from error
