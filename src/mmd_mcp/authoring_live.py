"""Serialized direct pose application and sampled motion previews."""
import json
import time
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
from pydantic import Field
from . import scene_controls as scene
from .bone_controls import AxisValues, _set_selected_bone_transform
from .bone_selection import _select_bone, exposed_bone_names
from .bone_state import list_bones
from .capture import capture_png
from .motion_document import Strict, BoneKey
from .pose_authoring import compile_pose, read_profile
from .ui_state import UIReader, MORPH_CONTROLS


class PoseMorph(Strict):
    category: scene.MorphCategory
    name: str
    weight: Annotated[float, Field(allow_inf_nan=False, ge=0, le=1)]


def apply_pose(model_path, pose, morphs, hwnd):
    compiled = compile_pose(model_path, pose)
    profile = read_profile(model_path)
    if profile['model_sha256'] != compiled['profile']['model_sha256']:
        raise RuntimeError('Model file changed while preparing the pose; inspect it before retrying.')
    keys = [BoneKey.model_validate(k) for k in compiled['bones']]
    completed = []
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'model')
        live = list_bones(reader.target.hwnd)
        if [b['name'] for b in live['bones']] != [b['name'] for b in profile['bones']]:
            raise ValueError('Active model bone signature does not match the supplied model.')
        reader.deadline = time.monotonic() + 30
        exposed = exposed_bone_names(reader.combo(434)['items'])
        if any(k.name not in exposed for k in keys):
            raise ValueError('Compiled pose contains a bone not exposed by this model.')
        if len({(m.category, m.name) for m in morphs}) != len(morphs):
            raise ValueError('Duplicate morph requests.')
        for morph in morphs:
            combo = reader.combo(MORPH_CONTROLS[morph.category][0])
            if combo is None or combo['items'].count(morph.name) != 1:
                raise ValueError(f'Morph is missing or ambiguous: {morph.name}')
        try:
            for key in keys:
                reader.deadline = time.monotonic() + 8
                reader.verify(anchor)
                _select_bone(key.name, None, reader.target.hwnd, verified_exposed_names=exposed)
                reader.verify(anchor)
                result = _set_selected_bone_transform(AxisValues(**key.position.model_dump()),
                    AxisValues(**key.rotation_degrees.model_dump()), reader.target.hwnd,
                    expected_bone_name=key.name)
                completed.append(key.name)
                if not result['requested_axes_match_display']:
                    raise RuntimeError(f'Bone readback mismatch: {key.name}')
                reader.verify(anchor)
            for morph in morphs:
                reader.deadline = time.monotonic() + 8
                reader.verify(anchor)
                result = scene._set_morph(morph.category, morph.name, morph.weight, reader.target.hwnd)
                completed.append(f'{morph.category}:{morph.name}')
                if abs(result['after_weight']-morph.weight) > .0051:
                    raise RuntimeError(f'Morph readback mismatch: {morph.name}')
                reader.verify(anchor)
        except Exception as exc:
            raise RuntimeError(f'Pose incomplete; completed: {completed}. Partial changes remain. Cause: {exc}') from exc
    return {'completed': completed, 'profile': compiled['profile'],
            'keyframes_registered': False, 'saved_to_disk': False,
            'verification': 'Native edit handlers and UI-rounded readback; inspect a capture for visual correctness.'}


def preview_motion(output_directory, start_frame, end_frame, step, allow_frame_evaluation, hwnd):
    if allow_frame_evaluation is not True:
        raise ValueError('Frame sampling replaces unregistered edits. Set allow_frame_evaluation=true explicitly.')
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (start_frame, end_frame, step)):
        raise ValueError('Frame bounds and step must be integers.')
    if not 0 <= start_frame <= end_frame <= 999999 or not 1 <= step <= 30:
        raise ValueError('Invalid preview frame range/step.')
    frames = list(range(start_frame, end_frame+1, step))
    if len(frames) > 180:
        raise ValueError('Preview is limited to 180 samples; narrow the range or increase step.')
    output = Path(output_directory)
    if not output.is_absolute():
        raise ValueError('Use an absolute new output directory.')
    with scene.mutation():
        reader = UIReader(hwnd)
        original = scene.context(reader)
        output.mkdir(exist_ok=False)
        expected = original
        writer = None
        thumbs = []
        completed = []
        try:
            for index, frame in enumerate(frames):
                reader.deadline = time.monotonic() + 8
                reader.verify(expected)
                scene._set_frame(frame, reader.target.hwnd)
                expected = scene.context(reader)
                time.sleep(.08)
                data = capture_png(reader.target.hwnd)
                reader.deadline = time.monotonic() + 8
                reader.verify(expected)
                image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise RuntimeError('Preview PNG decoding failed.')
                (output/f'frame-{frame:06d}.png').write_bytes(data)
                if writer is None:
                    size = (image.shape[1], image.shape[0])
                    writer = cv2.VideoWriter(str(output/'preview.avi'), cv2.VideoWriter_fourcc(*'MJPG'), 30/step, size)
                    if not writer.isOpened():
                        raise RuntimeError('MJPG video writer is unavailable.')
                if (image.shape[1], image.shape[0]) != size:
                    raise RuntimeError('MMD window resized during preview.')
                writer.write(image)
                if index % max(1, (len(frames)+11)//12) == 0:
                    thumb = cv2.resize(image, (480, round(image.shape[0]*480/image.shape[1])))
                    cv2.putText(thumb, f'frame {frame}', (12, 25), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 255, 255), 2)
                    thumbs.append(thumb)
                completed.append(frame)
            reader.verify(expected)
            scene._set_frame(int(original[0]), reader.target.hwnd)
        except Exception as exc:
            raise RuntimeError(f'Preview incomplete. Captured frames: {completed}. Files remain in {output}; frame was not blindly restored. {exc}') from exc
        finally:
            if writer is not None:
                writer.release()
        while len(thumbs) % 3:
            thumbs.append(np.zeros_like(thumbs[0]))
        sheet = np.vstack([np.hstack(thumbs[i:i+3]) for i in range(0, len(thumbs), 3)])
        ok, png = cv2.imencode('.png', sheet)
        if not ok:
            raise RuntimeError('Contact sheet encoding failed.')
        (output/'contact-sheet.png').write_bytes(png.tobytes())
        result = {'directory': str(output), 'video': str(output/'preview.avi'),
                  'contact_sheet': str(output/'contact-sheet.png'), 'frames': completed,
                  'fps': 30/step, 'restored_frame': int(original[0]),
                  'limitations': ['Sampled frame evaluation, not real-time playback or a deterministic physics bake.',
                                  'Physics-dependent hair/cloth require a separate real-time playback check.']}
        (output/'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
