"""Tests for app.core.data_persistence — CollectionManager and managers."""

import json
import os
from unittest.mock import patch, MagicMock
from app.core.data_persistence import CollectionManager


class TestCollectionManager:
    """Test CollectionManager CRUD operations.

    CollectionManager uses AutoSaveMixin which delegates to a global
    persistence_manager. We mock save/load to isolate the logic.
    """

    def _make_cm(self):
        """Create a CollectionManager with mocked persistence."""
        with patch("app.core.data_persistence.persistence_manager") as mock_pm:
            mock_pm.load_data.return_value = []
            mock_pm.save_data.return_value = True
            mock_pm.mark_dirty.return_value = None
            cm = CollectionManager("test_data", key_field="id")
        # Replace the save method so subsequent calls don't need the patch active
        cm.save_changes = MagicMock(return_value=True)
        return cm

    def test_add(self):
        """Add an item and verify it's in the items list."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        assert len(cm.items) == 1
        assert cm.items[0]["name"] == "alpha"

    def test_add_multiple(self):
        """Add multiple items."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.add({"id": "2", "name": "beta"})
        assert len(cm.items) == 2

    def test_remove(self):
        """Remove an item by key value."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.add({"id": "2", "name": "beta"})
        cm.remove("1")
        assert len(cm.items) == 1
        assert cm.items[0]["id"] == "2"

    def test_remove_nonexistent(self):
        """Remove with nonexistent key doesn't crash."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.remove("999")
        assert len(cm.items) == 1

    def test_update(self):
        """Update modifies matching item."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha", "value": 10})
        cm.update("1", {"value": 42})
        assert cm.items[0]["value"] == 42

    def test_update_nonexistent(self):
        """Update with nonexistent key is a no-op."""
        cm = self._make_cm()
        cm.add({"id": "1", "name": "alpha"})
        cm.update("999", {"name": "ghost"})
        assert cm.items[0]["name"] == "alpha"

    def test_items_starts_empty(self):
        """New CollectionManager starts with empty items."""
        cm = self._make_cm()
        assert cm.items == []

    def test_save_called_on_add(self):
        """save_changes is called when adding an item."""
        cm = self._make_cm()
        cm.add({"id": "1"})
        cm.save_changes.assert_called()

    def test_save_called_on_remove(self):
        """save_changes is called when removing an item."""
        cm = self._make_cm()
        cm.add({"id": "1"})
        cm.save_changes.reset_mock()
        cm.remove("1")
        cm.save_changes.assert_called()
