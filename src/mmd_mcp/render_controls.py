"""Verified output-size, model-order and gravity native dialogs."""

import ctypes
from typing import Annotated

import win32gui
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from . import native_dialogs as dialogs
from .bone_controls import _message
from .file_operations import window_text
from .scene_controls import mutation, context
from .scene_controls import RGBValues
from .ui_state import UIReader


class OutputSize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: Annotated[int, Field(strict=True, ge=16, le=8192)]
    height: Annotated[int, Field(strict=True, ge=16, le=8192)]


class GravityValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acceleration: Annotated[float, Field(allow_inf_nan=False, ge=0, le=1000)] | None = None
    x: Annotated[float, Field(allow_inf_nan=False, ge=-1, le=1)] | None = None
    y: Annotated[float, Field(allow_inf_nan=False, ge=-1, le=1)] | None = None
    z: Annotated[float, Field(allow_inf_nan=False, ge=-1, le=1)] | None = None
    noise: StrictBool | None = None
    noise_amount: Annotated[int, Field(strict=True, ge=0, le=1000)] | None = None

    @model_validator(mode="after")
    def content(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Specify at least one gravity value.")
        if self.noise is False and self.noise_amount is not None:
            raise ValueError("noise_amount requires noise enabled.")
        return self


class RenderStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_width: Annotated[float, Field(allow_inf_nan=False, ge=0, le=2)] | None = None
    edge_color: RGBValues | None = None
    ground_shadow_brightness: Annotated[float, Field(allow_inf_nan=False, ge=0, le=2)] | None = None

    @model_validator(mode="after")
    def content(self):
        if not self.model_dump(exclude_none=True) or self.edge_color is not None and not self.edge_color.model_dump(exclude_none=True):
            raise ValueError("Provide nonempty render style values.")
        return self


def set_style(style, hwnd=None):
    style = RenderStyle.model_validate(style)
    with mutation():
        reader = UIReader(hwnd)
        context(reader, "model" if style.edge_width is not None or style.edge_color is not None else None)
        result = {}
        for name, command, title, cid in [("edge_width", 253, "エッジ太さ設定", 646),
                                          ("ground_shadow_brightness", 248, "地面影色設定", 626),
                                          ("edge_color", 286, "色の設定", None)]:
            value = getattr(style, name)
            if value is None:
                continue
            dialogs.menu_command(reader.target.hwnd, command)
            dialog = dialogs.wait_dialog(reader.target, title)
            if cid is None:
                for channel, number in value.model_dump(exclude_none=True).items():
                    dialogs.text(dialog, 706 + "rgb".index(channel), number)
                dialogs.close(reader.target, dialog, 1)
            else:
                dialogs.text(dialog, cid, format(value, ".9g"))
                _message(dialogs.control(dialog, cid, "Edit"), 0x100, 13, 1)
                dialogs.close(reader.target, dialog, None)
            dialogs.menu_command(reader.target.hwnd, command)
            dialog = dialogs.wait_dialog(reader.target, title)
            if cid is None:
                actual = {channel: int(window_text(dialogs.control(dialog, 706 + index, "Edit")))
                          for index, channel in enumerate("rgb")}
                mismatch = any(actual[channel] != number for channel, number in value.model_dump(exclude_none=True).items())
                dialogs.close(reader.target, dialog)
            else:
                actual = float(window_text(dialogs.control(dialog, cid, "Edit")))
                mismatch = abs(actual - value) > .0051
                dialogs.close(reader.target, dialog, None)
            result[name] = actual
            if mismatch:
                return {"status": "partial", "readback": result, "failed_setting": name,
                        "note": "Native style readback mismatch; earlier changes remain applied."}
        return {"status": "completed", "readback": result}


def output_size(size=None, hwnd=None):
    size = OutputSize.model_validate(size) if size is not None else None
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader)
        def open_size():
            dialogs.menu_command(reader.target.hwnd, 212)
            return dialogs.wait_dialog(reader.target, "出力画面サイズ変更")
        def read_size(dialog):
            return {name: int(window_text(dialogs.control(dialog, cid, "Edit")))
                    for name, cid in [("width", 621), ("height", 622)]}
        dialog = open_size()
        before = read_size(dialog)
        if size is not None:
            dialogs.text(dialog, 621, size.width)
            dialogs.text(dialog, 622, size.height)
            dialogs.close(reader.target, dialog, 1)
            dialog = open_size()
        after = read_size(dialog)
        dialogs.close(reader.target, dialog)
        reader.verify(anchor)
        if size is not None and after != size.model_dump():
            raise RuntimeError(f"Output size readback mismatch: {after}")
        return {"status": "completed", "before": before, "size": after,
                "changed": before != after}


def listbox_items(dialog):
    handle = dialogs.control(dialog, 628, "ListBox")
    count = _message(handle, 0x18B)
    if not 0 <= count <= 1024:
        raise RuntimeError("Unsupported model order list size.")
    values = []
    for index in range(count):
        length = _message(handle, 0x18A, index)
        if not 0 <= length < 4096:
            raise RuntimeError("Unsupported model name length.")
        buffer = ctypes.create_unicode_buffer(length + 1)
        if _message(handle, 0x189, index, ctypes.addressof(buffer)) != length:
            raise RuntimeError("Model order list changed while reading.")
        values.append(buffer.value)
    return values


def model_order(kind, order=None, expected_names=None, hwnd=None):
    if kind not in {"draw", "compute"}:
        raise ValueError("Expected draw or compute order.")
    if order is not None and (any(type(i) is not int for i in order) or expected_names is None):
        raise ValueError("An order needs integer indices and expected_names from the previous read.")
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        def open_order():
            dialogs.menu_command(reader.target.hwnd, 288 if kind == "draw" else 289)
            return dialogs.wait_dialog(reader.target, "モデル描画順設定" if kind == "draw" else "モデル計算順設定")
        dialog = open_order()
        before = listbox_items(dialog)
        if order is not None:
            if expected_names != before or sorted(order) != list(range(len(before))):
                dialogs.close(reader.target, dialog)
                raise ValueError("Order must permute all current zero-based indices and expected_names must match exactly.")
            indices = list(range(len(before)))
            for destination, item in enumerate(order):
                current = indices.index(item)
                while current > destination:
                    handle = dialogs.control(dialog, 628, "ListBox")
                    if _message(handle, 0x186, current) != current:
                        raise RuntimeError("Model order selection failed.")
                    _message(dialog["hwnd"], 0x111, 628 | (1 << 16), handle)
                    _message(dialogs.control(dialog, 630, "Button"), 0xF5)
                    indices[current - 1], indices[current] = indices[current], indices[current - 1]
                    current -= 1
                    if listbox_items(dialog) != [before[i] for i in indices]:
                        raise RuntimeError("Model order changed unexpectedly.")
            dialogs.close(reader.target, dialog, 632)
            dialog = open_order()
        after = listbox_items(dialog)
        dialogs.close(reader.target, dialog)
        if order is not None and after != [before[i] for i in order]:
            raise RuntimeError("Model order did not persist after dialog close.")
        return {"status": "completed", "kind": kind, "before": before, "names": after,
                "note": "Indices are zero-based in this order list, not model selector IDs. Reread model selectors after changing order."}


GRAVITY_FIELDS = {"acceleration": 709, "x": 710, "y": 711, "z": 712, "noise_amount": 713}


def gravity_read(dialog):
    result = {}
    for name, cid in GRAVITY_FIELDS.items():
        handle = win32gui.GetDlgItem(dialog["hwnd"], cid)
        if not handle or win32gui.GetClassName(handle) != "Edit":
            raise RuntimeError("Gravity dialog layout mismatch.")
        result[name] = float(window_text(handle))
    result["noise"] = bool(_message(dialogs.control(dialog, 731, "Button"), 0xF0))
    return result


def gravity(reader, values=None, register=False):
    dialogs.menu_command(reader.target.hwnd, 266)
    dialog = dialogs.wait_dialog(reader.target, "重力設定")
    before = gravity_read(dialog)
    if values is not None:
        requested = values.model_dump(exclude_none=True)
        if values.noise_amount is not None and not requested.get("noise", before["noise"]):
            dialogs.close(reader.target, dialog)
            raise ValueError("Enable noise before setting its amount.")
        if values.noise is not None and values.noise != before["noise"]:
            _message(dialogs.control(dialog, 731, "Button"), 0xF5)
        for name, cid in GRAVITY_FIELDS.items():
            if name in requested:
                dialogs.text(dialog, cid, format(requested[name], ".9g"))
                _message(dialogs.control(dialog, cid, "Edit"), 0x100, 13, 1)
        if register:
            _message(dialogs.control(dialog, 1, "Button"), 0xF5)
    after = gravity_read(dialog)
    dialogs.close(reader.target, dialog)
    if values is not None:
        for name, wanted in requested.items():
            if abs(after[name] - wanted) > .0051:
                raise RuntimeError(f"Gravity {name} readback mismatch: {after[name]}")
    return {"before": before, "gravity": after, "registered": register}


def get_gravity(hwnd=None):
    with mutation():
        reader = UIReader(hwnd)
        anchor = context(reader)
        result = gravity(reader)
        reader.verify(anchor)
        return result
