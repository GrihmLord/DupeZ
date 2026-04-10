"""Tests for app.core.profiles — profile CRUD and import/export."""

import json
import os
from app.core.profiles import ProfileManager, DisruptionProfile


class TestProfileManager:
    """Test ProfileManager save/load/delete/list lifecycle."""

    def test_save_and_load(self, profiles_dir):
        """Save a profile and load it back."""
        pm = ProfileManager(profiles_dir=profiles_dir)
        pm.save("test_preset", methods=["lag", "drop"],
                params={"lag_delay": 1500, "drop_chance": 90})

        loaded = pm.load("test_preset")
        assert loaded is not None
        assert loaded.name == "test_preset"
        assert loaded.methods == ["lag", "drop"]
        assert loaded.params["lag_delay"] == 1500

    def test_list_profiles(self, profiles_dir):
        """list_profiles returns all saved profiles."""
        pm = ProfileManager(profiles_dir=profiles_dir)
        pm.save("alpha", methods=["lag"], params={})
        pm.save("beta", methods=["drop"], params={})

        profiles = pm.list_profiles()
        names = [p.name for p in profiles]
        assert "alpha" in names
        assert "beta" in names

    def test_delete(self, profiles_dir):
        """delete removes a profile."""
        pm = ProfileManager(profiles_dir=profiles_dir)
        pm.save("to_delete", methods=["lag"], params={})
        assert pm.load("to_delete") is not None

        pm.delete("to_delete")
        assert pm.load("to_delete") is None

    def test_load_nonexistent(self, profiles_dir):
        """Loading a nonexistent profile returns None."""
        pm = ProfileManager(profiles_dir=profiles_dir)
        assert pm.load("does_not_exist") is None

    def test_export_and_import(self, profiles_dir, tmp_path):
        """Export a profile to JSON and import it back."""
        pm = ProfileManager(profiles_dir=profiles_dir)
        pm.save("exportable", methods=["throttle"],
                params={"throttle_chance": 80}, description="test export")

        export_path = str(tmp_path / "exported.json")
        result = pm.export_profile("exportable", export_path)
        assert result is True
        assert os.path.exists(export_path)

        # Import into a fresh manager
        pm2 = ProfileManager(profiles_dir=str(tmp_path / "profiles2"))
        imported = pm2.import_profile(export_path)
        assert imported is not None
        assert imported.name == "exportable"
        assert imported.methods == ["throttle"]

    def test_save_overwrites(self, profiles_dir):
        """Saving with same name updates the profile."""
        pm = ProfileManager(profiles_dir=profiles_dir)
        pm.save("update_me", methods=["lag"], params={"lag_delay": 500})
        pm.save("update_me", methods=["drop"], params={"drop_chance": 100})

        loaded = pm.load("update_me")
        assert loaded.methods == ["drop"]
        assert loaded.params["drop_chance"] == 100


class TestDisruptionProfile:
    """Test DisruptionProfile dataclass."""

    def test_to_dict(self):
        """to_dict returns all fields."""
        p = DisruptionProfile(name="test", methods=["lag"])
        d = p.to_dict()
        assert d["name"] == "test"
        assert d["methods"] == ["lag"]

    def test_from_dict(self):
        """from_dict creates profile from dict."""
        d = {"name": "test", "methods": ["drop"], "params": {"drop_chance": 50}}
        p = DisruptionProfile.from_dict(d)
        assert p.name == "test"
        assert p.methods == ["drop"]

    def test_from_dict_ignores_unknown(self):
        """from_dict ignores unknown keys."""
        d = {"name": "test", "unknown_field": True}
        p = DisruptionProfile.from_dict(d)
        assert p.name == "test"
