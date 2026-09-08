"""Native range selection; exact track names are read from the current UI."""

import ctypes
import time

import win32gui

from .bone_controls import _message
from .file_operations import owned_dialogs
from .scene_controls import mutation, context, available
from .ui_state import UIReader


def get_context(hwnd=None):
    reader = UIReader(hwnd)
    anchor = context(reader)
    result = {"range_tracks": reader.combo(434), "interpolation_channels": reader.combo(433),
              "range_start_text": reader.text(reader.control(425, "Edit")),
              "range_end_text": reader.text(reader.control(426, "Edit")),
              "displayed_frame": int(anchor[0])}
    reader.verify(anchor)
    return result


def select_range(start_frame, end_frame, track_name, hwnd=None):
    if type(start_frame) is not int or type(end_frame) is not int or not 0 <= start_frame <= end_frame <= 999999:
        raise ValueError("Provide an ordered frame range within 0..999999.")
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader)
        tracks = reader.combo(434)
        if tracks is None or tracks["items"].count(track_name) != 1:
            raise ValueError(f"Select an exact current range track name: {tracks}")
        combo = available(reader, 434, "ComboBox")
        index = tracks["items"].index(track_name)
        if _message(combo, 0x14E, index) != index:
            raise RuntimeError("Timeline track selection failed.")
        _message(reader.target.hwnd, 0x111, 434 | (1 << 16), combo)
        for cid, value in [(425, start_frame), (426, end_frame)]:
            edit = available(reader, cid, "Edit")
            buffer = ctypes.create_unicode_buffer(str(value))
            _message(edit, 0xC, 0, ctypes.addressof(buffer))
            if reader.text(edit) != str(value):
                raise RuntimeError("Timeline range text readback mismatch.")
        win32gui.PostMessage(available(reader, 415, "Button"), 0xF5, 0, 0)
        time.sleep(.05)
        found = owned_dialogs(reader.target)
        if found:
            return {"status": "dialog_requires_action", "dialogs": found}
        reader.verify(anchor)
        return {"status": "completed", "track_name": track_name, "start_frame": start_frame,
                "end_frame": end_frame, "note": "Native range selection applied; selected key identities are not read back."}
