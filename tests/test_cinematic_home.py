#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'apply-cinematic-home.py'
spec = importlib.util.spec_from_file_location('cinema_home', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CinematicHomeTest(unittest.TestCase):
    SAMPLE = """<div className='hero-wrap w-full mb-4'>
<div className='home-content px-2 sm:px-10 pb-4 sm:pb-8 overflow-visible'>
            {/* 继续观看 */}"""

    def test_transforms_and_preserves_watch_history(self):
        result = module.apply(self.SAMPLE)
        self.assertIn('cinema-hero', result)
        self.assertIn('cinema-channel-nav', result)
        self.assertIn('/douban?type=anime', result)
        self.assertIn('{/* 继续观看 */}', result)
        self.assertNotIn('/under', result)
        self.assertEqual(result, module.apply(result))

    def test_desktop_shelves_break_out_of_old_fixed_width(self):
        css = (SCRIPT.parents[1] / 'custom' / 'cinematic-home-v2.1.css').read_text(encoding='utf-8')
        self.assertIn('.cinema-home-content .home-section:not(.continue-watching) .media-row > div', css)
        self.assertIn('max-width: none !important', css)
        self.assertIn('.cinema-hero .hero-content', css)
        self.assertIn('@media (max-width: 767px)', css)

    def test_unknown_structure_fails_closed(self):
        with self.assertRaises(ValueError):
            module.apply('arbitrary upstream markup')

if __name__ == '__main__':
    unittest.main()
