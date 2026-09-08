"""EMM patch behavior against the structure exported by MME 0.37 / Ray-MMD 1.5.2."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from mmd_mcp import effects


# Object numbering, bracket subsets, Owner and .show reflect a native MME export.
# Paths and the material count are synthetic; no model or effect assets are included.
EMM = r"""; 日本語コメント
[Info]
Version = 3

[Object]
Acs1 = effects\ray.x
Pmd2 = models\sky.pmx
Pmd3 = models\stage.pmx
Pmd4 = models\miku.pmx

[Effect]
Default = none
Pmd2 = effects\sky.fx
Pmd3 = effects\main.fx
Pmd3[17] = effects\alpha.fx
Pmd3[17].show = true
Pmd4 = none

[Effect@EnvLightMap]
Owner = Acs1
Default = sky*.pmx=effects\sky_none.fx; *=hide;
Acs1.show = false
Pmd2 = effects\sky_none.fx
Pmd2.show = true
Pmd3 = none
Pmd3.show = false

[Effect@MaterialMap]
Owner = Acs1
Acs1.show = false
Pmd2 = effects\material_skybox.fx
Pmd3 = effects\material_2.0.fx
Pmd4 = effects\material_2.0.fx

[Effect@PSSM1]
Owner = Acs1
Pmd3 = effects\PSSM1.fx
Pmd4 = effects\PSSM1.fx

[Unrelated]
; Keep whitespace, comments and equals signs.
custom = x=y;z
""".replace('\n', '\r\n').encode('cp932')


class EffectSectionsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'scene.emm'
        self.path.write_bytes(EMM)

    def read(self):
        return effects.read_emm(str(self.path))

    def write(self, **kwargs):
        return effects.write_emm(str(self.path), **kwargs)

    def test_read_separates_assignments_visibility_and_metadata(self):
        result = self.read()
        self.assertEqual(result['objects']['Pmd2'], r'models\sky.pmx')
        main = result['effect_sections']['Effect']
        self.assertIsNone(main['assignments']['Pmd4'])
        self.assertTrue(main['visibility']['Pmd3[17]'])
        env = result['effect_sections']['Effect@EnvLightMap']
        self.assertEqual(env['owner'], 'Acs1')
        self.assertEqual(env['default'], r'sky*.pmx=effects\sky_none.fx; *=hide;')
        self.assertIsNone(env['assignments']['Pmd3'])
        self.assertFalse(env['visibility']['Pmd3'])
        self.assertNotIn('Owner', env['assignments'])
        self.assertNotIn('Unrelated', result['effect_sections'])
        self.assertIn('Unrelated', result['sections'])
        self.assertNotIn('Pmd4', result['effect_sections']['Effect@MaterialMap']['visibility'])

    def test_multi_section_edit_preserves_owner_defaults_and_unrelated_bytes(self):
        before = self.read()
        result = self.write(sections=[
            {'section': 'Effect', 'assignments': {'Pmd4': 'effects/main.fx'}},
            {'section': 'Effect@EnvLightMap', 'assignments': {'Pmd2': 'effects/lighting.fx'}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3[17]': 'effects/skin.fxsub'},
             'visibility': {'Pmd3[17]': True}},
            {'section': 'Effect@PSSM1', 'visibility': {'Pmd3': False}},
        ])
        after = self.read()
        self.assertFalse(result['applied_to_mmd'])
        self.assertEqual(len(result['changed_sections']), 4)
        self.assertEqual(after['effects']['Pmd4'], 'effects/main.fx')
        self.assertEqual(after['effect_sections']['Effect@EnvLightMap']['assignments']['Pmd2'],
                         'effects/lighting.fx')
        self.assertTrue(after['effect_sections']['Effect@MaterialMap']['visibility']['Pmd3[17]'])
        self.assertEqual(after['effect_sections']['Effect@MaterialMap']['assignments']['Pmd3[17]'],
                         'effects/skin.fxsub')
        self.assertFalse(after['effect_sections']['Effect@PSSM1']['visibility']['Pmd3'])
        for name, old in before['effect_sections'].items():
            self.assertEqual(after['effect_sections'][name]['owner'], old['owner'])
            self.assertEqual(after['effect_sections'][name]['default'], old['default'])
        self.assertEqual(after['objects'], before['objects'])
        self.assertEqual(self.path.read_bytes().split(b'[Unrelated]')[1], EMM.split(b'[Unrelated]')[1])

    def test_null_assignment_does_not_change_visibility(self):
        self.write(sections=[{'section': 'Effect@EnvLightMap', 'assignments': {'Pmd2': None}}])
        env = self.read()['effect_sections']['Effect@EnvLightMap']
        self.assertIsNone(env['assignments']['Pmd2'])
        self.assertTrue(env['visibility']['Pmd2'])

    def test_legacy_main_input_and_dotted_subsets_write_native_brackets(self):
        result = self.write(assignments={'Pmd3.17': 'effects/changed.fxm'})
        self.assertEqual(result['changed'], {'Pmd3[17]': 'effects/changed.fxm'})
        self.assertEqual(self.read()['effects']['Pmd3[17]'], 'effects/changed.fxm')
        self.assertNotIn(b'Pmd3.17', self.path.read_bytes())

    def test_new_output_keeps_source_and_refuses_existing_destination(self):
        output = self.path.with_name('draft.emm')
        result = self.write(sections=[{'section': 'Effect@PSSM1', 'visibility': {'Pmd3': False}}],
                            output_path=str(output))
        self.assertEqual(result['path'], str(output))
        self.assertEqual(self.path.read_bytes(), EMM)
        expected = output.read_bytes()
        self.assertNotEqual(expected, EMM)
        for destination in (output, self.path):
            with self.subTest(destination=destination), self.assertRaises(FileExistsError):
                self.write(assignments={'Pmd4': 'effects/main.fx'}, output_path=str(destination))
        self.assertEqual(output.read_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), EMM)

    def test_all_sections_validate_before_any_file_is_written(self):
        bad_patches = [
            {'section': 'Effect@DoesNotExist', 'assignments': {'Pmd3': None}},
            {'section': 'Object', 'assignments': {'Pmd3': None}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd99': None}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Owner': None}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Default': None}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3.show': None}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3': 'bad\nPmd4=other.fx'}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3': 'bad\x00.fx'}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3': 'notes.txt'}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3': str(self.path.with_name('missing.fx'))}},
            {'section': 'Effect@MaterialMap', 'assignments': {'Pmd3': 'emoji-\U0001f600.fx'}},
        ]
        output = self.path.with_name('never-created.emm')
        for bad in bad_patches:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.write(sections=[{'assignments': {'Pmd4': 'effects/main.fx'}}, bad],
                           output_path=str(output))
            self.assertEqual(self.path.read_bytes(), EMM)
            self.assertFalse(output.exists())

    def test_strict_patch_fields_and_booleans(self):
        for bad in [
            {'section': 'Effect@MaterialMap'},
            {'visibility': {'Pmd3': 'false'}},
            {'visibility': {'Pmd3': 0}},
            {'assignments': {'Pmd3': False}},
            {'assignments': {'Pmd3': None}, 'owner': 'Acs1'},
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.write(sections=[bad])
        self.assertEqual(self.path.read_bytes(), EMM)

    def test_duplicate_sections_and_alias_collisions_are_refused(self):
        for kwargs in [
            {'assignments': {'Pmd3': None}, 'sections': [{'assignments': {'Pmd4': None}}]},
            {'sections': [{'section': 'Effect@PSSM1', 'visibility': {'Pmd3': False}}] * 2},
            {'sections': [{'assignments': {'Pmd3.17': None, 'Pmd3[17]': None}}]},
            {'sections': [{'visibility': {'Pmd3.17': False, 'Pmd3[17]': True}}]},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.write(**kwargs)
        self.assertEqual(self.path.read_bytes(), EMM)

    def test_offscreen_owner_must_exist_and_remains_uneditable(self):
        for owner in (b'', b'Owner = Acs99\r\n'):
            original = EMM.replace(b'Owner = Acs1\r\n', owner)
            self.path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'Owner'):
                self.write(sections=[{'section': 'Effect@MaterialMap', 'assignments': {'Pmd3': None}}])
            self.assertEqual(self.path.read_bytes(), original)

    def test_byte_preservation_including_alternate_cp932_and_whitespace(self):
        # CP932 has multiple byte representations for some Unicode characters.
        original = EMM + b'; alternative encoding: \xfa\x4a\r\n'
        original = original.replace(b'Pmd4 = none\r\n', b'\tPmd4\t=\t none  \r\n')
        self.path.write_bytes(original)
        self.write(assignments={'Pmd4': 'effects/main.fx'})
        self.assertEqual(self.path.read_bytes(),
                         original.replace(b'\tPmd4\t=\t none  \r\n', b'\tPmd4\t=\t effects/main.fx  \r\n'))

    def test_missing_main_and_final_newline_can_be_added_without_rewriting_existing_data(self):
        original = b'[Object]\nPmd1 = model.pmx'
        self.path.write_bytes(original)
        self.write(assignments={'Pmd1': 'main.fx'})
        self.assertTrue(self.path.read_bytes().startswith(original + b'\n'))
        self.assertEqual(self.read()['effects']['Pmd1'], 'main.fx')

    def test_idempotent_patch_leaves_file_untouched(self):
        before_stamp = self.path.stat().st_mtime_ns
        self.write(assignments={'Pmd4': None})
        self.assertEqual(self.path.read_bytes(), EMM)
        self.assertEqual(self.path.stat().st_mtime_ns, before_stamp)

    def test_replace_failure_preserves_source_and_cleans_temporary_file(self):
        with patch.object(effects.os, 'replace', side_effect=PermissionError('busy')):
            with self.assertRaises(PermissionError):
                self.write(assignments={'Pmd4': 'effects/main.fx'})
        self.assertEqual(self.path.read_bytes(), EMM)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_concurrent_external_change_is_not_overwritten(self):
        mkstemp = effects.tempfile.mkstemp
        external = EMM + b'; external change\r\n'

        def concurrent_change(*args, **kwargs):
            self.path.write_bytes(external)
            return mkstemp(*args, **kwargs)

        with patch.object(effects.tempfile, 'mkstemp', side_effect=concurrent_change):
            with self.assertRaisesRegex(RuntimeError, 'changed while editing'):
                self.write(assignments={'Pmd4': 'effects/main.fx'})
        self.assertEqual(self.path.read_bytes(), external)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_ambiguous_files_are_refused_before_edit(self):
        for original in (EMM + b'[Effect]\r\nPmd4 = other.fx\r\n',
                         EMM.replace(b'Pmd4 = none', b'Pmd4 = none\r\nPmd4 = other.fx')):
            self.path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                self.write(assignments={'Pmd4': 'effects/main.fx'})
            self.assertEqual(self.path.read_bytes(), original)

    def test_size_limit_applies_to_read_and_write(self):
        with patch.object(effects, 'MAX_BYTES', len(EMM) - 1):
            with self.assertRaisesRegex(ValueError, 'large'):
                self.read()
            with self.assertRaisesRegex(ValueError, 'large'):
                self.write(assignments={'Pmd4': None})
        self.assertEqual(self.path.read_bytes(), EMM)


if __name__ == '__main__':
    unittest.main()
