"""Select one named bone using a single-purpose temporary MMD UI-thread hook."""

from .ui_language import matches, english_mode

import ctypes
import mmap
import secrets
import struct
import time
from pathlib import Path

import win32process

from .bone_state import BoneMemory, inspect_bones, list_bones, selected_identity
from .scene_controls import context, mutation
from .ui_state import UIReader, _send

PROTOCOL = struct.Struct("<IIQQQiiii20siii")
DLL_PATH = Path(__file__).resolve().parent / "_native" / "mmd_selection.dll"
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
_user32.RegisterWindowMessageW.restype = ctypes.c_uint
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
_user32.SetWindowsHookExW.restype = ctypes.c_void_p
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.UnhookWindowsHookEx.restype = ctypes.c_int
_kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
_kernel32.LoadLibraryW.restype = ctypes.c_void_p
_kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
_kernel32.GetProcAddress.restype = ctypes.c_void_p
_kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
_kernel32.FreeLibrary.restype = ctypes.c_int


def find_bone(bones, name, index):
    if (name is None) == (index is None):
        raise ValueError("Specify exactly one of name or bone_index.")
    if name is not None:
        matches = [bone["index"] for bone in bones if name in {bone["name"], bone.get("display_name")}]
        if len(matches) != 1:
            raise ValueError("Bone name is missing or ambiguous. Use bone_index from mmd_list_bones.")
        return matches[0]
    if isinstance(index, bool) or not 0 <= index < len(bones):
        raise ValueError("bone_index is out of range.")
    return index


def exposed_bone_names(items):
    markers = [item for item in items if matches(item, "全ボーンﾌﾚｰﾑ")]
    marker = markers[0] if len(markers) == 1 else None
    if len(items) < 2 or items.count(marker) != 1:
        raise RuntimeError("MMD bone range selector layout is unsupported.")
    # Entry 1 is the root/center row. Entries before this marker also contain
    # morph names and generic selection commands, which must not grant access.
    return {items[1], *items[items.index(marker) + 1:]}


def dispatch_selection(target, anchor, frame, index, raw_name):
    if not DLL_PATH.is_file():
        raise RuntimeError("Native selection bridge is not built. Run scripts/build_native.cmd on Windows x64.")
    if struct.calcsize("P") != 8:
        raise RuntimeError("Bone selection requires 64-bit Python.")
    thread, pid = win32process.GetWindowThreadProcessId(target.hwnd)
    if pid != target.pid or not thread:
        raise RuntimeError("MMD UI thread changed.")
    nonce = secrets.randbits(64) or 1
    mapping_name = f"Local\\MmdMcp.Selection.v1.{pid}.{nonce:016x}"
    main, slot, model, _, previous_bone, _ = anchor
    with mmap.mmap(-1, PROTOCOL.size, tagname=mapping_name) as shared:
        shared[:] = PROTOCOL.pack(0x4D4D4442, 1, target.hwnd, main, model, slot, frame,
                                  previous_bone, index, raw_name, 0, -1, 0)
        module = _kernel32.LoadLibraryW(str(DLL_PATH))
        if not module:
            raise ctypes.WinError(ctypes.get_last_error())
        hook = None
        try:
            procedure = _kernel32.GetProcAddress(module, b"BoneSelectHook")
            message = _user32.RegisterWindowMessageW("MmdMcp.SelectBone.v1")
            if not procedure or not message:
                raise RuntimeError("Native selection bridge protocol is unavailable.")
            hook = _user32.SetWindowsHookExW(4, procedure, module, thread)
            if not hook:
                raise ctypes.WinError(ctypes.get_last_error())
            result = ctypes.c_size_t()
            if not _send(target.hwnd, message, nonce, 0, 0x2 | 0x20, 3000, ctypes.byref(result)):
                raise RuntimeError("Native bone selection timed out. Selection may have changed; inspect MMD before retrying.")
            response = PROTOCOL.unpack(shared[:])
            status, observed, exception = response[-3:]
            if status != 2 or observed != index:
                raise RuntimeError(f"Native bone selection failed (status={status}, exception=0x{exception & 0xffffffff:08x}). "
                                   "Inspect selection before retrying; a native failure may leave partial selection changes.")
        finally:
            cleanup_error = 0
            if hook:
                if not _user32.UnhookWindowsHookEx(hook):
                    cleanup_error = ctypes.get_last_error() or -1
            _kernel32.FreeLibrary(module)
            if cleanup_error:
                raise RuntimeError(f"Could not confirm removal of the temporary MMD hook (Windows error {cleanup_error}). "
                                   "Selection may have completed. Stop this MCP server and inspect MMD before retrying.")


def select_bone(name=None, bone_index=None, hwnd=None):
    with mutation():
        return _select_bone(name, bone_index, hwnd)


def _select_bone(name=None, bone_index=None, hwnd=None, *, verified_exposed_names=None):
    reader = UIReader(hwnd)
    ui_anchor = context(reader, "model")
    if not matches(reader.text(reader.control(536, "Button")), "カメラ編"):
        raise ValueError("Switch MMD to bone editing mode before selecting a bone.")
    memory = BoneMemory(reader.target)  # Exact executable digest checked first.
    try:
        switched_from = memory.ensure_selectable_mode(reader)
        snapshot = inspect_bones(memory, ui_anchor[2], english=english_mode(reader))
        index = find_bone(snapshot["bones"], name, bone_index)
        runtime_name = snapshot["bones"][index]["name"]
        # MMD lists its exposed bones in the frame-range selector. Internal/end
        # bones missing from this list are deliberately not selection targets.
        if verified_exposed_names is None:
            # Large PMX models have hundreds of rows; text is read with bounded
            # Win32 messages and can exceed the small-panel deadline.
            reader.deadline = time.monotonic() + 30
            exposed = reader.combo(434)
            names = exposed_bone_names(exposed['items']) if exposed is not None else set()
        else:
            # Compound caller holds mutation() and has checked this exact model.
            names = verified_exposed_names
        if snapshot["bones"][index].get("display_name", runtime_name) not in names:
            raise ValueError("This internal/end bone is not exposed in MMD's bone UI.")
        anchor = memory.anchor()
        if (anchor[1], anchor[4]) != (snapshot["model_slot"], snapshot["selected_bone_index"] if snapshot["selected_bone_index"] is not None else -1):
            raise RuntimeError("MMD selection changed before the native request.")
        raw_name = memory.read(anchor[5] + index * 624, 20)
        reader.verify(ui_anchor)
        dispatch_selection(reader.target, anchor, int(ui_anchor[0]), index, raw_name)
        reader.verify(ui_anchor)
    finally:
        memory.close()
    after = list_bones(reader.target.hwnd)
    if after["selected_bone_index"] != index or after["selected_bone_name"] != runtime_name:
        raise RuntimeError("Bone selection changed after native completion.")
    return {"model_name": ui_anchor[2], "displayed_frame": int(ui_anchor[0]),
            "selected_bone_index": index, "selected_bone_name": runtime_name,
            "single_bone_selected": True, "keyframes_registered": False,
            "operation_mode_switched_from": switched_from,
            "saved_to_disk": False, "native_bridge": "temporary_ui_thread_hook_v1"}


def refresh_selected_panel(reader):
    """Caller holds the mutation lock; preserve an existing single selection.

    MMD can leave stale numeric text after importing a VPD. Its selection routine
    synchronizes the fields without moving frames (which would discard the pose).
    Multiple selections are left untouched and require explicit later selection.
    """
    ui_anchor = context(reader, "model")
    before = selected_identity(reader.target)
    if before["selection_count"] != 1:
        return False
    memory = BoneMemory(reader.target)
    try:
        anchor = memory.anchor()
        index = before["selected_bone_index"]
        if anchor[4] != index:
            raise RuntimeError("Selection changed before refreshing the pose panel.")
        raw_name = memory.read(anchor[5] + index * 624, 20)
        reader.verify(ui_anchor)
        dispatch_selection(reader.target, anchor, int(ui_anchor[0]), index, raw_name)
        reader.verify(ui_anchor)
    finally:
        memory.close()
    if selected_identity(reader.target) != before:
        raise RuntimeError("Selection changed while refreshing the pose panel.")
    return True
