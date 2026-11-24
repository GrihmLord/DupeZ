"""Historical source samples must not become a complete native-build claim."""
import io
import json
import stat
import sys
import zipfile

import pytest

from scripts import verify_iup_source_revision as review


def archive_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def samples():
    return {name: ("test source " + name + "\n").encode() for name in review.SELECTED}


def xml_records():
    dated = b'<S:dated-rev-report xmlns:S="svn:" xmlns:D="DAV:"><D:version-name>5892</D:version-name></S:dated-rev-report>'
    rows = []
    for revision in (5892, 5891, 5890, 5889):
        extra = ('<S:date>' + review.REVISION_DATE + '</S:date><S:modified-path>/trunk/iup/html/en/history3.html</S:modified-path>') if revision == 5892 else ''
        rows.append(f'<S:log-item><D:version-name>{revision}</D:version-name>{extra}</S:log-item>')
    log = ('<S:log-report xmlns:S="svn:" xmlns:D="DAV:">' + ''.join(rows) + '</S:log-report>').encode()
    return dated, log


def test_selected_bytes_match_without_normalization_and_ignore_unselected_content():
    selected = samples()
    data = archive_bytes([*(('iup/' + name, body) for name, body in selected.items()), ('iup/unreviewed.c', b'not compared')])
    result = review.compare_selected(data, selected)
    assert len(result) == 7
    assert all(row['exact_match'] is True and row['normalization'] == 'none' for row in result)
    assert all('/!svn/rvr/5892/trunk/iup/' in row['svn_url'] for row in result)


@pytest.mark.parametrize('change', ['missing', 'changed', 'crlf', 'duplicate-case', 'traversal', 'symlink', 'bzip2', 'different-scope'])
def test_source_archive_or_scope_changes_fail(change):
    selected = samples()
    entries = [('iup/' + name, body) for name, body in selected.items()]
    if change == 'missing':
        entries.pop()
    elif change == 'changed':
        name, data = entries[0]
        entries[0] = name, b'X' + data[1:]
    elif change == 'crlf':
        name, data = entries[0]
        entries[0] = name, data.replace(b'\n', b'\r\n')
    elif change == 'duplicate-case':
        entries.append((entries[0][0].upper(), entries[0][1]))
    elif change == 'traversal':
        entries.append(('iup/../outside', b'bad'))
    elif change in {'symlink', 'bzip2'}:
        name, data = entries[0]
        member = zipfile.ZipInfo(name)
        if change == 'symlink':
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
        else:
            member.compress_type = zipfile.ZIP_BZIP2
        entries[0] = member, data
    elif change == 'different-scope':
        selected.pop(next(iter(selected)))
    with pytest.raises(ValueError):
        review.compare_selected(archive_bytes(entries), selected)


@pytest.mark.parametrize('change', ['revision', 'duplicate', 'date', 'changed-path', 'doctype', 'wrong-root'])
def test_revision_metadata_rejects_unreviewed_scope(change):
    dated, log = xml_records()
    if change == 'revision':
        dated = dated.replace(b'5892', b'5893')
    elif change == 'duplicate':
        dated = dated.replace(b'</D:version-name>', b'</D:version-name><D:version-name>5892</D:version-name>')
    elif change == 'date':
        log = log.replace(review.REVISION_DATE.encode(), b'2023-10-13T12:00:00Z')
    elif change == 'changed-path':
        log = log.replace(b'html/en/history3.html', b'src/iup.c')
    elif change == 'doctype':
        dated = b'<!DOCTYPE foo>' + dated
    else:
        log = log.replace(b'log-report', b'other-report')
    with pytest.raises(ValueError):
        review.revision_metadata(dated, log)


@pytest.mark.parametrize('replacement', [b'changed', b'overlong replacement', b''])
def test_pinned_snapshot_rejects_wrong_bytes_and_sizes(tmp_path, replacement):
    path = tmp_path / 'source'
    path.write_bytes(replacement)
    with pytest.raises(ValueError, match='Pinned input differs'):
        review.pinned_bytes(path, (7, review.digest(b'correct')))


def fixture_inputs(tmp_path, monkeypatch):
    root = tmp_path / 'metadata'
    root.mkdir()
    selected = samples()
    source = tmp_path / 'source.zip'
    body = archive_bytes([('iup/' + name, data) for name, data in selected.items()])
    source.write_bytes(body)
    monkeypatch.setattr(review, 'SOURCE_PIN', (len(body), review.digest(body)))
    monkeypatch.setattr(review, 'SELECTED', {name: (len(data), review.digest(data)) for name, data in selected.items()})
    for name, data in selected.items():
        path = root / 'files' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    records = dict(zip(('dated-revision.xml', 'revision-log.xml'), xml_records()))
    monkeypatch.setattr(review, 'METADATA', {name: (len(data), review.digest(data)) for name, data in records.items()})
    for name, data in records.items():
        (root / name).write_bytes(data)
    return source, root


def test_receipt_cannot_assert_full_source_rebuild_or_release(tmp_path, monkeypatch):
    source, root = fixture_inputs(tmp_path, monkeypatch)
    result = review.run(source, root)
    assert result['selected_member_count'] == 7
    for key in ('whole_archive_revision_identity_proven', 'dll_build_source_identity_proven',
                'native_rebuild_performed', 'native_execution_performed', 'release_approval'):
        assert result[key] is False
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize('target', ['source', 'metadata', 'selected'])
def test_input_replacement_during_verification_is_rejected(tmp_path, monkeypatch, target):
    source, root = fixture_inputs(tmp_path, monkeypatch)
    changed = {'source': source, 'metadata': root / 'dated-revision.xml', 'selected': root / 'files/include/iup.h'}[target]
    compare = review.compare_selected

    def replace_after_snapshot(data, selected):
        changed.write_bytes(b'replacement')
        return compare(data, selected)

    monkeypatch.setattr(review, 'compare_selected', replace_after_snapshot)
    with pytest.raises(ValueError, match='Pinned input differs'):
        review.run(source, root)


def test_cli_never_overwrites_existing_receipt(tmp_path, monkeypatch):
    output = tmp_path / 'receipt.json'
    output.write_bytes(b'original')
    monkeypatch.setattr(sys, 'argv', ['verify', '--source', 'unused', '--metadata-root', 'unused', '--output', str(output)])
    with pytest.raises(ValueError, match='Refusing to replace'):
        review.main()
    assert output.read_bytes() == b'original'
