"""Regression: Google's update-on-pan checkbox persists across tabs.

An unconditional click turns the local search off for every second tile.
"""
import unittest
from finder.google_browser import _refresh_map_area_results


class Toggle:
    def __init__(self, checked):
        self.checked = checked
        self.clicks = 0
    def count(self): return 1
    def is_visible(self): return True
    def get_attribute(self, name):
        assert name == 'aria-checked'
        return 'true' if self.checked else 'false'
    def click(self, timeout=5000):
        self.clicks += 1
        self.checked = not self.checked


class Mouse:
    def move(self, *args, **kwargs): pass
    def down(self): pass
    def up(self): pass


class Page:
    def __init__(self, checked):
        self.control = Toggle(checked)
        self.mouse = Mouse()
        self.viewport_size = {'width':1400, 'height':960}
        self.reads = 0
    def get_by_role(self, role, name):
        assert role == 'checkbox'
        assert name == 'Update results when map moves'
        return self.control
    def wait_for_timeout(self, timeout): pass
    @property
    def url(self):
        self.reads += 1
        if self.reads == 1:
            return 'https://www.google.com/maps/search/psychotherapist/@44.281874,-79.954025,14z?hl=en'
        return 'https://www.google.com/maps/search/psychotherapist/@44.281883,-79.954015,14z?hl=en&entry=ttu'


class GoogleToggleRegression(unittest.TestCase):
    def test_unchecked_is_enabled(self):
        p = Page(False)
        result = _refresh_map_area_results(p, 44.281874, -79.954025)
        self.assertEqual(p.control.clicks, 1)
        self.assertTrue(p.control.checked)
        self.assertLess(result['map_center_offset_km'], .01)

    def test_previously_enabled_remains_on_across_new_tab(self):
        p = Page(True)
        _refresh_map_area_results(p, 44.281874, -79.954025)
        self.assertEqual(p.control.clicks, 0)
        self.assertTrue(p.control.checked)

    def test_repeating_enabled_scans_never_toggles_off(self):
        for index in range(12):
            p = Page(True)
            _refresh_map_area_results(p, 44.281874, -79.954025)
            self.assertTrue(p.control.checked)
            self.assertEqual(p.control.clicks, 0)


if __name__=='__main__':
    unittest.main()
