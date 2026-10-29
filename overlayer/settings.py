import copy
import json
import logging
import math
import os
from pathlib import Path

from .geometry import GUIDES, ASPECTS
from .keys import ACTIONS, validated_hotkeys

DEFAULTS = {
    "guides": ["thirds"],
    "color": "#000000",
    "opacity": 75,
    "thickness": 1.25,
    "flip_h": False,
    "flip_v": False,
    "rotation": 0,
    "aspect": "Viewport",
    "custom_w": 16,
    "custom_h": 9,
    "margins": False,
    "margin_pct": 5,
    "focal": False,
    "border": True,
    "halo": False,
    "dim_outside": False,
    "rows": 4,
    "columns": 4,
    "vp": [0.5, 0.42],
    "left_vp": [0.12, 0.42],
    "right_vp": [0.88, 0.42],
    "focus": [0.62, 0.38],
    "reference": "",
    "reference_opacity": 25,
    "reference_scale": 100,
    "reference_dx": 0,
    "reference_dy": 0,
    "rect": [120, 120, 1000, 640],
    "locked": False,
}
SECTIONS = {"guides": True, "frame": True, "follow": True, "refs": False, "keys": False}


def _finite(value):
    return (
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def data_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OverLayer"


def validated(value):
    result = copy.deepcopy(DEFAULTS)
    if not isinstance(value, dict):
        return result
    for key, default in DEFAULTS.items():
        v = value.get(key, default)
        if isinstance(default, bool):
            if isinstance(v, bool):
                result[key] = v
        elif isinstance(default, (float, int)):
            bounds = {
                "opacity": (10, 100),
                "thickness": (0.5, 6),
                "rotation": (0, 3),
                "rows": (2, 16),
                "columns": (2, 16),
                "reference_opacity": (0, 100),
                "reference_scale": (10, 400),
                "reference_dx": (-100, 100),
                "reference_dy": (-100, 100),
                "margin_pct": (1, 25),
                "custom_w": (1, 999),
                "custom_h": (1, 999),
            }
            if _finite(v):
                lo, hi = bounds[key]
                result[key] = type(default)(max(lo, min(hi, v)))
        elif key == "guides" and isinstance(v, list):
            result[key] = list(
                dict.fromkeys(x for x in v if isinstance(x, str) and x in GUIDES)
            )
        elif key in ("vp", "left_vp", "right_vp", "focus", "rect"):
            length = 4 if key == "rect" else 2
            if (
                isinstance(v, list)
                and len(v) == length
                and all(
                    isinstance(n, (int, float))
                    and not isinstance(n, bool)
                    and math.isfinite(n)
                    for n in v
                )
            ):
                if key == "rect":
                    result[key] = [
                        int(v[0]),
                        int(v[1]),
                        max(240, min(16000, int(v[2]))),
                        max(180, min(16000, int(v[3]))),
                    ]
                else:
                    result[key] = [max(0, min(1, n)) for n in v]
        elif key == "aspect":
            if isinstance(v, str) and v in ASPECTS:
                result[key] = v
        elif key == "color":
            if isinstance(v, str) and len(v) == 7 and v.startswith("#"):
                try:
                    int(v[1:], 16)
                    result[key] = v
                except ValueError:
                    pass
        elif key == "reference" and isinstance(v, str):
            result[key] = v
    return result


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "settings.json"
        self.error = ""
        self.presets = {}
        self.ui = {}
        self.hotkeys = validated_hotkeys({})
        self.state = copy.deepcopy(DEFAULTS)
        load_path = self.path
        if path is None and not load_path.exists():
            legacy = self.path.parent.parent / "D5OverLayer" / "settings.json"
            if legacy.is_file():
                load_path = legacy
        try:
            data = json.loads(load_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected an object")
            self.state = validated(data.get("state", {}))
            ui = data.get("ui", {})
            if isinstance(ui, dict):
                for key in ("panel_screen", "overlay_screen"):
                    if isinstance(ui.get(key), str):
                        self.ui[key] = ui[key][:256]
                for key in ("panel_maximized", "auto_follow"):
                    if isinstance(ui.get(key), bool):
                        self.ui[key] = ui[key]
                if isinstance(ui.get("follow_exe"), str):
                    self.ui["follow_exe"] = ui["follow_exe"][:260]
                sections = ui.get("sections")
                if isinstance(sections, dict):
                    self.ui["sections"] = {
                        k: v
                        for k, v in sections.items()
                        if k in SECTIONS and isinstance(v, bool)
                    }
                relative = ui.get("relative")
                if (
                    isinstance(relative, list)
                    and len(relative) == 4
                    and all(_finite(n) for n in relative)
                    and relative[2] > 0
                    and relative[3] > 0
                ):
                    self.ui["relative"] = [float(n) for n in relative]
                rect = ui.get("panel_rect")
                if (
                    isinstance(rect, list)
                    and len(rect) == 4
                    and all(_finite(n) for n in rect)
                ):
                    self.ui["panel_rect"] = [
                        int(rect[0]),
                        int(rect[1]),
                        max(440, min(16000, int(rect[2]))),
                        max(300, min(16000, int(rect[3]))),
                    ]
            self.hotkeys = validated_hotkeys(data.get("hotkeys"))
            presets = data.get("presets", {})
            if isinstance(presets, dict):
                self.presets = {
                    str(k)[:80]: validated(v)
                    for k, v in presets.items()
                    if isinstance(v, dict)
                }
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"Could not load settings: {exc}"
            logging.warning(self.error)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "state": self.state,
                    "presets": self.presets,
                    "ui": self.ui,
                    "hotkeys": self.hotkeys,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def hotkey_bindings(self):
        """RegisterHotKey id -> shortcut text."""
        return {ident: self.hotkeys[name] for ident, name, _, _ in ACTIONS}
