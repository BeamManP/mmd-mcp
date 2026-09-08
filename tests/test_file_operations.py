import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mmd_mcp import file_operations as files


class FileTests(unittest.TestCase):
    def test_existing_output_needs_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.pmm"
            path.write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "already exists"):
                files.file_path(str(path), {".pmm"}, write=True)
            self.assertEqual(files.file_path(str(path), {".pmm"}, write=True, overwrite=True), path.resolve())
            self.assertEqual(path.read_bytes(), b"existing")

    def test_relative_and_wrong_extension_are_rejected(self):
        for path in ("relative.pmm", "C:/scene.exe"):
            with self.assertRaises(ValueError):
                files.file_path(path, {".pmm"})

    def test_unknown_dialog_is_not_accepted(self):
        dialog = {"hwnd": 42, "title": "Unknown confirmation", "controls": []}
        with patch.object(files, "verify_process"), \
             patch.object(files, "owned_dialogs", return_value=[dialog]), \
             patch.object(files.win32gui, "PostMessage") as post:
            result = files.run_dialog_flow(MagicMock(), Path("C:/scene.pmm"))
            self.assertEqual(result["status"], "dialog_requires_action")
            post.assert_not_called()

    def test_address_bar_is_not_treated_as_filename(self):
        dialog = {"title": "ファイルを保存する", "controls": [
            {"hwnd": 1, "class": "Edit", "id": 41477}]}
        with patch.object(files.win32gui, "GetParent", return_value=2):
            self.assertIsNone(files.filename_edit(dialog))

    def test_overwrite_requires_opt_in_and_exact_parent_filename(self):
        confirm = {"hwnd": 10, "title": "名前を付けて保存の確認", "controls": [
            {"hwnd": 11, "class": "Button", "text": "はい(&Y)", "enabled": True}]}
        parent = {"hwnd": 20, "title": "ファイルを保存する", "controls": []}
        with tempfile.TemporaryDirectory() as directory:
            output = (Path(directory) / "scene.pmm").resolve()
            output.write_bytes(b"existing")
            with patch.object(files.win32gui, "GetWindow", return_value=20), \
                 patch.object(files, "filename_edit", return_value=30), \
                 patch.object(files, "window_text", return_value=str(output)) as text:
                self.assertIsNone(files.overwrite_button(confirm, [parent], output, authorized=False, submitted=True))
                self.assertIsNone(files.overwrite_button(confirm, [parent], output, authorized=True, submitted=False))
                self.assertEqual(files.overwrite_button(confirm, [parent], output, authorized=True, submitted=True), 11)
                text.return_value = str(output.with_name("different.pmm"))
                self.assertIsNone(files.overwrite_button(confirm, [parent], output, authorized=True, submitted=True))


if __name__ == "__main__":
    unittest.main()
