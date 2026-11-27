#!/usr/bin/env python3
"""Offline regression tests for structural admin upstream drift."""
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "apply-admin-customization.py"
spec = importlib.util.spec_from_file_location("admin_customization", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AdminCompatibility(unittest.TestCase):
    def test_modern_upstream_preserves_content_class_name(self):
        source = "before\n" + module.MODERN_BEFORE + "\nafter"
        output = module.transform(source)
        self.assertIn("moontv-admin-tab-content", output)
        self.assertIn("contentClassName ||", output)
        self.assertEqual(module.transform(output), output)

    def test_legacy_upstream(self):
        output = module.transform(module.LEGACY_BEFORE)
        self.assertIn("moontv-admin-tab-content", output)
        self.assertEqual(module.transform(output), output)

    def test_unknown_upstream_fails_closed(self):
        with self.assertRaises(ValueError):
            module.transform("unrelated admin component")

    def test_partial_customization_fails_closed(self):
        with self.assertRaises(ValueError):
            module.transform("moontv-admin-tab-content")

if __name__ == "__main__":
    unittest.main()
