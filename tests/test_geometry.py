import copy
import math
import unittest

from overlayer.geometry import (
    GUIDES,
    aspect_value,
    composed_paths,
    frame_rect,
    golden_construction,
    guide_paths,
    ratio_label,
    transform,
)
from overlayer.settings import DEFAULTS


class GeometryTests(unittest.TestCase):
    def test_transform_roundtrip_all_orientations(self):
        for rotation in range(4):
            for h in (False, True):
                for v in (False, True):
                    state = {"rotation": rotation, "flip_h": h, "flip_v": v}
                    for p in ((0, 0), (0.2, 0.7), (1, 1)):
                        result = transform(transform(p, state), state, inverse=True)
                        self.assertAlmostEqual(result[0], p[0])
                        self.assertAlmostEqual(result[1], p[1])

    def test_all_guides_stay_finite_and_in_frame(self):
        for width, height in ((1920, 1080), (1080, 1920), (800, 800), (240, 180)):
            for kind in GUIDES:
                for rotation in range(4):
                    state = copy.deepcopy(DEFAULTS)
                    state.update(guides=[kind], rotation=rotation)
                    paths = composed_paths(width, height, state)
                    self.assertTrue(paths, kind)
                    for path in paths:
                        for x, y in path:
                            self.assertTrue(math.isfinite(x) and math.isfinite(y), kind)
                            self.assertTrue(
                                -1e-6 <= x <= 1 + 1e-6 and -1e-6 <= y <= 1 + 1e-6, kind
                            )

    def test_golden_triangle_altitudes_are_perpendicular_in_pixels(self):
        for w, h in ((1600, 900), (900, 1600)):
            paths = guide_paths("triangles", w, h, DEFAULTS)
            for a, b in paths[1:]:
                dx, dy = (b[0] - a[0]) * w, (b[1] - a[1]) * h
                self.assertAlmostEqual(dx * w + dy * h, 0, places=6)

    def test_aspect_fit_centered_and_exact(self):
        for w, h in ((1920, 1080), (800, 1200)):
            for aspect in (1, 16 / 9, 9 / 16, 2.39):
                x, y, fw, fh = frame_rect(w, h, aspect)
                self.assertAlmostEqual(fw / fh, aspect)
                self.assertAlmostEqual(x + fw / 2, w / 2)
                self.assertAlmostEqual(y + fh / 2, h / 2)
                self.assertLessEqual(fw, w)
                self.assertLessEqual(fh, h)

    def test_leading_rays_share_selected_point(self):
        state = {"vp": [0.3, 0.6]}
        for path in guide_paths("leading", 1000, 600, state):
            self.assertEqual(path[0], [0.3, 0.6])

    def test_golden_construction_matches_classic_diagram(self):
        w, h = 1618.0, 1000.0
        lines, arcs = golden_construction(w, h)
        cuts = [
            tuple(round(v) for pt in line for v in (pt[0] * w, pt[1] * h))
            for line in lines[:4]
        ]
        self.assertEqual(
            cuts,
            [
                (1000, 1000, 1000, 0),  # first square, full height
                (1000, 618, 1618, 618),  # square above the remainder
                (1236, 618, 1236, 1000),  # square on the right
                (1236, 764, 1000, 764),  # square along the bottom
            ],
        )
        self.assertGreaterEqual(len(arcs), 8)

    def test_golden_arcs_are_continuous_true_circles(self):
        for w, h in ((1618, 1000), (1920, 1080), (1080, 1920), (2390, 1000)):
            lines, arcs = golden_construction(float(w), float(h))
            self.assertEqual(len(lines), len(arcs))
            for a, b in zip(arcs, arcs[1:]):
                self.assertAlmostEqual(a[-1][0], b[0][0])
                self.assertAlmostEqual(a[-1][1], b[0][1])
            # Every arc is a quarter circle in pixel space (no stretching).
            for arc, (c, e) in zip(arcs, lines):
                cx, cy = c[0] * w, c[1] * h
                radius = math.hypot(arc[0][0] * w - cx, arc[0][1] * h - cy)
                for x, y in arc:
                    self.assertAlmostEqual(
                        math.hypot(x * w - cx, y * h - cy), radius, places=6
                    )

    def test_golden_spiral_guide_includes_squares_and_arcs(self):
        paths = guide_paths("spiral", 1600, 900, DEFAULTS)
        lines, arcs = golden_construction(1600.0, 900.0)
        self.assertEqual(len(paths), len(lines) + len(arcs))

    def test_aspect_value_and_ratio_label(self):
        self.assertEqual(aspect_value({"aspect": "Viewport"}), 0)
        self.assertAlmostEqual(aspect_value({"aspect": "16:9"}), 16 / 9)
        self.assertAlmostEqual(
            aspect_value({"aspect": "Custom", "custom_w": 21, "custom_h": 9}), 21 / 9
        )
        self.assertEqual(ratio_label(1920, 1080), "16:9")
        self.assertEqual(ratio_label(1080, 1920), "9:16")
        self.assertEqual(ratio_label(1000, 640), "1.56:1")
        self.assertEqual(ratio_label(0, 5), "")
