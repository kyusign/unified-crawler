# app.py — YouTube Data API 전환판
from diag_bootstrap import install as _install_diag
_install_diag()  # 반드시 가장 먼저

# --- Shiboken 중복 초기화 가드 ---
import sys, importlib
try:
    _shib = importlib.import_module("shiboken6.Shiboken")
    sys.modules.setdefault("Shiboken", _shib)
except Exception:
    pass

# 부트로그 유틸
from pathlib import Path
def BOOTLOG(msg: str):
    from diag_bootstrap import log
    log(msg)

# (변경) pytube 패치 제거 — 더 이상 사용하지 않음
# from pytube_patches import apply_pytube_after_patch
# apply_pytube_after_patch()

BOOTLOG("STEP-1: before PySide6 import")
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget
BOOTLOG("STEP-2: after PySide6 import")

# 개발 모드에서도 Qt plugin 루트 등록 (안전빵)
try:
    import PySide6
    _site_pyside = Path(PySide6.__file__).resolve().parent
    for _cand in (_site_pyside / "plugins", _site_pyside / "Qt" / "plugins", _site_pyside / "qt-plugins"):
        if _cand.exists():
            QCoreApplication.addLibraryPath(str(_cand))
            BOOTLOG(f"Added Qt lib path: {_cand}")
            break
except Exception as e:
    BOOTLOG(f"Add Qt lib path failed: {e!r}")

# 나머지 앱 위젯/테마 import
from community_tab import CommunityCrawlerWidget
from youtube_tab import YouTubeSearchWidget
from theme import apply_theme

BOOTLOG("STEP-3: after imports")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("원초적인 인사이트 – 통합 크롤러")
        self.resize(1600, 900)
        tabs = QTabWidget()
        tabs.addTab(CommunityCrawlerWidget(), "커뮤니티 크롤러")
        tabs.addTab(YouTubeSearchWidget(), "YouTube 검색")
        self.setCentralWidget(tabs)

def main():
    BOOTLOG("STEP-4: before QApplication()")
    # 하이 DPI 옵션
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
    w = MainWindow()
    BOOTLOG("STEP-6: window created")
    w.show()
    BOOTLOG("STEP-7: window shown")
    rc = app.exec()
    BOOTLOG(f"STEP-8: app.exec() returned rc={rc}")
    return rc

if __name__ == "__main__":
    BOOTLOG("__main__ entered")
    sys.exit(main())
