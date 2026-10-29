import copy
from pathlib import Path
import tempfile
import unittest

from overlayer.settings import DEFAULTS, Store, validated


class SettingsTests(unittest.TestCase):
    def test_invalid_values_are_rejected_or_clamped(self):
        result = validated(
            {
                "guides": ["thirds", "unknown", "thirds", {}],
                "opacity": 999,
                "rows": 0,
                "thickness": float("nan"),
                "aspect": [],
                "rotation": 99,
                "color": "#zzzzzz",
                "rect": [0, 0, -3, 4],
                "vp": [-5, 4],
                "locked": "false",
            }
        )
        self.assertEqual(result["guides"], ["thirds"])
        self.assertEqual(result["opacity"], 100)
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["thickness"], DEFAULTS["thickness"])
        self.assertEqual(result["aspect"], "Viewport")
        self.assertEqual(result["rotation"], 3)
        self.assertEqual(result["rect"], [0, 0, 240, 180])
        self.assertEqual(result["vp"], [0, 1])
        self.assertFalse(result["locked"])

    def test_new_fields_are_clamped_and_old_files_get_defaults(self):
        result = validated(
            {
                "margin_pct": 99,
                "reference_scale": 1,
                "reference_dx": -500,
                "custom_w": 0,
                "halo": "yes",
            }
        )
        self.assertEqual(result["margin_pct"], 25)
        self.assertEqual(result["reference_scale"], 10)
        self.assertEqual(result["reference_dx"], -100)
        self.assertEqual(result["custom_w"], 1)
        self.assertTrue(result["halo"])  # invalid type -> default
        old = validated({"guides": ["thirds"], "opacity": 50})
        self.assertEqual(old["reference_scale"], 100)
        self.assertFalse(old["dim_outside"])

    def test_hotkeys_are_validated_and_roundtrip(self):
        from overlayer import keys

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            store = Store(path)
            self.assertEqual(store.hotkeys, keys.DEFAULT_HOTKEYS)
            store.hotkeys["draw_area"] = "ctrl+shift+f7"
            store.ui.update(
                auto_follow=True,
                follow_exe="d5.exe",
                sections={"refs": True},
                relative=[0.1, 0.2, 0.5, 0.5],
            )
            store.save()
            loaded = Store(path)
            self.assertEqual(loaded.hotkeys["draw_area"], "Ctrl+Shift+F7")
            self.assertEqual(loaded.ui["follow_exe"], "d5.exe")
            self.assertEqual(loaded.ui["sections"], {"refs": True})
            self.assertEqual(loaded.ui["relative"], [0.1, 0.2, 0.5, 0.5])
            path.write_text(
                '{"hotkeys": {"quit": "Q", "toggle_lock": "Ctrl+Alt+O"},'
                ' "ui": {"relative": [0, 0, 0, 1], "sections": {"bogus": true}}}'
            )
            bad = Store(path)
            self.assertEqual(bad.hotkeys["quit"], "Ctrl+Alt+Q")  # no modifier
            self.assertEqual(bad.hotkeys["toggle_lock"], "Ctrl+Alt+L")  # duplicate
            self.assertNotIn("relative", bad.ui)
            self.assertEqual(bad.ui.get("sections"), {})

    def test_defaults_are_independent(self):
        value = validated({})
        value["vp"][0] = 0.9
        self.assertEqual(DEFAULTS["vp"], [0.5, 0.42])

    def test_roundtrip_preserves_presets(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            store = Store(path)
            store.state["guides"] = ["perspective", "horizon"]
            store.presets["Camera A"] = copy.deepcopy(store.state)
            store.ui["panel_rect"] = [120, 130, 500, 600]
            store.save()
            loaded = Store(path)
            self.assertEqual(loaded.state, store.state)
            self.assertEqual(loaded.presets, store.presets)
            self.assertEqual(loaded.ui, store.ui)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_corrupted_file_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text("invalid")
            with self.assertLogs(level="WARNING"):
                store = Store(path)
            self.assertTrue(store.error)
            self.assertEqual(store.state, DEFAULTS)
