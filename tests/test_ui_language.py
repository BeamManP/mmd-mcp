import unittest
from unittest.mock import patch

from mmd_mcp.ui_language import matches
from mmd_mcp.bone_selection import exposed_bone_names, find_bone
from mmd_mcp.scene_lifecycle import confirm


class LanguageTests(unittest.TestCase):
    def test_both_native_english_camera_labels_and_unknown_translation(self):
        for label in ("カメラ編", "camera", "To camera"):
            self.assertTrue(matches(label, "カメラ編"))
        for label in ("To model", "Camera", "カメラ編集", None):
            self.assertFalse(matches(label, "カメラ編"))

    def test_english_bone_range_keeps_morphs_out(self):
        items = ["All frame", "center", "blink", "All bone", "arm_L"]
        self.assertEqual(exposed_bone_names(items), {"center", "arm_L"})
        with self.assertRaises(RuntimeError):
            exposed_bone_names(items + ["全ボーンﾌﾚｰﾑ"])

    def test_display_alias_collisions_rejected(self):
        bones = [{"index": 0, "name": "左腕", "display_name": "arm_L"},
                 {"index": 1, "name": "arm_L", "display_name": "another"}]
        with self.assertRaises(ValueError):
            find_bone(bones, "arm_L", None)
        self.assertEqual(find_bone(bones, "左腕", None), 0)

    @patch("mmd_mcp.scene_lifecycle.dialogs.close")
    @patch("mmd_mcp.scene_lifecycle.dialogs.wait_dialog")
    def test_translated_title_does_not_authorize_different_message(self, wait, close):
        wait.return_value = {"title": "model delete", "controls": [
            {"class": "Static", "text": "delete some other model"}]}
        with self.assertRaises(RuntimeError):
            confirm(None, "モデル削除", "日本語の本文", english_message="delete intended model")
        close.assert_not_called()

    @patch("mmd_mcp.scene_lifecycle.dialogs.close")
    @patch("mmd_mcp.scene_lifecycle.dialogs.wait_dialog")
    def test_exact_english_confirmation(self, wait, close):
        wait.return_value = {"title": "new", "controls": [
            {"class": "Static", "text": "The existing state will be annulled.\n\nAre you OK?"}]}
        confirm(None, "新規作成", "現在の状態は破棄されます\n\nよろしいですか？",
                english_message="The existing state will be annulled.\n\nAre you OK?")
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
