"""Typed parameter dialogs for native timeline transformations."""

from typing import Annotated, Literal

from .ui_language import english_mode

import win32gui
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from . import native_dialogs as dialogs
from .bone_controls import _message
from .scene_controls import mutation, context, available
from .ui_state import UIReader

Number = Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000)]


class TransformSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["scale_time", "bone_correction", "camera_correction", "morph_correction", "center_bias", "random_blink", "lip_shift", "physics_state"]
    start_frame: Annotated[int, Field(strict=True, ge=0, le=999999)] | None = None
    end_frame: Annotated[int, Field(strict=True, ge=0, le=999999)] | None = None
    factor: Annotated[float, Field(allow_inf_nan=False, gt=0, le=1000)] | None = None
    tracks: list[Literal["bones", "morphs", "model_flags", "camera", "light", "shadow", "gravity", "accessory"]] | None = None
    position_scale: dict[Literal["x", "y", "z"], Number] | None = None
    position_offset: dict[Literal["x", "y", "z"], Number] | None = None
    rotation_scale: dict[Literal["x", "y", "z"], Number] | None = None
    rotation_offset_degrees: dict[Literal["x", "y", "z"], Number] | None = None
    weight_scale: Number | None = None
    weight_offset: Number | None = None
    distance_scale: Number | None = None
    distance_offset: Number | None = None
    fov_scale: Number | None = None
    fov_offset: Number | None = None
    shift_frames: Annotated[int, Field(strict=True, ge=-999999, le=999999)] | None = None
    physics_enabled: StrictBool | None = None

    @model_validator(mode="after")
    def content(self):
        allowed = {
            "scale_time": {"start_frame", "end_frame", "factor", "tracks"},
            "bone_correction": {"position_scale", "position_offset", "rotation_scale", "rotation_offset_degrees"},
            "camera_correction": {"position_scale", "position_offset", "rotation_scale", "rotation_offset_degrees", "distance_scale", "distance_offset", "fov_scale", "fov_offset"},
            "morph_correction": {"weight_scale", "weight_offset"},
            "center_bias": {"position_offset"}, "random_blink": {"start_frame", "end_frame"},
            "lip_shift": {"shift_frames"},
            "physics_state": {"physics_enabled"},
        }[self.operation]
        provided = set(self.model_dump(exclude_none=True)) - {"operation"}
        if not provided or provided - allowed:
            raise ValueError(f"{self.operation} accepts only {sorted(allowed)} and needs values.")
        if self.operation in {"scale_time", "random_blink"}:
            if self.start_frame is None or self.end_frame is None or self.end_frame < self.start_frame:
                raise ValueError("Provide an ordered start/end frame range.")
        if self.operation == "scale_time" and (self.factor is None or not self.tracks or len(set(self.tracks)) != len(self.tracks)):
            raise ValueError("Time scaling requires a factor and unique nonempty tracks.")
        for value in (self.position_scale, self.position_offset, self.rotation_scale, self.rotation_offset_degrees):
            if value == {}:
                raise ValueError("Empty axis mappings are not allowed.")
        return self


COMMANDS = {"bone_correction": (251, "ﾎﾞｰﾝﾌﾚｰﾑ位置角度補正"),
            "camera_correction": (242, "ｶﾒﾗﾌﾚｰﾑ位置角度補正"),
            "morph_correction": (252, "表情大きさ補正"), "center_bias": (219, "バイアス付加"),
            "random_blink": (227, "まばたき登録"), "lip_shift": (225, "シフトするﾌﾚｰﾑ数"),
            "physics_state": (275, "物理ON/OFFフレーム変換")}


def transform(spec, hwnd=None):
    spec = TransformSpec.model_validate(spec)
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader)
        if spec.operation == "camera_correction" and anchor[1] != 0:
            raise ValueError("Camera correction requires camera mode.")
        if spec.operation not in {"scale_time", "camera_correction"} and anchor[1] == 0:
            raise ValueError("This operation requires a selected model.")
        is_english = english_mode(reader)
        if spec.operation == "scale_time":
            if anchor[1] == 0:
                raise ValueError("MMD's native time-scale dialog is model-only; use VMD file edits for camera/light/shadow.")
            tracks = {"bones": 688, "morphs": 689, "model_flags": 690}
            if set(spec.tracks) - set(tracks):
                raise ValueError(f"This mode accepts tracks {list(tracks)}.")
            win32gui.PostMessage(available(reader, 424, "Button"), 0xF5, 0, 0)
            dialog = dialogs.wait_dialog(reader.target, "時間拡大(縮小)率")
            for cid, value in [(686, spec.start_frame), (687, spec.end_frame), (605, spec.factor)]:
                dialogs.text(dialog, cid, value)
            for name, cid in tracks.items():
                button = win32gui.GetDlgItem(dialog["hwnd"], cid)
                if not button or win32gui.GetClassName(button) != "Button":
                    if name in spec.tracks:
                        raise RuntimeError(f"Time scaling track {name} is unavailable.")
                    continue
                wanted = name in spec.tracks
                if bool(_message(button, 0xF0)) != wanted:
                    _message(dialogs.control(dialog, cid, "Button"), 0xF5)
        else:
            command, title = COMMANDS[spec.operation]
            dialogs.menu_command(reader.target.hwnd, command)
            dialog = dialogs.wait_dialog(reader.target, title)
            values = {}
            if spec.operation in {"bone_correction", "camera_correction"}:
                for field, base in [("position_scale", 686), ("position_offset", 687),
                                    ("rotation_scale", 692), ("rotation_offset_degrees", 693)]:
                    for axis, value in (getattr(spec, field) or {}).items():
                        values[base + "xyz".index(axis) * 2] = value
                if spec.operation == "camera_correction":
                    values.update({cid: value for cid, value in [(698, spec.distance_scale), (699, spec.distance_offset),
                                  (700, spec.fov_scale), (701, spec.fov_offset)] if value is not None})
            elif spec.operation == "morph_correction":
                values = {cid: value for cid, value in [(686, spec.weight_scale), (687, spec.weight_offset)] if value is not None}
            elif spec.operation == "center_bias":
                values = {601 + "xyz".index(axis): value for axis, value in spec.position_offset.items()}
            elif spec.operation == "random_blink":
                values = {618: spec.start_frame, 619: spec.end_frame}
            elif spec.operation == "lip_shift":
                values = {616: spec.shift_frames}
            elif spec.operation == "physics_state":
                combo = dialogs.control(dialog, 669, "ComboBox")
                if _message(combo, 0x146) != 2:
                    raise RuntimeError("Physics conversion selector layout mismatch.")
                index = 0 if spec.physics_enabled else 1
                if _message(combo, 0x14E, index) != index:
                    raise RuntimeError("Physics state selection failed.")
                _message(dialog["hwnd"], 0x111, 669 | (1 << 16), combo)
            for cid, value in values.items():
                dialogs.text(dialog, cid, format(value, ".9g"))
        notice = ("まばたき追加", r"\d+回のまばたきを追加しました") if spec.operation == "random_blink" else None
        if notice and is_english:
            notice = ("register blinking", r"\d+ blinking is registerd")
        dialogs.close(reader.target, dialog, 1, notice=notice)
        return {"status": "completed", "operation": spec.operation,
                "note": "Native transformation applied using current selection and MMD semantics. Export VMD to verify results; no save or rollback. Random blink uses MMD's own randomness."}
