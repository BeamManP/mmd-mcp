"""Read displayed MMD controls without changing selection or scene data.

Control IDs are a version-specific adapter, verified on the local MMD 9.32 x64
installation. This is a UI observation, not an authoritative scene snapshot.
Only Windows system-range read messages are used (marshalled by Windows).
"""

import ctypes
import math
import time
from concurrent.futures import ThreadPoolExecutor, wait
from ctypes import wintypes
from datetime import datetime, timezone

import win32con
import win32gui

from .windows import select_window

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_send = _user32.SendMessageTimeoutW
_send.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
                  wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
_send.restype = ctypes.c_ssize_t

WM_GETTEXT = 0x000D
CB_GETCOUNT, CB_GETCURSEL, CB_GETLBTEXT, CB_GETLBTEXTLEN = 0x146, 0x147, 0x148, 0x149
READ_MESSAGES = {WM_GETTEXT, CB_GETCOUNT, CB_GETCURSEL, CB_GETLBTEXT, CB_GETLBTEXTLEN}
MAX_TEXT = 65536


class NativeMessageError(RuntimeError):
    def __init__(self, message, winerror):
        super().__init__(message)
        self.winerror = winerror


MORPH_CONTROLS = {"eyes": (509, 511), "mouth": (514, 516),
                  "eyebrows": (504, 506), "other": (519, 521)}

# MMD services cross-process messages on its UI loop. Independent reads can
# share one loop iteration; mutations must never use this executor.
_read_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="mmd-read")


def _read_group(reads):
    futures = []
    try:
        for read in reads:
            futures.append(_read_pool.submit(read))
        return [future.result() for future in futures]
    finally:
        # Even on error, no read may outlive the caller's context guard/lock.
        for future in futures:
            future.cancel()
        wait(futures)


def parse_number(text: str, integer: bool = False):
    """Empty/partially edited text is unknown, never implicitly zero."""
    try:
        value = int(text) if integer else float(text)
        return value if math.isfinite(value) else None
    except (ValueError, OverflowError):
        return None


class UIReader:
    def __init__(self, hwnd: int | None):
        self.target = select_window(hwnd)
        self.deadline = time.monotonic() + 8

    def message(self, hwnd, message, wparam=0, lparam=0):
        if message not in READ_MESSAGES:
            raise ValueError("Only approved read messages are supported.")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("UI read exceeded its time limit. Retry while MMD is idle.")
        result = ctypes.c_size_t()
        ctypes.set_last_error(0)
        if not _send(hwnd, message, wparam, lparam, win32con.SMTO_ABORTIFHUNG,
                     200, ctypes.byref(result)):
            code = ctypes.get_last_error()
            raise NativeMessageError(f"MMD control did not respond (Windows error {code}).", code)
        return ctypes.c_ssize_t(result.value).value

    def control(self, control_id: int, expected_class: str):
        hwnd = win32gui.GetDlgItem(self.target.hwnd, control_id)
        if not hwnd or win32gui.GetClassName(hwnd) != expected_class:
            raise RuntimeError(f"Unsupported MMD layout: expected {expected_class} control {control_id}.")
        return hwnd

    def text(self, hwnd):
        buffer = ctypes.create_unicode_buffer(MAX_TEXT)
        length = self.message(hwnd, WM_GETTEXT, len(buffer), ctypes.addressof(buffer))
        if length >= len(buffer) - 1:
            raise RuntimeError("MMD text exceeded the supported length.")
        return buffer.value

    def texts(self, handles):
        return _read_group([lambda h=h: self.text(h) for h in handles])

    def edit(self, control_id: int):
        hwnd = self.control(control_id, "Edit")
        if not win32gui.IsWindowVisible(hwnd):
            return None
        return self.text(hwnd)

    def combo(self, control_id: int):
        hwnd = self.control(control_id, "ComboBox")
        if not win32gui.IsWindowVisible(hwnd):
            return None
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if style & (win32con.CBS_OWNERDRAWFIXED | win32con.CBS_OWNERDRAWVARIABLE) and not style & win32con.CBS_HASSTRINGS:
            raise RuntimeError("Owner-drawn combo without text is unsupported.")
        count = self.message(hwnd, CB_GETCOUNT)
        selected = self.message(hwnd, CB_GETCURSEL)
        if count < 0 or count > 1024:
            raise RuntimeError("MMD selector size is unsupported.")
        def item(index):
            length = self.message(hwnd, CB_GETLBTEXTLEN, index)
            if not 0 <= length < MAX_TEXT - 1:
                raise RuntimeError("MMD selector text is unavailable or too long.")
            buffer = ctypes.create_unicode_buffer(MAX_TEXT)
            actual = self.message(hwnd, CB_GETLBTEXT, index, ctypes.addressof(buffer))
            if actual < 0 or actual >= MAX_TEXT - 1:
                raise RuntimeError("MMD selector changed while being read. Retry.")
            return buffer.value
        items = _read_group([lambda i=i: item(i) for i in range(count)])
        if self.message(hwnd, CB_GETCOUNT) != count or self.message(hwnd, CB_GETCURSEL) != selected:
            raise RuntimeError("MMD selector changed while being read. Retry.")
        if selected < -1 or selected >= count:
            raise RuntimeError("MMD selector returned an invalid selection.")
        return {"items": items, "selected_index": selected if selected >= 0 else None,
                "selected_name": items[selected] if selected >= 0 else None}

    def anchor(self):
        model = self.control(436, "ComboBox")
        return tuple(_read_group([lambda: self.edit(417),
                                  lambda: self.message(model, CB_GETCURSEL),
                                  lambda: self.text(model)]))

    def verify(self, before):
        after = select_window(self.target.hwnd)
        if (after.pid, after.process_started) != (self.target.pid, self.target.process_started):
            raise RuntimeError("MMD process changed during the read.")
        if self.anchor() != before:
            raise RuntimeError("Frame or model selection changed during the read. Retry while MMD is idle.")


def model_entries(selector):
    """The verified MMD selector reserves entry zero for camera/light/accessory."""
    if selector is None or not selector["items"]:
        raise RuntimeError("Model selector unavailable; cannot infer loaded models.")
    return {
        "models": [{"selector_index": index, "name": name,
                    "selected": index == selector["selected_index"]}
                   for index, name in enumerate(selector["items"]) if index > 0],
        "selected_index": selector["selected_index"],
        "selected_name": selector["selected_name"],
        "camera_light_accessory_selected": selector["selected_index"] == 0,
        "index_scope": "Current UI selector only; indices may change after loading/deleting models.",
    }


def list_models(hwnd: int | None = None):
    reader = UIReader(hwnd)
    before = reader.anchor()
    result = model_entries(reader.combo(436))
    reader.verify(before)
    return {"source": "win32_ui", "window": reader.target.public_info(), **result}


def get_ui_state(hwnd: int | None = None):
    reader = UIReader(hwnd)
    before = reader.anchor()
    selector = reader.combo(436)
    models = model_entries(selector)
    frame_text = before[0]
    morphs = {}
    ik_selector = None
    # Hidden controls can retain data from the previously selected model.
    if selector["selected_index"] is not None and selector["selected_index"] > 0:
        for category, (combo_id, value_id) in MORPH_CONTROLS.items():
            names = reader.combo(combo_id)
            raw_value = reader.edit(value_id)
            morphs[category] = None if names is None else {
                **names,
                "displayed_weight_text": raw_value,
                "displayed_weight": parse_number(raw_value) if raw_value is not None and names["selected_index"] is not None else None,
            }
        ik_selector = reader.combo(443)
    reader.verify(before)
    return {
        "source": "win32_ui",
        "adapter": "mmd-9.x-controls-v1 (verified on local 9.32 x64 installation)",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "atomic": False,
        "window": reader.target.public_info(),
        "displayed_frame": {"text": frame_text, "value": parse_number(frame_text, integer=True) if frame_text is not None else None},
        "model_selector": models,
        "morph_panels": morphs,
        "ik_selector": ik_selector,
        "limitations": [
            "UI observation, not internal scene state. Uncommitted edit text can be included.",
            "Only the selected morph in each visible panel has a displayed weight; other weights are unknown.",
            "Morph lists contain only UI-exposed entries, not necessarily all model morphs.",
            "IK entries are selector names; enabled states and IK chains are not retrieved.",
            "Bone hierarchy, selected bone name, all bone transforms, model paths and keyframes are not retrieved.",
            "Controls are read sequentially; frame/model changes are checked, but the snapshot is not atomic.",
        ],
    }
