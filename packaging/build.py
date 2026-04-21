"""
Build the YouTubeCollector desktop app with PyInstaller.

Run this on the target machine. macOS builds must be produced on macOS.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build YouTubeCollector with PyInstaller.")
    parser.add_argument("--name", default="YouTubeCollector", help="Bundle name.")
    parser.add_argument("--onefile", action="store_true", help="Build a one-file executable.")
    parser.add_argument("--onedir", action="store_true", help="Build an app bundle / folder bundle.")
    parser.add_argument("--clean", action="store_true", help="Remove previous build output first.")
    parser.add_argument(
        "--target-arch",
        choices=("x86_64", "arm64", "universal2"),
        help="macOS target architecture to pass through to PyInstaller.",
    )
    parser.add_argument(
        "--package-zip",
        action="store_true",
        help="Package the generated macOS .app bundle into a distributable zip file.",
    )
    parser.add_argument(
        "--zip-name",
        help="Name of the generated distributable zip file.",
    )
    return parser.parse_args()


def package_mac_app(app_path: Path, zip_path: Path) -> None:
    if sys.platform != "darwin":
        raise SystemExit("--package-zip is only supported on macOS.")

    if not app_path.exists():
        raise SystemExit(f"App bundle not found: {app_path}")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.unlink(missing_ok=True)

    subprocess.run(
        [
            "ditto",
            "-c",
            "-k",
            "--keepParent",
            "--sequesterRsrc",
            str(app_path),
            str(zip_path),
        ],
        check=True,
    )


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    dist_dir = project_root / "dist"
    build_dir = project_root / "build" / "pyinstaller"

    if args.onefile and args.onedir:
        raise SystemExit("Cannot combine --onefile and --onedir.")

    if args.onefile:
        bundle_mode = "onefile"
    elif args.onedir:
        bundle_mode = "onedir"
    else:
        bundle_mode = "onedir" if sys.platform == "darwin" else "onefile"

    if args.clean:
        shutil.rmtree(dist_dir, ignore_errors=True)
        shutil.rmtree(build_dir, ignore_errors=True)

    try:
        import PyInstaller.__main__
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyInstaller is not installed. Install it with:\n"
            "    python -m pip install pyinstaller"
        ) from exc

    app_entry = project_root / "app.py"
    pyinstaller_args = [
        str(app_entry),
        "--noconfirm",
        "--windowed",
        f"--name={args.name}",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        "--clean",
        "--collect-submodules=PySide6.QtCore",
        "--collect-submodules=PySide6.QtGui",
        "--collect-submodules=PySide6.QtWidgets",
        "--collect-submodules=PySide6.QtNetwork",
        "--collect-submodules=googleapiclient",
        "--collect-submodules=httplib2",
        "--collect-submodules=urllib3",
        "--collect-data=certifi",
        "--exclude-module=PySide6.QtWebEngineCore",
        "--exclude-module=PySide6.QtWebEngineWidgets",
        "--exclude-module=PySide6.QtWebEngineQuick",
    ]

    pyinstaller_args.append("--onedir" if bundle_mode == "onedir" else "--onefile")

    if sys.platform == "darwin":
        if args.target_arch:
            pyinstaller_args.append(f"--target-arch={args.target_arch}")
        pyinstaller_args.append("--osx-bundle-identifier=com.oneinsight.youtubecollector")

    PyInstaller.__main__.run(pyinstaller_args)

    if args.package_zip:
        zip_name = args.zip_name or f"{args.name}.zip"
        package_mac_app(dist_dir / f"{args.name}.app", dist_dir / zip_name)


if __name__ == "__main__":
    main()
