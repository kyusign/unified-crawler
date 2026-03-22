from diag_bootstrap import install as _install_diag, runtime_is_frozen

_install_diag()

import importlib
import os
import sys
from pathlib import Path

IS_FROZEN = runtime_is_frozen()


def BOOTLOG(msg: str):
    from diag_bootstrap import log

    log(msg)


BOOTLOG("STEP-1: before PySide6 import")
BOOTLOG(f"IS_FROZEN={IS_FROZEN}")

if IS_FROZEN:
    try:
        os.environ.pop("PYSIDE_DISABLE_INTERNAL_QT_CONF", None)

        program_dir = Path(sys.executable).resolve().parent
        runtime_dir = program_dir / ".UnifiedRuntime"

        def _belongs_to_us(value: str) -> bool:
            if not value:
                return False
            parts = [p.strip() for p in value.split(os.pathsep) if p.strip()]
            for p in parts:
                try:
                    p_norm = str(Path(p).resolve())
                except Exception:
                    p_norm = p
                if p_norm.startswith(str(program_dir)) or p_norm.startswith(str(runtime_dir)):
                    return True
            return False

        for var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            val = os.environ.get(var, "")
            if val and not _belongs_to_us(val):
                BOOTLOG(f"FROZEN: drop foreign {var}={val}")
                os.environ.pop(var, None)
            elif val:
                BOOTLOG(f"FROZEN: keep {var}={val}")
    except Exception as exc:
        BOOTLOG(f"FROZEN: QT_* sanitize failed: {exc!r}")

if not IS_FROZEN:
    try:
        _shib = importlib.import_module("shiboken6.Shiboken")
        sys.modules.setdefault("Shiboken", _shib)
    except Exception:
        pass

try:
    import certifi
    import googleapiclient
    import googleapiclient.discovery
    import googleapiclient.errors
    import httplib2
    import http.client
    import json
    import logging
    import ssl
    import urllib.error
    import urllib.parse
    import urllib.request
    import webbrowser

    BOOTLOG("YouTube Data API modules loaded successfully")
except ImportError as exc:
    BOOTLOG(f"Some API modules missing: {exc}")

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMainWindow

    BOOTLOG("STEP-2: after PySide6 import")
except Exception as exc:
    BOOTLOG(f"PySide6 import failed: {exc!r}")
    raise

if not IS_FROZEN:
    try:
        site_pyside = Path(PySide6.__file__).resolve().parent
        for candidate in (site_pyside / "plugins", site_pyside / "Qt" / "plugins", site_pyside / "qt-plugins"):
            if candidate.exists():
                QCoreApplication.addLibraryPath(str(candidate))
                BOOTLOG(f"Added Qt lib path: {candidate}")
                break
    except Exception as exc:
        BOOTLOG(f"Add Qt lib path failed: {exc!r}")

try:
    from theme import apply_theme
    from youtube_collector_widget import YouTubeCollectorWidget

    BOOTLOG("STEP-3: after imports")
except ImportError as exc:
    BOOTLOG(f"Failed to import app modules: {exc}")
    raise


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("유튜브 수집기")
        self.resize(1480, 900)
        self.setCentralWidget(YouTubeCollectorWidget())


def main():
    BOOTLOG("STEP-4: before QApplication()")

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            QGuiApplication.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    BOOTLOG("STEP-5: after QApplication()")

    apply_theme(app, "#ff3030")
    window = MainWindow()
    BOOTLOG("STEP-6: window created")
    window.show()
    BOOTLOG("STEP-7: window shown")

    rc = app.exec()
    BOOTLOG(f"STEP-8: app.exec() returned rc={rc}")
    return rc


if __name__ == "__main__":
    BOOTLOG("__main__ entered")
    try:
        sys.exit(main())
    except Exception as exc:
        BOOTLOG(f"Main execution failed: {exc}")
        import traceback

        BOOTLOG(traceback.format_exc())
        try:
            print(f"Error: {exc}")
            print(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
