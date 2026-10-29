"""Portable entry point, including a silent startup check for release builds."""

import json
import os
from pathlib import Path
import sys
import traceback


def start():
    from overlayer.app import main

    if "--smoke-test" not in sys.argv:
        return main()
    from PySide6.QtWidgets import QApplication
    from overlayer import __version__
    from overlayer.overlay import Overlay
    from overlayer.settings import validated
    from overlayer.windows import get_style

    app = QApplication([])
    overlay = Overlay(validated({"locked": True}))
    app.processEvents()
    assert get_style(int(overlay.winId()), -20) & 0x20
    assert not overlay.grab().isNull()
    result = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
    result.write_text(
        json.dumps(
            {
                "ok": True,
                "version": __version__,
                "qt_render": True,
                "native_click_through": True,
                "default_guide_color": validated({})["color"],
            }
        ),
        encoding="utf-8",
    )
    overlay.hide()
    return 0


if __name__ == "__main__":
    try:
        status = start()
    except Exception:
        error = traceback.format_exc()
        if "--smoke-test" in sys.argv:
            result = Path(sys.argv[sys.argv.index("--smoke-test") + 1])
            result.write_text(
                json.dumps({"ok": False, "error": error}), encoding="utf-8"
            )
        else:
            folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OverLayer"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "startup-error.log").write_text(error, encoding="utf-8")
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                "OverLayer could not start. Details were saved to:\n"
                + str(folder / "startup-error.log"),
                "OverLayer startup error",
                0x10,
            )
        status = 1
    raise SystemExit(status)
