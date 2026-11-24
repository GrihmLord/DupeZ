"""An export template must not be mistaken for binary/source revision proof."""
import hashlib
import io
import tarfile
from types import SimpleNamespace

import pytest

from scripts import verify_qt_export_metadata as review


ATTRIBUTES = b".tag export-subst\n.gitignore export-ignore\n.gitattributes export-ignore\n"
REVISION = "a" * 40


def checksums():
    return {name: hashlib.sha1(body.replace(b"\n", b"\r\n")).hexdigest()
            for name, body in ((".tag", review.TEMPLATE), (".gitattributes", ATTRIBUTES))}


def test_export_substitution_explains_metadata_without_attesting_binary_origin():
    result = review.explain_export(review.TEMPLATE, ATTRIBUTES,
                                   REVISION.encode() + b"\n", checksums(), REVISION)
    assert result["export_substitution_verified"]
    assert result["root_git_metadata_exclusion_declared"]
    assert result["binary_source_revision_identity_proven"] is False


@pytest.mark.parametrize("changed", ["template", "revision", "tag", "declaration", "checksum"])
def test_evidence_changes_fail_closed(changed):
    template, attributes, tag, revision, sums = review.TEMPLATE, ATTRIBUTES, REVISION.encode() + b"\n", REVISION, checksums()
    if changed == "template":
        template = b"unreviewed\n"
    elif changed == "revision":
        revision = "not-a-commit"
    elif changed == "tag":
        tag = b"b" * 40 + b"\n"
    elif changed == "declaration":
        attributes = attributes.replace(b"export-subst", b"text")
    else:
        sums[".tag"] = "0" * 40
    with pytest.raises(ValueError):
        review.explain_export(template, attributes, tag, sums, revision)


def test_spdx_requires_unique_complete_metadata_records():
    body = "".join(f"FileName: ./\\{name}\nFileChecksum: SHA1: {sha}\n"
                   for name, sha in checksums().items()).replace("./\\", ".\\")
    assert review.metadata_checksums(body.encode()) == checksums()
    with pytest.raises(ValueError, match="Ambiguous"):
        review.metadata_checksums((body + body).encode())
    with pytest.raises(ValueError, match="Incomplete"):
        review.metadata_checksums(b"FileName: ./unrelated\n")


def test_input_pin_rejects_modified_metadata(tmp_path):
    path = tmp_path / "metadata"
    path.write_bytes(b"bad")
    with pytest.raises(ValueError, match="size"):
        review.pinned_bytes(path, 4, review.sha256(b"good"))
    with pytest.raises(ValueError, match="SHA256"):
        review.pinned_bytes(path, 3, review.sha256(b"yes"))


@pytest.mark.parametrize("kind", ["duplicate", "symlink", "oversized", "missing"])
def test_tag_archive_member_is_bounded_regular_and_unique(tmp_path, kind):
    path = tmp_path / "source.tar.xz"
    with tarfile.open(path, "w:xz") as archive:
        if kind != "missing":
            member = tarfile.TarInfo(".tag")
            member.size = 42 if kind == "oversized" else 41
            if kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "elsewhere"
                archive.addfile(member)
            else:
                archive.addfile(member, io.BytesIO(b"a" * member.size))
                if kind == "duplicate":
                    archive.addfile(member, io.BytesIO(b"a" * member.size))
    with pytest.raises(ValueError):
        review.archive_tag(path.read_bytes())


def test_source_replaced_after_verified_snapshot_cannot_change_parsed_tag(tmp_path, monkeypatch):
    candidate_root, metadata_root = tmp_path / "candidate", tmp_path / "metadata"
    source = candidate_root / "inputs/qtbase-everywhere-src-6.11.3.tar.xz"
    spdx = candidate_root / "6.11.3/msvc2022_64/sbom/qtbase-6.11.3.source.spdx"
    source.parent.mkdir(parents=True)
    spdx.parent.mkdir(parents=True)
    metadata_root.mkdir()

    def make_archive(revision):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:xz") as archive:
            member = tarfile.TarInfo(".tag")
            member.size = 41
            archive.addfile(member, io.BytesIO(revision.encode() + b"\n"))
        return stream.getvalue()

    original_source = make_archive(REVISION)
    replacement_source = make_archive("b" * 40)
    source.write_bytes(original_source)
    spdx.write_text("".join(f"FileName: ./{name}\nFileChecksum: SHA1: {sha}\n"
                            for name, sha in checksums().items()), encoding="utf-8")
    pin = {**review.METADATA["qtbase"], "revision": REVISION,
           "source_size": len(original_source), "source_sha256": review.sha256(original_source),
           "spdx_size": spdx.stat().st_size, "spdx_sha256": review.sha256(spdx.read_bytes()),
           "attributes_size": len(ATTRIBUTES), "attributes_sha256": review.sha256(ATTRIBUTES)}
    (metadata_root / pin["git_tag_file"]).write_bytes(review.TEMPLATE)
    (metadata_root / pin["attributes_file"]).write_bytes(ATTRIBUTES)
    monkeypatch.setattr(review, "METADATA", {"qtbase": pin})
    original_reader = review.pinned_bytes

    def replace_after_snapshot(path, size, expected):
        snapshot = original_reader(path, size, expected)
        if path == source:
            source.write_bytes(replacement_source)
        return snapshot

    monkeypatch.setattr(review, "pinned_bytes", replace_after_snapshot)
    result = review.run(SimpleNamespace(candidate_root=candidate_root, metadata_root=metadata_root,
                                      qttools_root=tmp_path))
    assert source.read_bytes() == replacement_source
    assert review.archive_tag(source.read_bytes()) == b"b" * 40 + b"\n"
    assert result["modules"]["qtbase"]["exported_revision"] == REVISION
    assert result["modules"]["qtbase"]["input_pins"]["source_sha256"] == review.sha256(original_source)
