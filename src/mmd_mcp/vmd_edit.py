"""Preserve native VMD payloads while editing key timing or interpolation in a new file."""

import hashlib
import struct
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .motion_document import Curve
from .vmd_reader import Reader, TRACKS, inspect, MAX_BYTES


class VmdEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["shift", "scale_time", "delete", "interpolation"]
    track: Literal["bones", "morphs", "camera", "light", "shadow", "model_flags"]
    start_frame: Annotated[int, Field(strict=True, ge=0, le=999999)] = 0
    end_frame: Annotated[int, Field(strict=True, ge=0, le=999999)] = 999999
    names: list[str] | None = None
    shift_frames: Annotated[int, Field(strict=True, ge=-999999, le=999999)] | None = None
    factor: Annotated[float, Field(allow_inf_nan=False, gt=0, le=1000)] | None = None
    curves: dict[Literal["x", "y", "z", "rotation", "distance", "fov"], Curve] | None = None

    @model_validator(mode="after")
    def content(self):
        if self.end_frame < self.start_frame:
            raise ValueError("Provide an ordered frame range.")
        if self.names is not None and (self.track not in {"bones", "morphs"} or not self.names):
            raise ValueError("names is a nonempty bone/morph name filter only.")
        payloads = {"shift": self.shift_frames, "scale_time": self.factor,
                    "interpolation": self.curves}
        if self.action != "delete" and payloads[self.action] is None:
            raise ValueError("Missing action payload.")
        if any(value is not None and key != self.action for key, value in payloads.items()):
            raise ValueError("Unexpected action payload.")
        if self.action == "interpolation":
            if self.track not in {"bones", "camera"} or not self.curves:
                raise ValueError("Interpolation edits require bone or camera curves.")
            if self.track == "bones" and set(self.curves) - {"x", "y", "z", "rotation"}:
                raise ValueError("Bone interpolation has x/y/z/rotation channels only.")
        return self


def split_records(data):
    source = Reader(data)
    signature = source.take(30).rstrip(b"\0")
    source.take(20 if signature == b"Vocaloid Motion Data 0002" else 10)
    prefix = data[:source.offset]
    tracks = {}
    for kind, size in zip(TRACKS, (111, 23, 61, 28, 9, 9)):
        if source.offset == len(data):
            break
        records = []
        for _ in range(source.count(size)):
            start = source.offset
            source.take(size)
            if kind == "model_flags":
                ik_count = struct.unpack_from("<I", data, start + 5)[0]
                source.take(ik_count * 21)
            records.append(bytearray(data[start:source.offset]))
        tracks[kind] = records
    return prefix, tracks, data[source.offset:]


def edit(source_path, output_path, edits):
    source_path, output_path = Path(source_path), Path(output_path)
    observed = inspect(str(source_path), limit=1)  # Validate the complete source before mutation.
    if not output_path.is_absolute() or output_path.suffix.lower() != ".vmd" or output_path.exists():
        raise ValueError("Choose a new absolute .vmd output path; existing files are not overwritten.")
    if not edits or len(edits) > 100:
        raise ValueError("Provide 1–100 VMD edits.")
    edits = [VmdEdit.model_validate(item) for item in edits]
    data = source_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != observed["sha256"]:
        raise RuntimeError("Source VMD changed after validation; no output written.")
    if len(data) > MAX_BYTES:
        raise ValueError("VMD exceeds 128 MiB.")
    prefix, tracks, trailer = split_records(data)
    changes = []
    for spec in edits:
        changed, output = 0, []
        frame_offset = 15 if spec.track in {"bones", "morphs"} else 0
        for record in tracks.get(spec.track, []):
            frame, = struct.unpack_from("<I", record, frame_offset)
            name = bytes(record[:15]).split(b"\0", 1)[0].decode("cp932") if frame_offset else None
            matches = spec.start_frame <= frame <= spec.end_frame and (spec.names is None or name in spec.names)
            if matches:
                changed += 1
                if spec.action == "delete":
                    continue
                if spec.action in {"shift", "scale_time"}:
                    frame = frame + spec.shift_frames if spec.action == "shift" else spec.start_frame + round((frame - spec.start_frame) * spec.factor)
                    if not 0 <= frame <= 999999:
                        raise ValueError("Timing edit would put a key outside 0..999999.")
                    struct.pack_into("<I", record, frame_offset, frame)
                else:
                    for channel, curve in spec.curves.items():
                        index = ("x", "y", "z", "rotation", "distance", "fov").index(channel)
                        if spec.track == "bones":
                            # Native MMD keeps each channel in its own 16-byte block.
                            # Preserve unrelated redundant bytes, including native physics flags.
                            for step, value in enumerate((curve.x1, curve.y1, curve.x2, curve.y2)):
                                record[47 + index * 16 + step * 4] = value
                        else:
                            record[32 + index * 4:36 + index * 4] = bytes((curve.x1, curve.x2, curve.y1, curve.y2))
            output.append(record)
        if not changed:
            raise ValueError(f"No keys matched {spec.action} on {spec.track}.")
        identities = [(bytes(r[:15]) if frame_offset else b"", struct.unpack_from("<I", r, frame_offset)[0]) for r in output]
        if len(set(identities)) != len(identities):
            raise ValueError("VMD edit creates duplicate name/frame keys; choose non-colliding timing.")
        tracks[spec.track] = output
        changes.append({"action": spec.action, "track": spec.track, "matched_keys": changed})
    result = bytearray(prefix)
    for kind in TRACKS:
        if kind in tracks:
            result.extend(struct.pack("<I", len(tracks[kind])))
            for record in tracks[kind]:
                result.extend(record)
    result.extend(trailer)
    if source_path.read_bytes() != data:
        raise RuntimeError("Source VMD changed during editing; no output written.")
    with output_path.open("xb") as stream:
        stream.write(result)
    return {"path": str(output_path), "sha256": hashlib.sha256(result).hexdigest(), "changes": changes,
            "applied_to_mmd": False, "note": "New file only; source preserved. Timing scale rounds to nearest integer frame. Import at frame 0; for timing/deletion replace the intended live key range first, because VMD import merges keys."}
