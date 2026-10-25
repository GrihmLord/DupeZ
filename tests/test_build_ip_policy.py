"""Release packaging guards for reviewed third-party payloads."""

from pathlib import Path

from app.ai import voice_control


ROOT = Path(__file__).resolve().parents[1]
ASIO_NAME = "libportaudio64bit-asio.dll"


def test_build_filter_removes_unapproved_asio_payload() -> None:
    policy = (ROOT / "packaging" / "build_common.py").read_text(
        encoding="utf-8"
    )

    assert ASIO_NAME in policy
    assert "_filter_unapproved_collected_binaries(a.binaries)" in policy


def test_shared_pyinstaller_policy_excludes_scapy() -> None:
    policy = (ROOT / "packaging" / "build_common.py").read_text(
        encoding="utf-8"
    )
    excludes = policy.split("def _excludes() -> list:", 1)[1].split(
        "def _upx_excludes() -> list:",
        1,
    )[0]

    assert '"scapy",' in excludes
    assert "excludes=_excludes()" in policy


def test_all_portable_specs_share_the_hardened_build_policy() -> None:
    common = (ROOT / "packaging" / "build_common.py").read_text(
        encoding="utf-8"
    )
    legacy = (ROOT / "packaging" / "dupez.spec").read_text(encoding="utf-8")

    assert 'os.environ["DUPEZ_BUILD_ANALYSIS"] = "1"' in common
    assert 'os.environ["DUPEZ_FORCE_USER_DATA"] = "1"' in common
    assert 'os.environ["DUPEZ_USER_ROOT"] = analysis_user_root' in common
    assert "_configure_build_analysis_state()" in common
    assert "import build_common as shared_build" in legacy
    assert "shared_build.build_variant(" in legacy
    assert 'manifest_path="dupez_compat.manifest"' in legacy
    assert "scapy" not in legacy.casefold()


def test_voice_runtime_ignores_inherited_asio_selection(monkeypatch) -> None:
    monkeypatch.setenv("SD_ENABLE_ASIO", "1")

    voice_control._enforce_reviewed_audio_backend()

    assert "SD_ENABLE_ASIO" not in voice_control.os.environ
