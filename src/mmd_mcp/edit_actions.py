"""Named native editing actions with bounded execution and modal refusal."""

import time
from typing import Literal

import win32gui

from .bone_controls import _message
from .file_operations import owned_dialogs
from .native_dialogs import menu_command
from .scene_controls import mutation, context, available
from .ui_state import UIReader
from .scene_lifecycle import confirm

Action = Literal[
    "undo", "redo", "select_all_bones", "select_unregistered_bones",
    "reset_bones", "copy_bones", "paste_bones", "mirror_paste_bones",
    "reset_camera", "reset_light", "view_front", "view_back", "view_top",
    "view_left", "view_right", "view_camera", "camera_follow_selected",
    "select_bone_keys", "select_morph_keys", "select_model_flag_keys",
    "select_camera_keys", "select_light_keys", "select_shadow_keys",
    "select_gravity_keys", "select_accessory_keys", "select_column_keys",
    "copy_keys", "paste_keys", "mirror_paste_keys", "delete_keys",
    "insert_bone_camera_frame", "delete_bone_camera_column",
    "insert_morph_light_frame", "delete_morph_light_column",
    "reset_morphs", "register_all_morphs", "delete_lip_keys", "delete_eye_keys",
    "delete_eyebrow_keys", "select_physics_bones", "select_physics_keys",
    "reset_rigid_bodies", "refresh_effects",
    "reload_textures", "copy_interpolation", "paste_interpolation", "linear_interpolation",
]
BUTTONS = {"undo": 400, "redo": 401, "select_all_bones": 494,
           "select_unregistered_bones": 501, "reset_bones": 495,
           "copy_bones": 496, "paste_bones": 497, "mirror_paste_bones": 498,
           "reset_camera": 451, "reset_light": 467, "view_front": 402,
           "view_back": 403, "view_top": 404, "view_left": 405,
           "view_right": 406, "view_camera": 407, "camera_follow_selected": 535,
           "select_column_keys": 416, "copy_keys": 420, "paste_keys": 421,
           "mirror_paste_keys": 422, "delete_keys": 423,
           "copy_interpolation": 430, "paste_interpolation": 431, "linear_interpolation": 432}
MENUS = {"select_bone_keys": 217, "select_morph_keys": 220, "select_model_flag_keys": 218,
         "select_camera_keys": 237, "select_light_keys": 238, "select_shadow_keys": 239,
         "select_gravity_keys": 240, "select_accessory_keys": 241,
         "insert_bone_camera_frame": 255, "delete_bone_camera_column": 256,
         "insert_morph_light_frame": 257, "delete_morph_light_column": 258,
         "reset_morphs": 230, "register_all_morphs": 229, "delete_lip_keys": 226,
         "delete_eye_keys": 228, "delete_eyebrow_keys": 231,
         "select_physics_bones": 273, "select_physics_keys": 274,
         "reset_rigid_bodies": 268,
         "refresh_effects": 40004, "reload_textures": 278}
MODEL_ACTIONS = {"select_all_bones", "select_unregistered_bones", "reset_bones", "copy_bones",
                 "paste_bones", "mirror_paste_bones", "reset_morphs", "register_all_morphs",
                 "delete_lip_keys", "delete_eye_keys", "delete_eyebrow_keys"}
CONFIRMATIONS = {
    "delete_lip_keys": ("リップフレーム削除", "リップ"),
    "delete_eye_keys": ("新規作成", "目"),
    "delete_eyebrow_keys": ("新規作成", "まゆ"),
}


def perform(actions, hwnd=None):
    if not actions or len(actions) > 64 or any(action not in BUTTONS and action not in MENUS for action in actions):
        raise ValueError("Supply 1–64 supported named actions.")
    applied = []
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        for action in actions:
            try:
                reader = UIReader(reader.target.hwnd)
                context(reader, "model" if action in MODEL_ACTIONS else None)
                if action in BUTTONS:
                    button = available(reader, BUTTONS[action], "Button")
                    win32gui.PostMessage(button, 0xF5, 0, 0)
                else:
                    menu_command(reader.target.hwnd, MENUS[action])
                if action in CONFIRMATIONS:
                    title, category = CONFIRMATIONS[action]
                    english_category = {"リップ": "lip", "目": "eyes", "まゆ": "eyebrow"}[category]
                    confirm(reader.target, title, f"{category}のフレームを全て削除します\n"
                            "表情フレームの変更は元に戻せません\n\nよろしいですか？",
                            english_message=(f"Trying to delete all {english_category} frame.\n"
                                             "You cannot undo this oparation.\n\nAre you OK?"))
                # Synchronize with the posted command before checking for native modal results.
                time.sleep(.05)
                found = owned_dialogs(reader.target)
                if found:
                    return {"status": "dialog_requires_action", "applied": applied,
                            "pending_action": action, "dialogs": found,
                            "note": "No unknown dialog was accepted. Earlier actions remain applied."}
                context(UIReader(reader.target.hwnd))
                applied.append(action)
            except (ValueError, RuntimeError, win32gui.error) as error:
                return {"status": "partial", "applied": applied, "failed_action": action,
                        "error": str(error), "note": "Earlier actions remain applied; no rollback."}
        return {"status": "completed", "applied": applied,
                "note": "Native commands completed. Key selection/clipboard contents are not read back; export motion to verify key edits."}
