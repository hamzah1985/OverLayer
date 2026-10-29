# Third-party components

OverLayer's own source is MIT licensed. Its portable distribution also
includes components under their own licenses; the MIT license does not replace
these terms. License texts and upstream notices are in `licenses/` in the ZIP.

* **Qt 6.10.0, PySide6 Essentials 6.10.0 and Shiboken6 6.10.0** — copyright
  The Qt Company Ltd. and other contributors; used under LGPL v3. Qt's Core,
  Gui and Widgets libraries and the Windows platform plugin are dynamically
  loaded from `_internal/`. Users may replace compatible libraries and modify
  the application. Reverse engineering for debugging modifications to these
  libraries is permitted. No application restriction overrides the LGPL.
  Upstream source: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.0-src/>;
  Qt source: <https://download.qt.io/official_releases/qt/6.10/6.10.0/submodules/>.
  Obtain the matching sources from these upstream locations, or request them
  from the distributor of your copy if they are unavailable. Distributors must
  preserve the license notices and meet LGPL source availability obligations;
  the build script packages the matching Qt and PySide source archives beside
  the binary to make redistribution straightforward.
* **CPython** — Python Software Foundation License, including upstream notices.
  Source and notices: <https://www.python.org/downloads/source/>.
* **PyInstaller bootloader** — GPL v2 or later with the PyInstaller exception
  permitting distribution of bundled applications under their own licenses.
  <https://pyinstaller.org/en/stable/license.html>.
* **Microsoft Visual C++ runtime libraries** — Microsoft Corporation; runtime
  DLLs supplied with the upstream Qt/PySide Windows wheels. These are proprietary
  redistributable components and are not covered by the application's MIT
  license. <https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files>.
* **Other Qt third-party code** — see Qt's upstream `LICENSES` and module
  attribution files included in the corresponding source archives.

This is an independent companion application. Host applications belong to their
respective owners. This project is not affiliated with their vendors and does
not bundle those applications.
