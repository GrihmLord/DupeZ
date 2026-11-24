"""Compile pinned upstream Clumsy source; never execute the resulting program."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/clumsy-native-rebuild-20261124'
sys.path.insert(0, str(ROOT))
from scripts.native_rebuild import common

PINS = {
    'clumsy': ('build/source-delivery-20261024/archives/clumsy-0.3.4-bc87e73066168520d76122c9165e99ea703b166c.zip', 18533657, 'b641300d1f9c6b3be1699ea9f9222052f212b116f2c72ad18ad8f687f63337bb'),
    'iup': ('build/native-source-mapping-20261025/archives/iup-3.30_Win64_dll16_lib.zip', 4323648, '10b7ea192c3fb6ca7493472ddbbffcbb4888b41053964e45802e171aa6f2e37c'),
    'windivert': ('build/native-source-mapping-20261025/archives/WinDivert-2.2.0-A.zip', 394610, '2a7630aac0914746fbc565ac862fa096e3e54233883ac52d17c83107496b7a7f'),
}
SOURCES = tuple(name + '.c' for name in (
    'bandwidth', 'disconnect', 'divert', 'drop', 'duplicate', 'elevate', 'ini', 'lag',
    'main', 'ood', 'packet', 'reset', 'tamper', 'throttle', 'utils'))


def captured(key):
    relative, size, digest = PINS[key]
    common.require(type(size) is int and 0 < size <= 32 * 1024 * 1024, 'Unreviewed archive size')
    path = common.ordinary(ROOT / relative)
    common.require(path.stat().st_size == size, 'Archive pin differs')
    with path.open('rb') as stream:
        raw = stream.read(size + 1)
    common.require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest, 'Archive pin differs')
    return raw


def members(raw):
    result, seen, total = {}, set(), 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        common.require(0 < len(archive.infolist()) < 20000, 'Archive count differs')
        for member in archive.infolist():
            name = member.filename
            parts = name.rstrip('/').split('/')
            common.require(member.orig_filename == name and len(name) <= 512
                           and '\\' not in name and ':' not in name and '%' not in name,
                           'Unsafe member name')
            common.require(all(part not in {'', '.', '..'} and not part.endswith(('.', ' '))
                               and not re.fullmatch(r'(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', part, re.I)
                               and not any(ord(c) < 32 for c in part) for part in parts), 'Unsafe member path')
            key = name.rstrip('/').casefold()
            common.require(key not in seen, 'Duplicate archive name')
            seen.add(key)
            kind = stat.S_IFMT(member.external_attr >> 16)
            common.require(kind in ({0, stat.S_IFDIR} if member.is_dir() else {0, stat.S_IFREG})
                           and not member.flag_bits & 1 and not member.external_attr & 0x400, 'Archive member type')
            total += member.file_size
            common.require(member.file_size <= 32 * 1024 * 1024 and total <= 128 * 1024 * 1024, 'Archive bound')
            if not member.is_dir():
                data = archive.read(member)
                common.require(len(data) == member.file_size, 'Truncated archive')
                result[name] = data
    return result


def write(path, raw):
    common.ordinary(path, missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': path.relative_to(ROOT).as_posix(), 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    common.require(re.fullmatch(r'[a-z0-9-]{1,40}', args.run), 'Invalid run name')
    output = common.ordinary(BASE / args.run, missing=True)
    output.mkdir(parents=True)
    source = output / 'source'
    objects = output / 'objects'
    objects.mkdir()
    commands = []
    raw_clumsy, raw_iup, raw_divert = (captured(name) for name in PINS)
    clumsy = members(raw_clumsy)
    iup = members(raw_iup)
    divert = members(raw_divert)
    prefix = 'clumsy-bc87e73066168520d76122c9165e99ea703b166c/'
    selected = {name[len(prefix):]: data for name, data in clumsy.items()
                if name.startswith(prefix) and (name[len(prefix):].startswith(('src/', 'etc/'))
                                               or name[len(prefix):] in {'genie.lua', 'build.zig', 'LICENSE'})}
    common.require(set(name.removeprefix('src/') for name in selected if name.startswith('src/') and name.endswith('.c'))
                   == set(SOURCES), 'Source selection differs')
    common.require(hashlib.sha256(selected['genie.lua']).hexdigest()
                   == '6f8ba730bcf1e42eeddea05397f6720464c095a8372685527f6c863642e44fd5', 'GENie recipe differs')
    staged = []
    for name, data in selected.items():
        staged.append(write(source / name, data))
    for name, data in iup.items():
        if name.startswith('include/') and name.endswith('.h'):
            staged.append(write(source / 'iup' / name, data))
    staged.append(write(source / 'iup/iup.lib', iup['iup.lib']))
    for name in ('include/windivert.h', 'x64/WinDivert.lib', 'LICENSE'):
        staged.append(write(source / 'windivert' / name, divert['WinDivert-2.2.0-A/' + name]))
    extra = [common.pin(Path(__file__)), common.pin(Path(common.__file__)), *staged]
    environment = common.closed_environment(output / 'private')
    # Upstream common.h contains the tentative definition `int NetworkType;`.
    # Explicit common-symbol mode preserves its legacy C semantics without
    # patching source or allowing arbitrary duplicate linker definitions.
    flags = ['--no-default-config', '-std=gnu99', '-fcommon', '-O2', '-DNDEBUG', '-DX64', '-D_CRT_SECURE_NO_WARNINGS',
             '-fno-ident', '-fstack-protector-strong', '-ffile-prefix-map=' + str(source) + '=clumsy-source',
             '-I', str(source / 'iup/include'), '-I', str(source / 'windivert/include'),
             '-Wno-missing-braces', '-Wno-missing-field-initializers']
    failure = None
    with common.held_inputs(extra) as held, ExitStack() as object_locks:
        inventory_pin = next(row for row in held if row['path'] == common.INVENTORY.relative_to(ROOT).as_posix())
        version = common.run_tool('x86_64-w64-mingw32-clang.exe', ['--no-default-config', '--version'],
                                  cwd=output, env=environment, log=output / 'compiler-version.log')
        commands.append(version)
        for name in SOURCES:
            command = common.run_tool('x86_64-w64-mingw32-clang.exe',
                                      [*flags, '-c', str(source / 'src' / name), '-o', str(objects / (name + '.o'))],
                                      cwd=source, env=environment, log=output / (name + '.log'))
            commands.append(command)
            if command['exit_code']:
                failure = (failure + ', ' if failure else '') + name
        if not failure:
            command = common.run_tool('x86_64-w64-mingw32-windres.exe',
                                      ['-DX64', '-DNDEBUG', '-I', str(source / 'etc'), '-O', 'coff',
                                       '-i', str(source / 'etc/clumsy.rc'), '-o', str(objects / 'clumsy.res.o')],
                                      cwd=source / 'etc', env=environment, log=output / 'resource.log')
            commands.append(command)
            if command['exit_code']:
                failure = 'resource'
        if not failure:
            object_pins = [common.pin(path) for path in objects.iterdir()]
            for row in object_pins:
                object_locks.enter_context(common.held_file(row))
            command = common.run_tool('x86_64-w64-mingw32-clang.exe',
                                      ['--no-default-config', *[str(objects / (name + '.o')) for name in SOURCES],
                                       str(objects / 'clumsy.res.o'), str(source / 'iup/iup.lib'),
                                       str(source / 'windivert/x64/WinDivert.lib'),
                                       '-lcomctl32', '-lwinmm', '-lws2_32', '-lkernel32', '-lgdi32', '-lcomdlg32',
                                       '-luuid', '-lole32', '-lshell32', '-ladvapi32', '-fstack-protector-strong',
                                       '-rtlib=compiler-rt', '-unwindlib=libunwind', '-stdlib=libc++', '-fuse-ld=lld',
                                       '-mwindows', '-Wl,--no-insert-timestamp,--dynamicbase,--nxcompat,--high-entropy-va',
                                       '-o', str(output / 'clumsy-rebuilt.exe')],
                                      cwd=source, env=environment, log=output / 'link.log')
            commands.append(command)
            if command['exit_code']:
                failure = 'link'
        if not failure:
            binary_pin = common.pin(output / 'clumsy-rebuilt.exe')
            object_locks.enter_context(common.held_file(binary_pin))
            command = common.run_tool('llvm-readobj.exe',
                                      ['--file-headers', '--coff-imports', str(output / 'clumsy-rebuilt.exe')],
                                      cwd=output, env=environment, log=output / 'pe-inspection.log')
            commands.append(command)
            if command['exit_code']:
                failure = 'data-only PE inspection'
    receipt = {'schema': 'dupez.clumsy-native-compilation.v1', 'observed_on': '2026-11-24',
               'upstream_commit': 'bc87e73066168520d76122c9165e99ea703b166c', 'run': args.run,
               'source_modified': False, 'source_files_attempted': sum('-c' in row['command'] for row in commands),
               'source_files_compiled': sum('-c' in row['command'] and row['exit_code'] == 0 for row in commands),
               'input_archives': [{'path': p, 'size': s, 'sha256': h} for p, s, h in PINS.values()],
               'toolchain_inventory': inventory_pin, 'held_input_count': len(held),
               'native_guard_dependencies': [row for row in held if row['path'].startswith('scripts/native_rebuild/')
                                             and row['path'].endswith('.py')],
               'source_and_recipe_inputs': extra, 'commands': commands, 'failure': failure,
               'binary': binary_pin if not failure else None,
               'linked_objects': object_pins if not failure else [],
               'child_environment_policy': {'inherited_credentials': False, 'system_and_private_toolchain_path_only': True,
                                            'direct_clang_default_configs_disabled': True,
                                            'requested_link_runtime_flags': ['compiler-rt', 'libunwind', 'libc++', 'lld'],
                                            'pure_c_note': 'Clang ignores the libc++ selection for pure C; inspect PE imports for actual DLL dependencies.'},
               'legacy_c_compatibility': '-fcommon coalesces upstream common.h NetworkType tentative definitions; no source patch.',
               'native_application_executed': False, 'compat_runtime_tested': False, 'release_approval': False,
               'scope': 'Compile-only engineering proof of pinned upstream source using private LLVM-MinGW; official IUP/WinDivert import libraries. No application/driver activation or canonical binary replacement.',
               'gaps': ['Not a byte-identical reconstruction of the shipped executable.',
                        'Vendored source contains prior changes and is not the source compiled by this proof.',
                        'Full dynamic compatibility and native application runtime remain untested.']}
    write(output / 'receipt.json', (json.dumps(receipt, indent=2) + '\n').encode())
    print(json.dumps({'failure': failure, 'binary': receipt['binary']}))
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
