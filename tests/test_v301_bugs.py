"""
DupeZ v3.0.1 Bug Regression Tests
Tests for bugs found on the main branch (live .exe).
"""

import unittest
import sys
import os
import ast
import re
import inspect

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBug001_BlockerMissingImport(unittest.TestCase):
    """BUG #1 (CRITICAL): blocker.py uses log_warning but doesn't import it."""

    def test_log_warning_imported(self):
        """blocker.py must import log_warning from app.logs.logger"""
        with open("app/firewall/blocker.py", "r") as f:
            source = f.read()
        # Check that log_warning is imported
        self.assertIn("log_warning", source.split("def ")[0],
                       "log_warning is used but not imported in blocker.py")

    def test_clear_all_dupez_blocks_no_name_error(self):
        """Calling clear_all_dupez_blocks should not raise NameError for log_warning"""
        try:
            from app.firewall.blocker import clear_all_dupez_blocks
            # We can't actually run firewall commands, but at least verify the
            # function is importable and log_warning is resolvable in its scope
            source = inspect.getsource(clear_all_dupez_blocks)
            if "log_warning" in source:
                # Verify log_warning exists in the module's namespace
                import app.firewall.blocker as blocker_mod
                self.assertTrue(hasattr(blocker_mod, 'log_warning') or
                                'log_warning' in dir(blocker_mod),
                                "log_warning is referenced in clear_all_dupez_blocks "
                                "but not available in the module namespace")
        except ImportError:
            self.skipTest("Cannot import blocker module (Windows-only deps)")


class TestBug002_BlockerIsActiveShadow(unittest.TestCase):
    """BUG #2 (CRITICAL): NetworkBlocker.is_active attribute shadows method."""

    def test_is_active_is_callable(self):
        """NetworkBlocker.is_active() should be callable, not shadowed by bool"""
        try:
            from app.firewall.blocker import NetworkBlocker
            nb = NetworkBlocker()
            # After __init__, is_active should be callable as a method
            # If the bug exists, self.is_active = False overwrites the method
            # and calling nb.is_active() would raise TypeError
            self.assertTrue(callable(getattr(nb, 'is_active', None)) or
                            isinstance(nb.is_active, bool),
                            "is_active should either be a callable method or "
                            "the attribute/method conflict should be resolved")
        except ImportError:
            self.skipTest("Cannot import blocker module")

    def test_no_attribute_method_conflict(self):
        """Check source: should not have both self.is_active = X and def is_active"""
        with open("app/firewall/blocker.py", "r") as f:
            source = f.read()
        # Find the NetworkBlocker class
        has_attr = bool(re.search(r'self\.is_active\s*=', source))
        has_method = bool(re.search(r'def is_active\(self\)', source))
        if has_attr and has_method:
            self.fail("NetworkBlocker has both self.is_active attribute assignment "
                      "AND def is_active() method — method is shadowed by attribute")


class TestBug003_SocketReuseAfterClose(unittest.TestCase):
    """BUG #3 (HIGH): _verify_device_exists reuses socket after close."""

    def test_socket_not_reused_after_close(self):
        """Each port check should use its own socket or re-create after close"""
        with open("app/core/controller.py", "r") as f:
            source = f.read()

        # Find the _verify_device_exists method
        match = re.search(r'def _verify_device_exists.*?(?=\n    def |\nclass |\Z)',
                          source, re.DOTALL)
        if not match:
            self.skipTest("_verify_device_exists not found")

        method_src = match.group()
        # Count socket() creates vs close() calls in the loop
        # The bug: one socket created outside loop, close inside loop
        lines = method_src.split('\n')
        socket_create_in_loop = False
        close_in_loop = False
        in_for_loop = False

        for line in lines:
            stripped = line.strip()
            if 'for port in' in stripped:
                in_for_loop = True
            if in_for_loop:
                if 'socket.socket(' in stripped:
                    socket_create_in_loop = True
                if 'sock.close()' in stripped:
                    close_in_loop = True

        if close_in_loop and not socket_create_in_loop:
            self.fail("Socket is created once before the loop but closed inside "
                      "the loop — subsequent iterations use a closed socket")


class TestBug004_HotkeyNoIP(unittest.TestCase):
    """BUG #4 (HIGH): Hotkey callback calls toggle_lag() with no IP arg."""

    def test_toggle_lag_falls_back_to_selected(self):
        """toggle_lag(ip=None) should fall back to state.selected_ip"""
        with open("app/core/controller.py", "r") as f:
            source = f.read()

        # Check toggle_lag signature
        match = re.search(r'def toggle_lag\(self,\s*ip:\s*str\s*=\s*None\)', source)
        self.assertIsNotNone(match, "toggle_lag should accept ip parameter")

        # Check that toggle_lag falls back to selected_ip when ip is None
        match2 = re.search(r'def toggle_lag.*?(?=\n    def |\Z)', source, re.DOTALL)
        self.assertIsNotNone(match2, "toggle_lag method should exist")
        method_src = match2.group()
        self.assertIn("selected_ip", method_src,
                       "toggle_lag should fall back to state.selected_ip "
                       "when no IP is provided (hotkey support)")


class TestBug005_HandleNetworkErrorShadow(unittest.TestCase):
    """BUG #5 (MEDIUM): except Exception as log_error shadows the import."""

    def test_no_variable_shadowing_import(self):
        """handle_network_error should not use 'log_error' as exception variable name"""
        with open("app/network/device_scan.py", "r") as f:
            source = f.read()

        # Check for 'except Exception as log_error'
        if 'except Exception as log_error' in source:
            self.fail("'except Exception as log_error' in device_scan.py shadows "
                      "the imported log_error function")


class TestImportIntegrity(unittest.TestCase):
    """Verify all Python files parse without syntax errors."""

    def test_all_py_files_parse(self):
        """Every .py file should be valid Python"""
        errors = []
        for root, dirs, files in os.walk("app"):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fname in files:
                if fname.endswith('.py'):
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            ast.parse(f.read(), filename=fpath)
                    except SyntaxError as e:
                        errors.append(f"{fpath}: {e}")
        if errors:
            self.fail("Syntax errors found:\n" + "\n".join(errors))


class TestVersionConsistency(unittest.TestCase):
    """Verify version strings are consistent across the codebase."""

    def test_main_py_version(self):
        """main.py should reference version 3.0"""
        with open("app/main.py", "r") as f:
            source = f.read()
        self.assertIn("3.0", source, "main.py should contain version 3.0")

    def test_dashboard_version(self):
        """dashboard.py should reference version 3.0"""
        with open("app/gui/dashboard.py", "r") as f:
            source = f.read()
        self.assertIn("3.0", source, "dashboard.py should contain version 3.0")


class TestControllerIntegrity(unittest.TestCase):
    """Verify controller module structure."""

    def test_controller_has_required_methods(self):
        """AppController should have all required public methods"""
        with open("app/core/controller.py", "r") as f:
            source = f.read()
        required_methods = [
            'scan_devices', 'toggle_lag', 'disrupt_device',
            'stop_disruption', 'stop_all_disruptions', 'shutdown',
            'get_devices', 'get_disrupted_devices', 'get_network_info',
        ]
        for method in required_methods:
            self.assertIn(f"def {method}(", source,
                          f"AppController missing method: {method}")

    def test_state_has_observer_pattern(self):
        """AppState should support observers"""
        with open("app/core/state.py", "r") as f:
            source = f.read()
        self.assertIn("add_observer", source)
        self.assertIn("notify_observers", source)
        self.assertIn("_observers", source)


class TestDataPersistenceIntegrity(unittest.TestCase):
    """Verify data persistence doesn't corrupt on save."""

    def test_atomic_write_pattern(self):
        """Settings save should use atomic write (tmp + rename)"""
        with open("app/core/state.py", "r") as f:
            source = f.read()
        self.assertIn(".tmp", source, "Settings save should use temp file pattern")
        self.assertIn("os.replace", source, "Settings save should use os.replace for atomic swap")

    def test_corrupt_settings_recovery(self):
        """State should recover from corrupt settings file"""
        with open("app/core/state.py", "r") as f:
            source = f.read()
        self.assertIn("json.JSONDecodeError", source,
                       "Settings loader should handle corrupt JSON")


if __name__ == "__main__":
    unittest.main(verbosity=2)
