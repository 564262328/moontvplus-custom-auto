#!/usr/bin/env python3
"""Only special-source browsing gets the layout changes."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply-adult-library-ui.py"
spec = importlib.util.spec_from_file_location("adult_library_ui", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AdultLibraryLayoutTests(unittest.TestCase):
    def test_all_five_special_only_modifiers(self):
        sample = """<div className='px-4 sm:px-10 py-4 sm:py-8 overflow-visible mb-10'>
<div className='mb-6'>
          <h1 className='flex items-center gap-2 text-2xl font-bold text-gray-800 dark:text-gray-200'>
            源站寻片
<div className='max-w-4xl mx-auto mb-8 space-y-6'>
<div className='max-w-[95%] mx-auto mt-8'>
<div className='grid grid-cols-3 gap-x-2 gap-y-14 sm:gap-y-20 px-0 sm:px-2 sm:grid-cols-[repeat(auto-fill,_minmax(11rem,_1fr))] sm:gap-x-8'>"""
        out = module.transform(sample)
        self.assertIn("{isSpecialVersion ? '成人片库' : '源站寻片'}", out)
        self.assertIn("isSpecialVersion ? 'adult-library-grid", out)
        self.assertIn("isSpecialVersion ? 'adult-library-page", out)
        self.assertEqual(module.transform(out), out)

    def test_unknown_upstream_fails_closed(self):
        with self.assertRaises(ValueError):
            module.transform("not a source search page")

if __name__ == "__main__":
    unittest.main()
