"""Composition geometry in logical pixels; independent of the GUI."""

from functools import lru_cache
from math import cos, sin, pi

PHI = (1 + 5**0.5) / 2
GUIDES = {
    "thirds": "Rule of thirds",
    "golden": "Golden ratio",
    "spiral": "Golden spiral",
    "triangles": "Golden triangles",
    "diagonals": "Diagonals",
    "symmetry": "Center & symmetry",
    "dynamic": "Dynamic symmetry",
    "pyramid": "Triangle / pyramid",
    "leading": "Leading lines / one point",
    "perspective": "Two-point perspective",
    "horizon": "Horizon / eye level",
    "grid": "Custom grid",
}
ASPECTS = {
    "Viewport": 0,
    "16:9": 16 / 9,
    "3:2": 1.5,
    "4:3": 4 / 3,
    "1:1": 1,
    "4:5": 0.8,
    "9:16": 9 / 16,
    "2.39:1": 2.39,
    "Custom": 0,  # ratio comes from the state's custom_w / custom_h
}
COMMON_RATIOS = (
    ("16:9", 16 / 9),
    ("9:16", 9 / 16),
    ("3:2", 3 / 2),
    ("2:3", 2 / 3),
    ("4:3", 4 / 3),
    ("3:4", 3 / 4),
    ("1:1", 1.0),
    ("4:5", 4 / 5),
    ("2.39:1", 2.39),
    ("21:9", 21 / 9),
)


def aspect_value(state):
    """Width / height of the crop frame; 0 means follow the viewport."""
    name = state.get("aspect", "Viewport")
    if name == "Custom":
        return state.get("custom_w", 16) / max(1, state.get("custom_h", 9))
    return ASPECTS.get(name, 0)


def ratio_label(width, height):
    """Name a frame's ratio: a familiar crop when close, otherwise decimal."""
    if width <= 0 or height <= 0:
        return ""
    ratio = width / height
    for name, value in COMMON_RATIOS:
        if abs(ratio / value - 1) < 0.01:
            return name
    return f"{ratio:.2f}:1"


def frame_rect(width, height, aspect=0):
    if not aspect:
        return (0.0, 0.0, float(width), float(height))
    w, h = float(width), float(height)
    if w / h > aspect:
        w = h * aspect
    else:
        h = w / aspect
    return ((width - w) / 2, (height - h) / 2, w, h)


def transform(point, state, inverse=False):
    """Map normalized guide coordinates through mirrors and quarter turns."""
    x, y = point
    turns = state.get("rotation", 0) % 4
    if inverse:
        for _ in range(turns):
            x, y = y, 1 - x
    if state.get("flip_h"):
        x = 1 - x
    if state.get("flip_v"):
        y = 1 - y
    if not inverse:
        for _ in range(turns):
            x, y = 1 - y, x
    return x, y


def anchors(state):
    active = state.get("guides", [])
    result = {}
    if "leading" in active or "horizon" in active:
        result["vp"] = state.get("vp", [0.5, 0.42])
    if "perspective" in active:
        result["left_vp"] = state.get("left_vp", [0.12, 0.42])
        result["right_vp"] = state.get("right_vp", [0.88, 0.42])
    if state.get("focal"):
        result["focus"] = state.get("focus", [0.62, 0.38])
    return result


@lru_cache(maxsize=32)
def golden_construction(width, height):
    """Whirling squares with a quarter-circle in each, filling the frame.

    Repeatedly cuts the largest square from the corner where the previous arc
    ended, so the arcs join smoothly and stay true circles in pixel space. On a
    golden-ratio frame this is the classic golden spiral diagram; on any other
    frame the same rule still tiles it exactly. Returns (cut lines, arcs) as
    tuples of polylines in normalized coordinates, starting at the bottom-left.
    """
    left, top, right, bottom = 0.0, 0.0, float(width), float(height)
    sx, sy = left, bottom
    lines, arcs = [], []
    min_side = 0.006 * max(width, height)
    for _ in range(16):
        w, h = right - left, bottom - top
        side = min(w, h)
        if side < min_side:
            break
        # Unit steps from the current corner into the remaining rectangle.
        ux = 1 if abs(sx - left) <= abs(sx - right) else -1
        uy = 1 if abs(sy - top) <= abs(sy - bottom) else -1
        if w >= h:
            along, across = (ux, 0), (0, uy)
        else:
            along, across = (0, uy), (ux, 0)
        cx, cy = sx + side * along[0], sy + side * along[1]
        ex, ey = cx + side * across[0], cy + side * across[1]
        steps = max(8, min(48, round(side / max(width, height) * 80)))
        arc = []
        for i in range(steps + 1):
            t = i * pi / 2 / steps
            # From S (opposite the along-axis) round to E (the across-axis).
            arc.append(
                (
                    (cx + side * (-along[0] * cos(t) + across[0] * sin(t))) / width,
                    (cy + side * (-along[1] * cos(t) + across[1] * sin(t))) / height,
                )
            )
        arcs.append(tuple(arc))
        lines.append(((cx / width, cy / height), (ex / width, ey / height)))
        if w >= h:
            left, right = (cx, right) if ux > 0 else (left, cx)
        else:
            top, bottom = (cy, bottom) if uy > 0 else (top, cy)
        sx, sy = ex, ey
    return tuple(lines), tuple(arcs)


def guide_paths(kind, width, height, state):
    """Return polylines in normalized, untransformed guide coordinates."""
    paths = []

    def line(a, b):
        paths.append([a, b])

    def grid(xs, ys):
        for x in xs:
            line((x, 0), (x, 1))
        for y in ys:
            line((0, y), (1, y))

    if kind == "thirds":
        grid([1 / 3, 2 / 3], [1 / 3, 2 / 3])
    elif kind == "golden":
        grid([1 - 1 / PHI, 1 / PHI], [1 - 1 / PHI, 1 / PHI])
    elif kind == "grid":
        cols, rows = state.get("columns", 4), state.get("rows", 4)
        grid([i / cols for i in range(1, cols)], [i / rows for i in range(1, rows)])
    elif kind == "symmetry":
        grid([0.5], [0.5])
    elif kind == "diagonals":
        line((0, 0), (1, 1))
        line((0, 1), (1, 0))
    elif kind in ("triangles", "dynamic"):
        # Altitudes from opposite corners to the main diagonal, in pixel space.
        t = width**2 / (width**2 + height**2)
        line((0, 0), (1, 1))
        line((1, 0), (t, t))
        line((0, 1), (1 - t, 1 - t))
        if kind == "dynamic":
            line((0, 1), (1, 0))
            line((0, 0), (1 - t, t))
            line((1, 1), (t, 1 - t))
    elif kind == "pyramid":
        paths.append([(0.5, 0.12), (0.1, 0.88), (0.9, 0.88), (0.5, 0.12)])
    elif kind == "spiral":
        # Square subdivisions plus the quarter-circle spiral through them.
        lines, arcs = golden_construction(float(width), float(height))
        paths.extend(list(line) for line in lines)
        paths.extend(list(arc) for arc in arcs)
    elif kind in ("leading", "perspective", "horizon"):
        vp = state.get("vp", [0.5, 0.42])
        if kind == "horizon":
            line((0, vp[1]), (1, vp[1]))
        elif kind == "leading":
            for i in range(7):
                x = i / 6
                line(vp, (x, 0))
                line(vp, (x, 1))
            for y in (1 / 3, 2 / 3):
                line(vp, (0, y))
                line(vp, (1, y))
        else:
            for key in ("left_vp", "right_vp"):
                p = state.get(key, [0.12 if key == "left_vp" else 0.88, 0.42])
                for x in (0.0, 0.25, 0.5, 0.75, 1.0):
                    line(p, (x, 0))
                    line(p, (x, 1))
            a = state.get("left_vp", [0.12, 0.42])
            b = state.get("right_vp", [0.88, 0.42])
            line((0, a[1]), (1, b[1]))
    return paths


def composed_paths(width, height, state):
    w, h = (height, width) if state.get("rotation", 0) % 2 else (width, height)
    return [
        [transform(p, state) for p in path]
        for kind in state.get("guides", [])
        for path in guide_paths(kind, w, h, state)
    ]
