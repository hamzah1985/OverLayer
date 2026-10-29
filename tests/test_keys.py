import unittest

from overlayer import keys


class KeyTests(unittest.TestCase):
    def test_parse_normalizes_and_accepts_qt_names(self):
        self.assertEqual(keys.parse("ctrl+alt+a"), (3, ord("A"), "Ctrl+Alt+A"))
        self.assertEqual(keys.canonical("Alt+Ctrl+PgDown"), "Ctrl+Alt+PgDown")
        self.assertEqual(keys.canonical("Meta+Shift+F5"), "Shift+Win+F5")
        self.assertEqual(keys.canonical("Ctrl+Alt+Del"), "Ctrl+Alt+Delete")

    def test_unusable_shortcuts_are_rejected(self):
        for spec in ("A", "Ctrl+Alt", "Ctrl+A+B", "Ctrl++", "", None, 5, "Ctrl+F13"):
            self.assertIsNone(keys.parse(spec), spec)

    def test_defaults_are_valid_and_unique(self):
        values = list(keys.DEFAULT_HOTKEYS.values())
        self.assertEqual(len(values), len(set(values)))
        for spec in values:
            self.assertEqual(keys.canonical(spec), spec)

    def test_validated_hotkeys_fill_defaults_and_drop_duplicates(self):
        result = keys.validated_hotkeys({"quit": "Ctrl+Shift+Q", "bogus": "Ctrl+X"})
        self.assertEqual(result["quit"], "Ctrl+Shift+Q")
        self.assertEqual(result["toggle_lock"], "Ctrl+Alt+L")
        self.assertNotIn("bogus", result)
        self.assertEqual(keys.validated_hotkeys("nope"), keys.DEFAULT_HOTKEYS)


if __name__ == "__main__":
    unittest.main()
