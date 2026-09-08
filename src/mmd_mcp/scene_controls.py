"""Explicit, bounded Win32 operations for MMD's scene editing panels."""

from .ui_language import matches

import ctypes
from contextlib import contextmanager
from typing import Annotated, Literal

import win32gui
from pydantic import BaseModel, ConfigDict, Field

from .bone_controls import AxisValues, _edit_lock, _message
from .ui_state import UIReader, MORPH_CONTROLS, parse_number

MorphCategory = Literal["eyes", "mouth", "eyebrows", "other"]
CAMERA_FIELDS = {"position": {"x": 544, "y": 545, "z": 546},
                 "rotation_degrees": {"x": 547, "y": 548, "z": 549},
                 "distance": 550, "fov_degrees": 448}
LIGHT_FIELDS = {"color": {"r": 461, "g": 462, "b": 463},
                "direction": {"x": 464, "y": 465, "z": 466}}
MORPH_REGISTER = {"eyes": 524, "mouth": 527, "eyebrows": 525, "other": 526}
EDIT_IDS = {417, 448, 561, *range(461, 467), *range(544, 551),
            *(value for _, value in MORPH_CONTROLS.values())}
BUTTON_IDS = {400, 401, 438, 439, 440, 441, 442, 444, 445, 446, 452, 468, 490, 500, 536, 562, 563, 564, 565, *MORPH_REGISTER.values()}


class RGBValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    r: Annotated[int, Field(ge=0, le=255)] | None = None
    g: Annotated[int, Field(ge=0, le=255)] | None = None
    b: Annotated[int, Field(ge=0, le=255)] | None = None


class DirectionValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: Annotated[float, Field(allow_inf_nan=False, ge=-1, le=1)] | None = None
    y: Annotated[float, Field(allow_inf_nan=False, ge=-1, le=1)] | None = None
    z: Annotated[float, Field(allow_inf_nan=False, ge=-1, le=1)] | None = None


@contextmanager
def mutation():
    if not _edit_lock.acquire(blocking=False):
        raise RuntimeError("Another MMD edit is in progress. Retry after it finishes.")
    try:
        yield
    finally:
        _edit_lock.release()


def context(reader, mode=None):
    from .video_export import block_if_active
    block_if_active(reader.target.hwnd)
    anchor = reader.anchor()
    frame = parse_number(anchor[0], integer=True) if anchor[0] is not None else None
    if frame is None or frame < 0:
        raise ValueError("Finish entering a valid MMD frame number first.")
    if _message(reader.control(408, "Button"), 0xF0):
        raise ValueError("Stop MMD playback before editing the scene.")
    if mode == "camera":
        if anchor[1] != 0 or not matches(reader.text(reader.control(536, "Button")), "モデル編"):
            raise ValueError("Select camera/light/accessory with mmd_select_model(selector_index=0) first.")
        if not win32gui.IsWindowVisible(reader.control(550, "Edit")):
            raise ValueError("The camera transform panel is not visible.")
    elif mode == "model" and anchor[1] <= 0:
        raise ValueError("Select a model with mmd_select_model first.")
    reader.verify(anchor)
    return anchor


def available(reader, control_id, class_name):
    handle = reader.control(control_id, class_name)
    if not win32gui.IsWindowVisible(handle) or not win32gui.IsWindowEnabled(handle):
        raise ValueError(f"MMD control {control_id} is unavailable. Expand its panel and stop playback.")
    return handle


def commit_number(reader, control_id, value):
    if control_id not in EDIT_IDS:
        raise ValueError("Unsupported numeric control.")
    edit = available(reader, control_id, "Edit")
    text = ctypes.create_unicode_buffer(format(value, ".9g"))
    if not _message(edit, 0xC, 0, ctypes.addressof(text)):
        raise RuntimeError("MMD rejected the numeric field text.")
    _message(edit, 0x100, 13, 1)


def click_button(reader, control_id):
    if control_id not in BUTTON_IDS:
        raise ValueError("Unsupported MMD action button.")
    handle = available(reader, control_id, "Button")
    _message(handle, 0xF5)  # BM_CLICK, invokes the actual button notification.


def choose_combo(reader, control_id, index):
    if control_id not in {436, 443, *(combo for combo, _ in MORPH_CONTROLS.values())}:
        raise ValueError("Unsupported MMD selector.")
    combo = reader.combo(control_id)
    if combo is None or isinstance(index, bool) or not 0 <= index < len(combo["items"]):
        raise ValueError("Selector index is out of range.")
    handle = available(reader, control_id, "ComboBox")
    if _message(handle, 0x14E, index) != index:
        raise RuntimeError("MMD rejected the selector index.")
    _message(reader.target.hwnd, 0x111, control_id | (1 << 16), handle)
    after = reader.combo(control_id)
    if after is None or after["selected_index"] != index or after["items"] != combo["items"]:
        raise RuntimeError("MMD selector changed during the operation. Inspect the current state.")


def resolve_index(items, index, name):
    if (index is None) == (name is None):
        raise ValueError("Specify exactly one of selector_index or name.")
    if name is not None:
        matches = [i for i, value in enumerate(items) if value == name]
        if len(matches) != 1:
            raise ValueError("Name is missing or ambiguous. Use an explicit selector_index from the current list.")
        return matches[0]
    if isinstance(index, bool) or not 0 <= index < len(items):
        raise ValueError("Selector index is out of range.")
    return index


def select_model(selector_index=None, name=None, hwnd=None):
    with mutation():
        reader = UIReader(hwnd)
        before = context(reader)
        combo = reader.combo(436)
        index = resolve_index(combo["items"], selector_index, name)
        choose_combo(reader, 436, index)
        after = context(reader)
        if after[0] != before[0]:
            raise RuntimeError("Frame changed while selecting the model.")
        return {"before_model_selector_index": before[1], "model_selector_index": after[1],
                "model_name": after[2], "displayed_frame": int(after[0]),
                "camera_light_accessory_selected": after[1] == 0,
                "selection_changed": before[1] != after[1]}


def numbers(reader, fields):
    leaves = []
    def collect(mapping):
        for ids in mapping.values():
            if isinstance(ids, dict):
                collect(ids)
            else:
                leaves.append(ids)
    collect(fields)
    # Resolve visibility/class before sending reads; retain every numeric check.
    handles = [available(reader, ids, "Edit") for ids in leaves]
    raw_values = reader.texts(handles)
    values = iter(zip(leaves, raw_values))
    def rebuild(mapping):
        result = {}
        for key, ids in mapping.items():
            if isinstance(ids, dict):
                result[key] = rebuild(ids)
            else:
                control_id, raw = next(values)
                value = parse_number(raw)
                if value is None:
                    raise ValueError(f"Invalid numeric text in MMD control {control_id}; finish the edit first.")
                result[key] = value
        return result
    return rebuild(fields)


def panel_state(reader, kind):
    anchor = context(reader, "camera")
    values = numbers(reader, CAMERA_FIELDS if kind == "camera" else LIGHT_FIELDS)
    if kind == "camera":
        values["perspective"] = bool(_message(available(reader, 446, "Button"), 0xF0))
    reader.verify(anchor)
    return {"source": "win32_ui", "displayed_frame": int(anchor[0]),
            "window": reader.target.public_info(), **values,
            "limitations": ["UI-rounded values; sequential observation, not an atomic snapshot.",
                            "Do not change the model, frame or fields while a call is running."]}


def get_camera(hwnd=None):
    return panel_state(UIReader(hwnd), "camera")


def get_light(hwnd=None):
    return panel_state(UIReader(hwnd), "light")


def apply_fields(reader, anchor, updates):
    completed = []
    try:
        for control_id, value in updates:
            reader.verify(anchor)
            commit_number(reader, control_id, value)
            completed.append(control_id)
            reader.verify(anchor)
        return completed
    except Exception as exc:
        raise RuntimeError(f"MMD edit did not finish. Completed controls: {completed}. "
                           f"Partial changes may remain; inspect MMD before retrying. Cause: {exc}") from exc


def set_camera(position=None, rotation_degrees=None, distance=None, fov_degrees=None,
               perspective=None, hwnd=None):
    updates = []
    for key, patch in (("position", position), ("rotation_degrees", rotation_degrees)):
        if patch is not None:
            updates.extend((CAMERA_FIELDS[key][axis], value) for axis, value in patch.model_dump(exclude_none=True).items())
    for key, value in (("distance", distance), ("fov_degrees", fov_degrees)):
        if value is not None:
            updates.append((CAMERA_FIELDS[key], value))
    if not updates and perspective is None:
        raise ValueError("Specify at least one camera value.")
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader, "camera")
        before = panel_state(reader, "camera")
        completed = []
        try:
            completed = apply_fields(reader, anchor, updates)
            if perspective is not None and before["perspective"] != perspective:
                reader.verify(anchor)
                click_button(reader, 446)
                completed.append(446)
            after = panel_state(reader, "camera")
        except Exception as exc:
            raise RuntimeError(f"Camera operation incomplete; partial changes may remain. Completed controls: {completed}. {exc}") from exc
        return {"before": before, "after": after, "completed_controls": completed,
                "keyframes_registered": False, "saved_to_disk": False}


def set_light(color=None, direction=None, hwnd=None):
    updates = [(LIGHT_FIELDS[key][axis], value)
               for key, patch in (("color", color), ("direction", direction)) if patch is not None
               for axis, value in patch.model_dump(exclude_none=True).items()]
    if not updates:
        raise ValueError("Specify at least one light value.")
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader, "camera")
        before = panel_state(reader, "light")
        merged = {**before["direction"], **(direction.model_dump(exclude_none=True) if direction else {})}
        if all(value == 0 for value in merged.values()):
            raise ValueError("Light direction must not be the zero vector.")
        completed = apply_fields(reader, anchor, updates)
        try:
            after = panel_state(reader, "light")
        except Exception as exc:
            raise RuntimeError(f"Light values were applied, but readback failed. Completed controls: {completed}. {exc}") from exc
        return {"before": before, "after": after, "completed_controls": completed,
                "keyframes_registered": False, "saved_to_disk": False}


def set_morph(category, name, weight, hwnd=None):
    with mutation():
        return _set_morph(category, name, weight, hwnd)


def _set_morph(category, name, weight, hwnd=None):
    combo_id, value_id = MORPH_CONTROLS[category]
    reader = UIReader(hwnd)
    anchor = context(reader, "model")
    combo = reader.combo(combo_id)
    if combo is None:
        raise ValueError("Expand the morph panel first.")
    index = resolve_index(combo["items"], None, name)
    choose_combo(reader, combo_id, index)
    reader.verify(anchor)
    before = numbers(reader, {"weight": value_id})["weight"]
    apply_fields(reader, anchor, [(value_id, weight)])
    after = numbers(reader, {"weight": value_id})["weight"]
    selected = reader.combo(combo_id)
    if selected["selected_name"] != name:
        raise RuntimeError("Morph selection changed during the edit. Partial changes may remain.")
    return {"category": category, "name": name, "before_weight": before,
            "after_weight": after, "keyframes_registered": False, "saved_to_disk": False}


def set_frame(frame, hwnd=None):
    with mutation():
        return _set_frame(frame, hwnd)


def _set_frame(frame, hwnd=None):
    reader = UIReader(hwnd)
    before = context(reader)
    commit_number(reader, 417, frame)
    after = context(reader)
    if int(after[0]) != frame or after[1:] != before[1:]:
        raise RuntimeError("MMD did not display the requested frame in the same model context.")
    return {"before_frame": int(before[0]), "displayed_frame": frame,
            "keyframes_registered": False,
            "note": "Changing frames evaluates the animation; unregistered edits may be replaced by keyed values."}


def register_keyframe(target, morph_category=None, hwnd=None):
    with mutation():
        reader = UIReader(hwnd)
        mode = "camera" if target in {"camera", "light"} else "model"
        anchor = context(reader, mode)
        if target == "morph":
            if morph_category is None:
                raise ValueError("Specify morph_category to register its currently selected morph.")
            control_id = MORPH_REGISTER[morph_category]
        else:
            if morph_category is not None:
                raise ValueError("morph_category is only valid for target=morph.")
            control_id = {"bone": 500, "camera": 452, "light": 468}[target]
        click_button(reader, control_id)
        reader.verify(anchor)
        return {"target": target, "morph_category": morph_category, "frame": int(anchor[0]),
                "registration_handler_completed": True, "saved_to_disk": False,
                "note": "Registers the current selection through MMD's native button. Existing keys at this frame may be replaced. Bone registration can affect multiple selected bones."}
