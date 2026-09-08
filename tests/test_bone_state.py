import unittest
from unittest.mock import MagicMock, patch

from mmd_mcp import bone_state as bones
from mmd_mcp.windows import MMDWindow


class MemoryFixture:
    def __init__(self):
        self.snapshot = (0x20000, 0, 0x30000, 3, 1, 0x40000)
        self.data = b"".join(name.encode("cp932").ljust(624, b"\0")
                             for name in ["センター", "左腕", "左腕"])

    def anchor(self):
        return self.snapshot

    def read(self, address, size):
        if address == 0x30000 + 8896:
            return "初音ミク".encode("cp932").ljust(size, b"\0")
        if address == 0x30000 + 8946:
            return b"Miku Hatsune".ljust(size, b"\0")
        return self.data[:size]


class BoneStateTests(unittest.TestCase):
    def test_english_display_preserves_original_bone_identity(self):
        memory = MemoryFixture()
        memory.data = b"".join(
            (ja.encode("cp932").ljust(20, b"\0") + en.encode().ljust(20, b"\0")).ljust(624, b"\0")
            for ja, en in [("センター", "center"), ("左腕", "arm_L"), ("左腕", "arm_L")])
        result = bones.inspect_bones(memory, "Miku Hatsune", english=True)
        self.assertEqual(result["selected_bone_name"], "左腕")
        self.assertEqual(result["bones"][1]["display_name"], "arm_L")
        with self.assertRaisesRegex(RuntimeError, "disagree"):
            bones.inspect_bones(memory, "初音ミク", english=True)

    def test_duplicates_preserve_distinct_indices_and_selected_identity(self):
        result = bones.inspect_bones(MemoryFixture(), "初音ミク")
        self.assertEqual(result["selected_bone_name"], "左腕")
        self.assertEqual(result["selected_bone_index"], 1)
        self.assertEqual(result["bones"][2], {"index": 2, "name": "左腕", "display_name": "左腕"})

    def test_model_mismatch_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "disagree"):
            bones.inspect_bones(MemoryFixture(), "別モデル")

    def test_selection_change_rejected(self):
        memory = MemoryFixture()
        changed = (*memory.snapshot[:4], 2, memory.snapshot[5])
        memory.anchor = MagicMock(side_effect=[memory.snapshot, changed])
        with self.assertRaisesRegex(RuntimeError, "changed"):
            bones.inspect_bones(memory, "初音ミク")

    def test_unselected_has_no_name(self):
        memory = MemoryFixture()
        memory.snapshot = (*memory.snapshot[:4], -1, memory.snapshot[5])
        self.assertIsNone(bones.inspect_bones(memory, "初音ミク")["selected_bone_name"])

    def test_bad_encoding_is_not_silently_replaced(self):
        with self.assertRaises(UnicodeDecodeError):
            bones.decode_name(b"\x81\0")

    @patch("mmd_mcp.bone_state.win32api.OpenProcess")
    @patch("mmd_mcp.bone_state.Path.read_bytes", return_value=b"unsupported executable")
    @patch("mmd_mcp.bone_state.psutil.Process")
    def test_unknown_executable_rejected_before_process_memory_access(self, process, _, open_process):
        process.return_value.create_time.return_value = 1.0
        process.return_value.exe.return_value = "C:/MikuMikuDance.exe"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            bones.BoneMemory(MMDWindow(1, 2, "MikuMikuDance", False, 1.0))
        open_process.assert_not_called()

    def test_implausible_bone_count_rejected(self):
        memory = object.__new__(bones.BoneMemory)
        memory.base = 0x10000
        memory.pointer = MagicMock(side_effect=[0x20000, 0x30000, 0x40000])
        memory.integer = MagicMock(side_effect=[0, 100000000, 0])
        with self.assertRaisesRegex(RuntimeError, "layout"):
            memory.anchor()


if __name__ == "__main__":
    unittest.main()
