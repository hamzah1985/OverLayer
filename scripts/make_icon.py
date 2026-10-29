"""Export the existing application mark as a multi-size Windows icon."""

from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from overlayer.app import app_icon  # noqa: E402


def main():
    app = QApplication([])
    icon = app_icon()
    images = []
    for size in (16, 24, 32, 48, 64):
        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not icon.pixmap(size, size).save(buffer, "PNG"):
            raise RuntimeError("Could not render application icon")
        buffer.close()
        images.append((size, bytes(array)))
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = []
    for size, data in images:
        entries.append(
            struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset)
        )
        offset += len(data)
    folder = ROOT / "assets"
    folder.mkdir(exist_ok=True)
    (folder / "overlayer.ico").write_bytes(
        header + b"".join(entries) + b"".join(data for size, data in images)
    )
    app.quit()


if __name__ == "__main__":
    main()
