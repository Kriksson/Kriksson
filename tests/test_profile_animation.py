import importlib.util
from io import BytesIO
from pathlib import Path
import unittest

from PIL import Image, ImageChops

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/render_profile_animation.py'
spec = importlib.util.spec_from_file_location('animation', SCRIPT)
animation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(animation)


class ProfileAnimationTests(unittest.TestCase):
    def test_labels_use_current_aggregate_values(self):
        self.assertEqual(animation.labels({'added_lines':9876543, 'total_repositories':27,
                                           'contributions_last_year':456}),
                         ('+9,876,543 lines of code', '+27 repositories', '+456 contributions'))

    def test_typing_moves_but_factory_stays_still_and_static_fallback_exists(self):
        data = {'added_lines':78659, 'total_repositories':12, 'contributions_last_year':345}
        outputs = animation.render(data)
        gif = Image.open(BytesIO(outputs['code-counter.gif']))
        self.assertEqual(gif.info['loop'], 0)
        self.assertEqual(gif.size, (1200, 440))
        self.assertGreater(gif.n_frames, 20)
        # At these times all labels have finished appearing; only hands move.
        frames = []
        for moment in (4000, 4200):
            elapsed = 0
            for index in range(gif.n_frames):
                gif.seek(index)
                elapsed += gif.info['duration']
                if elapsed > moment:
                    frames.append(gif.convert('RGB'))
                    break
        self.assertIsNone(ImageChops.difference(
            frames[0].crop((470, 40, 1200, 440)),
            frames[1].crop((470, 40, 1200, 440))).getbbox())
        self.assertIsNotNone(ImageChops.difference(frames[0], frames[1]).getbbox())
        fallback = Image.open(BytesIO(outputs['code-counter.png']))
        self.assertEqual(fallback.size, gif.size)
        self.assertFalse(getattr(fallback, 'is_animated', False))

    def test_values_arrive_in_order_and_remain_anchored(self):
        self.assertAlmostEqual(animation.arrival(0, 0), 0, places=5)
        self.assertGreater(animation.arrival(.8, 0), animation.arrival(.8, 1))
        for row in range(3):
            self.assertAlmostEqual(animation.arrival(2, row), 1, places=5)
            self.assertEqual(animation.arrival(3, row), animation.arrival(6, row))


if __name__ == '__main__':
    unittest.main()
