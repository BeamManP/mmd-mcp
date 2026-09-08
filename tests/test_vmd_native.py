import struct
import tempfile
import unittest
from pathlib import Path

from mmd_mcp import motion_document as motion, vmd_reader, vmd_edit


def fixture():
    document = motion.MotionDocument(model_name="fixture", model_sha256="a" * 64,
        bones=[motion.BoneKey(name="頭", frame=10), motion.BoneKey(name="頭", frame=20)],
        morphs=[motion.MorphKey(name="笑い", frame=10, weight=.5)])
    data = bytearray(motion.vmd_bytes(document))
    data[54 + 47 + 2:54 + 47 + 4] = b"\x01\x01"  # Native metadata in redundant slots.
    return bytes(data)


class NativeVmdTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "source.vmd"
        self.source.write_bytes(fixture())
        self.output = self.source.with_name("edited.vmd")

    def test_reader_uses_native_channel_blocks_and_paginates(self):
        read = vmd_reader.inspect(str(self.source), limit=1)
        self.assertEqual(read["matched_records"], 3)
        self.assertEqual(read["next_offset"], 1)
        self.assertEqual(read["records"][0]["interpolation"]["rotation"]["x1"], 20)
        next_page = vmd_reader.inspect(str(self.source), offset=1, limit=1)
        self.assertEqual(next_page["records"][0]["frame"], 20)

    def test_interpolation_preserves_native_flags_and_unrelated_records(self):
        original = self.source.read_bytes()
        curve = {"x1": 5, "y1": 10, "x2": 90, "y2": 120}
        vmd_edit.edit(str(self.source), str(self.output), [
            {"action": "interpolation", "track": "bones", "start_frame": 10, "end_frame": 10,
             "curves": {"rotation": curve}}])
        changed = self.output.read_bytes()
        allowed = {54 + 47 + 48 + step * 4 for step in range(4)}
        self.assertEqual({i for i, (a, b) in enumerate(zip(original, changed)) if a != b}, allowed)
        self.assertEqual(self.source.read_bytes(), original)
        read = vmd_reader.inspect(str(self.output))
        self.assertEqual(read["records"][0]["interpolation"]["rotation"], curve)

    def test_collision_and_unmatched_edit_leave_no_output(self):
        for edit in [{"action": "shift", "track": "bones", "start_frame": 10, "end_frame": 10, "shift_frames": 10},
                     {"action": "delete", "track": "bones", "names": ["missing"]}]:
            with self.assertRaises(ValueError):
                vmd_edit.edit(str(self.source), str(self.output), [edit])
            self.assertFalse(self.output.exists())

    def test_delete_keeps_other_tracks_and_updates_count(self):
        vmd_edit.edit(str(self.source), str(self.output), [{"action": "delete", "track": "bones", "start_frame": 10, "end_frame": 10}])
        read = vmd_reader.inspect(str(self.output))
        self.assertEqual(read["counts"]["bones"], 1)
        self.assertEqual(read["counts"]["morphs"], 1)
        self.assertEqual(read["trailing_bytes"], 0)

    def test_truncated_and_forged_count_are_rejected(self):
        for data in [fixture()[:-1], fixture()[:54], fixture()[:50] + struct.pack("<I", 2**32 - 1)]:
            self.source.write_bytes(data)
            with self.assertRaises(ValueError):
                vmd_reader.inspect(str(self.source))


if __name__ == "__main__":
    unittest.main()
