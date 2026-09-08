"""Read-only bone identity adapter for an explicitly verified MMD executable.

This is a private-layout adapter, not a supported MMD API. No DLL injection or
remote execution is used. The process handle grants QUERY_INFORMATION | VM_READ
only; offsets are never used until the executable digest has been verified.
"""

from .ui_language import english_mode

import ctypes
import hashlib
import struct
from pathlib import Path

import psutil
import win32api
import win32process

from .ui_state import UIReader, parse_number

VERIFIED_SHA256 = "07516fd3bf1e6b1339836b6773a156f61bdd6f848eeb621fdda012375df313a1"
MAIN_POINTER_RVA = 0x1445F8
MODEL_TABLE = 0xBE8
SELECTED_MODEL = 0x13E0
BONE_POINTER = 0x2748
BONE_COUNT = 0x3110
SELECTED_BONE = 0x311C
OPERATION_MODE = 0x13E4
SELECTABLE_MODES = {0, 3, 4}
SELECT_MODE_BUTTON = 490  # ボーン操作 panel: 選択=490, BOX選択=491, 移動=492, 回転=493
BONE_STRIDE = 624
# Paired CP932 name buffers, measured in the same hash-verified runtime layout.
MODEL_NAME_JA, MODEL_NAME_EN = 8896, 8946
MAX_BONES = 65535

_read = ctypes.WinDLL("kernel32", use_last_error=True).ReadProcessMemory
_read.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_read.restype = ctypes.c_int


def decode_name(raw: bytes) -> str:
    # MMD's runtime name field is CP932 even if the original PMX uses Unicode.
    return raw.split(b"\0", 1)[0].decode("cp932", errors="strict")


_DIGESTS = {}


def executable_digest(executable):
    """SHA-256 of the MMD executable, cached per (path, size, mtime) so repeated opens do not re-hash the file."""
    try:
        stat = executable.stat()
        key = (str(executable), stat.st_size, stat.st_mtime_ns)
    except OSError:
        key = None
    digest = _DIGESTS.get(key) if key else None
    if digest is None:
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        if key:
            _DIGESTS.clear()
            _DIGESTS[key] = digest
    return digest


class BoneMemory:
    def __init__(self, target):
        process = psutil.Process(target.pid)
        if process.create_time() != target.process_started:
            raise RuntimeError("MMD process changed before bone inspection.")
        executable = Path(process.exe())
        if executable_digest(executable) != VERIFIED_SHA256:
            raise ValueError("Bone identity requires the verified Japanese MMD 9.32 x64 executable. This executable is unsupported.")
        self.handle = win32api.OpenProcess(0x0410, False, target.pid)
        try:
            modules = win32process.EnumProcessModules(self.handle)
            if not modules or Path(win32process.GetModuleFileNameEx(self.handle, modules[0])).resolve() != executable.resolve():
                raise RuntimeError("MMD executable module could not be verified.")
            if psutil.Process(target.pid).create_time() != target.process_started:
                raise RuntimeError("MMD process changed while opening the read handle.")
            self.base = modules[0]
        except Exception:
            self.close()
            raise

    def close(self):
        self.handle.Close()

    def read(self, address, size):
        if not 0x10000 <= address < 0x0000800000000000 or not 0 < size <= MAX_BONES * BONE_STRIDE:
            raise RuntimeError("Invalid MMD bone memory range.")
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        if not _read(int(self.handle), address, buffer, size, ctypes.byref(count)) or count.value != size:
            raise RuntimeError("MMD bone state is unavailable or changed during inspection.")
        return buffer.raw

    def pointer(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]

    def integer(self, address):
        return struct.unpack("<i", self.read(address, 4))[0]

    def operation_mode(self):
        """MMD's bone-panel operation mode; the native selection bridge accepts 0, 3 and 4 only."""
        return self.integer(self.pointer(self.base + MAIN_POINTER_RVA) + OPERATION_MODE)

    def ensure_selectable_mode(self, reader):
        """Return the panel to 選択 mode when a rotate/move gizmo mode is active.

        Presses MMD's own 選択 button (control 490) and verifies the mode flag.
        Returns the mode found before switching, or None when no switch was needed.
        """
        mode = self.operation_mode()
        if mode in SELECTABLE_MODES:
            return None
        from .scene_controls import click_button  # local import: scene_controls imports this module
        click_button(reader, SELECT_MODE_BUTTON)
        after = self.operation_mode()
        if after not in SELECTABLE_MODES:
            raise RuntimeError(f'MMD bone panel stayed in operation mode {after} after pressing 選択. '
                               'Click 選択 in the ボーン操作 panel manually, then retry.')
        return mode

    def anchor(self):
        main = self.pointer(self.base + MAIN_POINTER_RVA)
        slot = self.integer(main + SELECTED_MODEL)
        if not 0 <= slot < 255:
            raise ValueError("Select a model in MMD before listing bones.")
        model = self.pointer(main + MODEL_TABLE + slot * 8)
        count = self.integer(model + BONE_COUNT)
        selected = self.integer(model + SELECTED_BONE)
        data = self.pointer(model + BONE_POINTER)
        if not 1 <= count <= MAX_BONES or not -1 <= selected < count:
            raise RuntimeError("MMD bone layout validation failed.")
        return main, slot, model, count, selected, data


def inspect_bones(memory, expected_model_name, *, english=False):
    anchor = memory.anchor()
    _, slot, model, count, selected, data = anchor
    name = decode_name(memory.read(model + (MODEL_NAME_EN if english else MODEL_NAME_JA), 50))
    if name != expected_model_name:
        raise RuntimeError("MMD internal model and visible model selector disagree.")
    raw = memory.read(data, count * BONE_STRIDE)
    bones = [{"index": i, "name": decode_name(raw[i * BONE_STRIDE:i * BONE_STRIDE + 20]),
              "display_name": decode_name(raw[i * BONE_STRIDE + (20 if english else 0):i * BONE_STRIDE + (40 if english else 20)])}
             for i in range(count)]
    # Re-read names as well as pointers/counts to reject a changing model table.
    again = memory.read(data, count * BONE_STRIDE)
    if any(raw[i * BONE_STRIDE:i * BONE_STRIDE + 40] != again[i * BONE_STRIDE:i * BONE_STRIDE + 40]
           for i in range(count)) or memory.anchor() != anchor:
        raise RuntimeError("MMD bone identity changed during inspection. Retry while MMD is idle.")
    return {"model_slot": slot, "bone_count": count, "bones": bones,
            "selected_bone_index": selected if selected >= 0 else None,
            "selected_bone_name": bones[selected]["name"] if selected >= 0 else None}


def list_bones(hwnd: int | None = None):
    reader = UIReader(hwnd)
    anchor = reader.anchor()
    if anchor[1] <= 0:
        raise ValueError("Select a model in MMD before listing bones.")
    memory = BoneMemory(reader.target)
    try:
        result = inspect_bones(memory, anchor[2], english=english_mode(reader))
        reader.verify(anchor)
        return {"source": "verified_mmd_932_x64_read_only_memory",
                "window": reader.target.public_info(), "model_name": anchor[2],
                "model_selector_index": anchor[1],
                "displayed_frame": parse_number(anchor[0], integer=True), **result,
                "limitations": [
                    "Private memory layout; available only for the exact verified executable SHA-256.",
                    "Indices are transient and names can be duplicated or truncated in MMD's 20-byte CP932 runtime field.",
                    "Includes internal/end bones; listing a bone does not imply it is selectable or editable.",
                    "Sequential observation, not an atomic snapshot. Do not change model or bone selection during the call.",
                ]}
    finally:
        memory.close()


def selected_identity(target):
    """Small checked identity snapshot, including the whole selection bitset."""
    memory = BoneMemory(target)
    try:
        anchor = memory.anchor()
        _, slot, model, count, selected, data = anchor
        if selected < 0:
            raise ValueError("Select an editable bone first.")
        english = english_mode(UIReader(target.hwnd))
        model_name = decode_name(memory.read(model + (MODEL_NAME_EN if english else MODEL_NAME_JA), 50))
        raw_name = memory.read(data + selected * BONE_STRIDE, 20)
        selection_pointer = memory.pointer(model + 0x3120)
        flags = memory.read(selection_pointer, count)
        if any(value not in (0, 1) for value in flags) or not flags[selected]:
            raise RuntimeError("MMD selection flags disagree with the active bone.")
        if memory.anchor() != anchor or memory.read(selection_pointer, count) != flags:
            raise RuntimeError("MMD bone selection changed during inspection.")
        return {"selected_bone_index": selected, "selected_bone_name": decode_name(raw_name),
                "selection_count": sum(flags), "model_name": model_name,
                "_guard": (anchor, raw_name, flags)}
    finally:
        memory.close()
