import unittest
from unittest.mock import MagicMock, patch

from mmd_mcp import accessory_controls as acc


def dialog(title=acc.DELETE_TITLE, name='Explosion2_lv1.x', ok_text='OK', enabled=True):
    return {'hwnd': 77, 'title': title, 'controls': [
        {'hwnd': 1, 'id': 65535, 'class': 'Static', 'text': acc.DELETE_TEXT.format(name=name).replace('\n', '\r\n'), 'enabled': True},
        {'hwnd': 2, 'id': 1, 'class': 'Button', 'text': ok_text, 'enabled': enabled},
        {'hwnd': 3, 'id': 2, 'class': 'Button', 'text': 'キャンセル', 'enabled': True}]}


class DeleteAccessoryTests(unittest.TestCase):
    def setUp(self):
        self.items = ['Explosion2_lv1.x', 'AutoLuminous.x', 'Explosion2_lv1.x']
        self.reader = MagicMock()
        self.reader.target.hwnd = 1
        self.reader.combo.return_value = {'items': self.items, 'selected_index': 2, 'selected_name': 'Explosion2_lv1.x'}

    def run_delete(self, dialog_sequence, index=2, name='Explosion2_lv1.x', after_items=None):
        after = {'items': after_items if after_items is not None else self.items[:2], 'selected_index': 1, 'selected_name': 'AutoLuminous.x'}
        after_reader = MagicMock()
        after_reader.combo.return_value = after
        with patch.object(acc, 'UIReader', side_effect=[self.reader, after_reader]), \
             patch.object(acc.scene, 'context', return_value=('0', 0, 'camera')), \
             patch.object(acc.scene, 'available', return_value=55), \
             patch.object(acc.files, 'owned_dialogs', side_effect=dialog_sequence), \
             patch.object(acc.win32gui, 'PostMessage') as post, patch.object(acc.time, 'sleep'):
            result = acc.delete_accessory(index, name, hwnd=1)
        return result, post

    def test_selection_and_open_dialog_are_checked_before_clicking(self):
        with patch.object(acc, 'UIReader', return_value=self.reader), patch.object(acc.scene, 'context'), \
             patch.object(acc.files, 'owned_dialogs', return_value=[]), patch.object(acc.win32gui, 'PostMessage') as post:
            for index, name in ((1, 'Explosion2_lv1.x'), (2, 'AutoLuminous.x')):
                with self.assertRaisesRegex(ValueError, 'must match'):
                    acc.delete_accessory(index, name, hwnd=1)
            post.assert_not_called()
        with patch.object(acc, 'UIReader', return_value=self.reader), patch.object(acc.scene, 'context'), \
             patch.object(acc.files, 'owned_dialogs', return_value=[dialog()]), patch.object(acc.win32gui, 'PostMessage') as post:
            with self.assertRaisesRegex(ValueError, 'Close the open'):
                acc.delete_accessory(2, 'Explosion2_lv1.x', hwnd=1)
            post.assert_not_called()

    def test_exact_dialog_is_accepted_and_selector_shrinks(self):
        result, post = self.run_delete([[], [dialog()], []])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['deleted'], {'selector_index': 2, 'name': 'Explosion2_lv1.x'})
        self.assertEqual([call.args[0] for call in post.call_args_list], [55, 2])  # delete button, then OK

    def test_mismatched_dialog_is_left_open(self):
        for wrong in (dialog(title='モデル削除'), dialog(name='Other.x'), dialog(ok_text='はい'), dialog(enabled=False)):
            result, post = self.run_delete([[], [wrong], []])
            self.assertEqual(result['status'], 'dialog_requires_action')
            self.assertEqual(post.call_count, 1)  # only the delete button; OK never pressed
        result, post = self.run_delete([[], [dialog(), dialog()], []])
        self.assertEqual(result['status'], 'dialog_requires_action')

    def test_unexpected_selector_after_close_is_reported(self):
        result, _ = self.run_delete([[], [dialog()], []], after_items=self.items)
        self.assertEqual(result['status'], 'verification_failed')

    def test_dialog_that_never_closes_times_out_without_extra_clicks(self):
        calls = []
        with patch.object(acc.time, 'monotonic', side_effect=[0, 0, 0, 0, 0, 100, 100, 100, 100, 100, 100]):
            result, post = self.run_delete(lambda _t: [dialog()] if calls.append(1) or len(calls) > 1 else [])
        self.assertEqual(result['status'], 'timeout')
        self.assertEqual(post.call_count, 2)


class DeleteAccessoriesTests(unittest.TestCase):
    def setUp(self):
        self.items = ['Explosion2_lv1.x', 'AutoLuminous.x', 'Explosion2_lv1.x', 'Explosion2_lv1.x']

    def test_targets_are_validated_against_the_list_before_any_click(self):
        reader = MagicMock()
        reader.combo.return_value = {'items': self.items, 'selected_index': 0, 'selected_name': self.items[0]}
        with patch.object(acc, 'UIReader', return_value=reader), patch.object(acc.scene, 'context'), \
             patch.object(acc, 'choose') as choose, patch.object(acc.win32gui, 'PostMessage') as post:
            for targets in ([], [{'selector_index': 3, 'expected_name': 'Other.x'}],
                            [{'selector_index': 9, 'expected_name': 'Explosion2_lv1.x'}],
                            [{'selector_index': 2, 'expected_name': 'Explosion2_lv1.x'}, {'selector_index': 2, 'expected_name': 'Explosion2_lv1.x'}]):
                with self.assertRaises(ValueError):
                    acc.delete_accessories(targets, hwnd=1)
            choose.assert_not_called()
            post.assert_not_called()

    def test_deletes_highest_index_first_and_stops_on_mismatch(self):
        reader = MagicMock()
        reader.combo.return_value = {'items': self.items, 'selected_index': 0, 'selected_name': self.items[0]}
        order = []

        def delete(_reader, _before, index, name, _timeout):
            order.append(index)
            if index == 2:
                return {'status': 'dialog_requires_action', 'dialogs': []}
            return {'status': 'completed', 'deleted': {'selector_index': index, 'name': name}}

        with patch.object(acc, 'UIReader', return_value=reader), patch.object(acc.scene, 'context', return_value=('0', 0, 'camera')), \
             patch.object(acc, 'choose'), patch.object(acc, '_delete_selected', side_effect=delete):
            result = acc.delete_accessories([{'selector_index': 2, 'expected_name': 'Explosion2_lv1.x'},
                                             {'selector_index': 3, 'expected_name': 'Explosion2_lv1.x'}], hwnd=1)
        self.assertEqual(order, [3, 2])
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['deleted'], [{'selector_index': 3, 'name': 'Explosion2_lv1.x'}])
        self.assertEqual(result['failed']['selector_index'], 2)
        self.assertEqual(result['remaining_targets'], [])


if __name__ == '__main__':
    unittest.main()
