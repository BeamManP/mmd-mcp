"""Camera and light keys across frames in one call (camera/light/accessory mode).

Per frame: enter the frame once, write the listed camera and light fields through the
native numeric controls, read them back, and press the camera (452) / light (468)
登録 buttons. Context is verified once per batch and once per frame.
"""
import time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import scene_controls as scene
from .bone_controls import AxisValues
from .ui_state import UIReader
from . import render_controls

STEP_SECONDS = 30
CAMERA_REGISTER, LIGHT_REGISTER = 452, 468


class CameraValues(BaseModel):
    position: AxisValues | None = None
    rotation_degrees: AxisValues | None = None
    distance: Annotated[float, Field(allow_inf_nan=False, ge=-100000, le=100000)] | None = None
    fov_degrees: Annotated[float, Field(allow_inf_nan=False, ge=1, le=125)] | None = None
    perspective: bool | None = None

    def updates(self):
        result = [(scene.CAMERA_FIELDS[kind][axis], value) for kind, patch in
                  [('position', self.position), ('rotation_degrees', self.rotation_degrees)]
                  if patch is not None for axis, value in patch.model_dump(exclude_none=True).items()]
        for kind, value in [('distance', self.distance), ('fov_degrees', self.fov_degrees)]:
            if value is not None:
                result.append((scene.CAMERA_FIELDS[kind], value))
        return result


class LightValues(BaseModel):
    color: scene.RGBValues | None = None
    direction: scene.DirectionValues | None = None

    def updates(self):
        result = [(scene.LIGHT_FIELDS['color'][ch], value) for ch, value in
                  (self.color.model_dump(exclude_none=True).items() if self.color else [])]
        result += [(scene.LIGHT_FIELDS['direction'][axis], value) for axis, value in
                   (self.direction.model_dump(exclude_none=True).items() if self.direction else [])]
        return result


class ShadowValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Annotated[int, Field(strict=True, ge=0, le=2)] | None = None
    distance: Annotated[float, Field(allow_inf_nan=False, ge=0, le=10000)] | None = None

    @model_validator(mode="after")
    def content(self):
        if self.mode is None and self.distance is None:
            raise ValueError("Specify shadow mode or distance.")
        return self


class CameraFrame(BaseModel):
    frame: Annotated[int, Field(strict=True, ge=0)]
    camera: CameraValues | None = None
    light: LightValues | None = None
    shadow: ShadowValues | None = None
    gravity: render_controls.GravityValues | None = None
    register_key: bool = True

    @model_validator(mode='after')
    def _content(self):
        if all(value is None for value in (self.camera, self.light, self.shadow, self.gravity)):
            raise ValueError('A frame item needs camera, light, shadow or gravity values.')
        if self.camera and not self.camera.updates() and self.camera.perspective is None:
            raise ValueError('camera has no values.')
        if self.light and not self.light.updates():
            raise ValueError('light has no values.')
        return self


def _check(actual, updates, tolerance):
    return [cid for cid, value in updates if abs(actual[cid] - value) > tolerance]


def batch_camera_keys(items, return_to_frame=True, hwnd=None):
    start = time.monotonic()
    if not items:
        raise ValueError('Provide at least one frame item.')
    if len({i.frame for i in items}) != len(items):
        raise ValueError('Each frame may appear once.')
    progress = {'frames_completed': [], 'timing': {}}

    def stop(status, error):
        progress['timing']['total_seconds'] = round(time.monotonic() - start, 3)
        return {'status': status, 'error': error, **progress, 'saved_to_disk': False,
                'note': 'Frames listed above are applied; nothing was rolled back.'}

    with scene.mutation():
        reader = UIReader(hwnd)
        origin = int(scene.context(reader, 'camera')[0])
        for frame in sorted(i.frame for i in items):
            item = next(i for i in items if i.frame == frame)
            record = {'frame': frame}
            try:
                reader.deadline = time.monotonic() + STEP_SECONDS
                scene.commit_number(reader, 417, frame)
                anchor = scene.context(reader, 'camera')
                if int(anchor[0]) != frame:
                    raise RuntimeError('MMD did not display the requested frame.')
                if item.camera:
                    updates = item.camera.updates()
                    scene.apply_fields(reader, anchor, updates)
                    if item.camera.perspective is not None:
                        current = bool(scene._message(scene.available(reader, 446, 'Button'), 0xF0))
                        if current != item.camera.perspective:
                            scene.click_button(reader, 446)
                    actual = scene.numbers(reader, {cid: cid for cid, _ in updates}) if updates else {}
                    bad = _check(actual, updates, .0051)
                    if bad:
                        raise RuntimeError(f'Camera readback mismatch on {bad}.')
                    if item.register_key:
                        scene.click_button(reader, CAMERA_REGISTER)
                    record['camera'] = {'written': len(updates), 'registered': item.register_key}
                if item.light:
                    updates = item.light.updates()
                    scene.apply_fields(reader, anchor, updates)
                    actual = scene.numbers(reader, {cid: cid for cid, _ in updates})
                    bad = _check(actual, updates, .0051)
                    if bad:
                        raise RuntimeError(f'Light readback mismatch on {bad}.')
                    if item.register_key:
                        scene.click_button(reader, LIGHT_REGISTER)
                    record['light'] = {'written': len(updates), 'registered': item.register_key}
                if item.shadow:
                    if item.shadow.mode is not None:
                        scene.click_button(reader, 562 + item.shadow.mode)
                        if not scene._message(scene.available(reader, 562 + item.shadow.mode, 'Button'), 0xF0):
                            raise RuntimeError('Shadow mode readback mismatch.')
                    if item.shadow.distance is not None:
                        scene.commit_number(reader, 561, item.shadow.distance)
                        actual = scene.numbers(reader, {561: 561})
                        if abs(actual[561] - item.shadow.distance) > .0051:
                            raise RuntimeError('Shadow distance readback mismatch.')
                    if item.register_key:
                        scene.click_button(reader, 565)
                    record['shadow'] = {'registered': item.register_key}
                if item.gravity:
                    record['gravity'] = render_controls.gravity(reader, item.gravity, item.register_key)
                reader.verify(anchor)
            except (ValueError, RuntimeError) as exc:
                progress['frames_completed'].append({**record, 'incomplete': True})
                return stop('incomplete', f'Frame {frame}: {exc}')
            progress['frames_completed'].append(record)
        try:
            reader.deadline = time.monotonic() + STEP_SECONDS
            if return_to_frame and int(scene.context(reader, 'camera')[0]) != origin:
                scene.commit_number(reader, 417, origin)
            final = scene.context(reader, 'camera')
        except (ValueError, RuntimeError) as exc:
            return stop('completed_unverified', f'Final check failed: {exc}')
    progress['timing']['total_seconds'] = round(time.monotonic() - start, 3)
    return {'status': 'completed', **progress, 'displayed_frame': int(final[0]), 'saved_to_disk': False,
            'note': 'Camera/light keys registered per frame when register_key=true. Omitted fields keep MMD\'s displayed values.'}
