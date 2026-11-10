from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = '{http://www.w3.org/2000/svg}'


class ProfileMotionTests(unittest.TestCase):
    def test_every_visible_image_has_motion_and_static_picture_fallback(self):
        readme = (ROOT/'README.md').read_text()
        images = re.findall(r'<img\b[^>]*src="([^"]+)"', readme)
        self.assertGreater(len(images), 50)
        for source in images:
            self.assertTrue('/motion/' in source or source.endswith('.gif'), source)
            self.assertTrue((ROOT/source).is_file(), source)
        for picture in re.findall(r'<picture>(.*?)</picture>', readme, re.S):
            self.assertIn('prefers-reduced-motion: reduce', picture)
            for path in re.findall(r'(?:src|srcset)="([^"]+)"', picture):
                self.assertTrue((ROOT/path).is_file(), path)
        # Intended links survive; decorative badges do not gain links.
        self.assertIn('href="https://github.com/Kriksson/item-bro"', readme)
        self.assertIn('href="mailto:k.kriksson@gmail.com"', readme)

    def test_animated_svgs_are_self_contained_and_support_reduced_motion(self):
        assets = list((ROOT/'assets/profile/motion').rglob('*.svg'))
        self.assertGreater(len(assets), 50)
        for path in assets:
            root = ET.parse(path).getroot()
            style = root.find(NS+'style').text
            self.assertIn('prefers-reduced-motion: reduce', style)
            self.assertIn('@keyframes profile-belt', style)
            for node in root.iter():
                self.assertNotEqual(node.tag, NS+'script', str(path))
                for attribute, value in node.attrib.items():
                    if attribute.endswith('href'):
                        self.assertTrue(value.startswith(('data:', '#')), str(path))


if __name__ == '__main__':
    unittest.main()
