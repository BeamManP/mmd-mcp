import struct
import tempfile
import unittest
from pathlib import Path

from mmd_mcp.model_inspection import inspect_skeleton
from mmd_mcp.pmd_geometry import read_pmd_geometry
from mmd_mcp.pmx_geometry import read_pmx_geometry
from mmd_mcp.pose_authoring import read_profile


def pmx_fixture(size=1, encoding=1, version=2.0, target=0, link=0, limited=1, axis=1.0):
    def text(value):
        raw = value.encode('utf-8' if encoding else 'utf-16-le')
        return struct.pack('<i', len(raw)) + raw
    def index(value):
        return struct.pack({1: '<b', 2: '<h', 4: '<i'}[size], value)
    header = b'PMX ' + struct.pack('<f9B', version, 8, encoding, 0, 1, 1, 1, size, 1, 1)
    flags = 1 | 0x20 | 0x80 | 0x300 | 0x400 | 0x800 | 0x1000 | 0x2000
    bone = text('右手首') + text('wrist') + struct.pack('<3f', 1, 2, 3) + index(-1)
    bone += struct.pack('<iH', 3, flags) + index(-1) + index(0) + struct.pack('<f9fi', .5, axis, 0, 0, 1, 0, 0, 0, 0, 1, 42)
    bone += index(target) + struct.pack('<ifi', 12, .25, 1) + index(link) + bytes([limited])
    if limited == 1:
        bone += struct.pack('<6f', -1, -2, -3, 1, 2, 3)
    return header + text('fixture') + text('')*3 + bytes(16) + struct.pack('<i', 1) + bone


def pmd_fixture(kind=0):
    header = b'Pmd' + struct.pack('<f', 1.) + bytes(276) + bytes(12)
    bone = struct.pack('<20sHHBH3f', '右手首'.encode('cp932'), 65535, 0, kind, 25, 1, 2, 3)
    ik = struct.pack('<HHHBHfH', 1, 0, 0, 1, 10, .5, 0)
    return header + struct.pack('<H', 1) + bone + ik


class ModelInspectionTests(unittest.TestCase):
    def test_pmx_layouts_and_preserved_fields(self):
        for size in (1, 2, 4):
            for encoding in (0, 1):
                for version in (2., 2.1):
                    with self.subTest(size=size, encoding=encoding, version=version):
                        _, bones = read_pmx_geometry(pmx_fixture(size, encoding, version))
                        b = bones[0]
                        self.assertEqual(b['english_name'], 'wrist')
                        self.assertEqual(b['external_parent_key'], 42)
                        self.assertEqual(b['inherit'], (0, .5))
                        self.assertEqual(b['ik']['iterations'], 12)
                        self.assertEqual(b['ik']['links'][0]['lower_radians'], (-1., -2., -3.))
                        report = inspect_skeleton(bones, 'pmx', bone_name='wrist')
                        self.assertTrue(report['target']['ancestor_chain'][0]['flag_meanings']['inherit_translation'])
                        self.assertEqual({d['kind'] for d in report['target']['related_dependencies']}, {'pmx_inherit', 'ik'})

    def test_unlimited_ik_is_not_zero_limit(self):
        _, bones = read_pmx_geometry(pmx_fixture(limited=0))
        self.assertIsNone(bones[0]['ik']['links'][0]['lower_radians'])

    def test_pmx_invalid_optional_data(self):
        for args in ({'target': 1}, {'link': -1}, {'limited': 2}, {'axis': float('nan')}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                read_pmx_geometry(pmx_fixture(**args))

    def test_truncation_at_every_byte(self):
        for read, fixture in ((read_pmx_geometry, pmx_fixture()), (read_pmd_geometry, pmd_fixture())):
            for length in range(len(fixture)):
                with self.subTest(parser=read.__name__, length=length), self.assertRaises(ValueError):
                    read(fixture[:length])

    def test_pmd_raw_ik_and_influence(self):
        _, bones = read_pmd_geometry(pmd_fixture(kind=9))
        self.assertEqual(bones[0]['ik_index_raw'], 25)
        self.assertEqual(bones[0]['ik_chains'][0]['control_weight_raw'], .5)
        self.assertIsNone(bones[0]['ik_chains'][0]['links'][0]['lower_radians'])
        report = inspect_skeleton(bones, 'pmd', bone_index=0)
        self.assertEqual(report['target']['related_dependencies'][0]['weight'], .25)
        self.assertIsNone(report['target']['ancestor_chain'][0]['local_axes'])
        bones[0]['kind'] = 5
        report = inspect_skeleton(bones, 'pmd', bone_index=0)
        self.assertEqual(report['target']['related_dependencies'][0]['source_index'], 25)
        self.assertFalse(report['target']['related_dependencies'][0]['source_in_bounds'])
        self.assertEqual(report['target']['related_dependencies'][0]['weight'], 1.)

    def test_pmd_version_and_bad_ik(self):
        data = pmd_fixture()
        for bad in (data[:3]+struct.pack('<f', float('nan'))+data[7:], data[:-2]+b'\xff\xff'):
            with self.assertRaises(ValueError):
                read_pmd_geometry(bad)

    def test_cycle_duplicate_and_selector_guards(self):
        _, bones = read_pmx_geometry(pmx_fixture())
        bones[0]['parent'] = 0
        result = inspect_skeleton(bones, 'pmx', bone_index=0)
        self.assertFalse(result['target']['chain_complete'])
        self.assertEqual(result['warnings'][0]['kind'], 'parent_cycle')
        bones.append(dict(bones[0], index=1))
        self.assertEqual(inspect_skeleton(bones, 'pmx')['duplicate_names']['右手首'], [0, 1])
        for args in ({'bone_name': 'wrist'}, {'bone_name': 'missing'}, {'bone_name': 'wrist', 'bone_index': 0},
                     {'bone_index': -1}, {'bone_index': True}, {'bone_index': 2}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                inspect_skeleton(bones, 'pmx', **args)

    def test_hand_geometry_is_derived_and_degenerate_is_null(self):
        bones = [{'index': i, 'name': name, 'parent': -1, 'rest_position': pos}
                 for i, (name, pos) in enumerate(zip(('右手首', '右人指１', '右小指１'),
                                                     ([0, 0, 0], [1, 0, 0], [0, 1, 0])))]
        hand = inspect_skeleton(bones, 'pmx')['derived_hand_geometry'][0]
        self.assertEqual(hand['normal_candidate'], [0, 0, 1])
        bones[2]['rest_position'] = [2, 0, 0]
        self.assertIsNone(inspect_skeleton(bones, 'pmx')['derived_hand_geometry'][0]['normal_candidate'])

    def test_profile_is_read_only_and_backwards_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix, fixture in (('pmd', pmd_fixture()), ('pmx', pmx_fixture())):
                path = Path(folder) / f'model.{suffix}'
                path.write_bytes(fixture)
                before = path.stat().st_mtime_ns
                profile = read_profile(str(path), bone_name='右手首')
                self.assertIn('bones', profile)
                self.assertIn('model_sha256', profile)
                self.assertIsNone(profile['semantic_profile'])
                self.assertEqual(profile['investigation']['target']['bone']['index'], 0)
                self.assertEqual(path.read_bytes(), fixture)
                self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == '__main__':
    unittest.main()
