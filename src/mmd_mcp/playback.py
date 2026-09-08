"""Read and control native playback with explicit optional loop/range settings."""

import ctypes
import time
from typing import Annotated

import win32gui
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from .bone_controls import _message
from .scene_controls import mutation, available
from .ui_state import UIReader, parse_number


class PlaybackOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_frame: Annotated[int, Field(strict=True, ge=0, le=999999)] | None = None
    end_frame: Annotated[int, Field(strict=True, ge=0, le=999999)] | None = None
    repeat: StrictBool | None = None

    @model_validator(mode="after")
    def range_valid(self):
        if self.start_frame is not None and self.end_frame is not None and self.end_frame < self.start_frame:
            raise ValueError("end_frame must be at least start_frame.")
        return self


def read(reader):
    return {"playing": bool(_message(reader.control(408, "Button"), 0xF0)),
            "repeat": bool(_message(reader.control(411, "Button"), 0xF0)),
            "start_enabled": bool(_message(reader.control(414, "Button"), 0xF0)),
            "end_enabled": bool(_message(reader.control(413, "Button"), 0xF0)),
            "start_frame": parse_number(reader.text(reader.control(409, "Edit")), True),
            "end_frame": parse_number(reader.text(reader.control(410, "Edit")), True),
            "displayed_frame": parse_number(reader.text(reader.control(417, "Edit")), True)}


def get(hwnd=None):
    return read(UIReader(hwnd))


def set_playback(playing=None, options=None, hwnd=None):
    if playing is not None and type(playing) is not bool:
        raise ValueError("playing must be a boolean.")
    options = PlaybackOptions.model_validate(options) if options is not None else None
    if playing is None and (options is None or not options.model_dump(exclude_none=True)):
        raise ValueError("Specify playing or playback options.")
    with mutation():
        reader = UIReader(hwnd)
        from .video_export import block_if_active
        block_if_active(reader.target.hwnd)
        before = read(reader)
        if options is not None and before["playing"]:
            raise ValueError("Stop playback before changing its range/options.")
        if options is not None:
            for field, cid, checkbox in [("start_frame", 409, 414), ("end_frame", 410, 413)]:
                value = getattr(options, field)
                if value is None:
                    continue
                edit = available(reader, cid, "Edit")
                buffer = ctypes.create_unicode_buffer(str(value))
                _message(edit, 0xC, 0, ctypes.addressof(buffer))
                if reader.text(edit) != str(value):
                    raise RuntimeError("Playback range text readback mismatch.")
                check = available(reader, checkbox, "Button")
                if not _message(check, 0xF0):
                    _message(check, 0xF5)
            if options.repeat is not None:
                repeat = available(reader, 411, "Button")
                if bool(_message(repeat, 0xF0)) != options.repeat:
                    _message(repeat, 0xF5)
        if playing is not None and before["playing"] != playing:
            win32gui.PostMessage(available(reader, 408, "Button"), 0xF5, 0, 0)
            time.sleep(.1)
        after = read(reader)
        if playing is False and after["playing"]:
            raise RuntimeError("MMD did not stop playback.")
        return {"status": "completed", "before": before, **after,
                "note": "A short non-looping range can finish before readback. No keys are changed or saved."}
