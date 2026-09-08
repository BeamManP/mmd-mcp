import unittest
from unittest.mock import MagicMock, patch

from mmd_mcp.ui_state import UIReader, get_ui_state, model_entries, parse_number
from mmd_mcp.windows import MMDWindow


class ModelListTests(unittest.TestCase):
    def test_camera_entry_is_not_a_model_and_duplicate_names_keep_indices(self):
        result = model_entries({"items": ["camera", "初音ミク", "初音ミク"],
                                "selected_index": 2, "selected_name": "初音ミク"})
        self.assertEqual([m["selector_index"] for m in result["models"]], [1, 2])
        self.assertFalse(result["models"][0]["selected"])
        self.assertTrue(result["models"][1]["selected"])

    def test_camera_only_is_an_empty_model_list(self):
        result = model_entries({"items": ["camera"], "selected_index": 0, "selected_name": "camera"})
        self.assertEqual(result["models"], [])
        self.assertTrue(result["camera_light_accessory_selected"])

    def test_missing_selector_is_not_an_empty_scene(self):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            model_entries(None)

    def test_blank_or_invalid_numbers_are_unknown(self):
        for value in ["", "-", "nan", "inf", "abc"]:
            self.assertIsNone(parse_number(value))
        self.assertEqual(parse_number("0.0000"), 0.0)
        self.assertEqual(parse_number("42", integer=True), 42)
        self.assertIsNone(parse_number("4.2", integer=True))


class ObservationTests(unittest.TestCase):
    def test_camera_mode_never_reads_stale_morph_or_ik_controls(self):
        reader = MagicMock()
        reader.anchor.return_value = ("0", 0, "camera")
        reader.combo.return_value = {"items": ["camera", "初音ミク"], "selected_index": 0, "selected_name": "camera"}
        with patch("mmd_mcp.ui_state.UIReader", return_value=reader):
            result = get_ui_state()
        self.assertEqual(result["morph_panels"], {})
        self.assertIsNone(result["ik_selector"])
        reader.combo.assert_called_once_with(436)
        reader.edit.assert_not_called()

    def test_frame_change_invalidates_snapshot(self):
        target = MMDWindow(123, 456, "MikuMikuDance", False, 1.0)
        with patch("mmd_mcp.ui_state.select_window", return_value=target):
            reader = UIReader(None)
            with patch.object(reader, "anchor", return_value=("1", 1, "初音ミク")):
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    reader.verify(("0", 1, "初音ミク"))

    def test_write_message_is_rejected_before_native_call(self):
        with patch("mmd_mcp.ui_state.select_window"):
            reader = UIReader(None)
        with patch("mmd_mcp.ui_state._send") as send:
            with self.assertRaisesRegex(ValueError, "read messages"):
                reader.message(123, 0x000C)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
