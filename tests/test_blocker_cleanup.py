from types import SimpleNamespace

from app.firewall import blocker
from app.firewall_helper import feature_flag


def _configure_local_windows_cleanup(monkeypatch, rule_names):
    monkeypatch.setattr(feature_flag, "is_split_mode", lambda: False)
    monkeypatch.setattr(blocker, "is_admin", lambda: True)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(blocker, "_resolve_netsh", lambda: "netsh.exe")
    stdout = "\n".join(f"Rule Name: {name}" for name in rule_names)
    monkeypatch.setattr(
        blocker._safe_sp,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=stdout,
            returncode=0,
        ),
    )


def test_clear_all_dupez_blocks_returns_false_on_partial_delete(monkeypatch):
    names = ["DupeZBlock_10.0.0.1_In", "DupeZBlock_10.0.0.1_Out"]
    _configure_local_windows_cleanup(monkeypatch, names)
    results = iter([True, False])
    monkeypatch.setattr(blocker, "_netsh", lambda *_args, **_kwargs: next(results))

    assert blocker.clear_all_dupez_blocks() is False


def test_clear_all_dupez_blocks_returns_true_when_every_delete_succeeds(
    monkeypatch,
):
    names = ["DupeZBlock_10.0.0.1_In", "DupeZBlock_10.0.0.1_Out"]
    _configure_local_windows_cleanup(monkeypatch, names)
    monkeypatch.setattr(blocker, "_netsh", lambda *_args, **_kwargs: True)

    assert blocker.clear_all_dupez_blocks() is True
