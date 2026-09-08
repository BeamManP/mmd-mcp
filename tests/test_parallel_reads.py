import ctypes
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from mmd_mcp import ui_state as ui, scene_controls as scene, accessory_controls as accessory


class ParallelReadTests(unittest.TestCase):
    def test_result_order_and_no_return_before_failed_group_drains(self):
        started = threading.Event()
        finished = threading.Event()
        def slow():
            started.set()
            time.sleep(.03)
            finished.set()
            return 2
        def fail():
            self.assertTrue(started.wait(1))
            raise RuntimeError('read failed')
        with self.assertRaisesRegex(RuntimeError, 'read failed'):
            ui._read_group([fail, slow])
        self.assertTrue(finished.is_set())
        self.assertEqual(ui._read_group([lambda: 3, lambda: 1]), [3, 1])

    def test_parallel_texts_keep_native_write_messages_rejected(self):
        reader = object.__new__(ui.UIReader)
        reader.deadline = time.monotonic() + 5
        with patch.object(ui, '_send') as native:
            with self.assertRaisesRegex(ValueError, 'read messages'):
                ui._read_group([lambda: reader.message(1, 0xC)])
            native.assert_not_called()

    def combo(self, changed=False, oversized=False):
        reader = object.__new__(ui.UIReader)
        reader.target = MagicMock()
        count_reads = 0
        def message(hwnd, msg, wparam=0, lparam=0):
            nonlocal count_reads
            if msg == ui.CB_GETCOUNT:
                count_reads += 1
                return 1 if changed and count_reads > 1 else 2
            if msg == ui.CB_GETCURSEL: return 1
            if msg == ui.CB_GETLBTEXTLEN: return ui.MAX_TEXT if oversized else 4
            if msg == ui.CB_GETLBTEXT:
                value = ['same', 'same'][wparam]
                buffer = ctypes.create_unicode_buffer(value)
                ctypes.memmove(lparam, buffer, ctypes.sizeof(buffer))
                return len(value)
            raise AssertionError(msg)
        with (patch.object(reader, 'control', return_value=1),
              patch.object(reader, 'message', side_effect=message),
              patch.object(ui.win32gui, 'IsWindowVisible', return_value=True),
              patch.object(ui.win32gui, 'GetWindowLong', return_value=0)):
            return reader.combo(471)

    def test_combo_preserves_duplicate_index_identity(self):
        self.assertEqual(self.combo(), {'items': ['same', 'same'],
                                       'selected_index': 1, 'selected_name': 'same'})

    def test_combo_rejects_count_drift_and_oversized_text(self):
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.combo(changed=True)
        with self.assertRaisesRegex(RuntimeError, 'too long'):
            self.combo(oversized=True)

    def test_numbers_reconstruct_nested_values_and_reject_invalid_text(self):
        reader = MagicMock()
        fields = {'position': {'x': 478, 'y': 479}, 'opacity': 485}
        with patch.object(scene, 'available', side_effect=lambda r, c, _: c):
            reader.texts.return_value = ['1.2', '-3', '.33']
            self.assertEqual(scene.numbers(reader, fields),
                             {'position': {'x': 1.2, 'y': -3.}, 'opacity': .33})
            reader.texts.assert_called_once_with([478, 479, 485])
            reader.texts.return_value = ['1', 'nan', '.33']
            with self.assertRaisesRegex(ValueError, '479'):
                scene.numbers(reader, fields)

    def test_accessory_guard_keeps_frame_and_full_selector_drift_checks(self):
        anchor = ('0', 0, 'camera')
        before = {'items': ['Explosion.x', 'AutoLuminous.x'], 'selected_index': 0,
                  'selected_name': 'Explosion.x'}
        reader = MagicMock()
        reader.combo.return_value = before
        with patch.object(scene, 'context', return_value=('5', 0, 'camera')):
            with self.assertRaisesRegex(RuntimeError, 'Frame or model'):
                accessory.verify(reader, anchor, before)
        reader.combo.assert_not_called()
        with patch.object(scene, 'context', return_value=anchor):
            accessory.verify(reader, anchor, before)
            for changed in [dict(before, selected_index=1),
                            dict(before, items=['Explosion.x', 'other.x']),
                            dict(before, items=['Explosion.x'])]:
                reader.combo.return_value = changed
                with self.assertRaisesRegex(RuntimeError, 'Accessory selection'):
                    accessory.verify(reader, anchor, before)

    def test_accessory_guard_still_rejects_playback_or_modal_context_error(self):
        with patch.object(scene, 'context', side_effect=ValueError('Stop MMD playback')):
            with self.assertRaisesRegex(ValueError, 'playback'):
                accessory.verify(MagicMock(), ('0', 0, 'camera'), {})


if __name__ == '__main__':
    unittest.main()
