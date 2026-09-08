import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import bone_batch as bb
from mmd_mcp.bone_controls import AxisValues


def item(frame, **kwargs):
    return bb.FrameItem(frame=frame, **kwargs)


class BoneBatchValidationTests(unittest.TestCase):
    def test_frame_item_needs_content_and_unique_names(self):
        with self.assertRaises(ValidationError):
            item(0)
        with self.assertRaises(ValidationError):
            item(0, bones=[{'name': '頭'}, {'name': '頭'}])
        item(0, bones=[{'name': '頭', 'rotation_degrees': AxisValues(x=5.0)}])

    def test_explicit_axes_override_compiled_pose(self):
        compiled = {'bones': [{'name': '頭', 'position': {'x': 0., 'y': 0., 'z': 0.},
                               'rotation_degrees': {'x': 1., 'y': 2., 'z': 3.}}]}
        with patch.object(bb, 'compile_with_profile', return_value=compiled), patch.object(bb, 'fk_summary', return_value={}):
            merged, _ = bb.resolve_frame(item(0, pose=bb.SemanticPose(), bones=[
                {'name': '頭', 'rotation_degrees': AxisValues(z=9.0)}, {'name': '首', 'position': AxisValues(y=1.0)}]), 'C:/m.pmx', profile={'bones': []})
        self.assertEqual(merged['頭'][('rotation_degrees', 'z')], 9.0)
        self.assertEqual(merged['頭'][('rotation_degrees', 'x')], 1.0)
        self.assertEqual(merged['首'], {('position', 'y'): 1.0})
        with self.assertRaisesRegex(ValueError, 'model_path'):
            bb.resolve_frame(item(0, pose=bb.SemanticPose()), None)

    def test_duplicate_frames_and_empty_batch_are_rejected(self):
        with self.assertRaises(ValueError):
            bb.batch_bone_keys([], hwnd=1)
        with self.assertRaises(ValueError):
            bb.batch_bone_keys([item(0, bones=[{'name': '頭'}]), item(0, bones=[{'name': '首'}])], hwnd=1)


class BoneBatchFlowTests(unittest.TestCase):
    def _env(self, bones=('センター', '頭', '頭')):
        reader = MagicMock()
        reader.target.hwnd = 1
        reader.text.return_value = 'カメラ編'
        reader.combo.return_value = {'items': ['x', 'センター', '全ボーンﾌﾚｰﾑ', '頭', '首'], 'selected_index': 0}
        memory = MagicMock()
        snapshot = {'bones': [{'index': i, 'name': n} for i, n in enumerate(bones)]}
        return reader, memory, snapshot

    def test_ambiguous_or_unexposed_bones_are_refused_before_any_frame_change(self):
        reader, memory, snapshot = self._env()
        with patch.object(bb, 'UIReader', return_value=reader), patch.object(bb.scene, 'context', return_value=('0', 1, 'Miku')), \
             patch.object(bb, 'BoneMemory', return_value=memory), patch.object(bb, 'inspect_bones', return_value=snapshot), \
             patch.object(bb.scene, 'commit_number') as commit:
            for name in ('頭', '首', '足首'):  # duplicated, not in table, not exposed
                with self.assertRaises(ValueError):
                    bb.batch_bone_keys([item(0, bones=[{'name': name, 'position': AxisValues(x=1.0)}])], hwnd=1)
            commit.assert_not_called()
            memory.close.assert_called()

    def test_frames_ascend_and_stop_on_failure_with_progress(self):
        reader, memory, snapshot = self._env(('センター', '首'))
        frames, keyed = [], []

        def key_bone(_r, _m, frame, name, index, axes, register):
            keyed.append((frame, name, register))
            if frame == 10:
                raise RuntimeError('readback mismatch')
            return {'bone': name, 'index': index, 'written': len(axes), 'registered': register}

        with patch.object(bb, 'UIReader', return_value=reader), \
             patch.object(bb.scene, 'context', side_effect=lambda _r, _m: (str(frames[-1] if frames else 0), 1, 'Miku')), \
             patch.object(bb, 'BoneMemory', return_value=memory), patch.object(bb, 'inspect_bones', return_value=snapshot), \
             patch.object(bb.scene, 'commit_number', side_effect=lambda _r, _c, v: frames.append(v)), \
             patch.object(bb, '_key_bone', side_effect=key_bone):
            result = bb.batch_bone_keys([
                item(10, bones=[{'name': '首', 'rotation_degrees': AxisValues(x=1.0)}]),
                item(0, bones=[{'name': 'センター', 'position': AxisValues(y=1.0)}], register_key=False),
                item(20, bones=[{'name': '首', 'rotation_degrees': AxisValues(x=0.0)}]),
            ], hwnd=1)
        self.assertEqual(frames, [0, 10])
        self.assertEqual(keyed, [(0, 'センター', False), (10, '首', True)])
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('Frame 10', result['error'])
        self.assertEqual([f['frame'] for f in result['frames_completed']], [0, 10])
        self.assertTrue(result['frames_completed'][1]['incomplete'])
        memory.close.assert_called()

    def test_key_bone_checks_native_landing_and_readback(self):
        reader = MagicMock()
        memory = MagicMock()
        memory.anchor.return_value = (1, 0, 2, 3, 7, 1000)
        memory.read.return_value = '頭'.encode('cp932').ljust(20, b'\0')
        writes = []
        with patch.object(bb, 'dispatch_selection') as dispatch, \
             patch.object(bb, '_commit_edit', side_effect=lambda _r, cid, v: writes.append((cid, v))), \
             patch.object(bb, '_read_fields', return_value={k: (5.0 if k == ('rotation_degrees', 'x') else 0.0) for k in bb.FIELD_IDS}), \
             patch.object(bb.scene, 'click_button') as click:
            result = bb._key_bone(reader, memory, 3, '頭', 7, {('rotation_degrees', 'x'): 5.0}, True)
            dispatch.assert_called_once()
            self.assertEqual(writes, [(547, 5.0)])
            click.assert_called_once_with(reader, 500)
            self.assertEqual(result['written'], 1)
            with self.assertRaisesRegex(RuntimeError, 'Readback mismatch'):
                bb._key_bone(reader, memory, 3, '頭', 7, {('rotation_degrees', 'x'): 6.0}, True)
            memory.anchor.return_value = (1, 0, 2, 3, 8, 1000)
            with self.assertRaisesRegex(RuntimeError, 'did not land'):
                bb._key_bone(reader, memory, 3, '頭', 7, {('rotation_degrees', 'x'): 5.0}, True)


class OperationModeTests(unittest.TestCase):
    def test_gizmo_mode_is_switched_back_to_select_and_verified(self):
        from mmd_mcp import bone_state as bs
        memory = MagicMock(spec=bs.BoneMemory)
        memory.operation_mode.side_effect = [2, 0]
        with patch.object(bs, 'BoneMemory') as _:
            pass
        with patch('mmd_mcp.scene_controls.click_button') as click:
            self.assertEqual(bs.BoneMemory.ensure_selectable_mode(memory, 'reader'), 2)
            click.assert_called_once_with('reader', 490)
        memory.operation_mode.side_effect = [0]
        with patch('mmd_mcp.scene_controls.click_button') as click:
            self.assertIsNone(bs.BoneMemory.ensure_selectable_mode(memory, 'reader'))
            click.assert_not_called()
        memory.operation_mode.side_effect = [1, 1]
        with patch('mmd_mcp.scene_controls.click_button'):
            with self.assertRaisesRegex(RuntimeError, 'stayed in operation mode'):
                bs.BoneMemory.ensure_selectable_mode(memory, 'reader')


if __name__ == '__main__':
    unittest.main()
