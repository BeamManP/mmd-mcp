"""One-call bone/morph keying across frames for the active model.

Per frame: enter the frame once, then for each bone select it through the native
bridge, write its six fields, read them back once and register the key. The MMD
executable digest, bone table and exposed-bone list are verified once per batch
instead of once per bone. The temporary UI-thread hook is still installed and
removed per selection. Stops at the first failure and reports what was applied.
"""
from .ui_language import matches, english_mode

import math
import time
from typing import Annotated

from pydantic import BaseModel, Field, StrictBool, model_validator

from . import scene_controls as scene
from .authoring_live import PoseMorph
from .bone_controls import AxisValues, POSITION_IDS, ROTATION_IDS, _commit_edit, parse_number
from .bone_selection import dispatch_selection, exposed_bone_names
from .bone_state import BONE_STRIDE, BoneMemory, decode_name, inspect_bones
from .pose_authoring import SemanticPose, compile_pose, compile_with_profile, fk_summary, read_profile
from .ui_state import MORPH_CONTROLS, UIReader

STEP_SECONDS = 30
FIELD_IDS = {('position', axis): cid for axis, cid in POSITION_IDS.items()} | \
            {('rotation_degrees', axis): cid for axis, cid in ROTATION_IDS.items()}
TOLERANCE = {'position': .0051, 'rotation_degrees': .051}


class BoneValue(BaseModel):
    """Absolute values for the listed axes of one bone; omitted axes are preserved."""
    name: str
    position: AxisValues | None = None
    rotation_degrees: AxisValues | None = None
    physics: StrictBool | None = None

    def axes(self):
        return {(kind, axis): value for kind, patch in
                [('position', self.position), ('rotation_degrees', self.rotation_degrees)]
                if patch is not None for axis, value in patch.model_dump(exclude_none=True).items()}


class FrameItem(BaseModel):
    """Everything to key at one frame: an optional semantic pose, explicit bone values, morphs."""
    frame: Annotated[int, Field(strict=True, ge=0)]
    pose: SemanticPose | None = None
    bones: list[BoneValue] = Field(default_factory=list)
    morphs: list[PoseMorph] = Field(default_factory=list)
    register_key: bool = True

    @model_validator(mode='after')
    def _content(self):
        if self.pose is None and not self.bones and not self.morphs:
            raise ValueError('A frame item needs a pose, bones or morphs.')
        names = [b.name for b in self.bones]
        if len(names) != len(set(names)):
            raise ValueError('Each bone may appear once per frame; merge its axes.')
        if len({(m.category, m.name) for m in self.morphs}) != len(self.morphs):
            raise ValueError('Duplicate morph requests in one frame.')
        return self


def _elapsed(start):
    return round(time.monotonic() - start, 3)


def resolve_frame(item, model_path, profile=None):
    """Merge a compiled pose (all six axes) with explicit values (listed axes win).

    Returns (axes per bone, fk summary or None). `profile` avoids re-reading the model per frame."""
    merged = {}
    fk = None
    if item.pose is not None:
        if model_path is None and profile is None:
            raise ValueError('model_path is required to compile a semantic pose.')
        profile = profile or read_profile(model_path)
        compiled = compile_with_profile(profile, item.pose, item.frame)
        for key in compiled['bones']:
            merged[key['name']] = {(kind, axis): key[kind][axis]
                                   for kind in ('position', 'rotation_degrees') for axis in 'xyz'}
        fk = {'summary': compiled.get('fk'), 'solved_goals': compiled.get('solved_goals')}
    for bone in item.bones:
        merged.setdefault(bone.name, {}).update(bone.axes())
    if fk and item.bones and profile is not None:
        rotations = [{'name': n, 'rotation_degrees': {a: axes.get(('rotation_degrees', a), 0.) for a in 'xyz'}}
                     for n, axes in merged.items()]
        fk['summary'] = fk_summary(profile, rotations)
    physical = {bone.name for bone in item.bones if bone.physics is not None}
    return {name: axes for name, axes in merged.items() if axes or name in physical}, fk


def _read_fields(reader):
    reader.deadline = time.monotonic() + STEP_SECONDS
    handles = [scene.available(reader, cid, 'Edit') for cid in FIELD_IDS.values()]
    values = {}
    for key, raw in zip(FIELD_IDS, reader.texts(handles)):
        value = parse_number(raw)
        if value is None:
            raise RuntimeError(f'Bone field {key} has no valid number.')
        values[key] = value
    return values


def _key_bone(reader, memory, frame, name, index, axes, register, physics=None):
    """Select one bone natively, write its listed axes, read back, optionally register."""
    anchor = memory.anchor()
    raw_name = memory.read(anchor[5] + index * BONE_STRIDE, 20)
    if decode_name(raw_name) != name:
        raise RuntimeError(f'Bone table changed: index {index} is no longer {name!r}.')
    dispatch_selection(reader.target, anchor, frame, index, raw_name)
    if memory.anchor()[4] != index:
        raise RuntimeError(f'Native selection did not land on {name!r}.')
    reader.deadline = time.monotonic() + STEP_SECONDS
    for key, value in axes.items():
        _commit_edit(reader, FIELD_IDS[key], value)
    actual = _read_fields(reader)
    mismatch = [key for key, value in axes.items()
                if not math.isclose(actual[key], value, rel_tol=0, abs_tol=TOLERANCE[key[0]])]
    if mismatch:
        raise RuntimeError(f'Readback mismatch on {name!r}: {mismatch}')
    if memory.anchor()[4] != index:
        raise RuntimeError(f'Bone selection drifted after writing {name!r}.')
    if physics is not None:
        checkbox = scene.available(reader, 499, 'Button')
        if bool(scene._message(checkbox, 0xF0)) != physics:
            scene._message(checkbox, 0xF5)
        if bool(scene._message(checkbox, 0xF0)) != physics:
            raise RuntimeError(f'Bone physics readback mismatch on {name!r}.')
    if register:
        scene.click_button(reader, 500)
    return {'bone': name, 'index': index, 'written': len(axes), 'registered': register}


def _key_morph(reader, morph, register):
    combo_id, value_id = MORPH_CONTROLS[morph.category]
    reader.deadline = time.monotonic() + STEP_SECONDS
    combo = reader.combo(combo_id)
    index = scene.resolve_index(combo['items'], None, morph.name)
    scene.choose_combo(reader, combo_id, index)
    scene.commit_number(reader, value_id, morph.weight)
    actual = scene.numbers(reader, {'weight': value_id})['weight']
    if abs(actual - morph.weight) > .0051:
        raise RuntimeError(f'Morph readback mismatch: {morph.name}')
    if register:
        scene.click_button(reader, scene.MORPH_REGISTER[morph.category])
    return {'morph': f'{morph.category}:{morph.name}', 'weight': actual, 'registered': register}


def batch_bone_keys(items, model_path=None, return_to_frame=True, hwnd=None):
    start = time.monotonic()
    if not items:
        raise ValueError('Provide at least one frame item.')
    frames = [item.frame for item in items]
    if len(frames) != len(set(frames)):
        raise ValueError('Each frame may appear once; merge its bones and morphs.')
    profile = read_profile(model_path) if model_path is not None and any(i.pose is not None for i in items) else None
    plan = {}
    for item in items:
        axes, fk = resolve_frame(item, model_path, profile)
        plan[item.frame] = (axes, item, fk)
    progress = {'frames_completed': [], 'timing': {}}

    def stop(status, error):
        progress['timing']['total_seconds'] = _elapsed(start)
        return {'status': status, 'error': error, **progress, 'keyframes_registered': 'partial',
                'saved_to_disk': False,
                'note': 'Frames listed above are applied and cannot be undone here. Nothing was rolled back.'}

    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'model')
        if not matches(reader.text(reader.control(536, 'Button')), 'カメラ編'):
            raise ValueError('Switch MMD to bone editing mode before keying bones.')
        origin = int(anchor[0])
        memory = BoneMemory(reader.target)
        try:
            progress['operation_mode_switched_from'] = memory.ensure_selectable_mode(reader)
            snapshot = inspect_bones(memory, anchor[2], english=english_mode(reader))
            counts = {}
            for bone in snapshot['bones']:
                counts[bone['name']] = counts.get(bone['name'], 0) + 1
            table = {b['name']: b['index'] for b in snapshot['bones'] if counts[b['name']] == 1}
            if profile is not None:
                if [b['name'] for b in snapshot['bones']] != [b['name'] for b in profile['bones']]:
                    raise ValueError('Active model bone signature does not match model_path.')
            reader.deadline = time.monotonic() + STEP_SECONDS
            exposed = exposed_bone_names(reader.combo(434)['items'])
            for frame, (bones, item, _) in plan.items():
                for name in bones:
                    if name not in table:
                        raise ValueError(f'Bone {name!r} is missing or ambiguous on the active model (frame {frame}).')
                    if snapshot['bones'][table[name]].get('display_name', name) not in exposed:
                        raise ValueError(f'Bone {name!r} is not exposed in MMD\'s bone UI (frame {frame}).')
                for morph in item.morphs:
                    combo = reader.combo(MORPH_CONTROLS[morph.category][0])
                    if combo is None or combo['items'].count(morph.name) != 1:
                        raise ValueError(f'Morph is missing or ambiguous: {morph.name} (frame {frame}).')

            for frame in sorted(plan):
                bones, item, fk = plan[frame]
                record = {'frame': frame, 'bones': [], 'morphs': []}
                if fk:
                    record['fk'] = fk
                try:
                    reader.deadline = time.monotonic() + STEP_SECONDS
                    scene.commit_number(reader, 417, frame)
                    if int(scene.context(reader, 'model')[0]) != frame:
                        raise RuntimeError('MMD did not display the requested frame.')
                    for name, axes in bones.items():
                        physics = next((bone.physics for bone in item.bones if bone.name == name), None)
                        kwargs = {'physics': physics} if physics is not None else {}
                        record['bones'].append(_key_bone(reader, memory, frame, name, table[name], axes, item.register_key, **kwargs))
                    for morph in item.morphs:
                        record['morphs'].append(_key_morph(reader, morph, item.register_key))
                except (ValueError, RuntimeError) as exc:
                    progress['frames_completed'].append({**record, 'incomplete': True})
                    return stop('incomplete', f'Frame {frame}: {exc}')
                progress['frames_completed'].append(record)
            progress['timing']['key_seconds'] = _elapsed(start)
            try:
                reader.deadline = time.monotonic() + STEP_SECONDS
                # Re-entering a frame re-evaluates the animation and discards unregistered
                # edits, so only move when the displayed frame actually differs.
                if return_to_frame and int(scene.context(reader, 'model')[0]) != origin:
                    scene.commit_number(reader, 417, origin)
                final = scene.context(reader, 'model')
            except (ValueError, RuntimeError) as exc:
                return stop('completed_unverified', f'Final check failed: {exc}')
        finally:
            memory.close()
    progress['timing']['total_seconds'] = _elapsed(start)
    bone_count = sum(len(f['bones']) for f in progress['frames_completed'])
    # Keep the response small: per frame, bone names and morph results (values were verified by readback).
    progress['frames_completed'] = [{'frame': f['frame'], 'bones': [b['bone'] for b in f['bones']],
                                     'registered': all(b['registered'] for b in f['bones']) if f['bones'] else None,
                                     'morphs': f['morphs'], **({'fk': f['fk']} if f.get('fk') else {})}
                                    for f in progress['frames_completed']]
    return {'status': 'completed', **progress, 'bone_keys': bone_count,
            'displayed_frame': int(final[0]), 'model_name': final[2], 'saved_to_disk': False,
            'note': 'Keys registered per bone/morph at each frame for items with register_key=true. '
                    'Unlisted bones and morphs are untouched. Inspect a capture for visual correctness.'}
