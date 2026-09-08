"""表示・IK・外親 panel of the active model: visibility flags, IK on/off, outer parents, keyed per frame.

Panel controls (MMD 9.32 x64, measured 2026-09-07): 表示=439, セルフ影=440, 加算=441,
外(outer-parent dialog)=442, IK selector=443, IK ON=444, IK OFF=445, 登録=438.
Outer-parent dialog「外部親設定」: target bone=669, parent model=673, parent bone=677,
外親登録=632, フレーム登録=630; it is closed with WM_CLOSE (no OK/Cancel buttons).
"""
from .ui_language import matches

import time
from typing import Annotated

import win32con
import win32gui
from pydantic import BaseModel, Field, model_validator

from . import file_operations as files
from . import scene_controls as scene
from .bone_controls import _message
from .ui_state import UIReader

STEP_SECONDS = 30
FLAGS = {'visible': 439, 'self_shadow': 440, 'additive': 441}
IK_COMBO, IK_ON, IK_OFF, REGISTER, OUTER_BUTTON = 443, 444, 445, 438, 442
DIALOG_TITLE = '外部親設定'
DIALOG = {'target': 669, 'model': 673, 'bone': 677, 'apply': 632}


class IKSwitch(BaseModel):
    name: str
    enabled: bool


class OuterParent(BaseModel):
    """Attach `bone` to a parent from the dialog's list: 0 = なし, 1 = 地面, 2+ = a model (needs parent_bone_name)."""
    bone: str
    parent_model_index: Annotated[int, Field(strict=True, ge=0)]
    parent_bone_name: str | None = None

    @model_validator(mode='after')
    def _pair(self):
        if (self.parent_model_index <= 1) != (self.parent_bone_name is None):
            raise ValueError('parent_model_index 0 (なし) and 1 (地面) take no bone; a model parent (2+) needs an exact bone name.')
        return self


class FlagFrame(BaseModel):
    frame: Annotated[int, Field(strict=True, ge=0)]
    visible: bool | None = None
    self_shadow: bool | None = None
    additive: bool | None = None
    ik: list[IKSwitch] = Field(default_factory=list)
    outer_parents: list[OuterParent] = Field(default_factory=list)
    register_key: bool = True

    @model_validator(mode='after')
    def _content(self):
        if self.visible is None and self.self_shadow is None and self.additive is None and not self.ik and not self.outer_parents:
            raise ValueError('A frame item needs a flag, an IK switch or an outer parent.')
        if len({s.name for s in self.ik}) != len(self.ik) or len({o.bone for o in self.outer_parents}) != len(self.outer_parents):
            raise ValueError('Each IK bone / target bone may appear once per frame.')
        return self


def _checked(reader, control_id):
    return bool(_message(scene.available(reader, control_id, 'Button'), win32con.BM_GETCHECK))


def _set_check(reader, control_id, wanted):
    if _checked(reader, control_id) != wanted:
        _message(scene.available(reader, control_id, 'Button'), win32con.BM_CLICK)
        if _checked(reader, control_id) != wanted:
            raise RuntimeError(f'MMD control {control_id} did not change to {wanted}.')
        return True
    return False


def _dialog_combo(reader, dialog_hwnd, control_id):
    """Read a combo inside an owned dialog with the same bounded read messages."""
    hwnd = win32gui.GetDlgItem(dialog_hwnd, control_id)
    if not hwnd or win32gui.GetClassName(hwnd) != 'ComboBox':
        raise RuntimeError(f'Outer-parent dialog layout changed (control {control_id}).')
    count = reader.message(hwnd, win32con.CB_GETCOUNT)
    items = []
    import ctypes
    for i in range(count):
        buffer = ctypes.create_unicode_buffer(512)
        reader.message(hwnd, win32con.CB_GETLBTEXT, i, ctypes.addressof(buffer))
        items.append(buffer.value)
    selected = reader.message(hwnd, win32con.CB_GETCURSEL)
    return hwnd, items, (selected if selected >= 0 else None)


def _dialog_choose(reader, hwnd, index, dialog_hwnd, control_id):
    if _message(hwnd, win32con.CB_SETCURSEL, index) != index:
        raise RuntimeError('Outer-parent dialog rejected the selection.')
    _message(dialog_hwnd, win32con.WM_COMMAND, control_id | (win32con.CBN_SELCHANGE << 16), hwnd)
    if reader.message(hwnd, win32con.CB_GETCURSEL) != index:
        raise RuntimeError('Outer-parent dialog selection readback mismatch.')


def _open_outer_dialog(reader, timeout=5):
    if files.owned_dialogs(reader.target):
        raise ValueError('Close the open MMD dialog first.')
    win32gui.PostMessage(scene.available(reader, OUTER_BUTTON, 'Button'), win32con.BM_CLICK, 0, 0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dialogs = files.owned_dialogs(reader.target)
        if dialogs:
            if len(dialogs) != 1 or not matches(dialogs[0]['title'], DIALOG_TITLE):
                raise RuntimeError(f'Unexpected dialog instead of {DIALOG_TITLE}: {[d["title"] for d in dialogs]}. Left open.')
            return dialogs[0]['hwnd']
        time.sleep(.05)
    raise RuntimeError('The outer-parent dialog did not appear.')


def _close_dialog(reader, dialog_hwnd, timeout=5):
    win32gui.PostMessage(dialog_hwnd, win32con.WM_CLOSE, 0, 0)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not files.owned_dialogs(reader.target):
            return
        time.sleep(.05)
    raise RuntimeError('The outer-parent dialog did not close. Inspect MMD.')


def _apply_outer_parent(reader, spec):
    dialog = _open_outer_dialog(reader)
    try:
        target_hwnd, targets, _ = _dialog_combo(reader, dialog, DIALOG['target'])
        _dialog_choose(reader, target_hwnd, scene.resolve_index(targets, None, spec.bone), dialog, DIALOG['target'])
        model_hwnd, models, _ = _dialog_combo(reader, dialog, DIALOG['model'])
        if not 0 <= spec.parent_model_index < len(models):
            raise ValueError(f'parent_model_index out of range; dialog lists {models}.')
        _dialog_choose(reader, model_hwnd, spec.parent_model_index, dialog, DIALOG['model'])
        chosen_bone = None
        if spec.parent_model_index >= 2:
            bone_hwnd, bones, _ = _dialog_combo(reader, dialog, DIALOG['bone'])
            index = scene.resolve_index(bones, None, spec.parent_bone_name)
            _dialog_choose(reader, bone_hwnd, index, dialog, DIALOG['bone'])
            chosen_bone = bones[index]
        apply_hwnd = win32gui.GetDlgItem(dialog, DIALOG['apply'])
        if not apply_hwnd or not win32gui.IsWindowEnabled(apply_hwnd):
            raise RuntimeError('外親登録 button is unavailable in the dialog.')
        _message(apply_hwnd, win32con.BM_CLICK)
    finally:
        _close_dialog(reader, dialog)
    # Read back through a fresh dialog: selecting the target bone shows its current parent.
    actual = read_outer_parent(reader, spec.bone)
    if actual['parent_model_index'] != spec.parent_model_index or actual['parent_bone'] != chosen_bone:
        raise RuntimeError(f'Outer parent readback mismatch for {spec.bone!r}: {actual}')
    return {'bone': spec.bone, **actual}


def read_outer_parent(reader, bone):
    """Open the dialog, select `bone`, read its parent model/bone, close the dialog."""
    dialog = _open_outer_dialog(reader)
    try:
        target_hwnd, targets, _ = _dialog_combo(reader, dialog, DIALOG['target'])
        _dialog_choose(reader, target_hwnd, scene.resolve_index(targets, None, bone), dialog, DIALOG['target'])
        _, models, model_index = _dialog_combo(reader, dialog, DIALOG['model'])
        _, bones, bone_index = _dialog_combo(reader, dialog, DIALOG['bone'])
        parent_bone = bones[bone_index] if model_index is not None and model_index >= 2 and bone_index is not None else None
        return {'parent_model_index': model_index, 'parent_model': models[model_index] if model_index is not None else None,
                'parent_bone': parent_bone}
    finally:
        _close_dialog(reader, dialog)


def batch_model_flags(items, return_to_frame=True, hwnd=None):
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
        anchor = scene.context(reader, 'model')
        origin = int(anchor[0])
        reader.deadline = time.monotonic() + STEP_SECONDS
        ik_names = reader.combo(IK_COMBO)
        if ik_names is None:
            raise ValueError('The 表示・IK・外親 panel is not visible.')
        for item in items:
            for switch in item.ik:
                scene.resolve_index(ik_names['items'], None, switch.name)
        for frame in sorted(i.frame for i in items):
            item = next(i for i in items if i.frame == frame)
            record = {'frame': frame, 'flags': {}, 'ik': [], 'outer_parents': []}
            try:
                reader.deadline = time.monotonic() + STEP_SECONDS
                scene.commit_number(reader, 417, frame)
                if int(scene.context(reader, 'model')[0]) != frame:
                    raise RuntimeError('MMD did not display the requested frame.')
                for name, control_id in FLAGS.items():
                    wanted = getattr(item, name)
                    if wanted is not None:
                        record['flags'][name] = {'value': wanted, 'changed': _set_check(reader, control_id, wanted)}
                for switch in item.ik:
                    index = scene.resolve_index(ik_names['items'], None, switch.name)
                    scene.choose_combo(reader, IK_COMBO, index)
                    _set_check(reader, IK_ON if switch.enabled else IK_OFF, True)
                    if _checked(reader, IK_ON) != switch.enabled:
                        raise RuntimeError(f'IK state readback mismatch for {switch.name}.')
                    record['ik'].append({'name': switch.name, 'enabled': switch.enabled})
                for spec in item.outer_parents:
                    record['outer_parents'].append(_apply_outer_parent(reader, spec))
                if item.register_key:
                    scene.click_button(reader, REGISTER)
                    record['registered'] = True
                reader.verify(scene.context(reader, 'model'))
            except (ValueError, RuntimeError) as exc:
                progress['frames_completed'].append({**record, 'incomplete': True})
                return stop('incomplete', f'Frame {frame}: {exc}')
            progress['frames_completed'].append(record)
        try:
            reader.deadline = time.monotonic() + STEP_SECONDS
            if return_to_frame and int(scene.context(reader, 'model')[0]) != origin:
                scene.commit_number(reader, 417, origin)
            final = scene.context(reader, 'model')
        except (ValueError, RuntimeError) as exc:
            return stop('completed_unverified', f'Final check failed: {exc}')
    progress['timing']['total_seconds'] = round(time.monotonic() - start, 3)
    return {'status': 'completed', **progress, 'displayed_frame': int(final[0]), 'model_name': final[2],
            'saved_to_disk': False,
            'note': 'Registered through the 表示・IK・外親 登録 button per frame when register_key=true. '
                    'Outer parents were applied with the dialog\'s 外親登録 button before registering.'}
