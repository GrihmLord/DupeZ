"""Native-browser admission tests; never instantiate a page or renderer."""

from types import SimpleNamespace
import sys

import pytest

from app.gui.map_host import security_policy as policy


REVIEWED_VERSIONS = ("6.11.3", "6.11.2", "151.0.7922.71")
_REAL_NON_ELEVATED_PROCESS = policy._non_elevated_process
_REAL_RUNTIME_VERSIONS = policy._runtime_versions


@pytest.fixture
def reviewed_runtime(monkeypatch):
    environment = {}
    arguments = ["DupeZ-GPU.exe"]
    calls = []

    def versions():
        calls.append("versions")
        return REVIEWED_VERSIONS

    monkeypatch.setattr(policy, "os", SimpleNamespace(environ=environment))
    monkeypatch.setattr(policy, "sys", SimpleNamespace(platform="win32", argv=arguments))
    monkeypatch.setattr(policy, "_non_elevated_process", lambda: True)
    monkeypatch.setattr(policy, "_runtime_versions", versions)
    monkeypatch.setattr(policy, "REVIEWED_NATIVE_COMBINATIONS", frozenset({REVIEWED_VERSIONS}))
    return SimpleNamespace(environment=environment, arguments=arguments, calls=calls)


def _denied():
    result = policy.assess_webengine_security()
    assert result.allowed is False
    assert result.reason
    return result


def test_reviewed_runtime_is_admitted_without_mutating_startup(reviewed_runtime):
    reviewed_runtime.environment["UNCHANGED"] = "fixture"
    environment = dict(reviewed_runtime.environment)
    arguments = list(reviewed_runtime.arguments)
    result = policy.assess_webengine_security()
    assert result.allowed is True
    assert reviewed_runtime.calls == ["versions"]
    assert reviewed_runtime.environment == environment
    assert reviewed_runtime.arguments == arguments


def test_release_policy_has_no_implicitly_approved_native_combination():
    # Do not put the available stale wheel baseline in the production allowlist.
    assert policy.REVIEWED_NATIVE_COMBINATIONS == frozenset()


def test_version_floors_alone_never_reenable_embedded_content(reviewed_runtime, monkeypatch):
    monkeypatch.setattr(policy, "REVIEWED_NATIVE_COMBINATIONS", frozenset())
    result = _denied()
    assert "no reviewed patched native-runtime combination" in result.reason
    assert reviewed_runtime.calls == ["versions"]


@pytest.mark.parametrize("versions", [
    ("6.11.4", "6.11.2", "151.0.7922.71"),
    ("6.11.3", "6.11.3", "151.0.7922.71"),
    ("6.11.3", "6.11.2", "156.0.8078.42"),
])
def test_newer_unreviewed_combinations_require_explicit_review(
    reviewed_runtime, monkeypatch, versions,
):
    monkeypatch.setattr(policy, "_runtime_versions", lambda: versions)
    assert "no reviewed patched native-runtime combination" in _denied().reason


@pytest.mark.parametrize("platform", ["linux", "darwin", "unknown", "cygwin", ""])
def test_unknown_platform_denies_before_loading_native_versions(
    reviewed_runtime, monkeypatch, platform
):
    monkeypatch.setattr(policy.sys, "platform", platform)
    monkeypatch.setattr(policy, "_non_elevated_process", _REAL_NON_ELEVATED_PROCESS)
    assert "Windows" in _denied().reason
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("elevated", [False, True])
def test_windows_token_result_controls_admission(reviewed_runtime, monkeypatch, elevated):
    class TokenApi:
        def current_process_is_elevated(self):
            return elevated

    monkeypatch.setitem(
        sys.modules, "app.gui.map_host.launcher", SimpleNamespace(_Win32ShellLaunchApi=TokenApi)
    )
    monkeypatch.setattr(policy, "_non_elevated_process", _REAL_NON_ELEVATED_PROCESS)
    assert policy.assess_webengine_security().allowed is not elevated
    assert reviewed_runtime.calls == ([] if elevated else ["versions"])


@pytest.mark.parametrize("failure_point", ["api-construction", "token-query"])
def test_token_inspection_errors_fail_closed_and_hide_private_details(
    reviewed_runtime, monkeypatch, failure_point
):
    class TokenApi:
        def __init__(self):
            if failure_point == "api-construction":
                raise OSError("private token fixture")

        def current_process_is_elevated(self):
            raise RuntimeError("private token fixture")

    monkeypatch.setitem(
        sys.modules, "app.gui.map_host.launcher", SimpleNamespace(_Win32ShellLaunchApi=TokenApi)
    )
    monkeypatch.setattr(policy, "_non_elevated_process", _REAL_NON_ELEVATED_PROCESS)
    assert "private" not in _denied().reason
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize(
    "key", ["QTWEBENGINE_DISABLE_SANDBOX", "qtwebengine_disable_sandbox",
            "QtWebEngine_Remote_Debugging", "QTWEBENGINE_REMOTE_DEBUGGING"]
)
@pytest.mark.parametrize("value", ["1", "0", "false", " 9222 "])
def test_configured_sandbox_or_debug_environment_denies_before_native_probe(
    reviewed_runtime, key, value
):
    reviewed_runtime.environment[key] = value
    _denied()
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("key", ["QTWEBENGINE_DISABLE_SANDBOX", "qtwebengine_disable_sandbox"])
@pytest.mark.parametrize("value", ["", " ", "\t", "\r\n", "0"])
def test_sandbox_bypass_variable_presence_denies_regardless_of_value(
    reviewed_runtime, key, value
):
    # Qt 6.11 WebEngineContext uses qEnvironmentVariableIsSet() and appends
    # --no-sandbox whenever this key exists, including an empty value.
    reviewed_runtime.environment[key] = value
    assert "sandbox bypass" in _denied().reason
    assert reviewed_runtime.calls == []


def test_empty_debug_and_chromium_flag_values_do_not_enable_bypasses(reviewed_runtime):
    reviewed_runtime.environment.update({
        "QTWEBENGINE_REMOTE_DEBUGGING": "",
        "QTWEBENGINE_CHROMIUM_FLAGS": "",
    })
    assert policy.assess_webengine_security().allowed is True


@pytest.mark.parametrize("key", [
    "QTWEBENGINEPROCESS_PATH", "QTWEBENGINE_RESOURCES_PATH", "QTWEBENGINE_LOCALES_PATH",
    "QtWebEngineProcess_Path", "qtwebengine_resources_path", "qtwebengine_locales_path",
])
@pytest.mark.parametrize("value", [r"C:\unreviewed\browser", "", " "])
def test_native_executable_and_resource_overrides_cannot_inherit_dll_approval(
    reviewed_runtime, key, value,
):
    reviewed_runtime.environment[key] = value
    assert "unreviewed browser executable or resource path" in _denied().reason
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("source", ["environment", "arguments"])
@pytest.mark.parametrize("flag", [
    "--no-sandbox", "--disable-sandbox", "--disable-setuid-sandbox",
    "--disable-gpu-sandbox", "--single-process", "--in-process-gpu",
    "--disable-web-security", "--ignore-certificate-errors",
    "--remote-debugging", "--remote-debugging-port=9222", "--remote-debugging-pipe",
    "--remote-debugging-address=127.0.0.1", '--NO-SANDBOX=0', '"--no-sandbox"',
    "--ignore-certificate-errors-spki-list=fixture",
    "--unsafely-treat-insecure-origin-as-secure=http://fixture.invalid",
    "--disable-features=NetworkServiceSandbox",
])
def test_unsafe_browser_switches_deny_for_both_startup_sources(
    reviewed_runtime, source, flag
):
    if source == "environment":
        reviewed_runtime.environment["QtWebEngine_Chromium_Flags"] = flag
    else:
        reviewed_runtime.arguments.extend(["--webEngineArgs", flag])
    _denied()
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("prefix", ["--", "-", "/"])
@pytest.mark.parametrize("source", ["environment", "arguments"])
def test_windows_chromium_switch_prefix_aliases_cannot_bypass_admission(
    reviewed_runtime, prefix, source
):
    # Chromium Windows base::CommandLine accepts all three switch prefixes.
    flag = prefix + "no-sandbox"
    if source == "environment":
        reviewed_runtime.environment["QTWEBENGINE_CHROMIUM_FLAGS"] = flag
    else:
        reviewed_runtime.arguments.append(flag)
    _denied()
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("flags", [
    "--disable-gpu",
    "--enable-gpu-rasterization --enable-zero-copy --use-gl=angle "
    "--use-angle=d3d11 --enable-features=CanvasOopRasterization",
])
def test_reviewed_renderer_flags_remain_admissible(reviewed_runtime, flags):
    reviewed_runtime.environment["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    assert policy.assess_webengine_security().allowed is True


@pytest.mark.parametrize("marker", ["--webEngineArgs", "--WEBENGINEARGS"])
@pytest.mark.parametrize("flags", [
    [],
    ["--disable-gpu"],
    ["--enable-gpu-rasterization", "--enable-zero-copy", "--use-gl=angle",
     "--use-angle=d3d11", "--enable-features=CanvasOopRasterization"],
])
def test_reviewed_webengine_argument_suffix_is_admitted(reviewed_runtime, marker, flags):
    reviewed_runtime.arguments.extend(["--normal-application-option", marker, *flags])
    assert policy.assess_webengine_security().allowed is True


@pytest.mark.parametrize("marker", ["--webEngineArgs", "--WEBENGINEARGS"])
@pytest.mark.parametrize("environment_override", [False, True])
@pytest.mark.parametrize("flag", [
    "--unreviewed-flag",
    "--disable-kill-after-bad-ipc",
    "--disable-ipc-flooding-protection",
])
def test_unreviewed_webengine_argument_suffix_is_always_denied(
    reviewed_runtime, marker, environment_override, flag
):
    if environment_override:
        reviewed_runtime.environment["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    reviewed_runtime.arguments.extend([marker, "--disable-gpu", flag])
    assert "unreviewed Chromium startup flags" in _denied().reason
    assert reviewed_runtime.calls == []


def test_known_unsafe_switch_before_webengine_marker_remains_denied(reviewed_runtime):
    reviewed_runtime.arguments.extend(["--no-sandbox", "--webEngineArgs", "--disable-gpu"])
    assert "unsafe browser startup flags" in _denied().reason
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("flags", [
    "--unreviewed-flag",
    "--disable-gpu --unreviewed-flag",
    "--use-angle=unreviewed-backend",
    "--enable-features=CanvasOopRasterization,UnreviewedFeature",
    "--disable-gpu 'unterminated",
])
def test_unknown_or_malformed_environment_flags_are_not_silently_accepted(
    reviewed_runtime, flags
):
    reviewed_runtime.environment["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    _denied()
    assert reviewed_runtime.calls == []


@pytest.mark.parametrize("stage", ["environment", "arguments", "versions"])
def test_inspection_failure_denies_without_exception_details(
    reviewed_runtime, monkeypatch, stage
):
    if stage == "environment":
        class BrokenEnvironment:
            def items(self):
                raise PermissionError("private environment fixture")

        monkeypatch.setattr(policy.os, "environ", BrokenEnvironment())
    elif stage == "arguments":
        reviewed_runtime.arguments.append(None)
    else:
        def failed_versions():
            raise ImportError("private native library fixture")

        monkeypatch.setattr(policy, "_runtime_versions", failed_versions)
    assert "private" not in _denied().reason


@pytest.mark.parametrize("qt", ["6.10.9", "6.11.0", "6.11.1", "6.11.2", "6.12.0", "7.0.0"])
def test_unpatched_or_unreviewed_qt_branch_is_denied(reviewed_runtime, monkeypatch, qt):
    monkeypatch.setattr(policy, "_runtime_versions", lambda: (qt, *REVIEWED_VERSIONS[1:]))
    assert "Qt" in _denied().reason


@pytest.mark.parametrize("engine", ["6.10.9", "6.11.0", "6.11.1", "6.12.0", "7.0.0"])
def test_unpatched_or_unreviewed_webengine_branch_is_denied(
    reviewed_runtime, monkeypatch, engine
):
    monkeypatch.setattr(
        policy, "_runtime_versions", lambda: (REVIEWED_VERSIONS[0], engine, REVIEWED_VERSIONS[2])
    )
    assert "WebEngine" in _denied().reason


@pytest.mark.parametrize("security", ["130.0.6723.192", "150.99.9999.99", "151.0.7922.70"])
def test_chromium_security_backports_below_floor_are_denied(
    reviewed_runtime, monkeypatch, security
):
    monkeypatch.setattr(policy, "_runtime_versions", lambda: (*REVIEWED_VERSIONS[:2], security))
    assert "Chromium" in _denied().reason


@pytest.mark.parametrize("field", [0, 1, 2])
@pytest.mark.parametrize("value", [None, 123, "", "6.11", "6.11.3-dev", " 6.11.3", "6.11.3\n"])
def test_malformed_native_version_fails_closed(reviewed_runtime, monkeypatch, field, value):
    versions = list(REVIEWED_VERSIONS)
    versions[field] = value
    monkeypatch.setattr(policy, "_runtime_versions", lambda: tuple(versions))
    _denied()


@pytest.mark.parametrize("versions", [None, ("6.11.3",), (*REVIEWED_VERSIONS, "extra")])
def test_incomplete_native_version_probe_is_denied(reviewed_runtime, monkeypatch, versions):
    monkeypatch.setattr(policy, "_runtime_versions", lambda: versions)
    _denied()


def test_runtime_probe_queries_loaded_library_versions_without_renderer(
    reviewed_runtime, monkeypatch
):
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", SimpleNamespace(qVersion=lambda: "6.11.3"))
    monkeypatch.setitem(sys.modules, "PyQt6.QtWebEngineCore", SimpleNamespace(
        qWebEngineVersion=lambda: "6.11.2",
        qWebEngineChromiumSecurityPatchVersion=lambda: "151.0.7922.71",
    ))
    assert _REAL_RUNTIME_VERSIONS() == REVIEWED_VERSIONS


def test_runtime_probe_api_absence_cannot_be_replaced_with_package_version(
    reviewed_runtime, monkeypatch
):
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", SimpleNamespace(qVersion=lambda: "6.11.3"))
    monkeypatch.setitem(sys.modules, "PyQt6.QtWebEngineCore", SimpleNamespace(
        qWebEngineVersion=lambda: "6.11.2",
    ))
    monkeypatch.setattr(policy, "_runtime_versions", _REAL_RUNTIME_VERSIONS)
    _denied()
