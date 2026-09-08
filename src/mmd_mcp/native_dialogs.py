"""Bounded helpers for individually verified native dialogs, not arbitrary UI automation."""

from .ui_language import matches

import ctypes
import re
import time

import win32gui

from .bone_controls import _message
from .file_operations import owned_dialogs, verify_process, window_text


def wait_dialog(target, title, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dialogs = owned_dialogs(target)
        if dialogs:
            if len(dialogs) != 1 or not matches(dialogs[0]["title"], title):
                raise RuntimeError(f"Expected {title}; unexpected dialog requires inspection: {dialogs}")
            return dialogs[0]
        time.sleep(.05)
    raise RuntimeError(f"MMD did not open {title} within the time limit.")


def control(dialog, cid, class_name):
    hwnd = win32gui.GetDlgItem(dialog["hwnd"], cid)
    if not hwnd or win32gui.GetClassName(hwnd) != class_name or not win32gui.IsWindowEnabled(hwnd):
        raise RuntimeError(f"Expected enabled {class_name} {cid} in {dialog['title']}.")
    return hwnd


def text(dialog, cid, value):
    edit = control(dialog, cid, "Edit")
    buffer = ctypes.create_unicode_buffer(str(value))
    if not _message(edit, 0xC, 0, ctypes.addressof(buffer)) or window_text(edit) != str(value):
        raise RuntimeError("Native dialog rejected the numeric text.")


def close(target, dialog, cid=2, timeout=5, notice=None):
    if cid is None:
        win32gui.PostMessage(dialog["hwnd"], 0x10, 0, 0)
    else:
        win32gui.PostMessage(control(dialog, cid, "Button"), 0xF5, 0, 0)
    deadline = time.monotonic() + timeout
    quiet_since = None
    while time.monotonic() < deadline:
        verify_process(target)
        remaining = owned_dialogs(target)
        if not any(item["hwnd"] == dialog["hwnd"] and item["title"] == dialog["title"] for item in remaining):
            if remaining:
                if notice is not None and len(remaining) == 1 and remaining[0]["title"] == notice[0]:
                    text = "\n".join(c["text"] for c in remaining[0]["controls"] if c["class"] == "Static" and c["text"])
                    if re.fullmatch(notice[1], text):
                        close(target, remaining[0], 2, timeout)
                        return
                raise RuntimeError(f"Unexpected dialog after applying operation: {remaining}")
            if win32gui.IsWindowEnabled(target.hwnd):
                if quiet_since is None:
                    quiet_since = time.monotonic()
                elif time.monotonic() - quiet_since >= .2:
                    return
            else:
                quiet_since = None
        else:
            quiet_since = None
        time.sleep(.05)
    raise RuntimeError("Native dialog did not close; inspect MMD before retrying.")


def menu_command(hwnd, command):
    """Initialize native menus before dispatch (MME builds its command state lazily)."""
    root = win32gui.GetMenu(hwnd)
    if not root:
        raise RuntimeError("Native menu is missing.")
    _message(hwnd, 0x116, root, 0)
    found = []
    def walk(menu):
        for index in range(win32gui.GetMenuItemCount(menu)):
            sub = win32gui.GetSubMenu(menu, index)
            if sub:
                _message(hwnd, 0x117, sub, index)
                walk(sub)
            elif win32gui.GetMenuItemID(menu, index) == command:
                found.append(win32gui.GetMenuState(menu, index, 0x400))
    walk(root)
    if len(found) != 1 or found[0] & 3:
        raise ValueError("Requested native command is missing or disabled.")
    win32gui.PostMessage(hwnd, 0x111, command, 0)
