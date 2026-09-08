"""Named, idempotent scene menu settings for the verified Japanese MMD UI."""

from typing import Literal

import win32gui
from pydantic import BaseModel, ConfigDict, StrictBool

from .bone_controls import _message
from .scene_controls import context, mutation
from .ui_state import UIReader

TOGGLES = {
    "axis": 215, "ground_shadow": 221, "translucent": 214,
    "hide_models": 283, "antialiasing": 277, "mipmaps": 298,
    "self_shadow": 279, "wireframe": 287, "black_background": 282,
    "background_image": 233, "background_video": 216,
    "rigid_bodies": 264, "physics_floor": 285, "physics_on_playback": 271,
    "information": 211, "camera_follow": 247, "transparent_ground_shadow": 254,
    "wav_on_frame_change": 284, "mute_wav": 297,
    "mme_enabled": 40006, "mme_auto_update": 40001, "mme_auto_save": 40022,
}
GROUPS = {"physics_mode": {"on_off": 269, "always": 265, "trace": 270, "off": 272},
          "fps_limit": {"unlimited": 234, "30": 235, "60": 236}}


class SceneSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    axis: StrictBool | None = None
    ground_shadow: StrictBool | None = None
    translucent: StrictBool | None = None
    hide_models: StrictBool | None = None
    antialiasing: StrictBool | None = None
    mipmaps: StrictBool | None = None
    self_shadow: StrictBool | None = None
    wireframe: StrictBool | None = None
    black_background: StrictBool | None = None
    background_image: StrictBool | None = None
    background_video: StrictBool | None = None
    rigid_bodies: StrictBool | None = None
    physics_floor: StrictBool | None = None
    physics_on_playback: StrictBool | None = None
    information: StrictBool | None = None
    camera_follow: StrictBool | None = None
    transparent_ground_shadow: StrictBool | None = None
    wav_on_frame_change: StrictBool | None = None
    mute_wav: StrictBool | None = None
    mme_enabled: StrictBool | None = None
    mme_auto_update: StrictBool | None = None
    mme_auto_save: StrictBool | None = None
    physics_mode: Literal["on_off", "always", "trace", "off"] | None = None
    fps_limit: Literal["unlimited", "30", "60"] | None = None


def menu_items(hwnd):
    """Read leaf menu commands, retaining the owning menu (IDs are scope-specific)."""
    result = {}
    def walk(menu):
        for index in range(win32gui.GetMenuItemCount(menu)):
            child = win32gui.GetSubMenu(menu, index)
            if child:
                walk(child)
            else:
                command = win32gui.GetMenuItemID(menu, index)
                if command > 0:
                    if command in result:
                        raise RuntimeError("Ambiguous MMD menu command.")
                    state = win32gui.GetMenuState(menu, index, 0x400)
                    result[command] = {"menu": menu, "checked": bool(state & 8),
                                       "enabled": not bool(state & 3)}
    menu = win32gui.GetMenu(hwnd)
    if not menu:
        raise RuntimeError("MMD menu is unavailable.")
    walk(menu)
    return result


def snapshot(reader):
    items = menu_items(reader.target.hwnd)
    values = {name: items[command]["checked"] if command in items else None
              for name, command in TOGGLES.items()}
    for name, choices in GROUPS.items():
        checked = [value for value, command in choices.items()
                   if command in items and items[command]["checked"]]
        values[name] = checked[0] if len(checked) == 1 else None
    return values, items


def get_settings(hwnd=None):
    reader = UIReader(hwnd)
    anchor = context(reader)
    values, _ = snapshot(reader)
    reader.verify(anchor)
    return {"window": reader.target.public_info(), "settings": values,
            "note": "Unavailable or ambiguous settings are null. These are scene settings, not keyframes."}


def set_settings(settings, hwnd=None):
    settings = SceneSettings.model_validate(settings)
    requested = settings.model_dump(exclude_none=True)
    if not requested:
        raise ValueError("Specify at least one scene setting.")
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader)
        before, items = snapshot(reader)
        commands = {}
        for name, value in requested.items():
            command = TOGGLES[name] if name in TOGGLES else GROUPS[name][value]
            if before[name] is None or command not in items or not items[command]["enabled"]:
                raise ValueError(f"Scene setting {name} is unavailable in the current MMD state.")
            if before[name] != value:
                commands[name] = command
        applied = []
        for name, command in commands.items():
            try:
                reader.verify(anchor)
                current = menu_items(reader.target.hwnd)
                if command not in current or not current[command]["enabled"]:
                    raise RuntimeError(f"Scene setting {name} became unavailable.")
                _message(reader.target.hwnd, 0x111, command, 0)
                after, _ = snapshot(reader)
                if after[name] != requested[name]:
                    raise RuntimeError(f"Scene setting {name} did not reach the requested value.")
                applied.append(name)
            except (ValueError, RuntimeError, win32gui.error) as error:
                return {"status": "partial", "before": before, "applied": applied,
                        "failed_setting": name, "error": str(error),
                        "note": "Earlier changes remain applied; inspect MMD before retrying."}
        reader.verify(anchor)
        after, _ = snapshot(reader)
        return {"status": "completed", "before": before, "settings": after, "applied": applied}
