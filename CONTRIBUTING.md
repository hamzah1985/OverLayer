# Contributing

## Development

Use Windows and Python 3.11 x64. Create a virtual environment as in the README,
then install the build tools:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m overlayer
```

Tests run actual Qt widgets and may briefly show a test overlay. Close another
OverLayer instance first so its shortcuts do not conflict with the test.

`geometry.py` generates guide paths; `overlay.py` paints and edits the frame;
`picker.py` provides screenshot-style drag selection without screen capture;
`windows.py` wraps the minimal Win32 APIs (window list, process file names,
keyboard-layout checks); `keys.py` defines and parses the global shortcuts
without Qt; `app.py` owns controls, tray and window following; `settings.py`
validates and atomically writes user settings.

Keep the app independent of host-application internals: no DLL injection,
process-memory reads, renderer hooks or dependencies on unpublished interfaces.

## Build a portable release

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py
```

The script builds an **onedir** app, keeping LGPL libraries replaceable, copies
documentation and license texts, includes application source in the portable
folder, and generates a ZIP plus SHA-256 file in `dist/`. A separate matching
dependency-source ZIP is also created for redistribution with each release.
The first build downloads matching upstream dependency source archives. Supply
`--skip-dependency-sources` only for local development builds, not public releases.

## Publish on GitHub

1. Create a public GitHub repository named `overlayer` under your account.
2. In this project folder, run:

   ```powershell
   git init -b main
   git add .
   git commit -m "Initial open-source release"
   git remote add origin https://github.com/YOUR-ACCOUNT/overlayer.git
   git push -u origin main
   ```

3. Use **Actions → Build Windows release → Run workflow** to build a downloadable
   artifact, or build locally with the command above.
4. To publish a release, set the same version in `overlayer/__init__.py` and
   `pyproject.toml`, commit it, then push a matching tag such as `v1.0.0`.
   The workflow tests, builds and creates a **draft** release with the binary
   ZIP, matching dependency-source ZIP and checksums.
5. Download and test the ZIP on a second Windows computer without Python.
   Review the draft release and publish it. Link its Releases page in the README.

The workflow uses GitHub's repository-scoped token. It does not need a personal
token checked into the repository. Never commit credentials or private reference
images. Distributed builds are unsigned until the maintainer adds code signing.

## Manual release checklist

* Lock the overlay and confirm orbiting/selecting in your app works through it.
* Draw a new viewport with Ctrl+Alt+A; try reverse-direction dragging and Escape.
* Resize with every corner/edge point and hold Shift for fine adjustment.
* Move, resize, minimize and restore the attached creative app window.
* Switch to another application and back; guides should follow visibility.
* Try 100%, 150% and 200% display scaling, including a second monitor.
* Drag all vanishing points, mirror and rotate, then save/reload a preset.
* Close controls, reopen with the tray and shortcut, and explicitly quit.
* Close unattached controls: the free guides should hide. Launch the EXE again
  and verify the same instance reopens its controls. Check Ctrl+Alt+H hides guides.
* Close the attached host window: no guides should remain on the desktop.
* Open a palette or file dialog of the followed app: the guides should stay.
* Rebind a shortcut under Shortcuts, restart, and confirm the new one works.
* Tick auto-follow, restart OverLayer and the host app in either order, and
  confirm the frame reattaches.
* Cycle presets with Ctrl+Alt+PgDn / PgUp while locked and following.
* Extract the ZIP onto a computer without Python and launch the EXE.

When reporting a bug, include Windows version, monitor scaling, app version,
steps and `%LOCALAPPDATA%\OverLayer\overlayer.log`. Remove private paths and
scene names from screenshots/logs before sharing.
