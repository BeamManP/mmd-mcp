"""One-call accessory workflow: load N files, set values per frame, register keys.

The per-call context checks of the single-step tools are kept once per batch and
once per frame; per-item checks shrink to "the accessory selector did not drift".
No unknown dialog is ever accepted; a stop returns the progress made so far.
"""
import ctypes
import time
from typing import Annotated

import win32gui
from pydantic import BaseModel, Field, StrictBool, model_validator

from . import accessory_controls as acc
from . import file_operations as files
from . import scene_controls as scene
from .bone_controls import AxisValues, _message
from .ui_state import UIReader

STEP_SECONDS = 30


class AccessoryKey(BaseModel):
    """Values applied at one frame; omitted fields keep whatever MMD displays there."""
    frame: Annotated[int, Field(strict=True, ge=0)]
    position: AxisValues | None = None
    rotation_degrees: AxisValues | None = None
    scale: Annotated[float, Field(gt=0, le=100000, allow_inf_nan=False)] | None = None
    opacity: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    visible: bool | None = None
    shadow: bool | None = None
    parent_model_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    parent_bone_name: str | None = None
    register_key: bool = True

    @model_validator(mode='after')
    def _parent_pair(self):
        if self.parent_model_index is None and self.parent_bone_name is not None:
            raise ValueError('parent_bone_name requires parent_model_index.')
        if self.parent_model_index is not None and (self.parent_model_index == 0) != (self.parent_bone_name is None):
            raise ValueError('Ground (parent_model_index 0) takes no bone; a model parent needs an exact bone name.')
        return self

    def updates(self):
        result = [(acc.FIELDS[kind][axis], value) for kind, patch in
                  [('position', self.position), ('rotation_degrees', self.rotation_degrees)]
                  if patch is not None for axis, value in patch.model_dump(exclude_none=True).items()]
        for kind, value in [('scale', self.scale), ('opacity', self.opacity)]:
            if value is not None:
                result.append((acc.FIELDS[kind], value))
        return result


class AccessoryItem(BaseModel):
    """Either a file to load (path) or an accessory already in the selector (selector_index)."""
    path: str | None = None
    selector_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    additive: StrictBool | None = None
    keys: list[AccessoryKey] = Field(default_factory=list)

    @model_validator(mode='after')
    def _one_target(self):
        if (self.path is None) == (self.selector_index is None):
            raise ValueError('Specify exactly one of path or selector_index per item.')
        frames = [key.frame for key in self.keys]
        if len(frames) != len(set(frames)):
            raise ValueError('Each item may have at most one key per frame.')
        if self.path is None and not self.keys and self.additive is None:
            raise ValueError('An existing accessory item needs at least one key.')
        return self


def _elapsed(start):
    return round(time.monotonic() - start, 3)


def _select(reader, index):
    """Selector switch with the same readback guard as the single-step tool."""
    reader.deadline = time.monotonic() + STEP_SECONDS
    acc.choose(reader, 471, index)


def _write_key(reader, index, key):
    """Write one key's fields to the selected accessory and read them back."""
    updates = key.updates()
    completed = []
    if key.parent_model_index is not None:
        reader.deadline = time.monotonic() + STEP_SECONDS
        models = reader.combo(474)
        scene.resolve_index(models['items'], key.parent_model_index, None)
        acc.choose(reader, 474, key.parent_model_index)
        completed.append(474)
        if key.parent_model_index:
            bones = reader.combo(475)
            acc.choose(reader, 475, scene.resolve_index(bones['items'], None, key.parent_bone_name))
            completed.append(475)
    for control_id, value in updates:
        reader.deadline = time.monotonic() + STEP_SECONDS
        edit = scene.available(reader, control_id, 'Edit')
        buffer = ctypes.create_unicode_buffer(format(value, '.9g'))
        if not _message(edit, 0xC, 0, ctypes.addressof(buffer)):
            raise RuntimeError('Accessory numeric text was rejected.')
        _message(edit, 0x100, 13, 1)
        completed.append(control_id)
    if updates:
        reader.deadline = time.monotonic() + STEP_SECONDS
        actual = scene.numbers(reader, {control_id: control_id for control_id, _ in updates})
        for control_id, value in updates:
            if abs(actual[control_id] - value) > (.0051 if control_id == 485 else .000051):
                raise RuntimeError(f'Accessory value readback mismatch on {control_id}.')
    for name, wanted, control_id in [('visible', key.visible, 476), ('shadow', key.shadow, 486)]:
        if wanted is None:
            continue
        button = scene.available(reader, control_id, 'Button')
        if bool(_message(button, 0xF0)) != wanted:
            _message(button, 0xF5)
            completed.append(control_id)
            if bool(_message(button, 0xF0)) != wanted:
                raise RuntimeError(f'Accessory {name} readback mismatch.')
    selector = acc._selector(reader)
    if selector['selected_index'] != index:
        raise RuntimeError('Accessory selection drifted during the batch; inspect MMD before retrying.')
    return {'written_controls': completed, 'values': actual if updates else {}}


def _load(reader, candidate, expected_items):
    """Load one X file; MMD selects the new accessory, whose index is returned."""
    reader.deadline = time.monotonic() + STEP_SECONDS
    control = reader.control(files.LOADS['accessory'][1], 'Button')
    win32gui.PostMessage(control, 0xF5, 0, 0)

    def probe():
        probe_reader = UIReader(reader.target.hwnd)
        selector = probe_reader.combo(471)
        if selector is None:
            raise RuntimeError('accessory panel not readable yet')
        return selector

    result = files.run_dialog_flow(reader.target, candidate, probe=probe)
    if result['status'] != 'completed':
        return result, None
    selector = result.pop('after')
    if (len(selector['items']) != len(expected_items) + 1 or selector['items'][:-1] != expected_items
            or selector['items'][-1] != candidate.name or selector['selected_index'] != len(expected_items)):
        result['status'] = 'verification_failed'
        result['note'] = 'Accessory selector did not grow by exactly the loaded file. Inspect MMD before retrying.'
        return result, None
    return result, len(expected_items)


def batch_accessories(items, return_to_frame=True, hwnd=None):
    start = time.monotonic()
    if not items:
        raise ValueError('Provide at least one accessory item.')
    candidates = {i: files.file_path(item.path, files.LOADS['accessory'][0])
                  for i, item in enumerate(items) if item.path is not None}
    progress = {'loaded': [], 'keys_completed': [], 'timing': {}}

    def stop(status, error, **extra):
        progress['timing']['total_seconds'] = _elapsed(start)
        return {'status': status, 'error': error, **progress, **extra,
                'saved_to_disk': False,
                'note': 'Progress above remains applied in MMD. Nothing was undone; no unknown dialog was accepted.'}

    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        origin_frame = int(anchor[0])
        selector = acc._selector(reader, False)
        if selector is None:
            raise ValueError('Expand the accessory panel before running an accessory batch.')
        names = list(selector['items'])
        indices = {}
        for i, item in enumerate(items):
            if item.selector_index is not None:
                scene.resolve_index(names, item.selector_index, None)
                indices[i] = item.selector_index

        # Phase 1: loads, serial by nature (one MMD file dialog at a time).
        phase = time.monotonic()
        for i, candidate in candidates.items():
            result, index = _load(reader, candidate, names)
            if index is None:
                return stop('incomplete', f'Load of item {i} stopped: {result["status"]}.', load_result=result)
            names.append(candidate.name)
            indices[i] = index
            progress['loaded'].append({'item': i, 'selector_index': index, 'path': str(candidate)})
        progress['timing']['load_seconds'] = _elapsed(phase)

        # Additive blending is an accessory-wide setting, not a frame key.
        for i, item in enumerate(items):
            if item.additive is None:
                continue
            try:
                _select(reader, indices[i])
                button = scene.available(reader, 477, 'Button')
                if bool(_message(button, 0xF0)) != item.additive:
                    _message(button, 0xF5)
                if bool(_message(button, 0xF0)) != item.additive:
                    raise RuntimeError('Accessory additive setting readback mismatch.')
                progress.setdefault('settings_completed', []).append({'item': i, 'additive': item.additive})
            except (ValueError, RuntimeError) as exc:
                return stop('incomplete', f'Accessory-wide settings on item {i}: {exc}')

        # Phase 2: keys grouped by frame so each frame is entered once.
        phase = time.monotonic()
        by_frame = {}
        for i, item in enumerate(items):
            for key in item.keys:
                by_frame.setdefault(key.frame, []).append((i, key))
        for frame in sorted(by_frame):
            try:
                reader.deadline = time.monotonic() + STEP_SECONDS
                scene.commit_number(reader, 417, frame)
                frame_anchor = scene.context(reader, 'camera')
                if int(frame_anchor[0]) != frame:
                    raise RuntimeError('MMD did not display the requested frame.')
            except (ValueError, RuntimeError) as exc:
                return stop('incomplete', f'Frame {frame}: {exc}')
            for i, key in by_frame[frame]:
                index = indices[i]
                try:
                    _select(reader, index)
                    written = _write_key(reader, index, key)
                    if key.register_key:
                        reader.deadline = time.monotonic() + STEP_SECONDS
                        _message(scene.available(reader, 487, 'Button'), 0xF5)
                        if acc._selector(reader)['selected_index'] != index:
                            raise RuntimeError('Accessory selection drifted after key registration.')
                except (ValueError, RuntimeError) as exc:
                    return stop('incomplete', f'Item {i} (selector {index}) at frame {frame}: {exc}')
                progress['keys_completed'].append({'item': i, 'selector_index': index, 'frame': frame,
                                                   'registered': key.register_key, **written})
        progress['timing']['key_seconds'] = _elapsed(phase)

        # Wrap-up: confirm the process/context still match, optionally return to the start frame.
        try:
            reader.deadline = time.monotonic() + STEP_SECONDS
            # Re-entering a frame re-evaluates the animation and discards unregistered
            # edits, so only move when the displayed frame actually differs.
            if return_to_frame and by_frame and int(scene.context(reader, 'camera')[0]) != origin_frame:
                scene.commit_number(reader, 417, origin_frame)
            final = scene.context(reader, 'camera')
            final_selector = acc._selector(reader, False)
            if final_selector['items'] != names:
                raise RuntimeError('Accessory list differs from the batch expectation.')
        except (ValueError, RuntimeError) as exc:
            return stop('completed_unverified', f'Final check failed: {exc}')
        progress['timing']['total_seconds'] = _elapsed(start)
        return {'status': 'completed', **progress, 'displayed_frame': int(final[0]),
                'accessory_selector': final_selector, 'saved_to_disk': False,
                'note': 'Keys were registered per frame for items with register_key=true; fields omitted in a key '
                        'were registered with the values MMD displayed at that frame.'}
