"""Read and patch MMEffect assignment files without changing the live MMD scene.

Observed MME v3 format: CP932, [Object] maps transient Pmd/Acs IDs to files,
[Effect] is Main, and [Effect@<render target>] retains an Owner object ID.
Material subsets use Pmd3[173], not Pmd3.173. Visibility is a separate .show key.
"""
import os
import re
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

ENCODING = 'cp932'
MAX_BYTES = 4 * 1024 * 1024
TARGET = re.compile(r'((?:Pmd|Acs)\d+)(?:\[(\d+)\])?')
LEGACY_SUBSET = re.compile(r'((?:Pmd|Acs)\d+)\.(\d+)')
APPLY_NOTE = (
    'File edit only; not applied to MMD. Import the EMM using the effect-assignment '
    'dialog File > Load settings, or reload the adjacent PMM (which replaces the scene). '
    'MMD project save can overwrite the adjacent EMM when assignment auto-save is on.'
)


class EffectSectionPatch(BaseModel):
    """Changes to one exact section name returned by read_emm.effect_sections."""
    model_config = ConfigDict(extra='forbid')

    section: StrictStr = 'Effect'
    assignments: dict[StrictStr, StrictStr | None] = Field(default_factory=dict)
    visibility: dict[StrictStr, StrictBool] = Field(default_factory=dict)

    @model_validator(mode='after')
    def _content(self):
        if not self.assignments and not self.visibility:
            raise ValueError('A section patch needs assignments or visibility.')
        return self


def _path(emm_path):
    path = Path(emm_path)
    if not path.is_absolute() or path.suffix.lower() != '.emm':
        raise ValueError('Provide an absolute .emm path.')
    return path


def _read(emm_path):
    path = _path(emm_path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('EMM file is missing or too large.')
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError('EMM file is too large.')
    sections, order = parse(data.decode(ENCODING))
    return path, data, sections, order


def parse(text):
    sections, order, current = {}, [], None
    keys = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            current = line[1:-1]
            if not current or current in sections:
                raise ValueError(f'Empty or duplicate EMM section: {current!r}')
            sections[current] = []
            order.append(current)
            keys = set()
            continue
        if current is None or '=' not in line:
            raise ValueError(f'Unrecognised EMM line: {raw!r}')
        key, value = (part.strip() for part in line.split('=', 1))
        if not key or key in keys:
            raise ValueError(f'Empty or duplicate EMM key in {current!r}: {key!r}')
        keys.add(key)
        sections[current].append((key, value))
    return sections, order


def _is_effect_section(name):
    return name == 'Effect' or name.startswith('Effect@') and len(name) > len('Effect@')


def read_emm(emm_path):
    path, _, sections, order = _read(emm_path)
    objects = dict(sections.get('Object', []))
    effects = dict(sections.get('Effect', []))
    effect_sections = {}
    for name in order:
        if not _is_effect_section(name):
            continue
        entries = dict(sections[name])
        assignments, visibility = {}, {}
        for key, value in entries.items():
            if TARGET.fullmatch(key):
                assignments[key] = None if value.lower() == 'none' else value
            elif key.endswith('.show') and TARGET.fullmatch(key[:-5]):
                if value.lower() not in {'true', 'false'}:
                    raise ValueError(f'Invalid visibility value in {name}: {key} = {value}')
                visibility[key[:-5]] = value.lower() == 'true'
        effect_sections[name] = {
            'owner': entries.get('Owner'), 'default': entries.get('Default'),
            'assignments': assignments, 'visibility': visibility,
        }
    return {
        'path': str(path), 'version': dict(sections.get('Info', [])).get('Version'),
        'objects': objects,
        # Keep the original Main-only response for existing callers.
        'effects': {key: None if value.lower() == 'none' else value for key, value in effects.items()},
        'effect_sections': effect_sections,
        'sections': {name: dict(sections[name]) for name in order},
        'note': 'Saved file state, not live MMD state. Use IDs from objects, not UI selector indices. '
                'Relative paths are usually based on the MMD folder, not the EMM folder. '
                'Assignments and visibility contain explicit entries only; defaults are not expanded. '
                'Null assignment means none, not hidden; visibility controls .show separately.',
    }


def _target(key, objects):
    # Accept the old API spelling, but always write MME's actual bracket syntax.
    legacy = LEGACY_SUBSET.fullmatch(key)
    if legacy:
        key = f'{legacy[1]}[{legacy[2]}]'
    match = TARGET.fullmatch(key)
    if match is None or match[1] not in objects:
        raise ValueError(f'{key!r} is not an object/subset of this EMM ({sorted(objects)}).')
    return key


def _effect_value(value):
    if value is None:
        return 'none'
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('An effect path must be a single line without control characters.')
    fx = Path(value)
    if value != value.strip() or fx.suffix.lower() not in {'.fx', '.fxsub', '.fxm'}:
        raise ValueError(f'{value!r} is not an effect file (.fx, .fxsub or .fxm).')
    if fx.is_absolute() and not fx.is_file():
        raise ValueError(f'Effect file does not exist: {value}')
    return value


def _patch_bytes(data, changes):
    """Replace only requested values; retain every untouched byte, including comments."""
    pending = {name: dict(entries) for name, entries in changes.items()}
    newline_match = re.search(br'\r\n|\n|\r', data)
    newline = newline_match[0] if newline_match else b'\r\n'
    out, current = [], None

    def append_entries(name):
        entries = pending.pop(name, {})
        if entries and out and not out[-1].endswith((b'\r', b'\n')):
            out.append(newline)
        out.extend(f'{key} = {value}'.encode(ENCODING) + newline for key, value in entries.items())

    for raw in data.splitlines(keepends=True):
        line = raw.decode(ENCODING).strip()
        if line.startswith('[') and line.endswith(']'):
            append_entries(current)
            current = line[1:-1]
        elif line and not line.startswith(';') and '=' in line:
            key, old_value = (s.strip() for s in line.split('=', 1))
            entries = pending.get(current, {})
            if key in entries:
                value = entries.pop(key)
                if old_value != value:
                    body = raw.rstrip(b'\r\n')
                    prefix, old = body.split(b'=', 1)
                    leading = old[:len(old) - len(old.lstrip(b' \t'))]
                    trailing = old[len(old.rstrip(b' \t')):]
                    raw = prefix + b'=' + leading + value.encode(ENCODING) + trailing + raw[len(body):]
        out.append(raw)
    append_entries(current)
    # Only Main may be added. Offscreen sections must already have a verified Owner.
    for name in list(pending):
        if out and not out[-1].endswith((b'\r', b'\n')):
            out.append(newline)
        out.append(f'[{name}]'.encode(ENCODING) + newline)
        append_entries(name)
    return b''.join(out)


def _write(path, original, data, output_path):
    if output_path is not None:
        destination = _path(output_path)
        with destination.open('xb') as stream:
            stream.write(data)
        return destination
    if data == original:
        return path
    # A validation or replacement failure must not truncate the existing assignment file.
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        if path.read_bytes() != original:
            raise RuntimeError('EMM changed while editing; read it again before retrying.')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def write_emm(emm_path, assignments=None, create_from_pmm=None, *, sections=None, output_path=None):
    if create_from_pmm is not None:
        raise ValueError('Creating an .emm from scratch is not supported; export the current '
                         'assignments in MME or save the project with assignment auto-save on.')
    patches = [EffectSectionPatch(assignments=assignments)] if assignments else []
    patches.extend(EffectSectionPatch.model_validate(p) for p in sections or [])
    if not patches:
        raise ValueError('Provide assignments or at least one section patch.')
    path, original, document, _ = _read(emm_path)
    objects = dict(document.get('Object', []))
    changes, changed_sections = {}, {}
    for patch in patches:
        name = patch.section
        if not _is_effect_section(name) or name != 'Effect' and name not in document:
            raise ValueError(f'Unknown effect section {name!r}. Use an exact name from '
                             'effect_sections; load the effect and export its EMM first.')
        if name in changes:
            raise ValueError(f'Duplicate section {name!r}; merge its changes into one patch.')
        if name != 'Effect':
            owner = dict(document[name]).get('Owner')
            if owner not in objects:
                raise ValueError(f'Effect section {name!r} has no known Owner object.')
        entries, changed, visibility = {}, {}, {}
        for key, value in patch.assignments.items():
            key = _target(key, objects)
            if key in changed:
                raise ValueError(f'Duplicate canonical assignment target: {key}')
            entries[key] = _effect_value(value)
            changed[key] = value
        for key, visible in patch.visibility.items():
            key = _target(key, objects)
            if key in visibility:
                raise ValueError(f'Duplicate canonical visibility target: {key}')
            entries[f'{key}.show'] = 'true' if visible else 'false'
            visibility[key] = visible
        changes[name] = entries
        changed_sections[name] = {'assignments': changed, 'visibility': visibility}
    data = _patch_bytes(original, changes)
    if len(data) > MAX_BYTES:
        raise ValueError('Edited EMM would be too large.')
    destination = _write(path, original, data, output_path)
    return {
        'path': str(destination), 'source_path': str(path),
        'changed': changed_sections.get('Effect', {}).get('assignments', {}),
        'changed_sections': changed_sections, 'bytes': len(data),
        'applied_to_mmd': False, 'note': APPLY_NOTE,
    }
