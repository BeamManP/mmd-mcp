"""Explicit accessory panel operations for the verified MMD 9.32 UI."""
from .ui_language import matches

import ctypes
import math
import time

import win32gui

from .bone_controls import _message
from . import file_operations as files
from . import scene_controls as scene
from .ui_state import UIReader

DELETE_TITLE = 'アクセサリ削除'
DELETE_TEXT = ('アクセサリ：{name}を削除します' + chr(10) + 'アクセサリのフレームデータも全て削除されます' + chr(10)
               + '(この操作は元に戻す事はできません)' + chr(10) + chr(10) + '削除してもよろしいですか？')

FIELDS = {'position': {'x': 478, 'y': 479, 'z': 480},
          'rotation_degrees': {'x': 481, 'y': 482, 'z': 483}, 'scale': 484, 'opacity': 485}


def selector(reader, required=True):
    scene.context(reader, 'camera')
    return _selector(reader, required)


def _selector(reader, required=True):
    """Read the whole selector after the caller checked camera context."""
    value = reader.combo(471)
    if value is None or required and value['selected_index'] is None:
        raise ValueError('Select a loaded accessory in the expanded accessory panel first.')
    return value


def verify(reader, anchor, before):
    # context() already validates process, playback, mode and a stable anchor.
    # Compare it to the operation anchor instead of redoing the same checks.
    if scene.context(reader, 'camera') != anchor:
        raise RuntimeError('Frame or model selection changed; inspect MMD before retrying.')
    if _selector(reader) != before:
        raise RuntimeError('Accessory selection changed; inspect MMD before retrying.')


def choose(reader, control_id, index):
    reader.deadline = time.monotonic() + 30
    if control_id not in {471, 474, 475}:
        raise ValueError('Unsupported accessory selector.')
    before = reader.combo(control_id)
    if before is None or isinstance(index, bool) or not 0 <= index < len(before['items']):
        raise ValueError('Accessory selector index out of range.')
    control = scene.available(reader, control_id, 'ComboBox')
    if _message(control, 0x14E, index) != index:
        raise RuntimeError('MMD rejected accessory selection.')
    _message(reader.target.hwnd, 0x111, control_id | (1 << 16), control)
    reader.deadline = time.monotonic() + 30
    after = reader.combo(control_id)
    if after['items'] != before['items'] or after['selected_index'] != index:
        raise RuntimeError('Accessory selector readback mismatch; selection may have changed.')


def list_accessories(hwnd=None):
    reader = UIReader(hwnd)
    anchor = scene.context(reader, 'camera')
    result = _selector(reader, False)
    reader.verify(anchor)
    return {'window': reader.target.public_info(), 'selector': result,
            'index_scope': 'Transient UI selector index; duplicate filenames require explicit indices.'}


def select_accessory(selector_index=None, name=None, hwnd=None):
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        before = _selector(reader, False)
        index = scene.resolve_index(before['items'], selector_index, name)
        choose(reader, 471, index)
        reader.verify(anchor)
        return {'before': before, 'after': _selector(reader), 'keyframes_registered': False}


def state(reader):
    reader.deadline = time.monotonic() + 30
    anchor = scene.context(reader, 'camera')
    selected = _selector(reader)
    result = {'selector': selected, **scene.numbers(reader, FIELDS),
              'visible': bool(_message(scene.available(reader, 476, 'Button'), 0xF0)),
              'shadow': bool(_message(scene.available(reader, 486, 'Button'), 0xF0)),
              'additive': bool(_message(scene.available(reader, 477, 'Button'), 0xF0)),
              'parent_model': reader.combo(474), 'parent_bone': reader.combo(475),
              'displayed_frame': int(anchor[0])}
    verify(reader, anchor, selected)
    return result


def get_accessory(hwnd=None):
    return state(UIReader(hwnd))


def set_accessory(position=None, rotation_degrees=None, scale=None, opacity=None,
                  visible=None, shadow=None, expected_index=None, hwnd=None):
    updates = [(FIELDS[kind][axis], value) for kind, patch in
               [('position', position), ('rotation_degrees', rotation_degrees)] if patch is not None
               for axis, value in patch.model_dump(exclude_none=True).items()]
    for kind, value in [('scale', scale), ('opacity', opacity)]:
        if value is not None:
            if isinstance(value, bool) or not math.isfinite(value) or not (0 < value <= 100000 if kind == 'scale' else 0 <= value <= 1):
                raise ValueError(f'Invalid accessory {kind}.')
            updates.append((FIELDS[kind], value))
    if not updates and visible is None and shadow is None:
        raise ValueError('Specify an accessory value.')
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        before = state(reader)
        selected = before['selector']
        if expected_index is None or isinstance(expected_index, bool) or selected['selected_index'] != expected_index:
            raise ValueError('Expected accessory index is required and must match the current selection.')
        completed = []
        try:
            for control_id, value in updates:
                reader.deadline = time.monotonic() + 30
                verify(reader, anchor, selected)
                edit = scene.available(reader, control_id, 'Edit')
                buffer = ctypes.create_unicode_buffer(format(value, '.9g'))
                if not _message(edit, 0xC, 0, ctypes.addressof(buffer)):
                    raise RuntimeError('Accessory numeric text was rejected.')
                _message(edit, 0x100, 13, 1)
                completed.append(control_id)
                verify(reader, anchor, selected)
                actual = scene.numbers(reader, {'value': control_id})['value']
                if abs(actual-value) > (.0051 if control_id == 485 else .000051):
                    raise RuntimeError(f'Accessory value readback mismatch on {control_id}.')
            for name, wanted, control_id in [('visible', visible, 476), ('shadow', shadow, 486)]:
                if wanted is not None and before[name] != wanted:
                    verify(reader, anchor, selected)
                    _message(scene.available(reader, control_id, 'Button'), 0xF5)
                    completed.append(control_id)
            after = state(reader)
            for name, wanted in [('visible', visible), ('shadow', shadow)]:
                if wanted is not None and after[name] != wanted:
                    raise RuntimeError(f'Accessory {name} readback mismatch.')
        except Exception as exc:
            raise RuntimeError(f'Accessory edit incomplete; completed controls: {completed}. Partial changes remain. {exc}') from exc
        return {'before': before, 'after': after, 'completed_controls': completed,
                'keyframes_registered': False, 'saved_to_disk': False}


def set_parent(parent_model_index, parent_bone_name, expected_index, hwnd=None):
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        before = state(reader)
        selected = before['selector']
        if selected['selected_index'] != expected_index:
            raise ValueError('Expected accessory does not match the current selection.')
        models = reader.combo(474)
        scene.resolve_index(models['items'], parent_model_index, None)
        if (parent_model_index == 0) != (parent_bone_name is None):
            raise ValueError('Ground (index 0) requires no bone; model parents require an exact bone name.')
        try:
            choose(reader, 474, parent_model_index)
            verify(reader, anchor, selected)
            if parent_model_index:
                reader.deadline = time.monotonic() + 30
                bones = reader.combo(475)
                index = scene.resolve_index(bones['items'], None, parent_bone_name)
                choose(reader, 475, index)
                verify(reader, anchor, selected)
            after = state(reader)
        except Exception as exc:
            raise RuntimeError(f'Accessory parent operation incomplete; parent may have changed. Inspect before retrying. {exc}') from exc
        return {'before': before, 'after': after, 'keyframes_registered': False,
                'note': 'Transforms are relative to the new parent; world position is not preserved automatically.'}


def register_accessory(expected_index, hwnd=None):
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        selected = _selector(reader)
        if selected['selected_index'] != expected_index:
            raise ValueError('Expected accessory does not match the current selection.')
        _message(scene.available(reader, 487, 'Button'), 0xF5)
        verify(reader, anchor, selected)
        return {'accessory': selected, 'frame': int(anchor[0]), 'registration_handler_completed': True,
                'saved_to_disk': False, 'note': 'Registers the selected accessory; an existing key at this frame can be replaced.'}


def _wait_dialogs(target, condition, timeout):
    deadline = time.monotonic() + timeout
    while True:
        dialogs = files.owned_dialogs(target)
        if condition(dialogs):
            return dialogs
        if time.monotonic() >= deadline:
            return None
        time.sleep(.05)


def _delete_selected(reader, before, expected_index, expected_name, timeout):
    """Delete the accessory that `before` shows selected; returns a status dict."""
    if before['selected_index'] != expected_index or before['selected_name'] != expected_name:
        raise ValueError('Select the accessory first; expected_index and expected_name must match the current selection.')
    if files.owned_dialogs(reader.target):
        raise ValueError('Close the open MMD dialog before deleting an accessory.')
    remaining = before['items'][:expected_index] + before['items'][expected_index+1:]
    win32gui.PostMessage(scene.available(reader, 473, 'Button'), 0xF5, 0, 0)
    dialogs = _wait_dialogs(reader.target, bool, timeout)
    if not dialogs:
        after = UIReader(reader.target.hwnd).combo(471)
        status = 'completed' if after is not None and after['items'] == remaining else 'verification_failed'
        return {'status': status, 'confirmation': 'none appeared', 'before': before, 'after': after,
                'note': 'No confirmation dialog appeared; the selector was compared instead.'}
    dialog = dialogs[0]
    texts = [c['text'].replace(chr(13) + chr(10), chr(10)) for c in dialog['controls'] if c['class'] == 'Static' and c['text']]
    ok = [c for c in dialog['controls'] if c['class'] == 'Button' and c['id'] == 1 and c['text'] == 'OK' and c['enabled']]
    expected_text = DELETE_TEXT.format(name=expected_name)
    if dialog["title"] != DELETE_TITLE:
        expected_text = (f'Trying to delete Accessory({expected_name}).\n'
                         'All flame data about this accessory will be deleted too.\n'
                         '(This operation cannot undo!!)\n\nAre you OK?')
    if len(dialogs) != 1 or not matches(dialog['title'], DELETE_TITLE) or texts != [expected_text] or len(ok) != 1:
        return {'status': 'dialog_requires_action', 'dialogs': dialogs, 'before': before,
                'note': 'The confirmation did not match the expected accessory deletion dialog. Nothing was accepted; inspect MMD.'}
    win32gui.PostMessage(ok[0]['hwnd'], 0xF5, 0, 0)
    if _wait_dialogs(reader.target, lambda d: not d, timeout) is None:
        return {'status': 'timeout', 'before': before,
                'note': 'The confirmation dialog did not close. Inspect MMD before retrying.'}
    reader.deadline = time.monotonic() + 30
    after = _selector(UIReader(reader.target.hwnd), False)
    if after is None or after['items'] != remaining:
        return {'status': 'verification_failed', 'before': before, 'after': after,
                'note': 'Accessory list after deletion differs from the expectation. Inspect MMD.'}
    return {'status': 'completed', 'deleted': {'selector_index': expected_index, 'name': expected_name},
            'before': before, 'after': after}


def delete_accessory(expected_index, expected_name, hwnd=None, timeout=10):
    """Delete the selected accessory after matching MMD's own confirmation dialog exactly.

    The dialog title, its full message for this accessory name and an enabled OK button must
    all match; anything else is reported and left open. Not undoable in MMD.
    """
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        result = _delete_selected(reader, _selector(reader), expected_index, expected_name, timeout)
        result.setdefault('note', 'Indices after the deleted accessory shift down by one. Its keys are gone; MMD cannot undo this.')
        return {**result, 'displayed_frame': int(anchor[0]), 'saved_to_disk': False}


def delete_accessories(targets, hwnd=None, timeout=10):
    """Delete several accessories in one call, highest index first so indices stay valid.

    `targets` is a list of {selector_index, expected_name}. Every entry is checked against
    the current list before anything is clicked; each deletion still matches MMD's own
    confirmation dialog exactly. Stops at the first failure and reports what was deleted.
    """
    if not targets:
        raise ValueError('Provide at least one accessory to delete.')
    ordered = sorted(((int(t['selector_index']), t['expected_name']) for t in targets), reverse=True)
    if len({index for index, _ in ordered}) != len(ordered):
        raise ValueError('Each selector_index may appear only once.')
    with scene.mutation():
        reader = UIReader(hwnd)
        anchor = scene.context(reader, 'camera')
        current = _selector(reader, False)
        if current is None:
            raise ValueError('Expand the accessory panel before deleting accessories.')
        items = current['items']
        for index, name in ordered:
            if not 0 <= index < len(items) or items[index] != name:
                raise ValueError(f'Accessory {index} is not named {name!r} in the current list; nothing was deleted.')
        deleted = []
        start = time.monotonic()
        for index, name in ordered:
            reader.deadline = time.monotonic() + 30
            try:
                choose(reader, 471, index)
                result = _delete_selected(reader, _selector(reader), index, name, timeout)
            except (ValueError, RuntimeError) as exc:
                result = {'status': 'error', 'error': str(exc)}
            if result['status'] != 'completed':
                return {'status': 'incomplete', 'deleted': deleted, 'failed': {'selector_index': index, 'name': name, **result},
                        'remaining_targets': [{'selector_index': i, 'expected_name': n} for i, n in ordered if i < index],
                        'elapsed_seconds': round(time.monotonic() - start, 3), 'saved_to_disk': False,
                        'note': 'Deletions listed above are done and cannot be undone. Lower indices were not touched.'}
            deleted.append({'selector_index': index, 'name': name})
        after = _selector(UIReader(reader.target.hwnd), False)
        return {'status': 'completed', 'deleted': deleted, 'accessory_selector': after,
                'elapsed_seconds': round(time.monotonic() - start, 3), 'displayed_frame': int(anchor[0]),
                'saved_to_disk': False, 'note': 'Deleted highest index first. Remaining indices are compacted; MMD cannot undo this.'}
