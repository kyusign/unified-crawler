from __future__ import annotations

import html
import logging
from typing import Any

import xlsxwriter
from PySide6.QtCore import QSignalBlocker, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import youtube_api_util as ytu

logger = logging.getLogger("ytcollector")


def format_duration(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def clamp_count(raw: str) -> int:
    try:
        value = int((raw or "").strip() or "50")
    except ValueError:
        value = 50
    return max(1, min(value, 200))


class InfoDialog(QDialog):
    def __init__(self, title: str, lines: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(8)

        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 700; font-size: 15px;")
        inner.addWidget(heading)

        for line in lines:
            label = QLabel(line)
            label.setWordWrap(True)
            inner.addWidget(label)

        root.addWidget(card)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok = QPushButton("확인")
        ok.setProperty("type", "primary")
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        root.addLayout(buttons)


class ApiKeyDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("YouTube API 키")
        self.setModal(True)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("YouTube Data API 키를 입력하세요")
        current = ytu.peek_effective_key()
        if current:
            self.key_edit.setText(current)

        self.status_label = QLabel("상태: 확인 전")

        load_button = QPushButton("파일에서 불러오기")
        load_button.clicked.connect(self.on_load_file)

        test_button = QPushButton("검증")
        test_button.setProperty("type", "outline")
        test_button.clicked.connect(self.on_validate)

        save_button = QPushButton("저장")
        save_button.setProperty("type", "primary")
        save_button.clicked.connect(self.on_save)

        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(16, 14, 16, 14)
        form.addRow("API 키", self.key_edit)
        form.addRow("검증 결과", self.status_label)
        root.addWidget(card)

        buttons = QHBoxLayout()
        buttons.addWidget(load_button)
        buttons.addStretch()
        buttons.addWidget(test_button)
        buttons.addWidget(save_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def on_load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "youtube_api_key.txt 선택",
            "",
            "텍스트 파일 (*.txt);;모든 파일 (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read().strip()
        except OSError as exc:
            QMessageBox.critical(self, "오류", f"파일을 읽을 수 없습니다.\n{exc}")
            return

        if not text:
            QMessageBox.warning(self, "빈 파일", "선택한 파일에 API 키가 없습니다.")
            return

        self.key_edit.setText(text)

    def on_validate(self):
        key = self.key_edit.text().strip()
        ok, message = ytu.validate_api_key(key)
        if ok:
            self.status_label.setText("상태: 유효함")
            QMessageBox.information(self, "검증", "API 키가 유효합니다.")
            return

        self.status_label.setText(f"상태: {message or '유효하지 않음'}")
        QMessageBox.warning(self, "검증 실패", message or "API 키가 유효하지 않습니다.")

    def on_save(self):
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "키 없음", "먼저 API 키를 입력하세요.")
            return

        ok, message = ytu.validate_api_key(key)
        if not ok:
            QMessageBox.warning(self, "검증 실패", message or "API 키가 유효하지 않습니다.")
            return

        try:
            path = ytu.save_api_key_to_disk(key)
        except OSError as exc:
            QMessageBox.critical(self, "저장 실패", f"API 키를 저장할 수 없습니다.\n{exc}")
            return

        QMessageBox.information(self, "저장 완료", f"API 키를 저장했습니다.\n{path}")
        self.accept()


class NumericItem(QTableWidgetItem):
    def __init__(self, value: int):
        self.value = int(value or 0)
        super().__init__(f"{self.value:,}")

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, NumericItem):
            return self.value < other.value
        return super().__lt__(other)


class DateItem(QTableWidgetItem):
    def __init__(self, value: str):
        self.value = value or ""
        super().__init__(self.value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, DateItem):
            return self.value < other.value
        return super().__lt__(other)


class DurationItem(QTableWidgetItem):
    def __init__(self, seconds: int):
        self.seconds = int(seconds or 0)
        super().__init__(format_duration(self.seconds))

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, DurationItem):
            return self.seconds < other.seconds
        return super().__lt__(other)


class SearchWorker(QThread):
    progress = Signal(int, int)
    result = Signal(dict)
    summary = Signal(int, int)
    done = Signal()
    error = Signal(str)

    def __init__(self, keyword: str, count: int):
        super().__init__()
        self.keyword = keyword
        self.count = count

    def run(self):
        try:
            ids = ytu.search_video_ids(self.keyword, self.count)
            total = len(ids)
            self.progress.emit(0, total)
            self.summary.emit(total, self.count)

            for index, info in enumerate(ytu.iter_videos_info(ids), start=1):
                if not info:
                    continue
                normalized = dict(info)
                normalized["form_label"] = "쇼츠" if normalized.get("is_shorts") else "롱폼"
                self.result.emit(normalized)
                self.progress.emit(index, total)
            self.done.emit()
        except Exception as exc:
            logger.exception("Search failed")
            self.error.emit(str(exc))


class YouTubeCollectorWidget(QWidget):
    COL_TITLE = 0
    COL_VIEWS = 1
    COL_LIKES = 2
    COL_COMMENTS = 3
    COL_SUBS = 4
    COL_DATE = 5
    COL_DURATION = 6
    COL_TYPE = 7
    COL_CHANNEL = 8
    COL_LINK = 9

    def __init__(self):
        super().__init__()
        self.worker: SearchWorker | None = None
        self.items: list[dict[str, Any]] = []
        self._build_ui()
        self.refresh_api_key_status()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top_card = QFrame()
        top_card.setObjectName("Card")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(8)

        self.api_status = QLabel("API 키 미설정")
        self.api_status.setStyleSheet(
            "padding:6px 10px; border-radius:10px; background:#fef3c7; color:#92400e;"
        )

        self.api_button = QPushButton("API 키")
        self.api_button.setProperty("type", "outline")
        self.api_button.clicked.connect(self.open_api_dialog)

        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("검색어")
        self.keyword_input.returnPressed.connect(self.on_search)

        self.count_input = QLineEdit("50")
        self.count_input.setPlaceholderText("개수")

        self.search_button = QPushButton("검색")
        self.search_button.setProperty("type", "primary")
        self.search_button.clicked.connect(self.on_search)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(14)
        self.progress.setFormat("%p%  (%v/%m)")

        left = QHBoxLayout()
        left.addWidget(QLabel("YouTube API"))
        left.addWidget(self.api_status)
        left.addWidget(self.api_button)
        left.addStretch()

        right = QHBoxLayout()
        right.addWidget(QLabel("검색어"))
        right.addWidget(self.keyword_input, 2)
        right.addWidget(QLabel("개수"))
        right.addWidget(self.count_input, 0)
        right.addWidget(self.search_button, 0)
        right.addWidget(self.progress, 1)

        top_layout.addLayout(left, 3)
        top_layout.addLayout(right, 7)
        root.addWidget(top_card)

        self.summary_label = QLabel("결과: 0개")
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 10)
        self.table.setObjectName("Card")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels(
            [
                "제목",
                "조회수",
                "좋아요",
                "댓글수",
                "구독자수",
                "업로드일",
                "길이",
                "형식",
                "채널명",
                "영상 링크",
            ]
        )

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_TITLE, QHeaderView.Interactive)
        header.setSectionResizeMode(self.COL_VIEWS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_LIKES, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_COMMENTS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_SUBS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_CHANNEL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_LINK, QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_TITLE, 440)
        self.table.setColumnWidth(self.COL_LINK, 260)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self.on_table_double_click)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()

        self.export_html_button = QPushButton("HTML 저장")
        self.export_html_button.setProperty("type", "outline")
        self.export_html_button.clicked.connect(self.export_html)

        self.export_excel_button = QPushButton("엑셀 저장")
        self.export_excel_button.setProperty("type", "outline")
        self.export_excel_button.clicked.connect(self.export_excel)

        bottom.addWidget(self.export_html_button)
        bottom.addWidget(self.export_excel_button)
        root.addLayout(bottom)

    def _set_busy(self, busy: bool):
        self.search_button.setEnabled(not busy)
        self.api_button.setEnabled(not busy)
        self.keyword_input.setEnabled(not busy)
        self.count_input.setEnabled(not busy)

    def _style_api_status(self, ok: bool):
        if ok:
            self.api_status.setText("API 키 설정됨")
            self.api_status.setStyleSheet(
                "padding:6px 10px; border-radius:10px; background:rgba(16,185,129,.15); color:#065f46;"
            )
        else:
            self.api_status.setText("API 키 미설정")
            self.api_status.setStyleSheet(
                "padding:6px 10px; border-radius:10px; background:#fef3c7; color:#92400e;"
            )

    def refresh_api_key_status(self):
        info = ytu.api_key_info()
        if info.get("found") == "1":
            masked = info.get("masked") or ""
            location = info.get("location") or ""
            self._style_api_status(True)
            self.api_status.setToolTip(f"{masked}\n{location}" if location else masked)
        else:
            self._style_api_status(False)
            self.api_status.setToolTip("검색 전에 API 키를 먼저 설정하세요.")

    def open_api_dialog(self):
        dialog = ApiKeyDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_api_key_status()

    def on_search(self):
        if not ytu.peek_effective_key():
            InfoDialog("API 키 필요", ["먼저 YouTube Data API 키를 설정하세요."], self).exec()
            self.open_api_dialog()
            if not ytu.peek_effective_key():
                return

        keyword = self.keyword_input.text().strip()
        if not keyword:
            InfoDialog("검색어 필요", ["검색어를 입력하세요."], self).exec()
            return

        count = clamp_count(self.count_input.text())
        self.count_input.setText(str(count))

        self.items.clear()
        self.summary_label.setText("결과: 0개")

        with QSignalBlocker(self.table):
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self._set_busy(True)

        self.worker = SearchWorker(keyword, count)
        self.worker.progress.connect(self._on_progress)
        self.worker.summary.connect(self._on_summary)
        self.worker.result.connect(self._on_result)
        self.worker.done.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        if total <= 0:
            self.progress.setRange(0, 0)
            return
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(current)

    def _on_summary(self, found: int, requested: int):
        if found < requested:
            InfoDialog(
                "일부 결과만 수집됨",
                [
                    f"요청 개수: {requested:,}개",
                    f"실제 수집: {found:,}개",
                    "이 검색어로는 요청한 수보다 적은 영상만 반환되었습니다.",
                ],
                self,
            ).exec()

    def _on_result(self, item: dict[str, Any]):
        self.items.append(item)
        self.summary_label.setText(f"결과: {len(self.items):,}개")
        self._append_row(item)

    def _on_done(self):
        if self.progress.maximum() > 0:
            self.progress.setValue(self.progress.maximum())
        QTimer.singleShot(400, lambda: self.progress.setVisible(False))
        self._set_busy(False)
        self.table.setSortingEnabled(True)
        self.worker = None

    def _on_error(self, message: str):
        self.progress.setVisible(False)
        self._set_busy(False)
        self.table.setSortingEnabled(True)
        self.worker = None
        InfoDialog("검색 실패", [message], self).exec()

    def _append_row(self, item: dict[str, Any]):
        row = self.table.rowCount()
        self.table.insertRow(row)

        title_item = QTableWidgetItem(item.get("title") or "")
        views_item = NumericItem(int(item.get("views") or 0))
        likes_item = NumericItem(int(item.get("likes") or 0))
        comments_item = NumericItem(int(item.get("comments") or 0))
        subs_item = NumericItem(int(item.get("subscribers") or 0))
        date_item = DateItem(item.get("upload_date") or "")
        duration_item = DurationItem(int(item.get("duration_sec") or 0))
        type_item = QTableWidgetItem(item.get("form_label") or "")
        channel_item = QTableWidgetItem(item.get("channel") or "")
        link_item = QTableWidgetItem(item.get("video_link") or "")

        self.table.setItem(row, self.COL_TITLE, title_item)
        self.table.setItem(row, self.COL_VIEWS, views_item)
        self.table.setItem(row, self.COL_LIKES, likes_item)
        self.table.setItem(row, self.COL_COMMENTS, comments_item)
        self.table.setItem(row, self.COL_SUBS, subs_item)
        self.table.setItem(row, self.COL_DATE, date_item)
        self.table.setItem(row, self.COL_DURATION, duration_item)
        self.table.setItem(row, self.COL_TYPE, type_item)
        self.table.setItem(row, self.COL_CHANNEL, channel_item)
        self.table.setItem(row, self.COL_LINK, link_item)

    def on_table_double_click(self, row: int, col: int):
        if col != self.COL_LINK:
            return
        item = self.table.item(row, col)
        if not item:
            return
        url = item.text().strip()
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    def _collect_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for row in range(self.table.rowCount()):
            rows.append(
                {
                    "title": self.table.item(row, self.COL_TITLE).text() if self.table.item(row, self.COL_TITLE) else "",
                    "views": self.table.item(row, self.COL_VIEWS).text() if self.table.item(row, self.COL_VIEWS) else "",
                    "likes": self.table.item(row, self.COL_LIKES).text() if self.table.item(row, self.COL_LIKES) else "",
                    "comments": self.table.item(row, self.COL_COMMENTS).text() if self.table.item(row, self.COL_COMMENTS) else "",
                    "subscribers": self.table.item(row, self.COL_SUBS).text() if self.table.item(row, self.COL_SUBS) else "",
                    "upload_date": self.table.item(row, self.COL_DATE).text() if self.table.item(row, self.COL_DATE) else "",
                    "duration": self.table.item(row, self.COL_DURATION).text() if self.table.item(row, self.COL_DURATION) else "",
                    "type": self.table.item(row, self.COL_TYPE).text() if self.table.item(row, self.COL_TYPE) else "",
                    "channel": self.table.item(row, self.COL_CHANNEL).text() if self.table.item(row, self.COL_CHANNEL) else "",
                    "video_link": self.table.item(row, self.COL_LINK).text() if self.table.item(row, self.COL_LINK) else "",
                }
            )
        return rows

    def export_excel(self):
        rows = self._collect_rows()
        if not rows:
            InfoDialog("데이터 없음", ["먼저 검색한 뒤 저장하세요."], self).exec()
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "엑셀 저장",
            "youtube_수집결과.xlsx",
            "Excel 파일 (*.xlsx)",
        )
        if not path:
            return

        try:
            workbook = xlsxwriter.Workbook(path)
            worksheet = workbook.add_worksheet("results")

            header_fmt = workbook.add_format({"bold": True, "bg_color": "#F0F3F8", "border": 1})
            text_fmt = workbook.add_format({"valign": "top"})
            num_fmt = workbook.add_format({"num_format": "#,##0", "valign": "top"})

            headers = [
                "제목",
                "조회수",
                "좋아요",
                "댓글수",
                "구독자수",
                "업로드일",
                "길이",
                "형식",
                "채널명",
                "영상 링크",
            ]
            for col, header in enumerate(headers):
                worksheet.write(0, col, header, header_fmt)

            worksheet.set_column(0, 0, 60)
            worksheet.set_column(1, 4, 14)
            worksheet.set_column(5, 8, 20)
            worksheet.set_column(9, 9, 44)

            def parse_int(text: str) -> int | None:
                stripped = (text or "").replace(",", "").strip()
                if not stripped:
                    return None
                try:
                    return int(stripped)
                except ValueError:
                    return None

            for row_index, row in enumerate(rows, start=1):
                worksheet.write(row_index, 0, row["title"], text_fmt)
                for col_index, key in enumerate(("views", "likes", "comments", "subscribers"), start=1):
                    value = parse_int(row[key])
                    if value is None:
                        worksheet.write(row_index, col_index, row[key], text_fmt)
                    else:
                        worksheet.write_number(row_index, col_index, value, num_fmt)
                worksheet.write(row_index, 5, row["upload_date"], text_fmt)
                worksheet.write(row_index, 6, row["duration"], text_fmt)
                worksheet.write(row_index, 7, row["type"], text_fmt)
                worksheet.write(row_index, 8, row["channel"], text_fmt)
                worksheet.write(row_index, 9, row["video_link"], text_fmt)

            workbook.close()
            InfoDialog("저장 완료", [path], self).exec()
        except Exception as exc:
            InfoDialog("저장 실패", [str(exc)], self).exec()

    def export_html(self):
        rows = self._collect_rows()
        if not rows:
            InfoDialog("데이터 없음", ["먼저 검색한 뒤 저장하세요."], self).exec()
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "HTML 저장",
            "youtube_수집결과.html",
            "HTML 파일 (*.html)",
        )
        if not path:
            return

        lines = [
            "<html><head><meta charset='utf-8'></head><body><table border='1' cellspacing='0' cellpadding='6'>",
            "<tr><th>제목</th><th>조회수</th><th>좋아요</th><th>댓글수</th><th>구독자수</th><th>업로드일</th><th>길이</th><th>형식</th><th>채널명</th><th>영상 링크</th></tr>",
        ]

        for row in rows:
            safe_title = html.escape(row["title"])
            safe_channel = html.escape(row["channel"])
            safe_link = html.escape(row["video_link"])
            safe_type = html.escape(row["type"])
            safe_date = html.escape(row["upload_date"])
            safe_duration = html.escape(row["duration"])
            lines.append(
                "<tr>"
                f"<td>{safe_title}</td>"
                f"<td>{html.escape(row['views'])}</td>"
                f"<td>{html.escape(row['likes'])}</td>"
                f"<td>{html.escape(row['comments'])}</td>"
                f"<td>{html.escape(row['subscribers'])}</td>"
                f"<td>{safe_date}</td>"
                f"<td>{safe_duration}</td>"
                f"<td>{safe_type}</td>"
                f"<td>{safe_channel}</td>"
                f"<td><a href='{safe_link}'>{safe_link}</a></td>"
                "</tr>"
            )

        lines.append("</table></body></html>")

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            InfoDialog("저장 완료", [path], self).exec()
        except Exception as exc:
            InfoDialog("저장 실패", [str(exc)], self).exec()
