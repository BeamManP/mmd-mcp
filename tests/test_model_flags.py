import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from mmd_mcp import model_flags as mf


class ModelFlagsValidationTests(unittest.TestCase):
    def test_frame_needs_content_and_unique_names(self):
        with self.assertRaises(ValidationError):
            mf.FlagFrame(frame=0)
        with self.assertRaises(ValidationError):
            mf.FlagFrame(frame=0, ik=[{'name': 'a', 'enabled': True}, {'name': 'a', 'enabled': False}])
        mf.FlagFrame(frame=0, visible=False)

    def test_outer_parent_index_semantics(self):
        for kwargs in ({'parent_model_index': 0, 'parent_bone_name': '頭'}, {'parent_model_index': 1, 'parent_bone_name': '頭'},
                       {'parent_model_index': 2}):
            with self.assertRaises(ValidationError):
                mf.OuterParent(bone='右ダミー', **kwargs)
        mf.OuterParent(bone='右ダミー', parent_model_index=1)
        mf.OuterParent(bone='右ダミー', parent_model_index=2, parent_bone_name='頭')


class ModelFlagsFlowTests(unittest.TestCase):
    def test_flags_ik_and_register_per_frame_and_stop_on_failure(self):
        reader = MagicMock()
        reader.combo.return_value = {'items': ['右足ＩＫ', '左足ＩＫ'], 'selected_index': 0}
        frames, checks, clicks = [], [], []
        state = {439: True, 440: True, 441: False, 444: True, 445: False}

        def set_check(_r, cid, wanted):
            checks.append((cid, wanted))
            if cid in (444, 445):
                state[444], state[445] = (wanted, not wanted) if cid == 444 else (not wanted, wanted)
            else:
                state[cid] = wanted
            return True

        with patch.object(mf, 'UIReader', return_value=reader), \
             patch.object(mf.scene, 'context', side_effect=lambda _r, _m: (str(frames[-1] if frames else 0), 1, 'Miku')), \
             patch.object(mf.scene, 'commit_number', side_effect=lambda _r, _c, v: frames.append(v)), \
             patch.object(mf.scene, 'choose_combo'), patch.object(mf, '_set_check', side_effect=set_check), \
             patch.object(mf, '_checked', side_effect=lambda _r, cid: state[cid]), \
             patch.object(mf.scene, 'click_button', side_effect=lambda _r, cid: clicks.append(cid)), \
             patch.object(mf, '_apply_outer_parent', side_effect=RuntimeError('dialog missing')):
            result = mf.batch_model_flags([
                mf.FlagFrame(frame=10, ik=[{'name': '右足ＩＫ', 'enabled': False}], visible=False),
                mf.FlagFrame(frame=0, self_shadow=False, register_key=False),
                mf.FlagFrame(frame=20, outer_parents=[{'bone': '右ダミー', 'parent_model_index': 1}]),
            ], hwnd=1)
        self.assertEqual(frames, [0, 10, 20])
        self.assertEqual(checks, [(440, False), (439, False), (445, True)])
        self.assertEqual(clicks, [438])  # registered only for frame 10 before the failure at 20
        self.assertEqual(result['status'], 'incomplete')
        self.assertIn('Frame 20', result['error'])
        self.assertTrue(result['frames_completed'][2]['incomplete'])

    def test_unknown_ik_name_is_refused_before_any_frame_change(self):
        reader = MagicMock()
        reader.combo.return_value = {'items': ['右足ＩＫ'], 'selected_index': 0}
        with patch.object(mf, 'UIReader', return_value=reader), patch.object(mf.scene, 'context', return_value=('0', 1, 'Miku')), \
             patch.object(mf.scene, 'commit_number') as commit:
            with self.assertRaises(ValueError):
                mf.batch_model_flags([mf.FlagFrame(frame=0, ik=[{'name': '無いIK', 'enabled': True}])], hwnd=1)
            commit.assert_not_called()

    def test_unexpected_dialog_is_left_open_and_reported(self):
        reader = MagicMock()
        with patch.object(mf.files, 'owned_dialogs', side_effect=[[], [{'title': 'モデル削除', 'hwnd': 5}]]), \
             patch.object(mf.scene, 'available', return_value=7), patch.object(mf.win32gui, 'PostMessage') as post:
            with self.assertRaisesRegex(RuntimeError, 'Unexpected dialog'):
                mf._open_outer_dialog(reader)
            self.assertEqual(post.call_count, 1)  # only the 外 button; nothing sent to the dialog


if __name__ == '__main__':
    unittest.main()
