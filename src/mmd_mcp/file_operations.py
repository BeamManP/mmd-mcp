"""MMD file commands through owned Win32 file dialogs; no screen automation."""

from .ui_language import matches, variants

import ctypes
import time
from pathlib import Path

import psutil
import win32gui
import win32process

from .bone_controls import _message
from .scene_controls import context, mutation
from .ui_state import UIReader, get_ui_state, NativeMessageError
from .windows import list_windows, select_window

LOADS = {"model": ({".pmd", ".pmx"}, 435), "project": ({".pmm"}, 205),
         "pose": ({".vpd"}, 202), "motion": ({".vmd"}, 209),
         "accessory": ({".x"}, 472), "audio": ({".wav"}, 206),
         "background_image": ({".bmp", ".png", ".jpg", ".jpeg", ".tga"}, 232),
         "background_video": ({".avi"}, 213)}

EXPORTS = {"pose": ({".vpd"}, 203), "motion": ({".vmd"}, 210),
           "image": ({".bmp", ".png", ".jpg"}, 276)}


def file_path(path, suffixes, *, write=False, overwrite=False):
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("Use an absolute file path.")
    candidate = candidate.resolve()
    if candidate.suffix.lower() not in suffixes:
        raise ValueError(f"Expected one of these extensions: {sorted(suffixes)}")
    if write:
        if not candidate.parent.is_dir():
            raise ValueError("Output directory does not exist.")
        if candidate.exists() and (not candidate.is_file() or not overwrite):
            raise ValueError("Output already exists. Choose a new path or explicitly set overwrite=true.")
    elif not candidate.is_file():
        raise ValueError("Input file does not exist.")
    return candidate


def verify_process(target):
    if (not win32gui.IsWindow(target.hwnd)
            or win32process.GetWindowThreadProcessId(target.hwnd)[1] != target.pid
            or psutil.Process(target.pid).create_time() != target.process_started):
        raise RuntimeError("MMD process/window changed during the file operation.")


def window_text(hwnd):
    buffer = ctypes.create_unicode_buffer(4096)
    _message(hwnd, 0xD, len(buffer), ctypes.addressof(buffer))
    return buffer.value


def owned_dialogs(target):
    verify_process(target)
    dialogs = []

    def visit(handle, _):
        try:
            if not win32gui.IsWindowVisible(handle) or win32gui.GetClassName(handle) != "#32770":
                return
            if win32process.GetWindowThreadProcessId(handle)[1] != target.pid:
                return
            owner = win32gui.GetWindow(handle, 4)
            visited = set()
            while owner and owner != target.hwnd and owner not in visited:
                visited.add(owner)
                owner = win32gui.GetWindow(owner, 4)
            if owner != target.hwnd:
                return
            children = []

            def child(control, _):
                if len(children) >= 256:
                    return
                try:
                    class_name = win32gui.GetClassName(control)
                except win32gui.error:
                    if win32gui.IsWindow(control):
                        raise
                    return
                if class_name in {"Button", "Static", "Edit"}:
                    try:
                        children.append({"hwnd": control, "id": win32gui.GetDlgCtrlID(control),
                                         "class": class_name, "text": window_text(control),
                                         "enabled": bool(win32gui.IsWindowEnabled(control))})
                    except (RuntimeError, win32gui.error):
                        if win32gui.IsWindow(control):
                            raise

            win32gui.EnumChildWindows(handle, child, None)
            dialogs.append({"hwnd": handle, "title": window_text(handle), "controls": children})
        except (RuntimeError, win32gui.error):
            if win32gui.IsWindow(handle):
                raise


    win32gui.EnumWindows(visit, None)
    return dialogs


def get_dialogs(hwnd=None):
    candidates = [target for target in list_windows() if hwnd is None or target.hwnd == hwnd]
    if len(candidates) != 1:
        raise ValueError("Specify the HWND of exactly one running MMD window.")
    return {"window": candidates[0].public_info(), "dialogs": owned_dialogs(candidates[0])}


def button(dialog, control_id):
    matches = [c for c in dialog["controls"] if c["class"] == "Button" and c["id"] == control_id and c["enabled"]]
    if len(matches) != 1:
        raise RuntimeError("Expected MMD dialog button is unavailable.")
    return matches[0]["hwnd"]


FILE_DIALOG_TITLES = {"load model", "open file data", "save file", "Open", "Save As", "背景画像データ読込", "WAVE Fileを開く", "AVIデータ読込", "AVI出力", "開く", "モーションデータ保存", "ポーズデータ保存", "画像ファイル出力", "ファイルを開く", "ファイルを保存する", "名前を付けて保存", "名前をつけて保存", "ポーズデータ読込", "モーションデータ読込"}
SAVE_DIALOG_TITLES = {"save file", "Save As", "AVI出力", "モーションデータ保存", "ポーズデータ保存", "画像ファイル出力",
                      "ファイルを保存する", "名前を付けて保存", "名前をつけて保存"}


def filename_edit(dialog):
    if dialog["title"] not in variants(FILE_DIALOG_TITLES):
        return None
    matches = []
    for control in dialog["controls"]:
        if control["class"] != "Edit":
            continue
        parent = win32gui.GetParent(control["hwnd"])
        if control["id"] == 1148 and win32gui.GetClassName(parent) == "ComboBox":
            matches.append(control["hwnd"])
        elif control["id"] == 1001 and win32gui.GetClassName(parent) == "ComboBox":
            grandparent = win32gui.GetParent(parent)
            if win32gui.GetClassName(grandparent) == "FloatNotifySink":
                matches.append(control["hwnd"])
    return matches[0] if len(matches) == 1 else None


def overwrite_button(dialog, dialogs, path, *, authorized, submitted):
    if not authorized or not submitted or not matches(dialog["title"], "名前を付けて保存の確認"):
        return None
    owner = win32gui.GetWindow(dialog["hwnd"], 4)
    parents = [item for item in dialogs if item["hwnd"] == owner
               and item["title"] in variants(SAVE_DIALOG_TITLES)]
    if len(parents) != 1:
        return None
    edit = filename_edit(parents[0])
    if edit is None or Path(window_text(edit)).resolve() != path or not path.is_file():
        return None
    buttons = [item["hwnd"] for item in dialog["controls"] if item["class"] == "Button"
               and matches(item["text"], "はい(&Y)") and item["enabled"]]
    return buttons[0] if len(buttons) == 1 else None


def run_dialog_flow(target, path, *, model_info=False, overwrite=False, timeout=30, probe=None,
                    parent_dialog=None):
    """Drive one MMD file dialog. `probe` replaces the full UI snapshot as the idle check;
    it must raise ValueError/RuntimeError while MMD is still busy and return the completion state otherwise."""
    deadline = time.monotonic() + timeout
    submitted = False
    notices = []
    acknowledged = set()
    quiet_since = None
    while time.monotonic() < deadline:
        verify_process(target)
        try:
            dialogs = owned_dialogs(target)
        except NativeMessageError as error:
            if not submitted or error.winerror != 1460:
                raise
            # Shader compilation can occupy MMD's UI thread after file submission.
            # Retry observation only; never submit the file or accept a dialog twice.
            time.sleep(.1)
            quiet_since = None
            continue
        completion_hwnd = target.hwnd
        if parent_dialog is not None:
            parent_hwnd, parent_title = parent_dialog
            parents = [d for d in dialogs if d["hwnd"] == parent_hwnd and d["title"] == parent_title]
            if len(parents) != 1:
                return {"status": "verification_failed", "path_submitted": submitted,
                        "note": "Expected parent dialog disappeared; inspect MMD before retrying."}
            dialogs = [d for d in dialogs if d["hwnd"] != parent_hwnd]
            completion_hwnd = parent_hwnd
        if dialogs:
            quiet_since = None
            for dialog in dialogs:
                edit = filename_edit(dialog)
                confirm = overwrite_button(dialog, dialogs, path, authorized=overwrite, submitted=submitted)
                if edit is not None:
                    if submitted:
                        continue
                    buffer = ctypes.create_unicode_buffer(str(path))
                    if not _message(edit, 0xC, 0, ctypes.addressof(buffer)) or window_text(edit) != str(path):
                        raise RuntimeError("MMD file dialog rejected the path.")
                    win32gui.PostMessage(button(dialog, 1), 0xF5, 0, 0)
                    submitted = True
                elif dialog["title"] in variants(FILE_DIALOG_TITLES) and any(
                        c["class"] == "Button" and c["id"] == 1
                        and c["text"] in {"保存(&S)", "開く(&O)", "保存", "開く", "&Save", "&Open", "Save", "Open"}
                        for c in dialog["controls"]):
                    # The shell may still be creating the filename control.
                    continue
                elif model_info and submitted and matches(dialog["title"], "モデル情報"):
                    if dialog["hwnd"] not in acknowledged:
                        notices.extend(c["text"] for c in dialog["controls"] if c["class"] == "Static" and c["text"])
                        win32gui.PostMessage(button(dialog, 1), 0xF5, 0, 0)
                        acknowledged.add(dialog["hwnd"])
                elif confirm is not None:
                    if dialog["hwnd"] not in acknowledged:
                        win32gui.PostMessage(confirm, 0xF5, 0, 0)
                        acknowledged.add(dialog["hwnd"])
                else:
                    return {"status": "dialog_requires_action", "path_submitted": submitted,
                            "dialogs": dialogs, "model_notices": notices,
                            "note": "No unknown dialog was accepted. Inspect MMD; do not blindly retry the load."}
        elif submitted and win32gui.IsWindowEnabled(completion_hwnd):
            try:
                state = probe() if probe is not None else get_ui_state(target.hwnd)
            except (ValueError, RuntimeError):
                quiet_since = None
            else:
                if quiet_since is None:
                    quiet_since = time.monotonic()
                if time.monotonic() - quiet_since >= 0.3:
                    return {"status": "completed", "path_submitted": True,
                            "model_notices": notices, "after": state}
        time.sleep(0.1)
    return {"status": "timeout", "path_submitted": submitted, "model_notices": notices,
            "note": "The native operation may still be running. Inspect MMD before retrying."}


def load_file(kind, path, hwnd=None):
    suffixes, command_id = LOADS[kind]
    candidate = file_path(path, suffixes)
    with mutation():
        reader = UIReader(hwnd)
        context(reader, "model" if kind == "pose" else 'camera' if kind == 'accessory' else None)
        before = get_ui_state(reader.target.hwnd)
        accessory_before = reader.combo(471) if kind == 'accessory' else None
        if kind == 'accessory' and accessory_before is None:
            raise ValueError('Expand the accessory panel before loading an accessory.')
        if kind in {"model", "accessory"}:
            control = reader.control(command_id, "Button")
            win32gui.PostMessage(control, 0xF5, 0, 0)
        else:
            win32gui.PostMessage(reader.target.hwnd, 0x111, command_id, 0)
        result = run_dialog_flow(reader.target, candidate, model_info=kind == "model")
        if kind == 'accessory' and result['status'] == 'completed':
            after_accessories = UIReader(reader.target.hwnd).combo(471)
            result['accessory_selector'] = after_accessories
            if after_accessories is None or len(after_accessories['items']) != len(accessory_before['items'])+1:
                result['status'] = 'verification_failed'
                result['note'] = 'Accessory count did not increase by exactly one. Inspect MMD before retrying.'
        if kind == "pose" and result["status"] == "completed":
            from .bone_selection import refresh_selected_panel
            try:
                refreshed = refresh_selected_panel(UIReader(reader.target.hwnd))
                result["transform_panel_refreshed"] = refreshed
                result["transform_panel_refresh_required"] = not refreshed
            except Exception as exc:
                result["status"] = "verification_failed"
                result["note"] = f"Pose was imported, but numeric panel synchronization failed: {exc}. Select a bone before further numeric editing."
        if kind == "model" and result["status"] == "completed":
            previous = len(before["model_selector"]["models"])
            current = len(result["after"]["model_selector"]["models"])
            if current != previous + 1:
                result["status"] = "verification_failed"
                result["note"] = "File dialog closed, but model count did not increase by exactly one. Inspect MMD."
        return {"kind": kind, "path": str(candidate), **result,
                "saved_to_disk": False,
                "note_on_data": "Native imports can replace current poses/keys. Project loading replaces the current scene. VMD key times are offset by the current frame; move to frame 0 first for file-absolute timing."}


def save_project(path, overwrite=False, hwnd=None):
    candidate = file_path(path, {".pmm"}, write=True, overwrite=overwrite)
    before_stamp = candidate.stat().st_mtime_ns if candidate.exists() else None
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        win32gui.PostMessage(reader.target.hwnd, 0x111, 208, 0)
        result = run_dialog_flow(reader.target, candidate, overwrite=overwrite)
        if result["status"] == "completed" and (not candidate.is_file() or candidate.stat().st_size == 0):
            result["status"] = "verification_failed"
            result["note"] = "MMD became idle, but no nonempty project file was found."
        if result["status"] == "completed" and before_stamp is not None and candidate.stat().st_mtime_ns == before_stamp:
            result["status"] = "verification_failed"
            result["note"] = "The save dialog closed, but the existing file was not modified. It may have been cancelled."
        return {"path": str(candidate), **result,
                "saved_to_disk": result["status"] == "completed"}


def export_file(kind, path, overwrite=False, hwnd=None):
    """Export using MMD's own encoder and current selection/range semantics."""
    suffixes, command = EXPORTS[kind]
    candidate = file_path(path, suffixes, write=True, overwrite=overwrite)
    before_stamp = candidate.stat().st_mtime_ns if candidate.exists() else None
    with mutation():
        reader = UIReader(hwnd)
        context(reader, "model" if kind == "pose" else None)
        win32gui.PostMessage(reader.target.hwnd, 0x111, command, 0)
        result = run_dialog_flow(reader.target, candidate, overwrite=overwrite)
        if result["status"] == "completed":
            if (not candidate.is_file() or candidate.stat().st_size == 0
                    or (before_stamp is not None and candidate.stat().st_mtime_ns == before_stamp)):
                result["status"] = "verification_failed"
                result["note"] = "No new nonempty output was observed; inspect MMD before retrying."
        return {"kind": kind, "path": str(candidate), **result,
                "saved_to_disk": result["status"] == "completed"}
