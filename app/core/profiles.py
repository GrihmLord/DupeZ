#!/usr/bin/env python3
"""
Disruption Profile System — save/load/share named disruption configs.

Profiles are stored as JSON files in ``app/data/profiles/``.
Each profile contains:
  - name, description, author
  - methods list + params dict (same format as PRESETS)
  - optional: target device type, connection type hints
  - metadata: created, modified, use_count

Profiles can be created from the current UI state, from SmartEngine
recommendations, or imported/exported as standalone JSON files.
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, List, Optional

from app.logs.logger import log_error, log_info


# ── Data model ────────────────────────────────────────────────────────

@dataclass
class DisruptionProfile:
    """A named, saveable disruption configuration."""

    name: str = ""
    description: str = ""
    author: str = ""

    # Disruption config
    methods: List[str] = field(default_factory=list)
    params: Dict = field(default_factory=dict)

    # Hints for smart matching
    target_device_type: str = ""      # console, pc, mobile, etc.
    target_connection_type: str = ""  # hotspot, lan, wan
    game_hint: str = ""              # DayZ, Fortnite, etc.

    # Metadata
    created: float = 0.0
    modified: float = 0.0
    use_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DisruptionProfile":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── Profile manager ──────────────────────────────────────────────────

class ProfileManager:
    """CRUD + import/export for disruption profiles.

    Usage::

        pm = ProfileManager()
        pm.save("my_preset", methods=["lag", "drop"], params={...})
        profile = pm.load("my_preset")
        all_profiles = pm.list_profiles()
        pm.export_profile("my_preset", "/path/to/share.json")
        pm.import_profile("/path/to/share.json")
    """

    def __init__(self, profiles_dir: str = "") -> None:
        if not profiles_dir:
            from app.core.data_persistence import _resolve_data_directory
            profiles_dir = os.path.join(_resolve_data_directory(), "profiles")
        self.profiles_dir = profiles_dir
        os.makedirs(profiles_dir, exist_ok=True)

    # ── Path helpers ──────────────────────────────────────────────

    def _profile_path(self, name: str) -> str:
        """Return the filesystem path for a profile name."""
        safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)
        safe = safe.strip().replace(" ", "_")
        return os.path.join(self.profiles_dir, f"{safe}.json")

    # ── CRUD ──────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        methods: List[str],
        params: Dict,
        description: str = "",
        author: str = "",
        device_type: str = "",
        connection_type: str = "",
        game_hint: str = "",
    ) -> DisruptionProfile:
        """Save or update a profile.  Returns the persisted profile."""
        path = self._profile_path(name)
        existing = self._load_file(path)
        now = time.time()

        profile = DisruptionProfile(
            name=name,
            description=description or (existing.description if existing else ""),
            author=author or (existing.author if existing else ""),
            methods=methods,
            params=params,
            target_device_type=device_type,
            target_connection_type=connection_type,
            game_hint=game_hint,
            created=existing.created if existing else now,
            modified=now,
            use_count=existing.use_count if existing else 0,
        )

        self._save_file(path, profile)
        log_info(f"ProfileManager: saved profile '{name}'")
        return profile

    def load(self, name: str) -> Optional[DisruptionProfile]:
        """Load a profile by name and increment its use count."""
        path = self._profile_path(name)
        profile = self._load_file(path)
        if profile:
            profile.use_count += 1
            self._save_file(path, profile)
            log_info(f"ProfileManager: loaded profile '{name}' (uses: {profile.use_count})")
        return profile

    def delete(self, name: str) -> bool:
        """Delete a profile by name.  Returns True on success."""
        path = self._profile_path(name)
        try:
            if os.path.exists(path):
                os.remove(path)
                log_info(f"ProfileManager: deleted profile '{name}'")
                return True
        except Exception as e:
            log_error(f"ProfileManager: failed to delete '{name}': {e}")
        return False

    def list_profiles(self) -> List[DisruptionProfile]:
        """Return all profiles sorted by most recently modified."""
        profiles: List[DisruptionProfile] = []
        try:
            for filename in os.listdir(self.profiles_dir):
                if filename.endswith(".json"):
                    path = os.path.join(self.profiles_dir, filename)
                    profile = self._load_file(path)
                    if profile:
                        profiles.append(profile)
        except Exception as e:
            log_error(f"ProfileManager: failed to list profiles: {e}")

        profiles.sort(key=lambda p: p.modified, reverse=True)
        return profiles

    # ── Import / export ───────────────────────────────────────────

    def export_profile(self, name: str, export_path: str) -> bool:
        """Export a profile to a standalone JSON file."""
        profile = self.load(name)
        if not profile:
            return False
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, indent=2)
            log_info(f"ProfileManager: exported '{name}' to {export_path}")
            return True
        except Exception as e:
            log_error(f"ProfileManager: export failed: {e}")
            return False

    def import_profile(self, import_path: str) -> Optional[DisruptionProfile]:
        """Import a profile from a JSON file."""
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profile = DisruptionProfile.from_dict(data)
            if not profile.name:
                profile.name = os.path.splitext(os.path.basename(import_path))[0]
            self._save_file(self._profile_path(profile.name), profile)
            log_info(f"ProfileManager: imported profile '{profile.name}'")
            return profile
        except Exception as e:
            log_error(f"ProfileManager: import failed: {e}")
            return None

    # ── File I/O (atomic write) ───────────────────────────────────

    def _save_file(self, path: str, profile: DisruptionProfile) -> None:
        """Atomic write: tmp -> fsync -> replace."""
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception as e:
            log_error(f"ProfileManager: save failed: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _load_file(self, path: str) -> Optional[DisruptionProfile]:
        """Load a profile from disk.  Returns None on any failure."""
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return DisruptionProfile.from_dict(data)
        except Exception as e:
            log_error(f"ProfileManager: load failed ({path}): {e}")
        return None
