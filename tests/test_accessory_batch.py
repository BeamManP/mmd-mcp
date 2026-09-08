import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import accessory_batch as batch, file_operations as files
from mmd_mcp.bone_controls import AxisValues


def item(**kwargs):
    return batch.AccessoryItem(**kwargs)


def key(frame, **kwargs):
    return batch.AccessoryKey(frame=frame, **kwargs)


class BatchValidationTests(unittest.TestCase):
    def test_item_needs_exactly_one_target_and_unique_frames(self):
        for kwargs in ({}, {'path': 'C:/a.x', 'selector_index': 1},
                       {'selector_index': 1},
                       {'selector_index': 1, 'keys': [key(0), key(0)]}):
            with self.assertRaises(ValidationError):
                item(**kwargs)
        item(path='C:/a.x')
        item(selector_index=2, keys=[key(0, position=AxisValues(x=1.0)), key(30, opacity=0)])

    def test_key_ranges_follow_single_step_tool(self):
        for kwargs in ({'frame': -1}, {'frame': 0, 'scale': 0}, {'frame': 0, 'opacity': 1.5},
                       {'frame': 0, 'opacity': float('nan')}):
            with self.assertRaises(ValidationError):
                batch.AccessoryKey(**kwargs)
        self.assertEqual(key(0, position=AxisValues(x=1.0, z=-2.0), opacity=.5).updates(),
                         [(478, 1.0), (480, -2.0), (485, .5)])

    def test_empty_batch_and_missing_file_are_rejected_before_any_native_call(self):
        with patch.object(batch, 'UIReader') as reader:
            with self.assertRaises(ValueError):
                batch.batch_accessories([], hwnd=1)
            with self.assertRaises(ValueError):
                batch.batch_accessories([item(path='C:/missing-fixture.x')], hwnd=1)
            reader.assert_not_called()

    def test_parent_fields_are_paired_and_applied_before_numbers(self):
        for kwargs in ({'frame': 0, 'parent_bone_name': 'head'}, {'frame': 0, 'parent_model_index': 0, 'parent_bone_name': 'head'},
                       {'frame': 0, 'parent_model_index': 1}):
            with self.assertRaises(ValidationError):
                batch.AccessoryKey(**kwargs)
        reader = MagicMock()
        reader.combo.side_effect = lambda cid: {474: {'items': ['地面', 'Miku'], 'selected_index': 0},
                                                475: {'items': ['センター', '頭'], 'selected_index': 0},
                                                471: {'items': ['a.x'], 'selected_index': 0, 'selected_name': 'a.x'}}[cid]
        chosen = []
        with patch.object(batch.acc, 'choose', side_effect=lambda _r, cid, idx: chosen.append((cid, idx))), \
             patch.object(batch.scene, 'available', return_value=9), patch.object(batch, '_message', return_value=1), \
             patch.object(batch.scene, 'numbers', return_value={478: 1.0}):
            result = batch._write_key(reader, 0, key(0, parent_model_index=1, parent_bone_name='頭', position=AxisValues(x=1.0)))
        self.assertEqual(chosen, [(474, 1), (475, 1)])
        self.assertEqual(result['written_controls'], [474, 475, 478])


class BatchFlowTests(unittest.TestCase):
    def _reader(self, names):
        reader = MagicMock()
        reader.target.hwnd = 1
        reader.combo.return_value = {'items': list(names), 'selected_index': 0, 'selected_name': names[0]}
        return reader

    def test_frames_are_entered_once_in_ascending_order(self):
        reader = self._reader(['a.x', 'b.x'])
        frames = []
        selects = []

        def commit(_reader, control_id, value):
            self.assertEqual(control_id, 417)
            frames.append(value)

        def context(_reader, _mode):
            return (str(frames[-1] if frames else 0), 0, 'camera')

        with patch.object(batch, 'UIReader', return_value=reader), \
             patch.object(batch.scene, 'context', side_effect=context), \
             patch.object(batch.scene, 'commit_number', side_effect=commit), \
             patch.object(batch, '_select', side_effect=lambda _r, index: selects.append(index)), \
             patch.object(batch, '_write_key', return_value={'written_controls': [], 'values': {}}), \
             patch.object(batch, '_message') as native, \
             patch.object(batch.scene, 'available', return_value=99):
            reader.combo.side_effect = lambda _id: {'items': ['a.x', 'b.x'], 'selected_index': selects[-1] if selects else 0, 'selected_name': 'a.x'}
            result = batch.batch_accessories([
                item(selector_index=1, keys=[key(30, opacity=0), key(0, opacity=1)]),
                item(selector_index=0, keys=[key(0, opacity=1, register_key=False)]),
            ], hwnd=1)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(frames, [0, 30, 0])  # both frame-0 keys share one frame entry; origin restored last
        self.assertEqual(selects, [1, 0, 1])
        self.assertEqual(native.call_count, 2)  # register clicked only for register_key=true keys
        self.assertEqual([(k['item'], k['frame'], k['registered']) for k in result['keys_completed']],
                         [(0, 0, True), (1, 0, False), (0, 30, True)])

    def test_failure_reports_progress_and_stops(self):
        reader = self._reader(['a.x', 'b.x'])
        calls = []

        def write(_reader, index, _key):
            calls.append(index)
            if index == 1:
                raise RuntimeError('readback mismatch')
            return {'written_controls': [478], 'values': {478: 1.0}}

        with patch.object(batch, 'UIReader', return_value=reader), \
             patch.object(batch.scene, 'context', return_value=('0', 0, 'camera')), \
             patch.object(batch.scene, 'commit_number'), \
             patch.object(batch, '_select'), \
             patch.object(batch, '_write_key', side_effect=write), \
             patch.object(batch, '_message'), patch.object(batch.scene, 'available', return_value=99):
            result = batch.batch_accessories([
                item(selector_index=0, keys=[key(0, position=AxisValues(x=1.0))]),
                item(selector_index=1, keys=[key(0, position=AxisValues(x=2.0))]),
                item(selector_index=0, keys=[key(5, position=AxisValues(x=3.0))]),
            ], hwnd=1)
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('Item 1 (selector 1) at frame 0', result['error'])
        self.assertEqual(calls, [0, 1])
        self.assertEqual(len(result['keys_completed']), 1)
        self.assertFalse(result['saved_to_disk'])

    def test_load_stops_on_unknown_dialog_and_verifies_selector_growth(self):
        reader = self._reader(['a.x'])
        with patch.object(batch, 'win32gui'), patch.object(batch.files, 'run_dialog_flow',
                                                           return_value={'status': 'dialog_requires_action', 'dialogs': []}):
            result, index = batch._load(reader, MagicMock(name='x'), ['a.x'])
        self.assertIsNone(index)
        self.assertEqual(result['status'], 'dialog_requires_action')
        candidate = MagicMock()
        candidate.name = 'new.x'
        for after in (['a.x'], ['a.x', 'other.x'], ['b.x', 'new.x']):
            with patch.object(batch, 'win32gui'), patch.object(batch.files, 'run_dialog_flow', return_value={
                    'status': 'completed', 'after': {'items': after, 'selected_index': len(after) - 1}}):
                self.assertIsNone(batch._load(reader, candidate, ['a.x'])[1])
        with patch.object(batch, 'win32gui'), patch.object(batch.files, 'run_dialog_flow', return_value={
                'status': 'completed', 'after': {'items': ['a.x', 'new.x'], 'selected_index': 1}}):
            self.assertEqual(batch._load(reader, candidate, ['a.x'])[1], 1)

    def test_dialog_flow_uses_probe_instead_of_full_snapshot(self):
        target = MagicMock(hwnd=1)
        path = MagicMock()
        path.__str__.return_value = 'C:/fixture.x'
        dialog = {'hwnd': 7, 'title': 'ファイルを開く', 'controls': []}
        probe = MagicMock(return_value={'items': ['new.x'], 'selected_index': 0})
        seen = []
        with patch.object(files, 'verify_process'), \
             patch.object(files, 'owned_dialogs', side_effect=lambda _t: [dialog] if not seen.append(1) and len(seen) == 1 else []), \
             patch.object(files, 'filename_edit', return_value=9), \
             patch.object(files, 'overwrite_button', return_value=None), \
             patch.object(files, '_message', return_value=1), \
             patch.object(files, 'window_text', return_value='C:/fixture.x'), \
             patch.object(files, 'button', return_value=8), \
             patch.object(files.win32gui, 'PostMessage'), \
             patch.object(files.win32gui, 'IsWindowEnabled', return_value=True), \
             patch.object(files, 'get_ui_state') as snapshot, \
             patch.object(files.time, 'sleep'):
            result = files.run_dialog_flow(target, path, probe=probe)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['after'], {'items': ['new.x'], 'selected_index': 0})
        self.assertTrue(result['path_submitted'])
        snapshot.assert_not_called()
        self.assertGreaterEqual(probe.call_count, 1)

if __name__ == '__main__':
    unittest.main()
