"""Editable sparse authoring data, deliberately separate from loaded PMM keys."""
import hashlib
import struct
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .rotation import from_ui

Number = Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000)]
Frame = Annotated[int, Field(strict=True, ge=0, le=999999)]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Vector(Strict):
    x: Number = 0.
    y: Number = 0.
    z: Number = 0.


class Curve(Strict):
    """VMD cubic Bezier control points, on the incoming segment of a key."""
    x1: Annotated[int, Field(ge=0, le=127)] = 20
    y1: Annotated[int, Field(ge=0, le=127)] = 20
    x2: Annotated[int, Field(ge=0, le=127)] = 107
    y2: Annotated[int, Field(ge=0, le=127)] = 107

    @model_validator(mode='after')
    def monotonic_time(self):
        if self.x1 > self.x2:
            raise ValueError('Bezier time controls require x1 <= x2.')
        return self


class Interpolation(Strict):
    x: Curve = Field(default_factory=Curve)
    y: Curve = Field(default_factory=Curve)
    z: Curve = Field(default_factory=Curve)
    rotation: Curve = Field(default_factory=Curve)


def encoded_name(name, size):
    if '\x00' in name:
        raise ValueError('NUL is not allowed in VMD names.')
    raw = name.encode('cp932')
    if len(raw) > size:
        raise ValueError(f'VMD name exceeds {size} CP932 bytes: {name}')
    return raw.ljust(size, b'\x00')


class BoneKey(Strict):
    name: Name
    frame: Frame
    position: Vector = Field(default_factory=Vector)
    rotation_degrees: Vector = Field(default_factory=Vector)
    interpolation: Interpolation = Field(default_factory=Interpolation)


class MorphKey(Strict):
    name: Name
    frame: Frame
    weight: Annotated[float, Field(allow_inf_nan=False, ge=0, le=1)]


class MotionDocument(Strict):
    version: Literal[1] = 1
    model_name: Name
    model_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    fps: Literal[30] = 30
    bones: Annotated[list[BoneKey], Field(max_length=50000)] = Field(default_factory=list)
    morphs: Annotated[list[MorphKey], Field(max_length=50000)] = Field(default_factory=list)

    @model_validator(mode='after')
    def identities(self):
        encoded_name(self.model_name, 20)
        for keys in (self.bones, self.morphs):
            ids = [(key.name, key.frame) for key in keys]
            if len(ids) != len(set(ids)):
                raise ValueError('Duplicate track/frame keys are not allowed.')
            for key in keys:
                encoded_name(key.name, 15)
        return self


class KeyEdit(Strict):
    action: Literal['upsert_bone', 'upsert_morph', 'delete_bone', 'delete_morph']
    name: Name
    frame: Frame
    bone: BoneKey | None = None
    morph: MorphKey | None = None

    @model_validator(mode='after')
    def payload(self):
        key = self.bone if self.action == 'upsert_bone' else self.morph
        if self.action.startswith('delete'):
            if self.bone is not None or self.morph is not None:
                raise ValueError('Delete accepts no key payload.')
        elif key is None or (key.name, key.frame) != (self.name, self.frame):
            raise ValueError('Upsert needs a matching complete key payload.')
        if self.action == 'upsert_bone' and self.morph is not None or self.action == 'upsert_morph' and self.bone is not None:
            raise ValueError('Unexpected key payload.')
        return self


def edit_document(document, edits):
    if not 1 <= len(edits) <= 10000:
        raise ValueError('Supply 1..10000 edits.')
    data = document.model_dump()
    for edit in edits:
        kind = 'bones' if edit.action.endswith('bone') else 'morphs'
        match = lambda k: (k['name'], k['frame']) == (edit.name, edit.frame)
        if edit.action.startswith('delete') and not any(match(k) for k in data[kind]):
            raise ValueError(f'Cannot delete missing key {edit.name}@{edit.frame}.')
        data[kind] = [k for k in data[kind] if not match(k)]
        if edit.action.startswith('upsert'):
            data[kind].append((edit.bone if kind == 'bones' else edit.morph).model_dump())
    for kind in ('bones', 'morphs'):
        data[kind].sort(key=lambda k: (k['name'], k['frame']))
    return MotionDocument.model_validate(data)


def interpolation_bytes(interpolation):
    # Interleaved first block plus its shifted redundant blocks. MMD reads the
    # channel's own block; repeating block zero silently copies X onto Y/Z/rot.
    channels = [getattr(interpolation, c) for c in ('x', 'y', 'z', 'rotation')]
    block = bytes(getattr(c, point) for point in ('x1', 'y1', 'x2', 'y2') for c in channels)
    return b''.join(block[channel:] + bytes(channel) for channel in range(4))


def vmd_bytes(document):
    result = bytearray(b'Vocaloid Motion Data 0002'.ljust(30, b'\x00'))
    result += encoded_name(document.model_name, 20)
    result += struct.pack('<I', len(document.bones))
    for key in sorted(document.bones, key=lambda k: (k.name, k.frame)):
        p, r = key.position, key.rotation_degrees
        result += encoded_name(key.name, 15)
        result += struct.pack('<I7f', key.frame, p.x, p.y, p.z, *from_ui(r.x, r.y, r.z))
        result += interpolation_bytes(key.interpolation)
    result += struct.pack('<I', len(document.morphs))
    for key in sorted(document.morphs, key=lambda k: (k.name, k.frame)):
        result += encoded_name(key.name, 15) + struct.pack('<If', key.frame, key.weight)
    result += bytes(16)  # camera, light, self-shadow, IK-display record counts
    return bytes(result)


def save_document(document, path, kind='json'):
    target = Path(path)
    if not target.is_absolute() or target.suffix.lower() != ('.json' if kind == 'json' else '.vmd'):
        raise ValueError('Provide an absolute path with the matching .json/.vmd extension.')
    data = (document.model_dump_json(indent=2).encode('utf-8') if kind == 'json' else vmd_bytes(document))
    with target.open('xb') as stream:
        stream.write(data)
    return {'path': str(target), 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'bone_keys': len(document.bones), 'morph_keys': len(document.morphs),
            'loaded_into_mmd': False}


def read_document(path):
    target = Path(path)
    if not target.is_absolute() or target.stat().st_size > 32*1024*1024:
        raise ValueError('Provide an absolute authoring JSON path under 32 MiB.')
    return MotionDocument.model_validate_json(target.read_bytes())
