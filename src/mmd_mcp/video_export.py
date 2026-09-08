"""Native AVI export jobs; completion requires the output writer to release the file."""

from .ui_language import matches

import ctypes
import struct
import time
import uuid
from typing import Annotated

import win32file
import win32gui
import pywintypes
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from . import native_dialogs as dialogs
from .bone_controls import _message
from .file_operations import file_path, owned_dialogs, run_dialog_flow, verify_process
from .scene_controls import context, mutation
from .ui_state import UIReader

_jobs = {}


class VideoOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_frame: Annotated[int, Field(strict=True, ge=0, le=999999)]
    end_frame: Annotated[int, Field(strict=True, ge=0, le=999999)]
    fps: Annotated[int, Field(strict=True, ge=1, le=120)] = 30
    codec: str = "未圧縮"
    include_audio: StrictBool = False

    @model_validator(mode="after")
    def range_valid(self):
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be at least start_frame.")
        return self


def codec_items(dialog):
    handle = dialogs.control(dialog, 628, "ComboBox")
    count = _message(handle, 0x146)
    if not 1 <= count <= 256:
        raise RuntimeError("Unsupported native codec list.")
    items = []
    for index in range(count):
        length = _message(handle, 0x149, index)
        if not 0 <= length < 4096:
            raise RuntimeError("Unsupported codec name length.")
        buffer = ctypes.create_unicode_buffer(length + 1)
        _message(handle, 0x148, index, ctypes.addressof(buffer))
        items.append(buffer.value)
    return handle, items


def avi_header(path):
    with path.open("rb") as source:
        data = source.read(65536)
    if data[:4] != b"RIFF" or data[8:12] != b"AVI ":
        raise ValueError("Output does not have an AVI RIFF header.")
    offset = data.find(b"avih", 12)
    if offset < 0 or offset + 64 > len(data) or struct.unpack_from("<I", data, offset + 4)[0] != 56:
        raise ValueError("AVI main header is missing or invalid.")
    micros, _, _, _, main_frames, _, streams, _, width, height = struct.unpack_from("<10I", data, offset + 8)
    # MMD's muxer can put a combined stream count in avih when audio is enabled.
    # The vids stream's dwLength is the actual number of video frames.
    video = []
    def chunks(start, end):
        while start + 8 <= min(end, len(data)):
            kind, length = data[start:start + 4], struct.unpack_from("<I", data, start + 4)[0]
            stop = start + 8 + length
            if stop > len(data):
                break
            if kind == b"LIST" and length >= 4 and data[start + 8:start + 12] in {b"hdrl", b"strl"}:
                chunks(start + 12, stop)
            elif kind == b"strh" and length >= 56 and data[start + 8:start + 12] == b"vids":
                scale, rate, _, frames = struct.unpack_from("<4I", data, start + 8 + 20)
                video.append((frames, rate / scale if scale else 0))
            start = stop + (length & 1)
    chunks(12, len(data))
    if len(video) != 1:
        raise ValueError("AVI video stream header is missing or ambiguous.")
    frames, fps = video[0]
    if not frames or not width or not height or not micros or not fps:
        raise ValueError("AVI header is incomplete or contains no frames.")
    return {"frames": frames, "width": width, "height": height,
            "fps": round(fps, 4), "streams": streams, "main_header_frames": main_frames,
            "bytes": path.stat().st_size}


def status(job_id):
    if job_id not in _jobs:
        raise ValueError("Unknown export job; job IDs belong to this server process.")
    job = _jobs[job_id]
    if "result" in job:
        return job["result"]
    target, path = job["target"], job["path"]
    verify_process(target)
    current_dialogs = owned_dialogs(target)
    result = {"job_id": job_id, "path": str(path), "status": "rendering",
              "elapsed_seconds": round(time.monotonic() - job["started"], 2)}
    if current_dialogs:
        return {**result, "status": "dialog_requires_action", "dialogs": current_dialogs}
    if not win32gui.IsWindowEnabled(target.hwnd):
        return result
    if not path.exists() or path.stat().st_mtime_ns == job.get("before_stamp"):
        if time.monotonic() - job["started"] < 1:
            return result
        result.update(status="verification_failed", error="No newly written AVI output was observed.")
        job["result"] = result
        return result
    try:
        handle = win32file.CreateFile(str(path), 0x80000000, 0, None, 3, 0, None)
    except pywintypes.error as error:
        if error.winerror in {32, 33}:
            return result
        raise
    else:
        handle.Close()
    try:
        header = avi_header(path)
    except ValueError as error:
        if time.monotonic() - job["started"] < 1:
            return result
        result.update(status="verification_failed", error=str(error))
        job["result"] = result
        return result
    result.update(status="completed", avi=header, saved_to_disk=True)
    job["result"] = result
    return result


def block_if_active(hwnd):
    for job_id, job in list(_jobs.items()):
        if "result" not in job and job["target"].hwnd == hwnd:
            result = status(job_id)
            if result["status"] in {"rendering", "dialog_requires_action"}:
                raise ValueError(f"MMD is exporting AVI (job {job_id}); check mmd_get_video_export_status before editing.")


def export(path, options, overwrite=False, hwnd=None):
    options = VideoOptions.model_validate(options)
    candidate = file_path(path, {".avi"}, write=True, overwrite=overwrite)
    before_stamp = candidate.stat().st_mtime_ns if candidate.exists() else None
    with mutation():
        reader = UIReader(hwnd)
        context(reader)
        for job in _jobs.values():
            if "result" not in job and job["target"].hwnd == reader.target.hwnd:
                raise ValueError("Check the existing AVI export job before starting another.")
        dialogs.menu_command(reader.target.hwnd, 223)
        result = run_dialog_flow(reader.target, candidate, overwrite=overwrite)
        found = result.get("dialogs", [])
        if (result["status"] != "dialog_requires_action" or not result["path_submitted"]
                or len(found) != 1 or not matches(found[0]["title"], "AVI出力設定")):
            return {"path": str(candidate), **result}
        dialog = found[0]
        combo, codecs = codec_items(dialog)
        codec = options.codec
        if codec in {"未圧縮", "AVI Raw", "uncompressed"}:
            raw = [name for name in codecs if name in {"未圧縮", "AVI Raw"}]
            codec = raw[0] if len(raw) == 1 else codec
        if codecs.count(codec) != 1:
            dialogs.close(reader.target, dialog)
            raise ValueError(f"Choose an exact installed codec name: {codecs}")
        if options.include_audio:
            dialogs.control(dialog, 614, "Button")
        for cid, value in [(609, options.start_frame), (610, options.end_frame), (611, options.fps)]:
            dialogs.text(dialog, cid, value)
        index = codecs.index(codec)
        if _message(combo, 0x14E, index) != index:
            raise RuntimeError("Codec selection failed.")
        _message(dialog["hwnd"], 0x111, 628 | (1 << 16), combo)
        audio = win32gui.GetDlgItem(dialog["hwnd"], 614)
        if bool(_message(audio, 0xF0)) != options.include_audio:
            _message(dialogs.control(dialog, 614, "Button"), 0xF5)
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {"target": reader.target, "path": candidate, "started": time.monotonic(),
                         "before_stamp": before_stamp}
        win32gui.PostMessage(dialogs.control(dialog, 1, "Button"), 0xF5, 0, 0)
        time.sleep(.2)
        return {**status(job_id), "options": options.model_dump(),
                "note": "For rendering jobs, call mmd_get_video_export_status until completed. Job IDs last for this server process; do not edit or close MMD during export."}
