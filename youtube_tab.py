# youtube_tab.py
import pandas as pd
from urllib.request import urlopen
from functools import partial

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog, QMessageBox,
    QHeaderView
)
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
            scaled = pixmap.scaled(200, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.imageLoaded.emit(self.row, scaled)
        except Exception as e:
            print(f"이미지 로드 실패: {e}")

# ▶ 자막 비동기 로더
class CaptionLoader(QThread):
    loaded = Signal(int, str)
    def __init__(self, row, url):
        super().__init__()
        self.row = row
        self.url = url
    def run(self):
        text = pu.get_caption_for_url(self.url)  # pytube_util.py에 이미 구현
        self.loaded.emit(self.row, text or "")

class YouTubeSearchWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.image_loaders = []
        self._cap_loaders = {}  # row -> loader
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # 상단 검색줄
        search_layout = QHBoxLayout()
        self.keyword_input = QLineEdit(); self.keyword_input.setPlaceholderText("키워드 입력")
        self.count_input   = QLineEdit(); self.count_input.setPlaceholderText("검색 개수 (예: 5)")
        self.search_button = QPushButton("검색"); self.search_button.clicked.connect(self.on_search)
        search_layout.addWidget(QLabel("키워드")); search_layout.addWidget(self.keyword_input)
        search_layout.addWidget(self.count_input); search_layout.addWidget(self.search_button)
        main_layout.addLayout(search_layout)

        # 테이블 + 우측 패널(B)
        # 컬럼: 썸, 제목, 영상링크, 채널명, 채널링크, 조회수, 구독자, 업로드, 자막(숨김 캐시), 스크립트(버튼)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "썸네일","제목","영상 링크","채널명","채널링크","영상 조회수","구독자 수","업로드 날짜","자막","스크립트"
        ])
        self.table.cellClicked.connect(self.on_table_click)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(116)

        # 헤더 리사이즈 정책 (보기 좋게)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)         # 썸네일
        self.table.setColumnWidth(0, 176)
        for col in (1,):  # 제목
            h.setSectionResizeMode(col, QHeaderView.Stretch)
        for col in (2,4,7):  # 링크/날짜
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col in (3,5,6):  # 채널/숫자
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(8, QHeaderView.ResizeToContents)  # 자막(숨김)
        h.setSectionResizeMode(9, QHeaderView.ResizeToContents)  # 스크립트 버튼

        # 우측 자막 보기(B)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("왼쪽 표에서 [스크립트] 버튼을 누르면 여기 표시됩니다.")
        self.detail_text.setLineWrapMode(QTextEdit.WidgetWidth)  # 줄바꿈

        content_layout = QHBoxLayout()
        content_layout.addWidget(self.table, 3)
        content_layout.addWidget(self.detail_text, 2)
        main_layout.addLayout(content_layout)

        # 하단 기능 버튼
        function_layout = QHBoxLayout()
        self.export_html_btn  = QPushButton("<HTML 저장>");  self.export_html_btn.clicked.connect(self.export_html)
        self.export_excel_btn = QPushButton("<엑셀 저장>");  self.export_excel_btn.clicked.connect(self.export_excel)
        function_layout.addStretch()
        function_layout.addWidget(self.export_html_btn)
        function_layout.addWidget(self.export_excel_btn)
        main_layout.addLayout(function_layout)

        # 표가 너무 넓으면 자막 컬럼(8)을 숨겨 UI를 깔끔하게
        self.table.setColumnHidden(8, True)

    def on_search(self):
        keyword = self.keyword_input.text().strip()
        try:
            count = int(self.count_input.text().strip() or "5")
        except ValueError:
            count = 5
        if not keyword:
            QMessageBox.warning(self, "입력 확인", "키워드를 입력하세요.")
            return

        # 기존 로더 정리
        for loader in self.image_loaders:
            if loader.isRunning(): loader.terminate()
        self.image_loaders.clear()
        for loader in self._cap_loaders.values():
            if loader.isRunning(): loader.terminate()
        self._cap_loaders.clear()

        # ▶ 빠른 검색(자막은 지연 로딩)
        results = pu.get_keyword_videos(keyword, count)

        self.table.setRowCount(0)
        for row, item in enumerate(results):
            self.table.insertRow(row)
            self.table.setRowHeight(row, 116)

            # 썸네일
            thumb_label = QLabel("로딩중...")
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setStyleSheet("border: 1px solid gray; background:#111;")
            self.table.setCellWidget(row, 0, thumb_label)
            self.table.setColumnWidth(0, 176)

            # 제목
            self.table.setItem(row, 1, QTableWidgetItem(item["title"]))

            # 영상 링크(클릭 열기)
            v_item = QTableWidgetItem(item["video_link"])
            v_item.setData(Qt.UserRole, item["video_link"])
            v_item.setForeground(Qt.blue)
            v_item.setToolTip("클릭하여 영상 보기")
            self.table.setItem(row, 2, v_item)

            # 채널명/링크
            self.table.setItem(row, 3, QTableWidgetItem(item["channel"]))
            c_item = QTableWidgetItem(item["channel_link"])
            c_item.setData(Qt.UserRole, item["channel_link"])
            c_item.setForeground(Qt.blue)
            c_item.setToolTip("클릭하여 채널 보기")
            self.table.setItem(row, 4, c_item)

            self.table.setItem(row, 5, QTableWidgetItem(str(item["views"])))
            self.table.setItem(row, 6, QTableWidgetItem(str(item["subscribers"])))
            self.table.setItem(row, 7, QTableWidgetItem(item["upload_date"]))

            # 자막(캐시용, 기본은 빈칸)
            self.table.setItem(row, 8, QTableWidgetItem(item.get("caption","") or ""))

            # ▶ 스크립트 보기 버튼 (A 영역)
            btn = QPushButton("스크립트")
            btn.setCursor(Qt.PointingHandCursor)
            # 안정적으로 URL 보관
            btn.setProperty("video_url", item["video_link"])
            btn.clicked.connect(partial(self._on_script_clicked, row))
            self.table.setCellWidget(row, 9, btn)

            # 썸네일 비동기 로딩
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
        # 링크 컬럼: 2=영상, 4=채널
        if col in (2, 4):
            item = self.table.item(row, col)
            if item:
                url = item.data(Qt.UserRole) or item.text()
                if url:
                    try:
                        QDesktopServices.openUrl(QUrl(url))
                    except Exception:
                        try: webbrowser.open(url)
                        except Exception: pass

    # ▶ 스크립트 버튼 핸들러
    def _on_script_clicked(self, row):
        # 이미 캐시되어 있으면 즉시 표시
        cached_item = self.table.item(row, 8)
        if cached_item and cached_item.text().strip():
            self.detail_text.setText(cached_item.text())
            return

        # URL 취득
        btn = self.table.cellWidget(row, 9)
        url = btn.property("video_url") if btn else None
        if not url:
            link_item = self.table.item(row, 2)
            url = link_item.data(Qt.UserRole) if link_item else ""

        self.detail_text.setText("자막 로딩 중…")
        loader = CaptionLoader(row, url)
        loader.loaded.connect(self._on_caption_loaded)
        self._cap_loaders[row] = loader
        loader.start()

    def _on_caption_loaded(self, row, text):
        self.detail_text.setText(text or "(자막 없음)")
        # 테이블에도 캐시
        self.table.setItem(row, 8, QTableWidgetItem(text or ""))

    # 저장 유틸
    def _collect_rows(self):
        rows=[]
        for r in range(self.table.rowCount()):
            rows.append({
                "title": self.table.item(r,1).text() if self.table.item(r,1) else "",
                "video_link": self.table.item(r,2).text() if self.table.item(r,2) else "",
                "channel": self.table.item(r,3).text() if self.table.item(r,3) else "",
                "channel_link": self.table.item(r,4).text() if self.table.item(r,4) else "",
                "views": self.table.item(r,5).text() if self.table.item(r,5) else "",
                "subscribers": self.table.item(r,6).text() if self.table.item(r,6) else "",
                "upload_date": self.table.item(r,7).text() if self.table.item(r,7) else "",
                "caption": self.table.item(r,8).text() if self.table.item(r,8) else "",
            })
        return rows

    def export_excel(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self,"알림","저장할 데이터가 없습니다."); return
        path,_ = QFileDialog.getSaveFileName(self,"엑셀 저장","youtube_results.xlsx","Excel 파일 (*.xlsx)")
        if not path: return
        pd.DataFrame(rows).to_excel(path, index=False)
        QMessageBox.information(self,"완료",f"엑셀 저장 완료\n{path}")

    def export_html(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self,"알림","저장할 데이터가 없습니다."); return
        path,_ = QFileDialog.getSaveFileName(self,"HTML 저장","youtube_results.html","HTML 파일 (*.html)")
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
        with open(path,"w",encoding="utf-8") as f: f.write("\n".join(html))
        QMessageBox.information(self,"완료",f"HTML 저장 완료\n{path}")
