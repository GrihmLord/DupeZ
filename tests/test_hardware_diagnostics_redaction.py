"""Privacy contract for hardware-smoke failure diagnostics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

import scripts.redact_hardware_diagnostics as redactor
from scripts.redact_hardware_diagnostics import (
    SCHEMA,
    SUMMARY_NAME,
    redact_diagnostics,
    redact_text,
    verify_redacted_output,
)


TARGET_IP = "192.168.50.42"
TARGET_MAC = "aa:bb:cc:dd:ee:ff"
TARGET_CIDR = "192.168.50.0/24"
WORKSPACE = r"C:\actions-runner\_work\DupeZ\DupeZ"


def _environment() -> dict[str, str]:
    return {
        "DUPEZ_SMOKETEST_TARGET_IP": TARGET_IP,
        "DUPEZ_SMOKETEST_TARGET_MAC": TARGET_MAC,
        "DUPEZ_SMOKETEST_CIDR": TARGET_CIDR,
        "DUPEZ_SMOKETEST_TARGET_HOSTNAME": "TARGET-CONSOLE",
        "GITHUB_WORKSPACE": WORKSPACE,
        "RUNNER_TEMP": r"C:\actions-runner\_work\_temp",
        "RUNNER_TOOL_CACHE": r"C:\actions-runner\_tool",
        "RUNNER_NAME": "private-hardware-runner",
        "COMPUTERNAME": "HW-RUNNER-01",
        "USERNAME": "RunnerAdmin",
        "USERDOMAIN": "PRIVATE-LAB",
        "USERPROFILE": r"C:\Users\ExampleOperator",
        "LOCALAPPDATA": r"C:\Users\ExampleOperator\AppData\Local",
        "APPDATA": r"C:\Users\ExampleOperator\AppData\Roaming",
    }


def _create_one_file_output(
    root: Path,
    name: str = "smoketest.log",
) -> tuple[Path, dict]:
    root.mkdir()
    (root / name).write_text(f"failed reaching {TARGET_IP}", encoding="utf-8")
    output = root / "hardware-diagnostics-redacted"
    summary = redact_diagnostics(
        root=root,
        sources=[name],
        output_directory=output,
        environment=_environment(),
    )
    return output, summary


def _make_symlink(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")


def test_redact_text_removes_exact_and_incidental_identifiers() -> None:
    raw = (
        f"target={TARGET_IP} mac={TARGET_MAC} cidr={TARGET_CIDR}\n"
        "gateway=10.0.0.1 peer=11-22-33-44-55-66\n"
        r"path=C:\Users\AnotherUser\DupeZ\logs"
    )

    rendered, replacements = redact_text(raw, environment=_environment())

    assert replacements >= 6
    for secret in (TARGET_IP, TARGET_MAC, TARGET_CIDR, "10.0.0.1"):
        assert secret.lower() not in rendered.lower()
    assert "11-22-33-44-55-66" not in rendered
    assert "AnotherUser" not in rendered


def test_redact_text_handles_serialized_paths_and_extended_network_ids() -> None:
    payload = {
        "escaped_user": r"C:\Users\Another Operator\private\logs",
        "workspace": WORKSPACE + r"\logs\errors.log",
        "runner_temp": r"C:\actions-runner\_work\_temp\trace.log",
        "ipv6": "fe80::dead:beef%12",
        "bracketed_ipv6": "[2001:db8::1]:443",
        "masked_subnet": "192.168.50.x/24",
        "wildcard_subnet": "10.*.*.*",
        "dotted_mac": "aabb.ccdd.eeff",
        "hostname": "PS5-LIVINGROOM",
        "missing_hostname": None,
        "computer": "HW-RUNNER-01",
        "runner": "private-hardware-runner",
        "operator": "RunnerAdmin",
    }
    raw = json.dumps(payload)

    rendered, replacements = redact_text(raw, environment=_environment())

    assert replacements >= 11
    # Redaction must preserve structured diagnostics as valid JSON.
    parsed = json.loads(rendered)
    assert parsed["bracketed_ipv6"] == "[REDACTED-IPV6]:443"
    for identifier in (
        "Another Operator",
        WORKSPACE,
        "actions-runner",
        "fe80::dead:beef%12",
        "2001:db8::1",
        "192.168.50.x",
        "10.*.*.*",
        "aabb.ccdd.eeff",
        "PS5-LIVINGROOM",
        "HW-RUNNER-01",
        "private-hardware-runner",
        "RunnerAdmin",
    ):
        assert identifier.casefold() not in rendered.casefold()

    log_line = (
        "hostname 'XBOX-DEN' matched xbox pattern; "
        "peer=fd00::1234 mapped=::ffff:192.0.2.128 "
        "mac=a1b2.c3d4.e5f6 subnet=172.16.4.*"
    )
    redacted_line, count = redact_text(log_line, environment={})
    assert count == 5
    for identifier in (
        "XBOX-DEN",
        "fd00::1234",
        "::ffff",
        "192.0.2.128",
        "a1b2.c3d4.e5f6",
        "172.16.4.*",
    ):
        assert identifier not in redacted_line

    null_host, count = redact_text('{"hostname": null}', environment={})
    assert count == 1
    assert json.loads(null_host)["hostname"] == "[REDACTED-HOST]"


def test_redact_diagnostics_uses_opaque_names_and_verified_summary(
    tmp_path: Path,
) -> None:
    (tmp_path / "smoketest.log").write_text(
        f"failed reaching {TARGET_IP} ({TARGET_MAC})",
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / f"target-{TARGET_IP}.log").write_text(
        r"C:\Users\ExampleOperator\private " + TARGET_CIDR,
        encoding="utf-8",
    )

    summary = redact_diagnostics(
        root=tmp_path,
        sources=["smoketest.log", "logs"],
        output_directory=tmp_path / "hardware-diagnostics-redacted",
        environment=_environment(),
    )

    assert summary["schema"] == SCHEMA
    assert summary["file_count"] == 2
    assert summary["replacement_count"] >= 4
    output = tmp_path / "hardware-diagnostics-redacted"
    assert sorted(summary["outputs"]) == [
        "diagnostic-001.log",
        "diagnostic-002.log",
    ]
    assert set(summary["output_bytes"]) == set(summary["outputs"])
    assert set(summary["output_sha256"]) == set(summary["outputs"])
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(output.glob("diagnostic-*"))
    )
    for value in (
        TARGET_IP,
        TARGET_MAC,
        TARGET_CIDR,
        "ExampleOperator",
    ):
        assert value.lower() not in combined.lower()
    stored_summary = json.loads(
        (output / SUMMARY_NAME).read_text(encoding="utf-8")
    )
    assert stored_summary == summary
    assert verify_redacted_output(output) == summary
    assert TARGET_IP not in json.dumps(stored_summary)


def test_redact_diagnostics_rejects_existing_output_without_touching_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "smoketest.log").write_text("safe input", encoding="utf-8")
    output = tmp_path / "hardware-diagnostics-redacted"
    output.mkdir()
    stale = output / "stale-private.log"
    stale.write_text("must not be uploaded or overwritten", encoding="utf-8")

    with pytest.raises(ValueError, match="new directory"):
        redact_diagnostics(
            root=tmp_path,
            sources=["smoketest.log"],
            output_directory=output,
        )

    assert (
        stale.read_text(encoding="utf-8")
        == "must not be uploaded or overwritten"
    )
    assert list(output.iterdir()) == [stale]


def test_destination_creation_is_exclusive_under_a_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "smoketest.log").write_text("diagnostic", encoding="utf-8")
    output = tmp_path / "hardware-diagnostics-redacted"
    original = redactor.redact_text

    def inject_destination(text: str, *, environment=None):
        (output / "diagnostic-001.log").write_text("raced", encoding="utf-8")
        return original(text, environment=environment)

    monkeypatch.setattr(redactor, "redact_text", inject_destination)
    with pytest.raises(FileExistsError):
        redactor.redact_diagnostics(
            root=tmp_path,
            sources=["smoketest.log"],
            output_directory=output,
        )
    assert (output / "diagnostic-001.log").read_text(encoding="utf-8") == "raced"
    assert not (output / SUMMARY_NAME).exists()


def test_output_verifier_rejects_extra_and_modified_files(tmp_path: Path) -> None:
    extra_output, _ = _create_one_file_output(tmp_path / "extra")
    (extra_output / "unexpected.log").write_text("unlisted", encoding="utf-8")
    with pytest.raises(ValueError, match="exact upload allowlist"):
        verify_redacted_output(extra_output)

    tamper_output, summary = _create_one_file_output(tmp_path / "tamper")
    (tamper_output / summary["outputs"][0]).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="content does not match"):
        verify_redacted_output(tamper_output)


def test_redact_diagnostics_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="root-relative"):
        redact_diagnostics(
            root=tmp_path,
            sources=["../outside.log"],
            output_directory=tmp_path / "hardware-diagnostics-redacted",
        )


def test_redact_diagnostics_rejects_symlink_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    _make_symlink(linked_root, real_root, directory=True)

    with pytest.raises(ValueError, match="symlink, junction, or reparse point"):
        redact_diagnostics(
            root=linked_root,
            sources=[],
            output_directory=linked_root / "redacted",
        )


@pytest.mark.parametrize("link_is_directory", [False, True])
def test_redact_diagnostics_rejects_symlinks_in_source_tree(
    tmp_path: Path,
    link_is_directory: bool,
) -> None:
    root = tmp_path / ("directory-link" if link_is_directory else "file-link")
    root.mkdir()
    logs = root / "logs"
    logs.mkdir()
    if link_is_directory:
        target = root / "real-logs"
        target.mkdir()
        (target / "trace.log").write_text("private", encoding="utf-8")
        link = logs / "linked"
    else:
        target = root / "real.log"
        target.write_text("private", encoding="utf-8")
        link = logs / "linked.log"
    _make_symlink(link, target, directory=link_is_directory)

    with pytest.raises(ValueError, match="symlink, junction, or reparse point"):
        redact_diagnostics(
            root=root,
            sources=["logs"],
            output_directory=root / "redacted",
        )
    assert not (root / "redacted").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_redact_diagnostics_rejects_windows_junction(tmp_path: Path) -> None:
    root = tmp_path / "junction-root"
    root.mkdir()
    target = root / "real-logs"
    target.mkdir()
    junction = root / "logs"
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"junction creation is unavailable: {completed.stderr}")
    try:
        with pytest.raises(ValueError, match="symlink, junction, or reparse point"):
            redact_diagnostics(
                root=root,
                sources=["logs"],
                output_directory=root / "redacted",
            )
        assert not (root / "redacted").exists()
    finally:
        junction.rmdir()
