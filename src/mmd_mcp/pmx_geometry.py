"""Bounded PMX 2.0/2.1 reader through the bone section (no asset mutation).

Rest geometry and declared bone/IK settings are returned. This is not a complete validator
for later morph, physics, display or soft-body sections.
"""
import math
import struct


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, size):
        if size < 0 or self.offset + size > len(self.data):
            raise ValueError('PMX section exceeds file bounds.')
        start = self.offset
        self.offset += size
        return self.data[start:self.offset]

    def unpack(self, fmt):
        return struct.unpack('<'+fmt, self.take(struct.calcsize('<'+fmt)))

    def count(self, maximum=2000000):
        value, = self.unpack('i')
        if not 0 <= value <= maximum:
            raise ValueError('PMX count is out of bounds.')
        return value

    def text(self):
        return self.take(self.count(1024*1024)).decode(self.encoding)

    def bone_index(self):
        return self.unpack({1: 'b', 2: 'h', 4: 'i'}[self.bone_size])[0]


def read_pmx_geometry(data):
    r = Reader(data)
    if r.take(4) != b'PMX ':
        raise ValueError('Invalid PMX magic.')
    version, = r.unpack('f')
    if not (abs(version-2.) < 1e-5 or abs(version-2.1) < 1e-5):
        raise ValueError('Unsupported PMX version.')
    size, = r.unpack('B')
    if size != 8:
        raise ValueError('Unsupported PMX header length.')
    encoding, uv, vertex_size, texture_size, material_size, bone_size, morph_size, rigid_size = r.unpack('8B')
    if encoding not in (0, 1) or uv > 4 or any(v not in (1, 2, 4) for v in
            (vertex_size, texture_size, material_size, bone_size, morph_size, rigid_size)):
        raise ValueError('Invalid PMX encoding, UV or index layout.')
    r.encoding = 'utf-16-le' if encoding == 0 else 'utf-8'
    r.bone_size = bone_size
    name = r.text()
    for _ in range(3):
        r.text()
    for _ in range(r.count()):
        r.take(32+16*uv)
        skin, = r.unpack('B')
        weights = {0: bone_size, 1: 2*bone_size+4, 2: 4*bone_size+16,
                   3: 2*bone_size+40, 4: 4*bone_size+16}
        if skin not in weights or skin == 4 and version < 2.05:
            raise ValueError('Unsupported PMX vertex skinning type.')
        r.take(weights[skin]+4)
    r.take(r.count(6000000)*vertex_size)
    for _ in range(r.count(100000)):
        r.text()
    for _ in range(r.count(100000)):
        r.text()
        r.text()
        r.take(44+1+20+2*texture_size+1)
        shared, = r.unpack('B')
        if shared not in (0, 1):
            raise ValueError('Invalid PMX shared toon flag.')
        r.take(1 if shared else texture_size)
        r.text()
        r.count(6000000)
    count = r.count(10000)
    bones = []
    for index in range(count):
        bone_name = r.text()
        english_name = r.text()
        position = r.unpack('3f')
        parent = r.bone_index()
        layer, flags = r.unpack('iH')
        if not all(math.isfinite(v) for v in position) or not -1 <= parent < count:
            raise ValueError('Invalid PMX bone geometry.')
        tail = r.bone_index() if flags & 1 else r.unpack('3f')
        inherit = None
        if flags & 0x300:
            inherit = (r.bone_index(), r.unpack('f')[0])
        fixed_axis = r.unpack('3f') if flags & 0x400 else None
        local_axes = r.unpack('6f') if flags & 0x800 else None
        external_parent_key = r.unpack('i')[0] if flags & 0x2000 else None
        ik = None
        if flags & 0x20:
            target = r.bone_index()
            iterations, angle = r.unpack('if')
            if not 0 <= target < count or iterations < 0 or not math.isfinite(angle):
                raise ValueError('Invalid PMX IK settings.')
            links = []
            for _ in range(r.count(10000)):
                link_index = r.bone_index()
                limited, = r.unpack('B')
                if limited not in (0, 1) or not 0 <= link_index < count:
                    raise ValueError('Invalid PMX IK limit flag.')
                lower = r.unpack('3f') if limited else None
                upper = r.unpack('3f') if limited else None
                if limited and not all(math.isfinite(v) for v in lower+upper):
                    raise ValueError('Invalid PMX IK limit values.')
                links.append({'bone_index': link_index, 'limited': bool(limited),
                              'lower_radians': lower, 'upper_radians': upper})
            ik = {'target_index': target, 'iterations': iterations,
                  'angle_limit_radians': angle, 'links': links}
        if flags & 1:
            if not -1 <= tail < count:
                raise ValueError('Invalid PMX tail index.')
        elif not all(math.isfinite(v) for v in tail):
            raise ValueError('Invalid PMX tail offset.')
        if inherit and (not -1 <= inherit[0] < count or not math.isfinite(inherit[1])):
            raise ValueError('Invalid PMX inheritance.')
        if any(not math.isfinite(v) for axis in (fixed_axis, local_axes) if axis for v in axis):
            raise ValueError('Invalid PMX axis values.')
        bones.append({'index': index, 'name': bone_name, 'parent': parent,
                      'english_name': english_name,
                      'rest_position': list(position), 'flags': flags, 'layer': layer,
                      'tail': tail, 'inherit': inherit, 'fixed_axis': fixed_axis,
                      'local_axes': local_axes, 'external_parent_key': external_parent_key,
                      'ik': ik})
    return name, bones
