# app.py
import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget
from community_tab import CommunityCrawlerWidget
from youtube_tab import YouTubeSearchWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("원초적 인사이트 – 통합 크롤러")
        self.resize(1280, 800)

        tabs = QTabWidget()
        tabs.addTab(CommunityCrawlerWidget(), "커뮤니티 크롤러")
        tabs.addTab(YouTubeSearchWidget(), "YouTube 검색")
        self.setCentralWidget(tabs)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
