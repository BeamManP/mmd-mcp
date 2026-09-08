"""Explicit scene replacement/model deletion through exact native confirmations."""

import win32gui

from . import native_dialogs as dialogs
from .file_operations import get_ui_state
from .scene_controls import mutation, context, available, choose_combo
from .ui_state import UIReader


def confirm(target, title, message, *, english_message=None):
    dialog = dialogs.wait_dialog(target, title)
    text = "\n".join(c["text"] for c in dialog["controls"] if c["class"] == "Static" and c["text"])
    if dialog["title"] != title:
        message = english_message
    if text != message:
        raise RuntimeError(f"Confirmation text does not match the expected operation. Left open: {text}")
    dialogs.close(target, dialog, 1)


def new_project(discard_current, hwnd=None):
    if discard_current is not True:
        raise ValueError("Creating a new scene requires discard_current=true; save the current project first if needed.")
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        dialogs.menu_command(reader.target.hwnd, 204)
        confirm(reader.target, "新規作成", "現在の状態は破棄されます\n\nよろしいですか？",
                english_message="The existing state will be annulled.\n\nAre you OK?")
        after = get_ui_state(reader.target.hwnd)
        if after["model_selector"]["models"] or after["displayed_frame"]["value"] != 0:
            raise RuntimeError("New scene verification failed; inspect MMD.")
        return {"status": "completed", "after": after, "saved_to_disk": False,
                "note": "Previous unsaved scene data was discarded through MMD's native confirmation."}


def delete_models(targets, hwnd=None):
    if not targets or len(targets) > 100:
        raise ValueError("Provide 1–100 models to delete.")
    indices = []
    for target in targets:
        if set(target) != {"selector_index", "expected_name"} or type(target["selector_index"]) is not int:
            raise ValueError("Each target requires selector_index and expected_name.")
        indices.append(target["selector_index"])
    if len(set(indices)) != len(indices):
        raise ValueError("Duplicate model targets are not allowed.")
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        before = reader.combo(436)["items"]
        for target in targets:
            index = target["selector_index"]
            if not 0 < index < len(before) or before[index] != target["expected_name"]:
                raise ValueError("Model target does not match the current selector list.")
        deleted = []
        remaining = list(before)
        for target in sorted(targets, key=lambda t: t["selector_index"], reverse=True):
            index, name = target["selector_index"], target["expected_name"]
            try:
                reader = UIReader(reader.target.hwnd)
                context(reader)
                if reader.combo(436)["items"] != remaining:
                    raise RuntimeError("Model list changed during deletion.")
                choose_combo(reader, 436, index)
                win32gui.PostMessage(available(reader, 437, "Button"), 0xF5, 0, 0)
                confirm(reader.target, "モデル削除",
                        f"モデル：{name}を削除します\nモデルのフレームデータも全て削除されます\n"
                        "またアクセサリでこのモデルに追従するものは地面に追従するように変更されます\n"
                        "(この操作は元に戻す事はできません)\n\n削除してもよろしいですか？",
                        english_message=(f"Trying to delete Model({name}). \n"
                                         "All flame data about this model will be deleted too.\n"
                                         "(This operation cannot undo!!)\n\nAre you OK?"))
                del remaining[index]
                if UIReader(reader.target.hwnd).combo(436)["items"] != remaining:
                    raise RuntimeError("Model deletion readback mismatch.")
                deleted.append(target)
            except (ValueError, RuntimeError, win32gui.error) as error:
                return {"status": "partial", "deleted": deleted, "failed_target": target,
                        "error": str(error), "note": "Model deletion is not undoable. Earlier deletions remain applied."}
        return {"status": "completed", "deleted": deleted, "remaining_names": remaining[1:],
                "note": "Models and their keys were deleted. Attached accessories now follow the ground. Not undoable."}
