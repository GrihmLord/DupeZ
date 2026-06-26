#!/usr/bin/env python3
"""Tests for public directional diagnostic presets."""

import unittest

from app.firewall.asymmetric_presets import (
    ALL_PRESETS,
    PUBLIC_METHODS,
    AsymmetricConfigBuilder,
    BIDIRECTIONAL_DEGRADE,
    INBOUND_JITTER,
    OUTBOUND_LOSS,
    get_preset,
    get_preset_names,
    list_presets,
)


QUARANTINED_METHODS = {
    "godmode",
    "pulse",
    "tick_sync",
    "stealth_drop",
    "stealth_lag",
}


class TestAsymmetricPreset(unittest.TestCase):
    def test_to_engine_config(self):
        config = INBOUND_JITTER.to_engine_config()
        self.assertEqual(config["methods"], ["lag"])
        self.assertEqual(config["params"]["lag_direction"], "inbound")

    def test_config_is_deep_copy(self):
        config = INBOUND_JITTER.to_engine_config()
        config["params"]["lag_delay"] = 9999
        fresh = INBOUND_JITTER.to_engine_config()
        self.assertEqual(fresh["params"]["lag_delay"], 250)


class TestPresetRegistry(unittest.TestCase):
    def test_all_presets_populated(self):
        self.assertGreaterEqual(len(ALL_PRESETS), 6)

    def test_get_preset_case_insensitive(self):
        preset = get_preset("INBOUND_JITTER")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.name, "Inbound Jitter Diagnostic")

    def test_get_preset_unknown(self):
        self.assertIsNone(get_preset("nonexistent_preset"))

    def test_legacy_names_are_not_public_presets(self):
        for name in QUARANTINED_METHODS:
            self.assertIsNone(get_preset(name))
            self.assertNotIn(name, get_preset_names())

    def test_list_presets_all(self):
        presets = list_presets()
        self.assertGreaterEqual(len(presets), 6)

    def test_list_presets_by_category(self):
        diagnostic = list_presets("diagnostic")
        self.assertGreaterEqual(len(diagnostic), 3)
        for preset in diagnostic:
            self.assertEqual(preset.category, "diagnostic")

    def test_all_presets_only_use_public_methods(self):
        for name, preset in ALL_PRESETS.items():
            self.assertGreater(len(preset.methods), 0)
            self.assertLessEqual(set(preset.methods), PUBLIC_METHODS, name)
            self.assertTrue(set(preset.methods).isdisjoint(QUARANTINED_METHODS), name)

    def test_all_presets_have_params(self):
        for name, preset in ALL_PRESETS.items():
            self.assertIsInstance(preset.params, dict, name)

    def test_effectiveness_range(self):
        for preset in ALL_PRESETS.values():
            self.assertGreaterEqual(preset.effectiveness, 0.0)
            self.assertLessEqual(preset.effectiveness, 1.0)

    def test_detectability_range(self):
        for preset in ALL_PRESETS.values():
            self.assertGreaterEqual(preset.detectability, 0.0)
            self.assertLessEqual(preset.detectability, 1.0)


class TestPresetContent(unittest.TestCase):
    def test_inbound_jitter(self):
        self.assertEqual(INBOUND_JITTER.methods, ["lag"])
        self.assertEqual(INBOUND_JITTER.params["lag_direction"], "inbound")

    def test_outbound_loss(self):
        self.assertEqual(OUTBOUND_LOSS.methods, ["drop"])
        self.assertEqual(OUTBOUND_LOSS.params["drop_direction"], "outbound")

    def test_bidirectional_degrade(self):
        self.assertEqual(BIDIRECTIONAL_DEGRADE.methods, ["drop", "lag"])
        self.assertEqual(BIDIRECTIONAL_DEGRADE.params["direction"], "both")


class TestAsymmetricConfigBuilder(unittest.TestCase):
    def test_add_inbound(self):
        config = (
            AsymmetricConfigBuilder()
            .add_inbound("lag", lag_delay=500)
            .build()
        )
        self.assertIn("lag", config["methods"])
        self.assertEqual(config["params"]["lag_direction"], "inbound")
        self.assertEqual(config["params"]["lag_delay"], 500)

    def test_add_outbound(self):
        config = (
            AsymmetricConfigBuilder()
            .add_outbound("drop", drop_chance=80)
            .build()
        )
        self.assertEqual(config["params"]["drop_direction"], "outbound")

    def test_add_both(self):
        config = (
            AsymmetricConfigBuilder()
            .add_both("corrupt", tamper_chance=10)
            .build()
        )
        self.assertEqual(config["params"]["corrupt_direction"], "both")

    def test_from_preset(self):
        config = (
            AsymmetricConfigBuilder()
            .from_preset("inbound_jitter")
            .set_param("lag_delay", 300)
            .build()
        )
        self.assertIn("lag", config["methods"])
        self.assertEqual(config["params"]["lag_delay"], 300)

    def test_rejects_quarantined_method(self):
        with self.assertRaises(ValueError):
            AsymmetricConfigBuilder().add_inbound("godmode")

    def test_rejects_quarantined_param(self):
        with self.assertRaises(ValueError):
            AsymmetricConfigBuilder().set_param("godmode_lag_ms", 3000)

    def test_multi_module(self):
        config = (
            AsymmetricConfigBuilder()
            .add_inbound("lag", lag_delay=200)
            .add_outbound("drop", drop_chance=50)
            .add_both("corrupt", tamper_chance=5)
            .build()
        )
        self.assertEqual(len(config["methods"]), 3)
        self.assertEqual(config["params"]["lag_direction"], "inbound")
        self.assertEqual(config["params"]["drop_direction"], "outbound")
        self.assertEqual(config["params"]["corrupt_direction"], "both")


if __name__ == "__main__":
    unittest.main()
