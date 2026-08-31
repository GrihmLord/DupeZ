"""Regression tests for complete-file plugin signature coverage."""

from __future__ import annotations

import builtins
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.plugins.signing as plugin_signing
from app.plugins.loader import PluginLoader
from app.plugins.signing import (
    MANIFEST_VERSION,
    PluginSigError,
    PluginSigState,
    pubkey_fingerprint,
    sign_manifest,
    verify_plugin_manifest,
)


@pytest.fixture(autouse=True)
def _explicit_unenrolled_second_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plugin tests opt into the documented, positively unenrolled state."""
    import app.core.second_factor as second_factor
    import app.core.secret_store as secret_store

    gate = types.SimpleNamespace(is_enrolled=lambda: False)
    health = types.SimpleNamespace(healthy=True)
    monkeypatch.setattr(second_factor, "get_gate", lambda: gate)
    monkeypatch.setattr(secret_store, "check_store_health", lambda: health)
    monkeypatch.setattr(secret_store, "get_secret", lambda _kind: None)
    monkeypatch.delenv("DUPEZ_SECOND_FACTOR_DISABLED", raising=False)


def _create_keypair(tmp_path: Path) -> tuple[Path, str, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "plugin-private.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_path, public_pem, private_key


def _create_plugin(tmp_path: Path) -> tuple[Path, Path, str, Ed25519PrivateKey]:
    private_path, public_pem, private_key = _create_keypair(tmp_path)
    plugin_dir = tmp_path / "plugins" / "complete_bundle"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "Complete Bundle",
                "version": "1.0.0",
                "description": "Whole-plugin signature test",
                "type": "generic",
                "entry_point": "plugin.py",
                "capabilities": [],
                "dependencies": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        "from app.plugins.base import GenericPlugin\n"
        "from dupez_complete_bundle_helper import VALUE\n\n"
        "class CompleteBundlePlugin(GenericPlugin):\n"
        "    bundle_value = VALUE\n",
        encoding="utf-8",
    )
    (plugin_dir / "dupez_complete_bundle_helper.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (plugin_dir / "theme.json").write_text(
        '{"accent":"blue"}\n',
        encoding="utf-8",
    )
    sign_manifest(str(private_path), str(plugin_dir))
    return plugin_dir, private_path, public_pem, private_key


def _create_signed_source_plugin(
    tmp_path: Path,
    *,
    name: str,
    source: str,
    capabilities: list[str],
    dependencies: list[str] | None = None,
    plugin_type: str = "generic",
    min_dupez_version: object = "4.0.0",
) -> tuple[Path, str]:
    private_path, public_pem, _ = _create_keypair(tmp_path)
    plugin_dir = tmp_path / "plugins" / name.lower().replace(" ", "_")
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "description": "Plugin lifecycle sandbox test",
                "type": plugin_type,
                "entry_point": "plugin.py",
                "capabilities": capabilities,
                "dependencies": dependencies or [],
                "min_dupez_version": min_dupez_version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    sign_manifest(str(private_path), str(plugin_dir))
    return plugin_dir, public_pem


def _lifecycle_source(phase: str) -> str:
    event = "_probe_capability()"
    lines = [
        "import socket",
        "from app.plugins.base import GenericPlugin",
        "",
        "def _probe_capability():",
        "    probe = socket.socket()",
        "    try:",
        "        probe.connect(('127.0.0.1', 1))",
        "    except OSError:",
        "        pass",
        "    finally:",
        "        probe.close()",
        "",
    ]
    if phase == "top_level":
        lines.extend((event, ""))
    lines.append("class ScopedPlugin(GenericPlugin):")
    if phase == "constructor":
        lines.extend((
            "    def __init__(self):",
            "        super().__init__()",
            f"        {event}",
        ))
    elif phase == "activate":
        lines.extend((
            "    def activate(self, controller):",
            f"        {event}",
            "        return super().activate(controller)",
        ))
    elif phase == "deactivate":
        lines.extend((
            "    def deactivate(self):",
            f"        {event}",
            "        return super().deactivate()",
        ))
    else:
        lines.append("    pass")
    return "\n".join(lines) + "\n"


def _discover_loader(
    plugin_dir: Path,
    public_pem: str,
    monkeypatch: pytest.MonkeyPatch,
) -> PluginLoader:
    monkeypatch.setattr(plugin_signing, "TRUSTED_PUBKEYS_PEM", [public_pem])
    monkeypatch.delenv("DUPEZ_PLUGIN_DEV_MODE", raising=False)
    loader = PluginLoader(str(plugin_dir.parent))
    assert len(loader.discover()) == 1
    return loader


def test_signer_emits_v2_complete_sorted_inventory(tmp_path: Path) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)

    data = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    assert data["manifest_version"] == MANIFEST_VERSION == "2.0"
    assert "entry_sha384" not in data
    assert [item["path"] for item in data["files"]] == [
        "dupez_complete_bundle_helper.py",
        "plugin.py",
        "theme.json",
    ]

    verified = verify_plugin_manifest(
        str(plugin_dir / "manifest.json"),
        trusted_pubkeys_pem=[public_pem],
    )
    assert verified.sig_state is PluginSigState.VERIFIED
    assert tuple(item.path for item in verified.files) == tuple(
        item["path"] for item in data["files"]
    )
    assert verified.entry_sha384 == next(
        item["sha384"] for item in data["files"] if item["path"] == "plugin.py"
    )


@pytest.mark.parametrize("minimum", ("5.8", "5.8.0-01", 58))
def test_manifest_rejects_invalid_min_dupez_version(
    tmp_path: Path,
    minimum: object,
) -> None:
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name="Invalid Minimum",
        source=(
            "from app.plugins.base import GenericPlugin\n\n"
            "class InvalidMinimumPlugin(GenericPlugin):\n"
            "    pass\n"
        ),
        capabilities=[],
        min_dupez_version=minimum,
    )

    with pytest.raises(PluginSigError, match="min_dupez_version.*strict SemVer"):
        verify_plugin_manifest(
            str(plugin_dir / "manifest.json"),
            trusted_pubkeys_pem=[public_pem],
        )


def test_loader_rejects_incompatible_host_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "_dupez_incompatible_plugin_executed"
    monkeypatch.delattr(builtins, marker, raising=False)
    name = "Future Host"
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=(
            "import builtins\n"
            "from app.plugins.base import GenericPlugin\n"
            f"builtins.{marker} = True\n\n"
            "class FutureHostPlugin(GenericPlugin):\n"
            "    pass\n"
        ),
        capabilities=[],
        min_dupez_version="99.0.0",
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)

    assert loader.load_plugin(name) is None
    assert name not in loader.plugins
    assert not hasattr(builtins, marker)


@pytest.mark.parametrize(
    "activation_statement",
    ("return False", "raise RuntimeError('activation failed')"),
)
def test_failed_activation_is_deactivated_and_fully_unloaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    activation_statement: str,
) -> None:
    name = "Activation Rollback"
    source = (
        "from app.plugins.base import GenericPlugin\n\n"
        "class ActivationRollbackPlugin(GenericPlugin):\n"
        "    def activate(self, controller):\n"
        "        self.events = controller.events\n"
        "        self.events.append('activate')\n"
        f"        {activation_statement}\n\n"
        "    def deactivate(self):\n"
        "        self.events.append('deactivate')\n"
        "        return True\n"
    )
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=source,
        capabilities=[],
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)
    controller = types.SimpleNamespace(events=[])

    assert loader.load_plugin(name, controller=controller) is None
    assert controller.events == ["activate", "deactivate"]
    assert name not in loader.plugins
    assert "dupez_plugin_Activation_Rollback" not in sys.modules


@pytest.mark.parametrize(
    ("relative_path", "replacement"),
    [
        ("dupez_complete_bundle_helper.py", "VALUE = 2\n"),
        ("theme.json", '{"accent":"evil"}\n'),
    ],
)
def test_modified_helper_or_resource_is_rejected(
    tmp_path: Path,
    relative_path: str,
    replacement: str,
) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)
    (plugin_dir / relative_path).write_text(replacement, encoding="utf-8")

    with pytest.raises(PluginSigError, match=r"inventory mismatch.*changed"):
        verify_plugin_manifest(
            str(plugin_dir / "manifest.json"),
            trusted_pubkeys_pem=[public_pem],
        )


def test_unsigned_added_file_is_rejected(tmp_path: Path) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)
    (plugin_dir / "unsigned_helper.py").write_text("PAYLOAD = True\n", encoding="utf-8")

    with pytest.raises(PluginSigError, match=r"unexpected=.*unsigned_helper\.py"):
        verify_plugin_manifest(
            str(plugin_dir / "manifest.json"),
            trusted_pubkeys_pem=[public_pem],
        )


def test_missing_signed_file_is_rejected(tmp_path: Path) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)
    (plugin_dir / "theme.json").unlink()

    with pytest.raises(PluginSigError, match=r"missing=.*theme\.json"):
        verify_plugin_manifest(
            str(plugin_dir / "manifest.json"),
            trusted_pubkeys_pem=[public_pem],
        )


def test_authentic_legacy_entry_only_manifest_requires_resigning(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "legacy"
    plugin_dir.mkdir()
    entry = plugin_dir / "plugin.py"
    entry.write_text("VALUE = 1\n", encoding="utf-8")
    private_path, public_pem, private_key = _create_keypair(tmp_path)
    assert private_path.is_file()
    manifest_bytes = json.dumps(
        {
            "description": "Legacy entry-only bundle",
            "entry_point": "plugin.py",
            "entry_sha384": hashlib.sha384(entry.read_bytes()).hexdigest(),
            "name": "Legacy",
            "type": "generic",
            "version": "1.0.0",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    manifest_path = plugin_dir / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    (plugin_dir / "manifest.json.sig").write_bytes(
        pubkey_fingerprint(public_pem) + private_key.sign(manifest_bytes)
    )

    with pytest.raises(PluginSigError, match="legacy entry-only.*re-sign"):
        verify_plugin_manifest(
            str(manifest_path),
            trusted_pubkeys_pem=[public_pem],
        )


def test_loader_reverifies_helper_before_any_plugin_code_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)
    monkeypatch.setattr(plugin_signing, "TRUSTED_PUBKEYS_PEM", [public_pem])
    monkeypatch.delenv("DUPEZ_PLUGIN_DEV_MODE", raising=False)

    loader = PluginLoader(str(plugin_dir.parent))
    discovered = loader.discover()
    assert [manifest.name for manifest in discovered] == ["Complete Bundle"]

    execution_marker = tmp_path / "modified-helper-executed"
    (plugin_dir / "dupez_complete_bundle_helper.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(execution_marker)!r}).write_text('executed', encoding='utf-8')\n"
        "VALUE = 999\n",
        encoding="utf-8",
    )

    assert loader.load_plugin("Complete Bundle") is None
    assert not execution_marker.exists()


def test_loader_accepts_unchanged_complete_bundle_without_writing_bytecode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)
    monkeypatch.setattr(plugin_signing, "TRUSTED_PUBKEYS_PEM", [public_pem])
    monkeypatch.delenv("DUPEZ_PLUGIN_DEV_MODE", raising=False)

    loader = PluginLoader(str(plugin_dir.parent))
    assert len(loader.discover()) == 1

    stale_helper = types.ModuleType("dupez_complete_bundle_helper")
    stale_helper.__file__ = str(plugin_dir / "dupez_complete_bundle_helper.py")
    stale_helper.VALUE = 999
    monkeypatch.setitem(sys.modules, "dupez_complete_bundle_helper", stale_helper)

    loaded = loader.load_plugin("Complete Bundle")
    assert loaded is not None
    assert loaded.active is True
    assert loaded.instance.bundle_value == 1
    assert loaded.manifest.sig_state is PluginSigState.VERIFIED
    assert not (plugin_dir / "__pycache__").exists()
    loader.unload_all()
    assert "dupez_complete_bundle_helper" not in sys.modules


def test_failed_plugin_import_removes_partially_imported_signed_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir, private_path, public_pem, _ = _create_plugin(tmp_path)
    (plugin_dir / "plugin.py").write_text(
        "from dupez_complete_bundle_helper import VALUE\n"
        "raise RuntimeError('fixture import failure')\n",
        encoding="utf-8",
    )
    sign_manifest(str(private_path), str(plugin_dir))
    monkeypatch.setattr(plugin_signing, "TRUSTED_PUBKEYS_PEM", [public_pem])
    monkeypatch.delenv("DUPEZ_PLUGIN_DEV_MODE", raising=False)
    monkeypatch.delitem(sys.modules, "dupez_complete_bundle_helper", raising=False)

    loader = PluginLoader(str(plugin_dir.parent))
    assert len(loader.discover()) == 1
    assert loader.load_plugin("Complete Bundle") is None
    assert "dupez_complete_bundle_helper" not in sys.modules


def test_loader_preloads_fixed_uncached_stdlib_before_plugin_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "Uncached Fractions"
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=(
            "import fractions\n"
            "from app.plugins.base import GenericPlugin\n\n"
            "class FractionsPlugin(GenericPlugin):\n"
            "    numerator = fractions.Fraction(2, 4).numerator\n"
        ),
        capabilities=[],
    )
    monkeypatch.delitem(sys.modules, "fractions", raising=False)

    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)
    assert "fractions" in sys.modules
    loaded = loader.load_plugin(name)

    assert loaded is not None
    assert loaded.active is True
    assert loaded.instance.numerator == 1
    loader.unload_all()


def test_loader_rejects_manifest_dependencies_until_exact_contract_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "External Dependency"
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=(
            "from app.plugins.base import GenericPlugin\n\n"
            "class DependencyPlugin(GenericPlugin):\n"
            "    pass\n"
        ),
        capabilities=[],
        dependencies=["requests>=2"],
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)

    assert loader.load_plugin(name) is None


def test_loader_rejects_local_module_name_owned_by_another_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_dir, _, public_pem, _ = _create_plugin(tmp_path)
    monkeypatch.setattr(plugin_signing, "TRUSTED_PUBKEYS_PEM", [public_pem])
    monkeypatch.delenv("DUPEZ_PLUGIN_DEV_MODE", raising=False)
    conflicting_helper = types.ModuleType("dupez_complete_bundle_helper")
    conflicting_helper.__file__ = str(tmp_path / "different_plugin" / "helper.py")
    conflicting_helper.VALUE = 999
    monkeypatch.setitem(sys.modules, "dupez_complete_bundle_helper", conflicting_helper)

    loader = PluginLoader(str(plugin_dir.parent))
    assert len(loader.discover()) == 1
    assert loader.load_plugin("Complete Bundle") is None


@pytest.mark.parametrize("phase", ("top_level", "constructor", "activate"))
def test_loader_denies_undeclared_capability_through_initial_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    name = f"Denied {phase}"
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=_lifecycle_source(phase),
        capabilities=[],
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)

    assert loader.load_plugin(name) is None
    assert name not in loader.plugins


@pytest.mark.parametrize("phase", ("top_level", "constructor", "activate"))
def test_loader_allows_declared_capability_through_initial_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    name = f"Allowed {phase}"
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=_lifecycle_source(phase),
        capabilities=["network.scan"],
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)

    loaded = loader.load_plugin(name)
    assert loaded is not None
    assert loaded.active is True
    assert loader.unload_plugin(name) is True


@pytest.mark.parametrize(
    ("capabilities", "expected_unloaded"),
    [
        ([], False),
        (["network.scan"], True),
    ],
)
def test_loader_enforces_declared_capability_during_deactivate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capabilities: list[str],
    expected_unloaded: bool,
) -> None:
    name = "Deactivate " + ("Allowed" if capabilities else "Denied")
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=_lifecycle_source("deactivate"),
        capabilities=capabilities,
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)
    loaded = loader.load_plugin(name)
    assert loaded is not None and loaded.active is True

    assert loader.unload_plugin(name) is expected_unloaded
    assert (name not in loader.plugins) is expected_unloaded

    # A rejected deactivation deliberately leaves the live instance registered
    # for diagnosis/retry. Remove only the test fixture's module references.
    if not expected_unloaded:
        loader.plugins.pop(name)
        for module_name in loaded.module_names:
            sys.modules.pop(module_name, None)


def test_false_deactivate_retains_live_plugin_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "Refuses Deactivation"
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=(
            "from app.plugins.base import GenericPlugin\n\n"
            "class RefusingPlugin(GenericPlugin):\n"
            "    def deactivate(self):\n"
            "        return False\n"
        ),
        capabilities=[],
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)
    loaded = loader.load_plugin(name)
    assert loaded is not None and loaded.active is True

    assert loader.unload_plugin(name) is False
    assert loader.plugins[name] is loaded
    assert loaded.active is True
    assert loaded.module_name in sys.modules

    loader.plugins.pop(name)
    for module_name in loaded.module_names:
        sys.modules.pop(module_name, None)


def test_unload_all_attempts_every_plugin_and_aggregates_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = PluginLoader(str(tmp_path))
    loader.plugins = {"first": object(), "second": object()}
    attempts: list[str] = []

    def unload(name: str) -> bool:
        attempts.append(name)
        return name == "second"

    monkeypatch.setattr(loader, "unload_plugin", unload)

    assert loader.unload_all() is False
    assert attempts == ["first", "second"]


@pytest.mark.parametrize(
    "dynamic_statement",
    (
        "exec(\"DYNAMIC_VALUE = 1\")",
        "eval(\"40 + 2\")",
        "exec(compile(\"DYNAMIC_VALUE = 1\", __file__, \"exec\"))",
        "exec((lambda: 42).__code__)",
    ),
)
def test_verified_code_scope_still_denies_dynamic_exec_and_eval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dynamic_statement: str,
) -> None:
    name = "Dynamic Code Denied"
    source = (
        "from app.plugins.base import GenericPlugin\n"
        f"{dynamic_statement}\n\n"
        "class DynamicCodePlugin(GenericPlugin):\n"
        "    pass\n"
    )
    plugin_dir, public_pem = _create_signed_source_plugin(
        tmp_path,
        name=name,
        source=source,
        capabilities=["network.http"],
    )
    loader = _discover_loader(plugin_dir, public_pem, monkeypatch)

    assert loader.load_plugin(name) is None
    assert name not in loader.plugins


def test_signer_refuses_generated_bytecode(tmp_path: Path) -> None:
    private_path, _, _ = _create_keypair(tmp_path)
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "__pycache__").mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "Bytecode",
                "version": "1.0.0",
                "description": "Bytecode rejection",
                "type": "generic",
                "entry_point": "plugin.py",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
    (plugin_dir / "__pycache__" / "plugin.pyc").write_bytes(b"not trusted")

    with pytest.raises(PluginSigError, match="generated bytecode"):
        sign_manifest(str(private_path), str(plugin_dir))
