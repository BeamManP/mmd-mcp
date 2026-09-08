"""Explain file-declared skeletons without evaluating or editing a live scene."""
import math
from collections import defaultdict


COMMON_NAMES = ['センター', '上半身', '上半身2', '首', '頭'] + [
    side + role for side in ('左', '右')
    for role in ('肩', '腕', '腕捩', 'ひじ', '手捩', '手首', '親指０', '親指１',
                 '人指１', '中指１', '薬指１', '小指１', '足', 'ひざ', '足首', '足ＩＫ')]


def unit(vector):
    length = math.sqrt(sum(v*v for v in vector))
    return [v/length for v in vector] if length > 1e-8 else None


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def inspect_skeleton(bones, file_format, bone_name=None, bone_index=None):
    if bone_name is not None and bone_index is not None:
        raise ValueError('Specify bone_name or bone_index, not both.')
    by_name = defaultdict(list)
    for bone in bones:
        by_name[bone['name']].append(bone['index'])
    if bone_name is not None:
        matches = [b['index'] for b in bones if bone_name in (b['name'], b.get('english_name'))]
        if len(matches) != 1:
            raise ValueError(f'Bone name must match exactly one bone; found {len(matches)}. Use bone_index for duplicates.')
        bone_index = matches[0]
    if bone_index is not None and (type(bone_index) is not int or not 0 <= bone_index < len(bones)):
        raise ValueError('bone_index is out of range.')

    def ref(index):
        return {'index': index, 'name': bones[index]['name']}

    def declared(bone):
        result = dict(bone)
        if file_format == 'pmx':
            flags = bone['flags']
            result['flag_meanings'] = {name: bool(flags & bit) for name, bit in (
                ('tail_is_index', 1), ('rotatable', 2), ('translatable', 4),
                ('visible', 8), ('operable', 16), ('ik_enabled', 32),
                ('inherit_local', 0x80), ('inherit_rotation', 0x100),
                ('inherit_translation', 0x200), ('fixed_axis_declared', 0x400),
                ('local_axes_declared', 0x800), ('after_physics', 0x1000), ('external_parent', 0x2000))}
        else:
            result['field_semantics'] = 'PMD kind/tail_raw/ik_index_raw are retained without PMX conversion; their meaning depends on kind.'
            result['kind_name'] = {0: 'rotation', 1: 'rotation_translation', 2: 'ik', 3: 'unknown',
                                   4: 'ik_link', 5: 'rotation_influence', 6: 'ik_target',
                                   7: 'hidden', 8: 'twist', 9: 'rotation_ratio'}.get(bone['kind'], 'unknown')
            result['local_axes'] = None
            result['fixed_axis'] = None
        return result

    warnings = []
    # Linear walk with a global visited set; tolerate/report cycles without hanging.
    visited = set()
    for start in range(len(bones)):
        cursor, path = start, set()
        while 0 <= cursor < len(bones) and cursor not in visited:
            if cursor in path:
                warnings.append({'kind': 'parent_cycle', 'bone': ref(cursor)})
                break
            path.add(cursor)
            cursor = bones[cursor]['parent']
        visited.update(path)
    for bone in bones:
        for field in ('fixed_axis', 'local_axes'):
            axis = bone.get(field)
            if axis and (unit(axis[:3]) is None or field == 'local_axes' and unit(cross(axis[:3], axis[3:])) is None):
                warnings.append({'kind': 'degenerate_declared_axis', 'bone': ref(bone['index']), 'field': field})

    result = {
        'source': 'local_model_file', 'format': file_format, 'coordinate_space': 'MMD model rest coordinates, unconverted',
        'parsed_through': 'bones_and_ik',
        'common_bone_presence': {'basis': 'Exact Japanese-name checklist, not a compatibility certification.',
                                 'indices_by_name': {name: by_name.get(name, []) for name in COMMON_NAMES}},
        'duplicate_names': {name: indices for name, indices in by_name.items() if len(indices) > 1},
        'warnings': warnings,
        'unknown': ['Current pose, camera, physics, IK ON/OFF and external-parent scene state are not read.',
                    'Morphs, rigid bodies, joints and later sections are not parsed or validated.',
                    'PMX fixed/local axes describe operation constraints/frames; they are not a VMD rotation-basis conversion.',
                    'Absent local-axis declarations do not prove identical operation axes across models.',
                    'PMD per-link IK limits and explicit local-axis vectors are not stored; runtime conventions are not inferred.'],
        'target': None, 'derived_hand_geometry': []}
    if bone_index is not None:
        chain, seen, cursor = [], set(), bone_index
        while 0 <= cursor < len(bones) and cursor not in seen:
            seen.add(cursor)
            chain.append(declared(bones[cursor]))
            cursor = bones[cursor]['parent']
        relationships = []
        for bone in bones:
            if file_format == 'pmd' and bone['kind'] in (5, 9):
                source = bone['ik_index_raw'] if bone['kind'] == 5 else bone['tail_raw']
                if bone['index'] in seen or source in seen:
                    relationships.append({'kind': 'pmd_rotation_influence', 'receiver': ref(bone['index']),
                                          'source_index': source, 'source_in_bounds': 0 <= source < len(bones),
                                          'weight': 1.0 if bone['kind'] == 5 else bone['ik_index_raw']/100.,
                                          'source': 'interpreted_from_pmd_kind_and_raw_fields'})
            inherit = bone.get('inherit')
            if inherit and (bone['index'] in seen or inherit[0] in seen):
                relationships.append({'kind': 'pmx_inherit', 'receiver': ref(bone['index']),
                                      'source_index': inherit[0], 'weight': inherit[1],
                                      'rotation': bool(bone['flags'] & 0x100),
                                      'translation': bool(bone['flags'] & 0x200),
                                      'local': bool(bone['flags'] & 0x80)})
            iks = [bone['ik']] if bone.get('ik') else bone.get('ik_chains', [])
            for ik in iks:
                participants = {bone['index'], ik['target_index'], *(link['bone_index'] for link in ik['links'])}
                if participants & seen:
                    relationships.append({'kind': 'ik', 'controller': ref(bone['index']), 'declared': ik})
        result['target'] = {'bone': ref(bone_index), 'ancestor_chain': chain,
                            'chain_order': 'target_to_root', 'chain_complete': cursor not in seen,
                            'related_dependencies': relationships}
    for side in ('左', '右'):
        names = [side + role for role in ('手首', '人指１', '小指１')]
        if not all(len(by_name.get(name, [])) == 1 for name in names):
            continue
        indices = [by_name[name][0] for name in names]
        positions = [bones[i]['rest_position'] for i in indices]
        a, b = [[value-origin for value, origin in zip(p, positions[0])] for p in positions[1:]]
        result['derived_hand_geometry'].append({
            'side': side, 'source': 'derived_from_rest_positions', 'bone_indices': indices,
            'wrist_to_index_base': a, 'wrist_to_little_base': b,
            'normal_candidate': unit(cross(a, b)),
            'formula': 'normalize((index1 - wrist) cross (little1 - wrist))',
            'limitation': 'Sign is geometric, not verified palm-facing; this is neither a bone operation frame nor the current posed hand.'})
    return result
