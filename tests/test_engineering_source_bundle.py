"""Engineering source delivery binds exact bytes while keeping unresolved gaps."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest

from scripts import corresponding_source as source
from scripts import engineering_source_bundle as review


def pin(data):
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def receipt_for(data=b"retained source"):
    return {"schema": review.SCHEMA, "files": [{"path": "archives/source.tar.gz", **pin(data)}],
            **{key: False for key in ("complete_corresponding_source", "native_rebuild_proven", "release_approved",
                                      "distribution_approved", "compat_runtime_tested", "public_delivery_proven")}}


@pytest.fixture
def read_lock(monkeypatch):
    if sys.platform != "win32":
        monkeypatch.setattr(review, "lock", lambda stack, path, expected=None: review.fingerprint(path))


def test_bundle_is_deterministic_and_independently_verified(tmp_path, read_lock):
    path = tmp_path / "source.tar.gz"
    body = b"retained source"
    path.write_bytes(body)
    expected = receipt_for(body)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    for bundle in (a, b):
        review.write_bundle(bundle, {"archives/source.tar.gz": (path, pin(body))}, {}, expected)
        assert review.verify_bundle(bundle, expected)["all_file_bytes_verified"] is True
    assert a.read_bytes() == b.read_bytes()
    before = a.read_bytes()
    with pytest.raises(source.SourceInputError, match="already exists"):
        review.write_bundle(a, {}, {}, expected)
    assert a.read_bytes() == before


def test_changed_input_cannot_publish(tmp_path):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(b"modified source")
    bundle = tmp_path / "out.zip"
    with pytest.raises(source.SourceInputError, match="changed|grew"):
        review.write_bundle(bundle, {"archives/source.tar.gz": (path, pin(b"retained source"))}, {}, receipt_for())
    assert not bundle.exists()
    assert not list(tmp_path.glob(".engineering-source-*"))


def test_verified_pin_cannot_be_replaced_after_lock_exit(tmp_path, monkeypatch):
    body = b"retained source"
    source_path, bundle = tmp_path / "source", tmp_path / "bundle.zip"
    source_path.write_bytes(body)
    receipt = receipt_for(body)
    review.write_bundle(bundle, {"archives/source.tar.gz": (source_path, pin(body))}, {}, receipt)
    verified_pin = review.fingerprint(bundle)

    def replacing_lock(stack, path, expected=None):
        observed = review.fingerprint(path)
        stack.callback(path.write_bytes, b"unverified replacement after lock release")
        return observed

    monkeypatch.setattr(review, "lock", replacing_lock)
    result = review.verify_bundle(bundle, receipt)
    assert result["bundle"] == verified_pin
    assert result["bundle"] != review.fingerprint(bundle)


def test_case_aliases_are_rejected_in_writer_and_expected_receipt(tmp_path):
    files = {"archives/A.tar.gz": (tmp_path / "source", pin(b"x")), "archives/a.tar.gz": (tmp_path / "source", pin(b"x"))}
    with pytest.raises(source.SourceInputError, match="Case-aliased"):
        review.write_bundle(tmp_path / "out.zip", files, {}, receipt_for())
    expected = receipt_for()
    expected["files"] = [{"path": name, **pin(b"x")} for name in files]
    with pytest.raises(source.SourceInputError, match="duplicate"):
        review.verify_bundle(tmp_path / "absent.zip", expected)


def test_git_transport_overrides_are_validated_and_never_forwarded(monkeypatch):
    monkeypatch.setattr(review.runtime, "_git_environment", lambda: {"SystemRoot": "trusted"})
    injected = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
                "GIT_CONFIG_KEY_1": "http.extraHeader", "GIT_CONFIG_VALUE_1": "private fixture"}
    assert review.local_git_environment(injected) == {"SystemRoot": "trusted"}
    for changed in ({**injected, "GIT_CONFIG_KEY_1": "core.worktree"}, {**injected, "GIT_CONFIG_KEY_7": "http.proxy"},
                    {**injected, "GIT_DIR": "elsewhere"}, {**injected, "GIT_CONFIG_COUNT": "-1"}):
        with pytest.raises(source.SourceInputError):
            review.local_git_environment(changed)


def test_checkpoint_recipe_bytes_must_match(monkeypatch, tmp_path):
    path = tmp_path / "recipe.py"
    path.write_bytes(b"reviewed recipe")
    monkeypatch.setattr(review, "git_bytes", lambda arguments, environment: b"reviewed recipe")
    files = {"recipes/scripts/recipe.py": (path, pin(path.read_bytes()))}
    review.verify_checkpoint_files("a" * 40, files, {})
    path.write_bytes(b"modified recipe")
    with pytest.raises(source.SourceInputError, match="differs from application checkpoint"):
        review.verify_checkpoint_files("a" * 40, files, {})


@pytest.mark.parametrize("change", ["content", "missing", "extra", "duplicate", "symlink", "compression", "timestamp", "receipt"])
def test_verification_rejects_changed_envelope_or_bytes(tmp_path, read_lock, change):
    data = b"retained source"
    expected = receipt_for(data)
    path = tmp_path / "mutant.zip"
    with zipfile.ZipFile(path, "w") as archive:
        if change != "missing":
            info = review.zip_info("archives/source.tar.gz")
            if change == "symlink":
                info.external_attr = 0o120777 << 16
            elif change == "compression":
                info.compress_type = zipfile.ZIP_DEFLATED
            elif change == "timestamp":
                info.date_time = (2020, 1, 1, 0, 0, 0)
            archive.writestr(info, b"changed source!" if change == "content" else data)
        if change in {"extra", "duplicate"}:
            with pytest.warns(UserWarning) if change == "duplicate" else ExitStack():
                archive.writestr(review.zip_info("extra" if change == "extra" else "archives/source.tar.gz"), data)
        archive.writestr(review.zip_info("bundle-receipt.json"), b"{}" if change == "receipt" else source.canonical_json(expected))
    with pytest.raises(source.SourceInputError):
        review.verify_bundle(path, expected)


@pytest.mark.parametrize("flag", ["complete_corresponding_source", "native_rebuild_proven", "release_approved",
                                 "distribution_approved", "compat_runtime_tested", "public_delivery_proven"])
def test_readiness_flags_cannot_be_promoted(tmp_path, flag):
    receipt = receipt_for()
    receipt[flag] = True
    with pytest.raises(source.SourceInputError, match="overstates"):
        review.verify_bundle(tmp_path / "absent.zip", receipt)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/private", "file:stream", "NUL", "a/../b"])
def test_archive_destinations_reject_unsafe_names(path):
    with pytest.raises(source.SourceInputError):
        review.zip_info(path)


def test_public_metadata_allows_urls_and_rejects_private_paths():
    review.public_metadata({"url": "https://download.qt.io/source"})
    for value in ("C:/private/file", "D:\\private\\file", "prefix C:\\Users\\private"):
        with pytest.raises(source.SourceInputError):
            review.public_metadata({"nested": [value]})


@pytest.mark.parametrize("name,origin,expected", [
    ("PyQt6/Qt6/bin/Qt6Core.dll", "locked-build-venv", "qtbase-native"),
    ("PyQt6/Qt6/plugins/imageformats/qwebp.dll", "locked-build-venv", "qtimageformats-native"),
    ("PyQt6/Qt6/plugins/iconengines/qsvgicon.dll", "locked-build-venv", "qtsvg-native"),
    ("PyQt6/sip.cp313-win_amd64.pyd", "locked-build-venv", "pyqt6-sip"),
    ("81d243bd2c585b0f4821__mypyc.cp313-win_amd64.pyd", "locked-build-venv", "charset-normalizer"),
    ("numpy.libs/libscipy_openblas.dll", "locked-build-venv", "numpy"),
    ("VCRUNTIME140.dll", "verified-base-python", "runtime-msvc"),
    ("libcrypto-3.dll", "verified-base-python", "cpython-runtime"),
    ("app/firewall/WinDivert64.sys", "managed-native", "windivert"),
])
def test_retained_native_mapping(name, origin, expected):
    assert review.native_component({"destination": name, "origin": origin}) == expected


@pytest.mark.parametrize("name,origin", [
    ("PyQt6/Qt6/bin/Qt6WebEngineCore.dll", "locked-build-venv"),
    ("PyQt6/Qt6/bin/opengl32sw.dll", "locked-build-venv"),
    ("unexpected.dll", "locked-build-venv"), ("unexpected.dll", "managed-native"),
    ("unexpected.dll", "pinned-msvc-redist"), ("unexpected.dll", "unknown-origin"),
])
def test_unmapped_native_files_fail_closed(name, origin):
    with pytest.raises(source.SourceInputError):
        review.native_component({"destination": name, "origin": origin})


def test_engineering_manifest_exactly_covers_profile_and_build_tools(tmp_path):
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / "packaging/third-party-components.json").read_text(encoding="utf-8"))
    inventory["runtime_components"] = [r for r in inventory["runtime_components"] if r["name"] not in {
        "pyqt6-qt6", "pyqt6-webengine", "pyqt6-webengine-qt6"}]
    for row in inventory["runtime_components"]:
        if row["name"] in {"pyqt6", "pyqt6-sip"}:
            row["version"] = "6.12.1" if row["name"] == "pyqt6" else "13.13.1"
    inventory["additional_components"].extend({"id": name + "-native", "version": "6.12.1"}
                                               for name in ("qtbase", "qtsvg", "qtimageformats", "qttranslations"))
    candidate = json.loads((root / "packaging/qt-raster-no-network-inputs.json").read_text(encoding="utf-8"))
    msvc = json.loads((root / "packaging/msvc-redist-inputs.json").read_text(encoding="utf-8"))
    build_lock = (root / "packaging/requirements-build-locked.txt").read_text(encoding="utf-8")
    effective = review.expected_inventory(inventory, build_lock, candidate, msvc)
    target = tmp_path / "expected.json"
    target.write_bytes(source.canonical_json(effective))
    manifest = source.load_manifest(root / "packaging/engineering-source-inputs.json", target)
    assert len(manifest["components"]) == 46
    assert sum(len(c["artifacts"]) for c in manifest["components"]) == 45
    assert [c["id"] for c in manifest["components"] if not c["artifacts"]] == ["runtime-msvc"]
    changed = copy.deepcopy(inventory)
    next(c for c in changed["additional_components"] if c["id"] == "pyinstaller-bootloader")["version"] = "1.0"
    with pytest.raises(source.SourceInputError, match="Freezer/source"):
        review.expected_inventory(changed, build_lock, candidate, msvc)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing-read boundary")
def test_input_lock_denies_mutation_until_bundle_reads_complete(tmp_path):
    path = tmp_path / "source.tar.gz"
    path.write_bytes(b"source")
    with ExitStack() as stack:
        assert review.lock(stack, path, pin(b"source")) == pin(b"source")
        assert path.read_bytes() == b"source"
        with pytest.raises(OSError):
            path.write_bytes(b"replace")
        with pytest.raises(OSError):
            path.unlink()
        with pytest.raises(OSError):
            path.rename(tmp_path / "renamed")
    path.write_bytes(b"replace")
    with ExitStack() as stack, pytest.raises(RuntimeError):
        review.lock(stack, path, pin(b"source"))
