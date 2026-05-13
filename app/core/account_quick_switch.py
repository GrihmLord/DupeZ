"""Multi-account quick-switch (v5.7.1 feature #9).

Lightweight active-account tracker. Maintains the notion of "which
account is the operator currently playing on" and tags subsequent
disruptions / episode records with that account name. UI can cycle
through tracker accounts via a global hotkey (registered in the GUI
layer; this module is GUI-agnostic).

Why this exists:
The account tracker already stores account metadata (name, email,
location, status, etc.). The episode recorder writes per-cut telemetry
but has no notion of WHICH account the cut was for. Without this
linkage, the post-session "dupe history" is ambiguous when an operator
ran multiple accounts in the same play session.

API:

    get_active_account() -> Optional[str]
    set_active_account(name: str) -> bool
    cycle_active_account(direction: int = 1) -> Optional[str]
    clear_active_account() -> None

The active selection is persisted to ``app/data/active_account.json``
so it survives restart.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from app.logs.logger import log_info, log_warning


__all__ = [
    "get_active_account",
    "set_active_account",
    "cycle_active_account",
    "clear_active_account",
    "active_account_names",
]


_DATA_TYPE = "active_account"
_lock = threading.Lock()
_cached_name: Optional[str] = None
_cache_loaded = False


def _load() -> Optional[str]:
    """Load the active-account name from disk. None when unset."""
    global _cached_name, _cache_loaded
    if _cache_loaded:
        return _cached_name
    try:
        from app.core.data_persistence import persistence_manager
        data = persistence_manager.load_data(_DATA_TYPE, default=None)
    except Exception as exc:
        log_warning(f"active_account: load failed: {exc}")
        data = None
    if isinstance(data, dict) and isinstance(data.get("name"), str):
        _cached_name = data["name"] or None
    else:
        _cached_name = None
    _cache_loaded = True
    return _cached_name


def _save(name: Optional[str]) -> bool:
    try:
        from app.core.data_persistence import persistence_manager
        return bool(persistence_manager.save_data(
            _DATA_TYPE, {"name": name or ""}, force=True
        ))
    except Exception as exc:
        log_warning(f"active_account: save failed: {exc}")
        return False


def active_account_names() -> List[str]:
    """Return the list of account names from the tracker, in order.

    Read-only convenience for the cycle hotkey — avoids the GUI
    layer needing to import the account_manager itself.
    """
    try:
        from app.core.data_persistence import account_manager
        return [
            str(a.get("account", "")).strip()
            for a in account_manager.accounts
            if str(a.get("account", "")).strip()
        ]
    except Exception as exc:
        log_warning(f"active_account: list failed: {exc}")
        return []


def get_active_account() -> Optional[str]:
    """Return the currently-active account name, or None if unset."""
    with _lock:
        return _load()


def set_active_account(name: str) -> bool:
    """Mark *name* as the active account. Returns True on persist success.

    Validates that *name* exists in the tracker — refuses to set an
    active account that isn't in the persisted account list (prevents
    typos from silently tagging episodes with a phantom name).
    """
    global _cached_name, _cache_loaded
    name = (name or "").strip()
    if not name:
        return False
    if name not in active_account_names():
        log_warning(
            f"active_account: refusing to set {name!r} — not in tracker"
        )
        return False
    with _lock:
        if not _save(name):
            return False
        _cached_name = name
        _cache_loaded = True
    log_info(f"active account set: {name}")
    return True


def cycle_active_account(direction: int = 1) -> Optional[str]:
    """Move the active selection forward (+1) or backward (-1) by one.

    If no active account is set, jumps to the first account. If the
    current active account no longer exists in the tracker (deleted
    after being set), restarts at the first account.
    """
    names = active_account_names()
    if not names:
        return None
    direction = 1 if direction >= 0 else -1
    with _lock:
        current = _load()
        if current is None or current not in names:
            new_idx = 0
        else:
            new_idx = (names.index(current) + direction) % len(names)
        new_name = names[new_idx]
        if _save(new_name):
            global _cached_name, _cache_loaded
            _cached_name = new_name
            _cache_loaded = True
    log_info(f"active account cycled: {new_name}")
    return new_name


def clear_active_account() -> None:
    """Unset the active-account marker.

    Persists ``{"name": ""}`` to disk (not literal null) so the on-disk
    schema stays a JSON object with a string field — consistent with
    every other persisted setting in DupeZ. The reader treats empty
    string as "not set" so the round-trip yields ``None``.
    """
    global _cached_name, _cache_loaded
    with _lock:
        _save(None)  # _save normalizes None → "" before persisting
        _cached_name = None
        _cache_loaded = True
    log_info("active account cleared")
