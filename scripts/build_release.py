"""Build a portable, dynamically linked Windows release and its source companion."""

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from overlayer import __version__  # noqa: E402

QT_VERSION = "6.10.0"
SOURCES = {
    "pyside-setup-everywhere-src-6.10.0.tar.xz": "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.0-src/",
    "qtbase-everywhere-src-6.10.0.tar.xz": "https://download.qt.io/official_releases/qt/6.10/6.10.0/submodules/",
    "qtsvg-everywhere-src-6.10.0.tar.xz": "https://download.qt.io/official_releases/qt/6.10/6.10.0/submodules/",
    "qtimageformats-everywhere-src-6.10.0.tar.xz": "https://download.qt.io/official_releases/qt/6.10/6.10.0/submodules/",
}


def download_sources():
    cache = ROOT / "build" / "dependency-sources"
    cache.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, base in SOURCES.items():
        path = cache / filename
        # Verify downloaded and cached files against upstream SHA-256 sidecars.
        with urllib.request.urlopen(
            base + filename + ".sha256", timeout=60
        ) as response:
            expected = response.read().decode().split()[0].lower()
        cached_hash = None
        if path.exists():
            with path.open("rb") as cached:
                cached_hash = hashlib.file_digest(cached, "sha256").hexdigest()
        if cached_hash != expected:
            print(f"Downloading matching source: {filename}", flush=True)
            partial = path.with_suffix(".partial")
            with (
                urllib.request.urlopen(base + filename, timeout=120) as response,
                partial.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
            with partial.open("rb") as data:
                if hashlib.file_digest(data, "sha256").hexdigest() != expected:
                    raise RuntimeError(f"Checksum mismatch: {filename}")
            partial.replace(path)
        paths.append(path)
    return paths


def collect_notices(licenses, sources):
    licenses.mkdir(parents=True, exist_ok=True)
    for source in sources:
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                # Copy upstream license/attribution files, never extract arbitrary paths.
                if not member.isfile() or member.size > 2_000_000:
                    continue
                if (
                    "LICENSES" not in parts
                    and not parts[-1]
                    .lower()
                    .startswith(("license", "copying", "copyright"))
                    and parts[-1] != "qt_attribution.json"
                ):
                    continue
                target = (
                    licenses / source.name.removesuffix(".tar.xz") / Path(*parts[1:])
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as data, target.open("wb") as output:
                    shutil.copyfileobj(data, output)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    for package in ("pyinstaller", "shiboken6", "PySide6-Essentials"):
        dist = metadata.distribution(package)
        for name in dist.files or []:
            if "/licenses/" in str(name).replace("\\", "/").lower() or str(
                name
            ).endswith("COPYING.txt"):
                target = licenses / package / Path(str(name)).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(name), target)


def checksum(path):
    with path.open("rb") as data:
        value = hashlib.file_digest(data, "sha256").hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{value}  {path.name}\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dependency-sources", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on Windows.")
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{__version__}"' not in config:
        raise SystemExit("Version files disagree")
    sources = [] if args.skip_dependency_sources else download_sources()
    # Do not let unrelated tools on the caller's PATH supply system DLLs.
    clean_env = os.environ.copy()
    windows_dir = Path(os.environ["SystemRoot"])
    clean_env["PATH"] = os.pathsep.join(
        (
            str(Path(sys.executable).parent),
            str(Path(sys.base_prefix)),
            str(windows_dir / "System32"),
            str(windows_dir),
        )
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_icon.py")],
        cwd=ROOT,
        env=clean_env,
        check=True,
    )
    version_tuple = tuple(int(part) for part in __version__.split(".")) + (0,)
    version_file = ROOT / "build" / "windows-version.txt"
    version_file.parent.mkdir(exist_ok=True)
    version_file.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={version_tuple!r}, prodvers={version_tuple!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Bogdan Demchenko'),
    StringStruct('FileDescription', 'OverLayer by Bogdan Demchenko'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', 'OverLayer'),
    StringStruct('ProductVersion', '{__version__}'),
    StringStruct('LegalCopyright', 'Copyright (c) 2026 Bogdan Demchenko'),
    StringStruct('OriginalFilename', 'OverLayer.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--name",
            "OverLayer",
            "--icon",
            str(ROOT / "assets" / "overlayer.ico"),
            "--version-file",
            str(version_file),
            "--exclude-module",
            "PySide6.QtQml",
            "--exclude-module",
            "PySide6.QtQuick",
            "--exclude-module",
            "PySide6.QtPdf",
            "--exclude-module",
            "PySide6.QtNetwork",
            str(ROOT / "run.py"),
        ],
        cwd=ROOT,
        env=clean_env,
        check=True,
    )
    folder = ROOT / "dist" / "OverLayer"
    shutil.copy2(ROOT / "assets" / "overlayer.ico", folder / "OverLayer.ico")
    # Keep the app-local MSVC runtime versions consistent with the Qt wheel.
    qt_dir = Path(metadata.distribution("PySide6-Essentials").locate_file("PySide6"))
    for runtime in qt_dir.glob("*140*.dll"):
        shutil.copy2(runtime, folder / "_internal" / runtime.name)
    # Windows 10/11 supply these OS libraries. App-local copies pulled from
    # other tools can shadow the real Windows ICU/API sets and break QtCore.
    for file in (folder / "_internal").iterdir():
        if file.is_file() and (
            file.name.lower() == "ucrtbase.dll"
            or file.name.lower().startswith(("api-ms-win-", "icu"))
        ):
            file.unlink()
    # QtGui discovers all installed image plugins. PDF is not a supported input;
    # omit its plugin/library to avoid bundling unrelated QtWebEngine components.
    for file in folder.rglob("*"):
        if file.is_file() and (file.name.lower() in ("qpdf.dll", "qt6pdf.dll")):
            file.unlink()
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md"):
        shutil.copy2(ROOT / name, folder / name)
    smoke_result = ROOT / "build" / "portable-smoke-test.json"
    if smoke_result.exists():
        smoke_result.unlink()
    subprocess.run(
        [str(folder / "OverLayer.exe"), "--smoke-test", str(smoke_result)],
        cwd=folder,
        env=clean_env,
        check=True,
        timeout=30,
    )
    if not json.loads(smoke_result.read_text(encoding="utf-8")).get("ok"):
        raise RuntimeError("Portable startup check failed")
    print("Portable startup / Qt render / native transparency: passed", flush=True)
    source_folder = folder / "source"
    source_folder.mkdir(exist_ok=True)
    (source_folder / "assets").mkdir(exist_ok=True)
    shutil.copy2(
        ROOT / "assets" / "overlayer.ico", source_folder / "assets" / "overlayer.ico"
    )
    shutil.copytree(
        ROOT / "overlayer",
        source_folder / "overlayer",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in (
        "run.py",
        "requirements.txt",
        "pyproject.toml",
        "LICENSE",
        "README.md",
    ):
        shutil.copy2(ROOT / name, source_folder / name)
    collect_notices(folder / "licenses", sources)
    (folder / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                "app": __version__,
                "python": sys.version,
                "qt": QT_VERSION,
                "dependencies": {
                    p: metadata.version(p)
                    for p in ("PySide6-Essentials", "shiboken6", "pyinstaller")
                },
                "dependency_sources_included": bool(sources),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    name = f"OverLayer-{__version__}-windows-x64"
    if sources:
        source_zip = ROOT / "dist" / f"OverLayer-{__version__}-dependency-sources.zip"
        with zipfile.ZipFile(
            source_zip, "w", compression=zipfile.ZIP_STORED
        ) as archive:
            for path in sources:
                archive.write(path, path.name)
        checksum(source_zip)
    package = Path(
        shutil.make_archive(
            str(ROOT / "dist" / name), "zip", ROOT / "dist", "OverLayer"
        )
    )
    checksum(package)
    print(f"Ready: {package}", flush=True)


if __name__ == "__main__":
    main()
