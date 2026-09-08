"""Bounded inspection of native VMD records for export/readback verification."""

import hashlib
import math
import struct
from pathlib import Path

TRACKS = ("bones", "morphs", "camera", "light", "shadow", "model_flags")
MAX_BYTES = 128 * 1024 * 1024


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, length):
        if length < 0 or self.offset + length > len(self.data):
            raise ValueError("Truncated VMD record.")
        value = self.data[self.offset:self.offset + length]
        self.offset += length
        return value

    def unpack(self, fmt):
        values = struct.unpack(fmt, self.take(struct.calcsize(fmt)))
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            raise ValueError("Nonfinite VMD numeric value.")
        return values

    def count(self, minimum_size):
        count, = self.unpack("<I")
        if count > 1_000_000 or count * minimum_size > len(self.data) - self.offset:
            raise ValueError("Invalid VMD record count.")
        return count

    def name(self, length):
        return self.take(length).split(b"\0", 1)[0].decode("cp932")


def inspect(path, track=None, start_frame=0, end_frame=999999, offset=0, limit=200):
    path = Path(path)
    if not path.is_absolute() or path.suffix.lower() != ".vmd" or not path.is_file():
        raise ValueError("Provide an existing absolute .vmd path.")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("VMD exceeds 128 MiB inspection limit.")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("VMD exceeds 128 MiB inspection limit.")
    if (track is not None and track not in TRACKS) or not 0 <= start_frame <= end_frame or offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("Invalid VMD inspection filters.")
    source = Reader(data)
    header = source.take(30).rstrip(b"\0")
    if header == b"Vocaloid Motion Data 0002":
        name_length = 20
    elif header == b"Vocaloid Motion Data file":
        name_length = 10
    else:
        raise ValueError("Unsupported VMD signature.")
    model_name = source.name(name_length)
    counts, records, matched = {}, [], 0
    def emit(kind, record):
        nonlocal matched
        if (track is None or kind == track) and start_frame <= record["frame"] <= end_frame:
            if offset <= matched < offset + limit:
                records.append({"track": kind, **record})
            matched += 1
    for kind, size in zip(TRACKS, (111, 23, 61, 28, 9, 9)):
        if source.offset == len(data) and kind not in {"bones", "morphs"}:
            counts[kind] = 0
            continue
        count = source.count(size)
        counts[kind] = count
        for _ in range(count):
            record = {}
            if kind == "bones":
                record["name"] = source.name(15)
                frame, *values = source.unpack("<I7f")
                record.update(frame=frame, position=dict(zip("xyz", values[:3])),
                              quaternion_xyzw=values[3:])
                curve = source.take(64)
                record["interpolation"] = {channel: dict(zip(("x1", "y1", "x2", "y2"),
                    [curve[index * 16 + component * 4] for component in range(4)]))
                    for index, channel in enumerate(("x", "y", "z", "rotation"))}
            elif kind == "morphs":
                record["name"] = source.name(15)
                record["frame"], record["weight"] = source.unpack("<If")
            elif kind == "camera":
                frame, distance, *values = source.unpack("<If6f")
                record.update(frame=frame, distance=distance, position=dict(zip("xyz", values[:3])),
                              rotation_radians=dict(zip("xyz", values[3:])))
                record["interpolation_bytes"] = list(source.take(24))
                record["fov_degrees"], perspective = source.unpack("<IB")
                record["perspective"] = perspective == 0
            elif kind == "light":
                frame, *values = source.unpack("<I6f")
                record.update(frame=frame, color=dict(zip("rgb", values[:3])),
                              direction=dict(zip("xyz", values[3:])))
            elif kind == "shadow":
                record["frame"], record["mode"], record["distance_raw"] = source.unpack("<IBf")
            else:
                record["frame"], visible = source.unpack("<IB")
                record["visible"] = bool(visible)
                ik = []
                for _ in range(source.count(21)):
                    name = source.name(20)
                    enabled, = source.unpack("<B")
                    ik.append({"name": name, "enabled": bool(enabled)})
                record["ik"] = ik
            emit(kind, record)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "model_name": model_name, "counts": counts, "records": records,
            "matched_records": matched, "next_offset": offset + len(records) if matched > offset + len(records) else None,
            "trailing_bytes": len(data) - source.offset,
            "note": "File records, not live MMD. Camera distance/rotation and shadow distance retain VMD storage conventions; gravity and outer parents may require PMM. Results follow file track order, not global frame order."}
