"""Reject unsafe native-build inputs before any compiler or application launch."""
import hashlib
import io
import zipfile

import pytest

from scripts.native_rebuild import build_clumsy as recipe


def container(names, *, mode=0o100644, body=b'source bytes'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in names:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, body)
    return buffer.getvalue()


def test_archive_bytes_are_captured_without_extraction(tmp_path):
    raw = container(['upstream/src/main.c', 'upstream/include/iup.h'])
    assert recipe.members(raw) == {'upstream/src/main.c': b'source bytes', 'upstream/include/iup.h': b'source bytes'}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('name', [
    '../escape', '/absolute', 'C:/root', 'file:stream', 'a/%2e%2e/b',
    'NUL', 'a/CON.txt', 'a/../b', 'a//b', 'a/trailing.', 'a/trailing ', 'a/\x01b',
])
def test_unsafe_archive_member_rejected(name):
    with pytest.raises(ValueError, match='Unsafe'):
        recipe.members(container([name]))


def test_windows_case_aliases_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        recipe.members(container(['include/IUP.h', 'include/iup.h']))


@pytest.mark.parametrize('replacement', [b'a\\b', b'a\x00b'])
def test_raw_archive_name_cannot_be_normalized_or_truncated(replacement):
    # ZipInfo normalizes backslashes when writing on Windows. Change both raw
    # directory/header names to exercise the input parser itself.
    raw = container(['a/b']).replace(b'a/b', replacement)
    with pytest.raises(ValueError, match='Unsafe'):
        recipe.members(raw)


@pytest.mark.parametrize('mode', [0o120777, 0o060600, 0o020600])
def test_nonregular_archive_member_rejected(mode):
    with pytest.raises(ValueError, match='member type'):
        recipe.members(container(['source/file'], mode=mode))


def test_missing_archive_pin_prevents_any_compiler_call(tmp_path, monkeypatch):
    monkeypatch.setattr(recipe, 'ROOT', tmp_path)
    monkeypatch.setattr(recipe.common, 'ROOT', tmp_path)
    source = tmp_path / 'source.zip'
    source.write_bytes(b'unreviewed content')
    monkeypatch.setitem(recipe.PINS, 'fixture', ('source.zip', 18, '0' * 64))
    with pytest.raises(ValueError, match='Archive pin differs'):
        recipe.captured('fixture')


def test_staged_pin_describes_verified_bytes_and_writes_exclusively(tmp_path, monkeypatch):
    monkeypatch.setattr(recipe, 'ROOT', tmp_path)
    monkeypatch.setattr(recipe.common, 'ROOT', tmp_path)
    target = tmp_path / 'source/input.h'
    raw = b'verified header'
    expected = recipe.write(target, raw)
    assert expected == {'path': 'source/input.h', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    with pytest.raises(FileExistsError):
        recipe.write(target, b'changed header')
    assert target.read_bytes() == raw
    target.write_bytes(b'changed header')
    assert recipe.common.pin(target) != expected


def test_captured_archive_uses_independent_size_and_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(recipe, 'ROOT', tmp_path)
    monkeypatch.setattr(recipe.common, 'ROOT', tmp_path)
    raw = container(['src/main.c'])
    (tmp_path / 'source.zip').write_bytes(raw)
    monkeypatch.setitem(recipe.PINS, 'fixture', ('source.zip', len(raw), hashlib.sha256(raw).hexdigest()))
    assert recipe.captured('fixture') == raw
    monkeypatch.setitem(recipe.PINS, 'fixture', ('source.zip', len(raw) + 1, hashlib.sha256(raw).hexdigest()))
    with pytest.raises(ValueError, match='Archive pin differs'):
        recipe.captured('fixture')
