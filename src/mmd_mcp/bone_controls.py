"""Direct control of MMD's active bone transform fields.

No screen coordinates, simulated mouse input, motion/pose files, process-memory
writes, key registration, or scene saving. Enter is sent only to the specific
Edit HWND whose value was set; MMD's own edit procedure applies the transform.
"""

from .ui_language import matches

import ctypes
import math
import threading
from typing import Annotated

import win32gui
from pydantic import BaseModel, ConfigDict, Field

from .ui_state import UIReader, _send, parse_number, NativeMessageError
from .bone_state import selected_identity

_edit_lock = threading.Lock()
POSITION_IDS = {"x": 544, "y": 545, "z": 546}
ROTATION_IDS = {"x": 547, "y": 548, "z": 549}
BM_GETCHECK = 0x00F0
WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100
VK_RETURN = 0x0D
MAX_ABSOLUTE_VALUE = 100000.0


class AxisValues(BaseModel):
    """Absolute values on the specified axes; omitted axes are preserved."""

    model_config = ConfigDict(extra="forbid", strict=True)
    x: Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000)] | None = None
    y: Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000)] | None = None
    z: Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000)] | None = None


def build_updates(position: AxisValues | None, rotation_degrees: AxisValues | None):
    updates = []
    for kind, patch, ids in (("position", position, POSITION_IDS),
                             ("rotation_degrees", rotation_degrees, ROTATION_IDS)):
        if patch is None:
            continue
        for axis, value in patch.model_dump(exclude_none=True).items():
            if isinstance(value, bool) or not math.isfinite(value) or abs(value) > MAX_ABSOLUTE_VALUE:
                raise ValueError("Transform values must be finite numbers in [-100000, 100000].")
            updates.append((kind, axis, ids[axis], value))
    if not updates:
        raise ValueError("Specify at least one position or rotation_degrees axis.")
    return updates


def _message(hwnd, message, wparam=0, lparam=0):
    """Bounded native call; never exposed as a generic MCP message tool."""
    result = ctypes.c_size_t()
    ctypes.set_last_error(0)
    if not _send(hwnd, message, wparam, lparam, 0x0002 | 0x0020, 1000, ctypes.byref(result)):
        code = ctypes.get_last_error()
        raise NativeMessageError(
            f"MMD did not finish the control message (Windows error {code}). "
            "The operation may have partially applied; inspect the current state before retrying.", code
        )
    return ctypes.c_ssize_t(result.value).value


def _active_panel(reader: UIReader):
    anchor = reader.anchor()
    frame = parse_number(anchor[0], integer=True) if anchor[0] is not None else None
    if frame is None or frame < 0:
        raise ValueError("Finish entering a valid frame number in MMD first.")
    if anchor[1] <= 0:
        raise ValueError("Select a model and a bone in MMD first.")
    camera_button = reader.control(536, "Button")
    # The button describes the destination mode, with two native English variants.
    if not matches(reader.text(camera_button), "カメラ編"):
        raise ValueError("MMD is not in the verified bone editing mode. Switch to bone editing first.")
    if win32gui.IsWindowVisible(reader.control(550, "Edit")):
        raise ValueError("Camera distance field is visible; refusing a bone edit in camera mode.")
    if _message(reader.control(408, "Button"), BM_GETCHECK):
        raise ValueError("Stop MMD playback before reading or changing the selected bone.")
    values = {}
    for kind, ids in (("position", POSITION_IDS), ("rotation_degrees", ROTATION_IDS)):
        values[kind] = {}
        for axis, control_id in ids.items():
            hwnd = reader.control(control_id, "Edit")
            if not win32gui.IsWindowVisible(hwnd) or not win32gui.IsWindowEnabled(hwnd):
                raise ValueError("The bone transform fields are not available. Select an editable bone first.")
            raw = reader.text(hwnd)
            value = parse_number(raw)
            if value is None:
                raise ValueError(f"The {kind}.{axis} field has no valid number. Finish editing it in MMD first.")
            values[kind][axis] = value
    reader.verify(anchor)
    return anchor, values


def _state(reader, anchor, values, identity):
    return {
        "source": "win32_bone_transform_panel",
        "window": reader.target.public_info(),
        "displayed_frame": parse_number(anchor[0], integer=True),
        "model_selector_index": anchor[1],
        "model_name": anchor[2],
        "selected_bone_name": identity["selected_bone_name"],
        "selected_bone_index": identity["selected_bone_index"],
        "selection_count": identity["selection_count"],
        **values,
        "limitations": [
            "Bone identity uses the exact verified MMD executable layout; values come from the transform panel.",
            "Do not change bone selection, model, frame or fields while a call is running.",
            "Values are those displayed by MMD: position in MMD units, rotation in degrees using MMD's angle convention.",
            "Readback is rounded by the UI (position typically 2 decimals, rotation 1 decimal).",
        ],
    }


def get_selected_bone_transform(hwnd: int | None = None):
    reader = UIReader(hwnd)
    identity = selected_identity(reader.target)
    anchor, values = _active_panel(reader)
    if identity != selected_identity(reader.target) or identity["model_name"] != anchor[2]:
        raise RuntimeError("MMD bone identity changed during the read.")
    return _state(reader, anchor, values, identity)


def _commit_edit(reader, control_id, value):
    if control_id not in {*POSITION_IDS.values(), *ROTATION_IDS.values()}:
        raise ValueError("Only the six bone transform fields may be changed.")
    edit = reader.control(control_id, "Edit")
    buffer = ctypes.create_unicode_buffer(format(value, ".9g"))
    if not _message(edit, WM_SETTEXT, 0, ctypes.addressof(buffer)):
        raise RuntimeError("MMD rejected the transform field text.")
    # A parent EN_CHANGE/EN_KILLFOCUS notification is insufficient in MMD.
    # The Edit's Enter handler applies the transform and enables native Undo.
    _message(edit, WM_KEYDOWN, VK_RETURN, 1)


def set_selected_bone_transform(position: AxisValues | None = None,
                                rotation_degrees: AxisValues | None = None,
                                hwnd: int | None = None,
                                expected_bone_name: str | None = None,
                                expected_bone_index: int | None = None):
    if not _edit_lock.acquire(blocking=False):
        raise RuntimeError("Another bone edit is in progress. Retry after it finishes.")
    try:
        return _set_selected_bone_transform(position, rotation_degrees, hwnd, expected_bone_name, expected_bone_index)
    finally:
        _edit_lock.release()


def _set_selected_bone_transform(position=None, rotation_degrees=None, hwnd=None,
                                 expected_bone_name=None, expected_bone_index=None):
    """Caller must hold the shared mutation lock."""
    updates = build_updates(position, rotation_degrees)
    completed = []
    try:
        reader = UIReader(hwnd)
        identity = selected_identity(reader.target)
        anchor, before = _active_panel(reader)
        if identity["selection_count"] != 1:
            raise ValueError("Select exactly one bone before setting its transform.")
        if identity["model_name"] != anchor[2]:
            raise RuntimeError("MMD model identity and UI selection disagree.")
        if ((expected_bone_name is not None and identity["selected_bone_name"] != expected_bone_name)
                or (expected_bone_index is not None and identity["selected_bone_index"] != expected_bone_index)):
            raise ValueError("Selected bone does not match the expected bone. Select it with mmd_select_bone first.")
        expected = before
        for kind, axis, control_id, value in updates:
            current_anchor, current = _active_panel(reader)
            if current_anchor != anchor or current != expected or selected_identity(reader.target) != identity:
                raise RuntimeError("MMD context or displayed transform changed during the edit.")
            _commit_edit(reader, control_id, value)
            completed.append(f"{kind}.{axis}")
            after_anchor, expected = _active_panel(reader)
            if after_anchor != anchor or selected_identity(reader.target) != identity:
                raise RuntimeError("MMD frame, model or bone selection changed during the edit.")
        requested = {kind: patch.model_dump(exclude_none=True)
                     for kind, patch in (("position", position), ("rotation_degrees", rotation_degrees))
                     if patch is not None}
        differences = [f"{kind}.{axis}" for kind, axes in requested.items()
                       for axis, value in axes.items()
                       if not math.isclose(expected[kind][axis], value, rel_tol=0,
                                           abs_tol=0.0051 if kind == "position" else 0.051)]
        return {
            "before": _state(reader, anchor, before, identity),
            "after": _state(reader, anchor, expected, identity),
            "requested": requested,
            "committed_fields": completed,
            "requested_axes_match_display": not differences,
            "display_differences": differences,
            "verification": "MMD edit handlers returned; displayed transform fields were read back. Confirm the resulting pose with mmd_capture_window.",
            "keyframes_registered": False,
            "saved_to_disk": False,
            "undo_note": "MMD's native Undo is available for applied edits; multiple axes can create multiple undo steps.",
        }
    except Exception as exc:
        if completed:
            raise RuntimeError(
                f"Bone edit did not finish. Fields with completed Enter handlers: {completed}. "
                "Partial changes remain; no automatic rollback was attempted. "
                f"Inspect MMD before retrying. Cause: {exc}"
            ) from exc
        raise
