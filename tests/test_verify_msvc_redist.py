"""Pure parser/pin checks; these tests do not execute native tools or installers."""
from copy import deepcopy
import json
import struct
import zipfile

import pytest

from scripts import verify_msvc_redist as verifier


def burn_image():
    data = bytearray(1440)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 134, 1)
    struct.pack_into("<H", data, 148, 224)
    struct.pack_into("<H", data, 152, 0x10B)
    struct.pack_into("<II", data, 280, 1424, 16)
    data[376:384] = b".wixburn"
    struct.pack_into("<II", data, 392, 512, 512)
    struct.pack_into("<II", data, 512, 0x00F14300, 2)
    struct.pack_into("<6I", data, 536, 1024, 0, 1152, 16, 1, 2)
    struct.pack_into("<2I", data, 560, 128, 256)
    return data


def cabinet(names=("a1", "a4"), sizes=None):
    if sizes is None:
        sizes = [32] * len(names)
    rows = b"".join(struct.pack("<IIHHHH", size, 0, 0, 0, 0, 0) + name.encode("ascii") + b"\0"
                    for name, size in zip(names, sizes))
    data = bytearray(44 + len(rows))
    data[:4] = b"MSCF"
    struct.pack_into("<I", data, 8, len(data))
    struct.pack_into("<I", data, 16, 44)
    struct.pack_into("<BBHHH", data, 24, 3, 1, 1, len(names), 0)
    data[44:] = rows
    return data


def manifest():
    return json.loads(verifier.MANIFEST.read_text())


def test_burn_offsets_follow_original_engine_signature():
    result = verifier.burn_containers(bytes(burn_image()))
    assert result["ux"]["offset"] == 1024
    assert result["attached"]["offset"] == 1168
    assert result["attached"]["size"] == 256


@pytest.mark.parametrize("offset,format_,value", [
    (512, "<I", 0), (516, "<I", 3), (556, "<I", 20),
    (548, "<I", 0), (560, "<I", 1024), (564, "<I", 10000),
    (280, "<I", 1200), (284, "<I", 0), (392, "<I", 100000),
])
def test_burn_rejects_corrupt_or_unsupported_ranges(offset, format_, value):
    data = burn_image()
    struct.pack_into(format_, data, offset, value)
    with pytest.raises(ValueError):
        verifier.burn_containers(bytes(data))


@pytest.mark.parametrize("data", [b"", b"MZ", b"MZ" + b"\0" * 60, b"not an installer"])
def test_burn_truncation_is_rejected(data):
    with pytest.raises(ValueError):
        verifier.burn_containers(data)


def test_cabinet_member_inventory():
    assert verifier.cabinet_members(bytes(cabinet())) == {"a1": 32, "a4": 32}


@pytest.mark.parametrize("names", [
    ("a1", "A1"), ("../outside",), ("dir/file",), ("dir\\file",),
    ("C:target",), ("NUL.txt",), ("COM1",), ("*",), ("-F:other",),
])
def test_cabinet_rejects_unsafe_or_colliding_members(names):
    with pytest.raises(ValueError):
        verifier.cabinet_members(bytes(cabinet(names)))


def test_cabinet_expansion_limit():
    with pytest.raises(ValueError, match="expansion"):
        verifier.cabinet_members(bytes(cabinet(sizes=[verifier.MAX_INPUT, 1])))


def test_cabinet_rejects_continuation_and_truncated_directory():
    data = cabinet()
    struct.pack_into("<H", data, 30, 1)
    with pytest.raises(ValueError, match="continuation"):
        verifier.cabinet_members(bytes(data))
    with pytest.raises(ValueError):
        verifier.cabinet_members(bytes(cabinet())[:-1])


def signed_cabinet():
    original = cabinet()
    data = bytearray(original[:36] + b"\0" * 24 + original[36:] + b"signature")
    size = len(data) - 9
    struct.pack_into("<I", data, 8, size)
    struct.pack_into("<I", data, 16, 68)
    struct.pack_into("<H", data, 30, 4)
    struct.pack_into("<HBB5I", data, 36, 20, 0, 0, 0x00100000, size, 9, 0, 0)
    return data


def test_signed_cabinet_has_bounded_separate_certificate_trailer():
    assert verifier.cabinet_members(bytes(signed_cabinet())) == {"a1": 32, "a4": 32}


@pytest.mark.parametrize("offset,value", [(40, 0), (44, 0), (48, 100000), (52, 1)])
def test_signed_cabinet_rejects_bad_signature_reserve(offset, value):
    data = signed_cabinet()
    struct.pack_into("<I", data, offset, value)
    with pytest.raises(ValueError, match="reserve/trailer"):
        verifier.cabinet_members(bytes(data))


def test_real_pin_inventory_has_exact_three_dlls_and_no_approval():
    verifier.validate_manifest(manifest())


@pytest.mark.parametrize("change", ["extra", "duplicate", "approval", "hash", "size", "cabinet-name"])
def test_manifest_rejects_widening_or_bad_pins(change):
    data = manifest()
    if change == "extra":
        data["binaries"].append(deepcopy(data["binaries"][0]))
    elif change == "duplicate":
        data["binaries"][1] = deepcopy(data["binaries"][0])
    elif change == "approval":
        data["distribution_approved"] = True
    elif change == "hash":
        data["binaries"][0]["sha256"] = "a" * 63
    elif change == "size":
        data["binaries"][0]["size"] = True
    else:
        data["binaries"][0]["cabinet_member"] = "unrelated.dll_amd64"
    with pytest.raises(ValueError):
        verifier.validate_manifest(data)


def msi_tables(data):
    return {
        "Property": [["ProductCode", data["minimum_runtime"]["product_code"]],
                     ["ProductVersion", "14.51.36247"], ["ProductName", "Microsoft runtime"]],
        "Media": [["1", "cab1.cab"]],
        "File": [[item["cabinet_member"], item["name"], str(item["size"]), "14.51.36247.0"]
                 for item in data["binaries"]],
    }


def test_msi_mapping_links_cabinet_keys_to_real_names():
    data = manifest()
    result = verifier.msi_mapping(msi_tables(data), data)
    assert result["files"][0]["file_key"] == "msvcp140.dll_amd64"
    assert result["files"][0]["filename"] == "MSVCP140.dll"


@pytest.mark.parametrize("column,value", [(1, "different.dll"), (2, "1"), (3, "14.0.0.0")])
def test_msi_mapping_rejects_unrelated_name_size_or_version(column, value):
    data = manifest()
    tables = msi_tables(data)
    tables["File"][0][column] = value
    with pytest.raises(ValueError):
        verifier.msi_mapping(tables, data)


def test_old_system_observation_must_match_exact_set():
    data = manifest()
    observation = {"binaries": deepcopy(data["binaries"])}
    verifier.verify_observation(observation, data["binaries"])
    observation["binaries"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        verifier.verify_observation(observation, data["binaries"])


def test_input_pin_rejects_replacement(tmp_path):
    path = tmp_path / "package"
    path.write_bytes(b"original")
    pin = verifier.identity(path)
    path.write_bytes(b"modified")
    with pytest.raises(ValueError):
        verifier.verify(path, pin)


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"release_approved":false,"release_approved":true}')
    with pytest.raises(ValueError, match="Duplicate"):
        verifier.read_json(path)


def test_license_text_preserves_words_split_between_formatting_runs():
    xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Cpp_v14_</w:t></w:r><w:r><w:t>ENU.1033</w:t></w:r></w:p><w:p><w:r><w:t>Last Updated: October 1, 2025</w:t></w:r></w:p></w:body></w:document>'
    assert verifier.word_text(xml) == "Cpp_v14_ENU.1033 Last Updated: October 1, 2025"


def mocked_preparation(tmp_path, monkeypatch, mutation=None):
    """Exercise receipt publication with inert fixtures in place of OS readers."""
    data = manifest()
    package = tmp_path / "package.exe"
    package.write_bytes(b"P" * 64)
    data["package"].update(verifier.identity(package))
    data["containers"] = {"ux": {"offset": 0, "size": 16, "sha256": verifier.digest(b"P" * 16)},
                          "attached": {"offset": 16, "size": 16, "sha256": verifier.digest(b"P" * 16)}}
    contents = {"a1": b"inert-msi", "a4": b"inert-cab"}
    for key in ("msi", "cabinet"):
        item = data["minimum_runtime"][key]
        content = contents[item["source_path"]]
        item.update(size=len(content), sha256=verifier.digest(content))
    for index, item in enumerate(data["binaries"]):
        content = bytes([index + 1]) * 32
        contents[item["cabinet_member"]] = content
        item.update(size=len(content), sha256=verifier.digest(content))
    import hashlib
    attributes = []
    for key in ("msi", "cabinet"):
        item = data["minimum_runtime"][key]
        attributes.append('<Payload Id="{payload_id}" SourcePath="{source_path}" FilePath="{file_path}" FileSize="{size}" Container="WixAttachedContainer" Hash="{sha1}"/>'.format(
            **item, sha1=hashlib.sha1(contents[item["source_path"]]).hexdigest()))
    contents["0"] = ("<Burn>" + "".join(attributes) + "</Burn>").encode()
    contents["u17"] = b'<Data><Information LicenseUrl="https://aka.ms/VCRedistLicense"/></Data>'
    license_doc = tmp_path / "license.docx"
    with zipfile.ZipFile(license_doc, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Cpp_v14_ENU.1033 Last Updated: October 1, 2025</w:t></w:r></w:p></w:document>')
    pin = verifier.identity(license_doc)
    data["license_reference"].update(document_size=pin["size"], document_sha256=pin["sha256"])
    manifest_path = tmp_path / "inputs.json"
    manifest_path.write_text(json.dumps(data))
    observation = tmp_path / "observation.json"
    observation.write_text(json.dumps({"binaries": data["binaries"]}))
    system = tmp_path / "system"
    system.mkdir()
    expand = system / "expand.exe"
    expand.write_bytes(b"inert-extractor")
    output = tmp_path / "output"
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "system_directory", lambda: system)
    monkeypatch.setattr(verifier, "burn_containers", lambda _content: data["containers"])
    monkeypatch.setattr(verifier, "cabinet_members", lambda _content: {})

    def fake_extract(_cabinet, tokens, destination, _expand, _env):
        destination.mkdir()
        result = {}
        for token in tokens:
            path = destination / token
            path.write_bytes(contents[token])
            result[token] = path
        return result

    targets = {"dll": output / "dlls/msvcp140.dll_amd64", "msi": output / "minimum-runtime/a1",
               "cabinet": output / "minimum-runtime/a4", "xml": output / "ux/0", "tool": expand}

    def mutate(stage):
        if mutation and mutation[0] == stage:
            targets[mutation[1]].write_bytes(b"unexpected replacement")

    def fake_signatures(paths, _system, _env):
        if "minimum-runtime.msi" in paths:
            mutate("signature")
        return [{"name": name, "thumbprint": data["package"]["signer_thumbprint"],
                 "file_version": data["package"]["version"]} for name in paths]

    def fake_tables(_path, _system):
        mutate("msi")
        return msi_tables(data)

    monkeypatch.setattr(verifier, "extract", fake_extract)
    monkeypatch.setattr(verifier, "signatures", fake_signatures)
    monkeypatch.setattr(verifier, "read_msi_tables", fake_tables)
    return lambda: verifier.prepare(package, license_doc, observation, output, manifest_path), output


def test_receipt_publication_with_stable_consumed_inputs(tmp_path, monkeypatch):
    prepare, output = mocked_preparation(tmp_path, monkeypatch)
    result = prepare()
    assert result["status"] == "exact-upstream-package-bytes-verified"
    assert (output / "receipt.json").is_file()
    assert len(result["consumed_artifacts"]) == 9


@pytest.mark.parametrize("stage,target", [("signature", "dll"), ("signature", "msi"),
    ("signature", "cabinet"), ("signature", "xml"), ("signature", "tool"), ("msi", "dll")])
def test_no_receipt_after_extracted_input_changes_during_os_observation(tmp_path, monkeypatch, stage, target):
    prepare, output = mocked_preparation(tmp_path, monkeypatch, (stage, target))
    with pytest.raises(ValueError, match="consumed input changed"):
        prepare()
    assert not (output / "receipt.json").exists()
