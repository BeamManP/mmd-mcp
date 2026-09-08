"""Read PMD 1.0 through IK; preserve raw fields rather than convert to PMX."""
import math
from .pmx_geometry import Reader


def read_pmd_geometry(data):
    r = Reader(data)
    if r.take(3) != b'Pmd':
        raise ValueError('Invalid PMD magic.')
    version, = r.unpack('f')
    if not math.isfinite(version) or abs(version - 1.0) > 1e-5:
        raise ValueError('Invalid or unsupported PMD header.')
    name = r.take(20).split(b'\0')[0].decode('cp932')
    r.take(256)
    for stride in (38, 2, 70):
        count, = r.unpack('I')
        r.take(count * stride)
    count, = r.unpack('H')
    bones = []
    for index in range(count):
        raw, parent, tail, kind, ik_index, x, y, z = r.unpack('20sHHBH3f')
        if (parent != 65535 and parent >= count) or not all(math.isfinite(v) for v in (x, y, z)):
            raise ValueError('Invalid PMD bone geometry.')
        bones.append({'index': index, 'name': raw.split(b'\0')[0].decode('cp932'),
                      'parent': parent, 'rest_position': [x, y, z], 'kind': kind,
                      'tail_raw': tail, 'ik_index_raw': ik_index, 'ik_chains': []})
    ik_count, = r.unpack('H')
    for _ in range(ik_count):
        controller, target, length, iterations, weight = r.unpack('HHBHf')
        links = list(r.unpack(f'{length}H'))
        if any(i >= count for i in [controller, target, *links]) or not math.isfinite(weight):
            raise ValueError('Invalid PMD IK settings.')
        bones[controller]['ik_chains'].append({
            'target_index': target, 'iterations': iterations,
            'control_weight_raw': weight,
            'links': [{'bone_index': i, 'lower_radians': None, 'upper_radians': None} for i in links],
            'limits_source': 'not_stored_in_pmd'})
    return name, bones
