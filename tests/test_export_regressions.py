import itertools
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mmd_mcp import file_operations as files, video_export
from mmd_mcp.ui_state import NativeMessageError


class ExportRegressions(unittest.TestCase):
    def test_shader_timeout_retries_observation_not_file_submission(self):
        target = MagicMock(hwnd=1)
        file_dialog = {"hwnd": 3, "title": "開く", "controls": [
            {"hwnd": 4, "class": "Button", "id": 1, "enabled": True, "text": "開く(&O)"}]}
        observations = [file_dialog], NativeMessageError("busy", 1460)
        calls = iter(observations)
        def observe(_):
            result = next(calls, [])
            if isinstance(result, Exception):
                raise result
            return result
        path = Path("C:/fixture.emm")
        with patch.object(files, "verify_process"), patch.object(files, "owned_dialogs", side_effect=observe), \
             patch.object(files, "filename_edit", return_value=5), \
             patch.object(files, "window_text", return_value=str(path)), patch.object(files, "_message", return_value=1), \
             patch.object(files.win32gui, "PostMessage") as post, patch.object(files.win32gui, "IsWindowEnabled", return_value=True), \
             patch.object(files.time, "monotonic", side_effect=itertools.count(0, .1)), patch.object(files.time, "sleep"), \
             patch.object(files, "get_ui_state", return_value={}):
            result = files.run_dialog_flow(target, path)
        self.assertEqual(result["status"], "completed")
        post.assert_called_once_with(4, 0xF5, 0, 0)

    def test_timeout_before_submission_is_not_masked(self):
        with patch.object(files, "verify_process"), \
             patch.object(files, "owned_dialogs", side_effect=NativeMessageError("busy", 1460)), \
             patch.object(files.win32gui, "PostMessage") as post:
            with self.assertRaises(NativeMessageError):
                files.run_dialog_flow(MagicMock(), Path("C:/fixture.emm"))
        post.assert_not_called()

    def test_custom_image_save_title_allows_only_authorized_same_path_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            path.write_bytes(b"old")
            parent = {"hwnd": 20, "title": "画像ファイル出力", "controls": []}
            confirm = {"hwnd": 21, "title": "名前を付けて保存の確認", "controls": [
                {"hwnd": 22, "class": "Button", "enabled": True, "text": "はい(&Y)"}]}
            with patch.object(files.win32gui, "GetWindow", return_value=20), \
                 patch.object(files, "filename_edit", return_value=23), \
                 patch.object(files, "window_text", return_value=str(path)):
                self.assertIsNone(files.overwrite_button(confirm, [parent], path, authorized=False, submitted=True))
                self.assertEqual(files.overwrite_button(confirm, [parent], path, authorized=True, submitted=True), 22)

    def test_video_frame_count_comes_from_video_stream_not_muxed_header(self):
        def chunk(kind, payload):
            return kind + struct.pack("<I", len(payload)) + payload + bytes(len(payload) & 1)
        main = struct.pack("<14I", 33333, 0, 0, 0, 7, 0, 2, 0, 320, 180, 0, 0, 0, 0)
        stream = b"vids" + struct.pack("<13I", 0, 0, 0, 0, 333333, 10000000, 0, 3, 0, 0, 0, 0, 0)
        header = chunk(b"LIST", b"hdrl" + chunk(b"avih", main) + chunk(b"LIST", b"strl" + chunk(b"strh", stream)))
        data = chunk(b"RIFF", b"AVI " + header)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio-video.avi"
            path.write_bytes(data)
            result = video_export.avi_header(path)
        self.assertEqual(result["frames"], 3)
        self.assertEqual(result["main_header_frames"], 7)
        self.assertEqual(result["streams"], 2)

    def test_active_video_job_blocks_edits_only_on_its_window(self):
        jobs = {"job": {"target": MagicMock(hwnd=12)}}
        with patch.object(video_export, "_jobs", jobs), \
             patch.object(video_export, "status", return_value={"status": "rendering"}):
            with self.assertRaisesRegex(ValueError, "exporting AVI"):
                video_export.block_if_active(12)
            video_export.block_if_active(13)


if __name__ == "__main__":
    unittest.main()
