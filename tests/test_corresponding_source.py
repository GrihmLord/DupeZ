"""The source collector never runs/extracts packages or erases known gaps."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import struct
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import corresponding_source as source


def archive(tmp_path, names=("project/README.txt",)):
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as handle:
        for name in names:
            handle.writestr(name, "reviewed source")
    # On Windows ZipInfo normalizes backslashes while *creating* an archive.
    # Inject the hostile raw name into both headers to exercise the reader.
    for name in names:
        if "\\" in name:
            path.write_bytes(path.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    data = path.read_bytes()
    return path, {
        "filename": "source.zip", "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "url": "https://files.pythonhosted.org/packages/aa/source.zip",
    }


@pytest.fixture
def manifest():
    return source.load_manifest(
        source.ROOT / "packaging/source-inputs.json",
        source.ROOT / "packaging/third-party-components.json",
    )


def test_checked_inventory_has_all_33_components_and_honest_gaps(manifest):
    assert len(manifest["components"]) == 33
    components = {item["id"]: item for item in manifest["components"]}
    assert components["iup"]["source_status"] == "unresolved"
    assert components["iup"]["artifacts"] == []
    for name in ("pyqt6-qt6", "pyqt6-webengine-qt6", "windivert"):
        assert components[name]["gaps"]
        assert components[name]["artifacts"]
    assert source.delivery_gaps(manifest)


@pytest.mark.parametrize("url", [
    "http://files.pythonhosted.org/packages/a/source.zip",
    "https://files.pythonhosted.org.evil.invalid/packages/a/source.zip",
    "https://files.pythonhosted.org@evil.invalid/packages/a/source.zip",
    "https://files.pythonhosted.org:443/packages/a/source.zip",
    "https://files.pythonhosted.org/packages/../source.zip",
    "https://files.pythonhosted.org/packages/%2e%2e/source.zip",
    "https://files.pythonhosted.org/packages/source.zip?token=x",
    "https://files.pythonhosted.org/packages/source.zip#fragment",
    "https://files.pythonhosted.org\\@evil.invalid/packages/source.zip",
    "https://files.pythonhosted.org./packages/source.zip",
    "https://FILES.PYTHONHOSTED.ORG/packages/source.zip",
    " https://files.pythonhosted.org/packages/source.zip",
    "https://files.pythonhosted.org/packages/\nsource.zip",
    "https://127.0.0.1/packages/source.zip",
    "file:///tmp/source.zip",
    "https://codeload.github.com/example/project/zip/main",
    "https://codeload.github.com/example/project/zip/v1.0.0",
    "https://download.qt.io/unreviewed/source.zip",
])
def test_download_origins_are_strict(url):
    with pytest.raises(source.SourceInputError):
        source.validate_download_url(url)


@pytest.mark.parametrize("mutator", [
    lambda m: m.update(schema="unknown"),
    lambda m: m.update(extra="unknown"),
    lambda m: m["components"].pop(),
    lambda m: m["components"].append(copy.deepcopy(m["components"][0])),
    lambda m: m["components"][0].update(version="999.0"),
    lambda m: m["components"][0].update(source_status="complete"),
    lambda m: m["components"][0]["artifacts"][0].update(filename="../escape.zip"),
    lambda m: m["components"][0]["artifacts"][0].update(filename="NUL.zip"),
    lambda m: m["components"][0]["artifacts"][0].update(size=True),
    lambda m: m["components"][0]["artifacts"][0].update(size=0),
    lambda m: m["components"][0]["artifacts"][0].update(size=source.MAX_ARTIFACT_BYTES + 1),
    lambda m: m["components"][0]["artifacts"][0].update(sha256="g" * 64),
    lambda m: m["components"][0].update(evidence_urls=[]),
])
def test_manifest_rejects_drift_and_unverified_inputs(tmp_path, manifest, mutator):
    mutator(manifest)
    path = tmp_path / "manifest.json"
    path.write_bytes(source.canonical_json(manifest))
    with pytest.raises(source.SourceInputError):
        source.load_manifest(path, source.ROOT / "packaging/third-party-components.json")


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(source.SourceInputError, match="duplicate"):
        source._read_json(path)


@pytest.mark.parametrize("name", [
    "../escape", "/escape", "C:/escape", "project/../../escape",
    "project/CON.txt", "project/file:stream", "project/dir\\file",
    "project/./file", "project//file", "project/trailing.", "project/trailing ",
])
def test_unsafe_archive_members_rejected(tmp_path, name):
    path, artifact = archive(tmp_path, [name])
    with pytest.raises(source.SourceInputError):
        source.verify_artifact(path, artifact)


def test_hash_size_and_archive_checks(tmp_path):
    path, artifact = archive(tmp_path)
    assert source.verify_artifact(path, artifact)["members"] == 1
    with pytest.raises(source.SourceInputError, match="hash/size"):
        source.verify_artifact(path, {**artifact, "sha256": "0" * 64})
    with pytest.raises(source.SourceInputError, match="exceeds pinned size"):
        source.verify_artifact(path, {**artifact, "size": 1})
    with pytest.raises(source.SourceInputError, match="hash/size"):
        source.verify_artifact(path, {**artifact, "size": artifact["size"] + 1})


def test_duplicate_members_and_expansion_limits(tmp_path, monkeypatch):
    with pytest.warns(UserWarning):
        path, artifact = archive(tmp_path, ["project/file", "project/file"])
    with pytest.raises(source.SourceInputError, match="duplicate"):
        source.verify_artifact(path, artifact)
    path, artifact = archive(tmp_path)
    monkeypatch.setattr(source, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(source.SourceInputError, match="inspection limits"):
        source.verify_artifact(path, artifact)


def tar_archive(tmp_path, target, *, hard=False, include_target=True):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as handle:
        if include_target:
            regular = tarfile.TarInfo("project/doc/readme")
            regular.size = 1
            handle.addfile(regular, io.BytesIO(b"x"))
        link = tarfile.TarInfo("project/news/readme")
        link.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
        link.linkname = target
        handle.addfile(link)
    return path


def test_internal_source_links_are_preserved_without_extracting(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("source archives must never be extracted")
    monkeypatch.setattr(tarfile.TarFile, "extract", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extractall", forbidden)
    path = tar_archive(tmp_path, "../doc/readme")
    assert source.inspect_archive(path, path.name)["internal_links"] == 1
    path = tar_archive(tmp_path, "project/doc/readme", hard=True)
    assert source.inspect_archive(path, path.name)["internal_links"] == 1


@pytest.mark.parametrize("target", ["../../../outside", "/outside", "C:/outside", "..\\outside", "../missing", "readme"])
def test_unsafe_dangling_or_cyclic_links_rejected(tmp_path, target):
    path = tar_archive(tmp_path, target)
    with pytest.raises(source.SourceInputError):
        source.inspect_archive(path, path.name)


def test_linked_ancestor_cannot_change_internal_target_resolution(tmp_path):
    path = tmp_path / "ancestor.tar.gz"
    with tarfile.open(path, "w:gz") as handle:
        directory = tarfile.TarInfo("project")
        directory.type = tarfile.DIRTYPE
        handle.addfile(directory)
        regular = tarfile.TarInfo("project/outside")
        regular.size = 1
        handle.addfile(regular, io.BytesIO(b"x"))
        for name, target in (("project/a", "."), ("project/a/b", "../outside")):
            link = tarfile.TarInfo(name)
            link.type = tarfile.SYMTYPE
            link.linkname = target
            handle.addfile(link)
    with pytest.raises(source.SourceInputError, match="linked ancestor"):
        source.inspect_archive(path, path.name)


def test_pax_metadata_is_bounded_before_tarfile_parses_it(tmp_path, monkeypatch):
    path = tmp_path / "pax.tar.gz"
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as handle:
        member = tarfile.TarInfo("project/readme")
        member.size = 1
        member.pax_headers = {"comment": "x" * 4096}
        handle.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(source, "MAX_MEMBER_BYTES", 64)
    monkeypatch.setattr(source, "MAX_EXPANDED_BYTES", 64)
    with pytest.raises(source.SourceInputError, match="TAR parser input"):
        source.inspect_archive(path, path.name)


def test_metadata_aggregate_cannot_hide_behind_small_yielded_files(tmp_path, monkeypatch):
    path = tmp_path / "aggregate.tar.gz"
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as handle:
        for index in range(4):
            member = tarfile.TarInfo(f"project/file-{index}")
            member.size = 1
            member.pax_headers = {"comment": "x" * 20}
            handle.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(source, "MAX_METADATA_BYTES", 64)
    with pytest.raises(source.SourceInputError, match="aggregate"):
        source.inspect_archive(path, path.name)


def test_zip_central_directory_is_bounded_before_allocation(tmp_path, monkeypatch):
    path = tmp_path / "directory.zip"
    path.write_bytes(struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, source.MAX_ZIP_DIRECTORY_BYTES + 1, 0, 0))
    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **kw: pytest.fail("unbounded central directory parsed"))
    with pytest.raises(source.SourceInputError, match="central directory"):
        source.inspect_archive(path, path.name)


def test_zip_internal_link_is_bounded_and_validated(tmp_path):
    path = tmp_path / "links.zip"
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("project/readme", "x")
        info = zipfile.ZipInfo("project/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        handle.writestr(info, "readme")
    assert source.inspect_archive(path, path.name)["internal_links"] == 1


def test_budget_prevents_download_and_does_not_create_cache(tmp_path, monkeypatch):
    _, artifact = archive(tmp_path)
    monkeypatch.setattr(source, "_download_to", lambda *a: pytest.fail("budget bypass"))
    cache = tmp_path / "cache"
    with pytest.raises(source.SourceInputError, match="budget"):
        source.collect_artifact(cache, artifact, max_bytes=1)
    assert not cache.exists()


def test_collector_reuses_verified_bytes_but_rejects_corruption(tmp_path, monkeypatch):
    original, artifact = archive(tmp_path)
    data = original.read_bytes()
    cache = tmp_path / "cache"
    monkeypatch.setattr(source, "_download_to", lambda handle, item: handle.write(data))
    assert source.collect_artifact(cache, artifact, max_bytes=len(data))["members"] == 1
    monkeypatch.setattr(source, "_download_to", lambda *a: pytest.fail("redownload"))
    source.collect_artifact(cache, artifact, max_bytes=len(data))
    (cache / artifact["filename"]).write_bytes(b"corrupt")
    with pytest.raises(source.SourceInputError):
        source.collect_artifact(cache, artifact, max_bytes=len(data))


def test_failed_download_has_no_published_artifact(tmp_path, monkeypatch):
    _, artifact = archive(tmp_path)
    def fail(handle, item):
        handle.write(b"partial")
        raise source.SourceInputError("interrupted")
    monkeypatch.setattr(source, "_download_to", fail)
    cache = tmp_path / "cache"
    with pytest.raises(source.SourceInputError):
        source.collect_artifact(cache, artifact, max_bytes=artifact["size"])
    assert list(cache.iterdir()) == []


def test_redirect_handler_always_refuses():
    with pytest.raises(source.SourceInputError, match="redirect"):
        source._RejectRedirect().redirect_request(None, None, 302, "Found", {}, "https://files.pythonhosted.org/packages/elsewhere.zip")


@pytest.mark.parametrize("change", [
    {"status": 302}, {"url": "https://evil.invalid/source.zip"},
    {"headers": {"Content-Encoding": "gzip"}},
    {"headers": {"Content-Length": "garbage"}},
    {"headers": {"Content-Length": "999"}}, {"data": b"short"}, {"data": b"too-long-contents"},
])
def test_download_response_checks(tmp_path, monkeypatch, change):
    values = {"status": 200, "url": "https://files.pythonhosted.org/packages/a.zip", "headers": {}, "data": b"12345678"}
    values.update(change)
    class Response(io.BytesIO):
        status = values["status"]
        headers = values["headers"]
        def geturl(self):
            return values["url"]
    monkeypatch.setattr(source.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=lambda *a, **k: Response(values["data"])))
    with pytest.raises(source.SourceInputError):
        source._download_to(io.BytesIO(), {"url": "https://files.pythonhosted.org/packages/a.zip", "size": 8})


def test_deterministic_bundles_include_explicit_gaps(tmp_path, manifest):
    path, artifact = archive(tmp_path)
    selected = [{"id": "example", "version": "1", "artifacts": [artifact]}]
    inspections = {artifact["filename"]: source.verify_artifact(path, artifact)}
    receipt = source.make_receipt(manifest, selected, inspections)
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    source.create_bundle(first, tmp_path, manifest, receipt)
    source.create_bundle(second, tmp_path, manifest, receipt)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as handle:
        stored = json.loads(handle.read("source-receipt.json"))
        assert stored["delivery_gaps"]
        assert stored["uncollected_components"]
        assert "not a release" in stored["claim"]
    with pytest.raises(source.SourceInputError, match="already exists"):
        source.create_bundle(first, tmp_path, manifest, receipt)


@pytest.mark.parametrize("mutation", [None, "content", "manifest", "gaps", "extra"])
def test_bundle_verifier_rehashes_against_reviewed_pins(tmp_path, manifest, mutation):
    path, artifact = archive(tmp_path)
    component = manifest["components"][0]
    component["artifacts"] = [artifact]
    selected = [component]
    receipt = source.make_receipt(manifest, selected, {artifact["filename"]: source.verify_artifact(path, artifact)})
    bundle_path = tmp_path / "bundle.zip"
    source.create_bundle(bundle_path, tmp_path, manifest, receipt)
    assert source.verify_bundle(bundle_path, manifest) == receipt
    if mutation is None:
        return
    with zipfile.ZipFile(bundle_path) as handle:
        contents = [(member, handle.read(member)) for member in handle.infolist()]
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(changed, "w") as handle:
        for member, content in contents:
            if mutation == "content" and member.filename.startswith("archives/"):
                content = b"!" + content[1:]
            elif mutation == "manifest" and member.filename == "source-inputs.json":
                content += b" "
            elif mutation == "gaps" and member.filename == "source-receipt.json":
                body = json.loads(content)
                body["delivery_gaps"] = []
                content = source.canonical_json(body)
            handle.writestr(member, content)
        if mutation == "extra":
            handle.writestr("unexpected.txt", "extra")
    with pytest.raises(source.SourceInputError):
        source.verify_bundle(changed, manifest)


def test_bundle_failure_cannot_publish_partial_zip(tmp_path, manifest, monkeypatch):
    target = tmp_path / "failed.zip"
    def fail(path, *args):
        path.write_bytes(b"partial zip")
        raise source.SourceInputError("copy mismatch")
    monkeypatch.setattr(source, "_write_bundle", fail)
    with pytest.raises(source.SourceInputError):
        source.create_bundle(target, tmp_path, manifest, {})
    assert not target.exists()
    assert not list(tmp_path.glob(".source-bundle-*"))


def test_receipt_is_canonical_and_never_overwrites(tmp_path):
    path = tmp_path / "receipt.json"
    source.emit_receipt({"z": 1, "a": 2}, path)
    assert path.read_bytes() == source.canonical_json({"a": 2, "z": 1})
    with pytest.raises(source.SourceInputError, match="already exists"):
        source.emit_receipt({"altered": True}, path)
    assert path.read_bytes() == source.canonical_json({"a": 2, "z": 1})
    assert not list(tmp_path.glob(".source-receipt-*"))


def test_reparse_paths_rejected_before_resolution(tmp_path, monkeypatch):
    original = Path.lstat
    def fake(path):
        metadata = original(path)
        if path == tmp_path:
            return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=0x400)
        return metadata
    monkeypatch.setattr(Path, "lstat", fake)
    with pytest.raises(source.SourceInputError, match="reparse"):
        source.checked_path(tmp_path / "new.zip")


@pytest.mark.parametrize("args", [
    ["plan", "--require-delivery-ready"],
    ["collect"], ["verify"], ["plan", "--component", "unknown"],
    ["plan", "--component", "pyqt6", "--component", "pyqt6"],
    ["plan", "--max-artifact-bytes", "0"],
    ["plan", "--bundle", "must-not-exist.zip"],
    ["verify-bundle"],
])
def test_cli_cannot_silently_claim_completeness_or_select_unresolved(args):
    assert source.main(args) == 1
