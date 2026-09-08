import unittest
from unittest.mock import MagicMock, patch

from mmd_mcp import bone_selection as selection


class SelectionTests(unittest.TestCase):
    def test_morph_names_do_not_expose_hidden_bones(self):
        names = selection.exposed_bone_names(["all", "center", "blink", "全ボーンﾌﾚｰﾑ", "arm"])
        self.assertEqual(names, {"center", "arm"})
        with self.assertRaisesRegex(RuntimeError, "unsupported"):
            selection.exposed_bone_names(["all", "center", "arm"])
    def test_duplicate_names_require_index(self):
        bones = [{"index": 0, "name": "arm"}, {"index": 1, "name": "arm"}]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            selection.find_bone(bones, "arm", None)
        self.assertEqual(selection.find_bone(bones, None, 1), 1)
        for name, index in ((None, True), (None, -1), (None, 2), ("arm", 0), (None, None)):
            with self.assertRaises(ValueError):
                selection.find_bone(bones, name, index)

    def test_missing_dll_fails_before_hook_installation(self):
        with patch.object(selection, "DLL_PATH") as path, \
             patch.object(selection, "_user32") as native:
            path.is_file.return_value = False
            with self.assertRaisesRegex(RuntimeError, "not built"):
                selection.dispatch_selection(MagicMock(), (), 0, 0, bytes(20))
            native.SetWindowsHookExW.assert_not_called()

    def test_protocol_has_native_size_and_status_offset(self):
        packed = selection.PROTOCOL.pack(1, 1, 1, 2, 3, 0, 12, 0, 1, bytes(20), 2, 1, 0)
        self.assertEqual(len(packed), 80)
        self.assertEqual(int.from_bytes(packed[68:72], "little"), 2)


if __name__ == "__main__":
    unittest.main()
