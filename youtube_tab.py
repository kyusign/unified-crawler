# youtube_tab.py
import pandas as pd
from urllib.request import urlopen

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog, QMessageBox
)
from PySide6.QtGui import QDesktopServices
import webbrowser

import pytube_util as pu

class ImageLoader(QThread):
    imageLoaded = Signal(int, QPixmap)
    def __init__(self, row, url):
        super().__init__()
        self.row = row
        self.url = url
    def run(self):
        try:
            with urlopen(self.url) as response:
                data = response.read()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            scaled = pixmap.scaled(200, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.imageLoaded.emit(self.row, scaled)
        except Exception as e:
            print(f"이미지 로드 실패: {e}")

class YouTubeSearchWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.image_loaders = []
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # 검색창
        search_layout = QHBoxLayout()
        self.keyword_input = QLineEdit(); self.keyword_input.setPlaceholderText("키워드 입력")
        self.count_input = QLineEdit(); self.count_input.setPlaceholderText("검색 개수 (예: 5)")
        self.search_button = QPushButton("검색"); self.search_button.clicked.connect(self.on_search)
        search_layout.addWidget(QLabel("키워드")); search_layout.addWidget(self.keyword_input)
        search_layout.addWidget(self.count_input); search_layout.addWidget(self.search_button)
        main_layout.addLayout(search_layout)

        # 테이블 + 상세
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "썸네일", "제목", "영상 링크", "채널명", "채널링크", "영상 조회수", "구독자 수", "업로드 날짜", "자막"
        ])
        self.table.cellClicked.connect(self.on_table_click)

        self.detail_text = QTextEdit(); self.detail_text.setReadOnly(True)

        content_layout = QHBoxLayout()
        content_layout.addWidget(self.table, 3)
        content_layout.addWidget(self.detail_text, 2)
        main_layout.addLayout(content_layout)

        # export
        function_layout = QHBoxLayout()
        self.export_html_btn = QPushButton("<HTML 저장>"); self.export_html_btn.clicked.connect(self.export_html)
        self.export_excel_btn = QPushButton("<엑셀 저장>"); self.export_excel_btn.clicked.connect(self.export_excel)
        function_layout.addStretch()
        function_layout.addWidget(self.export_html_btn)
        function_layout.addWidget(self.export_excel_btn)
        main_layout.addLayout(function_layout)

    def on_search(self):
        keyword = self.keyword_input.text().strip()
        try:
            count = int(self.count_input.text().strip() or "5")
        except ValueError:
            count = 5

        if not keyword:
            QMessageBox.warning(self, "입력 확인", "키워드를 입력하세요.")
            return

        for loader in self.image_loaders:
            if loader.isRunning(): loader.terminate()
        self.image_loaders.clear()

        results = pu.get_keyword_videos(keyword, count)
        self.table.setRowCount(0)

        for row, item in enumerate(results):
            self.table.insertRow(row)
            self.table.setRowHeight(row, 99)

            thumb_label = QLabel("로딩중...")
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setStyleSheet("border: 1px solid gray;")
            self.table.setCellWidget(row, 0, thumb_label)
            self.table.setColumnWidth(0, 176)

            self.table.setItem(row, 1, QTableWidgetItem(item["title"]))

            v_item = QTableWidgetItem(item["video_link"])
            v_item.setData(Qt.UserRole, item["video_link"])
            v_item.setForeground(Qt.blue)
            v_item.setToolTip("클릭하여 영상 보기")
            self.table.setItem(row, 2, v_item)

            self.table.setItem(row, 3, QTableWidgetItem(item["channel"]))

            c_item = QTableWidgetItem(item["channel_link"])
            c_item.setData(Qt.UserRole, item["channel_link"])
            c_item.setForeground(Qt.blue)
            c_item.setToolTip("클릭하여 채널 보기")
            self.table.setItem(row, 4, c_item)

            self.table.setItem(row, 5, QTableWidgetItem(str(item["views"])))
            self.table.setItem(row, 6, QTableWidgetItem(str(item["subscribers"])))
            self.table.setItem(row, 7, QTableWidgetItem(item["upload_date"]))
            self.table.setItem(row, 8, QTableWidgetItem(item["caption"] or ""))

            loader = ImageLoader(row, item["thumbnail"])
            loader.imageLoaded.connect(self.set_thumbnail)
            self.image_loaders.append(loader)
            loader.start()

    def set_thumbnail(self, row, pixmap):
        lab = self.table.cellWidget(row, 0)
        if lab:
            lab.setPixmap(pixmap)
            lab.setText("")
            lab.setScaledContents(True)

    def on_table_click(self, row, col):
        if col in (2, 4):
            item = self.table.item(row, col)
            if item:
                url = item.data(Qt.UserRole)
                if url:
                    try:
                        QDesktopServices.openUrl(QUrl(url))
                    except Exception:
                        try: webbrowser.open(url)
                        except Exception: pass
        caption_item = self.table.item(row, 8)
        if caption_item:
            self.detail_text.setText(caption_item.text())

    # 저장 유틸
    def _collect_rows(self):
        rows = []
        for r in range(self.table.rowCount()):
            rows.append({
                "title": self.table.item(r, 1).text() if self.table.item(r, 1) else "",
                "video_link": self.table.item(r, 2).text() if self.table.item(r, 2) else "",
                "channel": self.table.item(r, 3).text() if self.table.item(r, 3) else "",
                "channel_link": self.table.item(r, 4).text() if self.table.item(r, 4) else "",
                "views": self.table.item(r, 5).text() if self.table.item(r, 5) else "",
                "subscribers": self.table.item(r, 6).text() if self.table.item(r, 6) else "",
                "upload_date": self.table.item(r, 7).text() if self.table.item(r, 7) else "",
                "caption": self.table.item(r, 8).text() if self.table.item(r, 8) else "",
            })
        return rows

    def export_excel(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "알림", "저장할 데이터가 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "엑셀 저장", "youtube_results.xlsx", "Excel 파일 (*.xlsx)")
        if not path: return
        df = pd.DataFrame(rows)
        df.to_excel(path, index=False)
        QMessageBox.information(self, "완료", f"엑셀 저장 완료\n{path}")

    def export_html(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "알림", "저장할 데이터가 없습니다.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "HTML 저장", "youtube_results.html", "HTML 파일 (*.html)")
        if not path: return
        html = ["<html><head><meta charset='utf-8'></head><body><table border='1' cellspacing='0' cellpadding='6'>"]
        html.append("<tr><th>제목</th><th>영상 링크</th><th>채널</th><th>채널 링크</th><th>조회수</th><th>구독자</th><th>업로드</th></tr>")
        for r in rows:
            html.append(
                f"<tr>"
                f"<td>{r['title']}</td>"
                f"<td><a href='{r['video_link']}'>{r['video_link']}</a></td>"
                f"<td>{r['channel']}</td>"
                f"<td><a href='{r['channel_link']}'>{r['channel_link']}</a></td>"
                f"<td>{r['views']}</td>"
                f"<td>{r['subscribers']}</td>"
                f"<td>{r['upload_date']}</td>"
                f"</tr>"
            )
        html.append("</table></body></html>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(html))
        QMessageBox.information(self, "완료", f"HTML 저장 완료\n{path}")
