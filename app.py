# app.py
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget
from community_tab import CommunityCrawlerWidget
from youtube_tab import YouTubeSearchWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("원초적인 인사이트 – 통합 크롤러")
        self.resize(1600, 900)   # ← 넉넉한 기본 크기
        tabs = QTabWidget()
        tabs.addTab(CommunityCrawlerWidget(), "커뮤니티 크롤러")
        tabs.addTab(YouTubeSearchWidget(), "YouTube 검색")
        self.setCentralWidget(tabs)

if __name__ == "__main__":
    # High DPI
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # (선택) 스케일 반올림 정책
    try:
        from PySide6.QtGui import Qt as QtGuiQt
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            QGuiApplication.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
