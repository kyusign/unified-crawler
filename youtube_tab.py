# youtube_tab.py
import webbrowser
from urllib.request import urlopen

# pandas 제거
import xlsxwriter  # NEW: 경량 엑셀 라이브러리
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QPixmap, QDesktopServices, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QFileDialog, QMessageBox,
    QHeaderView, QProgressBar, QComboBox, QDialog, QFormLayout,
    QDialogButtonBox, QSplitter, QSizePolicy, QAbstractItemView
)

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pytube import Search
import pytube_util as pu

# ---------- 로거 ----------
logger = logging.getLogger("ytcrawl")


# ================== 이미지 비동기 로더 ==================
# 행 번호(row)를 넘기지 않고, 고유키(=영상 링크)를 넘겨서 정렬/필터 후에도 정확히 매칭
class ImageLoader(QThread):
    imageLoaded = Signal(str, QPixmap)  # key=video_link, pixmap

    def __init__(self, key: str, url: str):
        super().__init__()
        self.key = key          # 영상 링크(유일 키로 사용)
        self.url = url          # 썸네일 이미지 URL

    def run(self):
        try:
            with urlopen(self.url) as response:
                data = response.read()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            scaled = pixmap.scaled(200, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.imageLoaded.emit(self.key, scaled)
        except Exception as e:
            logger.exception(f"[IMG] 이미지 로드 실패: key={self.key}, url={self.url} :: {e}")


# ================== 정렬 정확도를 위한 아이템 ==================
class NumericItem(QTableWidgetItem):
    def __init__(self, value):
        try:
            ival = int(str(value).replace(",", ""))
        except Exception:
            ival = 0
        super().__init__(f"{ival:,}")
        self._ival = ival

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return self._ival < other._ival
        try:
            o = int(str(other.text()).replace(",", ""))
            return self._ival < o
        except Exception:
            return super().__lt__(other)


class DateItem(QTableWidgetItem):
    def __init__(self, s: str):
        super().__init__(s or "")
        self._key = s or ""

    def __lt__(self, other):
        if isinstance(other, DateItem):
            return self._key < other._key
        return super().__lt__(other)


# ================== 필터 대화창 ==================
class FilterDialog(QDialog):
    def __init__(self, parent=None, init: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("필터/정렬 설정")
        self.setModal(True)

        self.form_combo = QComboBox()
        self.form_combo.addItems(["형식: 전체", "형식: 롱폼", "형식: 숏폼"])

        self.min_views = QLineEdit(); self.min_views.setPlaceholderText("조회수 ≥ (예: 100k / 10만)")
        self.max_views = QLineEdit(); self.max_views.setPlaceholderText("조회수 ≤ (빈칸=무제한)")
        self.min_subs  = QLineEdit(); self.min_subs.setPlaceholderText("구독자 ≥ (예: 50k / 5만)")
        self.max_subs  = QLineEdit(); self.max_subs.setPlaceholderText("구독자 ≤ (빈칸=무제한)")

        if init:
            self.form_combo.setCurrentIndex(init.get("form_idx", 0))
            for w, k in ((self.min_views, "min_views_text"), (self.max_views, "max_views_text"),
                         (self.min_subs, "min_subs_text"), (self.max_subs, "max_subs_text")):
                if init.get(k): w.setText(init[k])

        form = QFormLayout(self)
        form.addRow("형식", self.form_combo)
        form.addRow("조회수 최소", self.min_views)
        form.addRow("조회수 최대", self.max_views)
        form.addRow("구독자 최소", self.min_subs)
        form.addRow("구독자 최대", self.max_subs)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        self.result = None

    @staticmethod
    def _parse_count(s: str | None) -> int | None:
        if not s: return None
        t = str(s).strip().lower().replace(",", "")
        if not t: return None
        if t.endswith(("k", "m", "b")):
            num = float(t[:-1]); unit = t[-1]
            mult = 1_000 if unit == "k" else (1_000_000 if unit == "m" else 1_000_000_000)
            return int(num * mult)
        if t.endswith("억"):
            return int(float(t[:-1]) * 100_000_000)
        if t.endswith("만"):
            return int(float(t[:-1]) * 10_000)
        if t.endswith("천"):
            return int(float(t[:-1]) * 1_000)
        return int(float(t))

    def accept(self):
        self.result = {
            "form_idx": self.form_combo.currentIndex(),
            "min_views": self._parse_count(self.min_views.text()),
            "max_views": self._parse_count(self.max_views.text()),
            "min_subs":  self._parse_count(self.min_subs.text()),
            "max_subs":  self._parse_count(self.max_subs.text()),
            "min_views_text": self.min_views.text(),
            "max_views_text": self.max_views.text(),
            "min_subs_text":  self.min_subs.text(),
            "max_subs_text":  self.max_subs.text(),
        }
        super().accept()


# ================== 검색 워커(페이지네이션 + 병렬 수집 + 중복제거) ==================
class SearchWorker(QThread):
    progress = Signal(int, int)     # (current, total)
    one = Signal(dict)
    done = Signal()
    error = Signal(str)

    def __init__(self, keyword: str, count: int, workers: int = 8):
        super().__init__()
        self.keyword = keyword
        self.count = count
        self.workers = max(1, workers)

    def run(self):
        try:
            logger.info(f"[UI-SEARCH] 시작: q='{self.keyword}', want={self.count}")
            s = Search(self.keyword)

            # ---- 결과에서 고유 video_id만 수집하는 헬퍼 ----
            seen = set()
            unique_vids: list[str] = []

            def harvest_from_results() -> None:
                for v in s.results:
                    vid = getattr(v, "video_id", None)
                    if not vid:
                        continue
                    if vid in seen:
                        continue
                    seen.add(vid)
                    unique_vids.append(vid)
                    if len(unique_vids) >= self.count:
                        break

            # 최초 수확
            harvest_from_results()

            # 원하는 개수만큼 고유 ID 확보될 때까지 추가 페이지 요청
            # 안전장치: 최대 30페이지까지 시도
            safety = 30
            while len(unique_vids) < self.count and safety > 0:
                prev_len = len(s.results)
                try:
                    s.get_next_results()
                except Exception as e:
                    logger.exception(f"[UI-SEARCH] get_next_results 실패 :: {e}")
                    break
                if len(s.results) == prev_len:
                    logger.debug("[UI-SEARCH] 더 이상 새로운 페이지 없음")
                    break
                harvest_from_results()
                safety -= 1

            total = len(unique_vids)
            logger.info(f"[UI-SEARCH] 대상(중복제거) {total}개: {unique_vids}")
            self.progress.emit(0, total)
            if total == 0:
                self.done.emit(); return

            # 병렬 수집
            done_cnt = 0
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                futures = {ex.submit(pu.get_video_info, vid): vid for vid in unique_vids}
                for fut in as_completed(futures):
                    vid = futures[fut]
                    try:
                        info = fut.result()
                        if info:
                            self.one.emit(info)
                    except Exception as e:
                        logger.exception(f"[UI-SEARCH] get_video_info 실패: {vid} :: {e}")
                    finally:
                        done_cnt += 1
                        self.progress.emit(done_cnt, total)

            self.done.emit()
            logger.info("[UI-SEARCH] 완료")
        except Exception as e:
            logger.exception(f"[UI-SEARCH] 전체 실패 :: {e}")
            self.error.emit(str(e))


# ================== 메인 위젯 ==================
class YouTubeSearchWidget(QWidget):
    # 컬럼 인덱스
    COL_THUMB = 0
    COL_TITLE = 1
    COL_VIEWS = 2
    COL_SUBS  = 3
    COL_DATE  = 4
    COL_CAPSN = 5  # 자막 스니펫
    COL_VURL  = 6
    COL_FORM  = 7
    COL_CH    = 8
    COL_CAPFULL = 9  # 숨김: 자막 전체

    # ---- 컬럼 최소/기본 폭(디자인) ----
    THUMB_W        = 176
    TITLE_MIN_W    = 420
    CAP_SNIPPET_W  = 260
    VURL_W         = 200
    FORM_W         = 70

    def __init__(self):
        super().__init__()
        self.image_loaders = []
        self.worker = None
        self.items_raw = []

        self._last_sort_col = None
        self._last_sort_order = Qt.AscendingOrder

        # 테이블/필터 상태
        self.active_filter = {
            "form_idx": 0,
            "min_views": None, "max_views": None,
            "min_subs": None,  "max_subs": None,
            "min_views_text": "", "max_views_text": "",
            "min_subs_text":  "", "max_subs_text":  "",
        }
        # UI 레벨에서도 혹시 모를 중복 방지(고유키=video_link)
        self._seen_links: set[str] = set()

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 상단 검색줄
        top = QHBoxLayout(); top.setSpacing(8)
        self.keyword_input = QLineEdit(); self.keyword_input.setPlaceholderText("키워드 입력")
        self.count_input = QLineEdit();   self.count_input.setPlaceholderText("개수 (예: 50)")
        self.search_button = QPushButton("검색"); self.search_button.setProperty("type", "primary")
        self.search_button.clicked.connect(self.on_search)

        self.filter_btn = QPushButton("필터/정렬…"); self.filter_btn.setProperty("type", "outline")
        self.filter_btn.clicked.connect(self.open_filter_dialog)

        self.progress = QProgressBar(); self.progress.setVisible(False); self.progress.setFixedHeight(14)
        self.progress.setFormat("%p%  (%v/%m)"); self.progress.setRange(0, 100); self.progress.setValue(0)

        top.addWidget(QLabel("키워드"))
        top.addWidget(self.keyword_input, 2)
        top.addWidget(self.count_input, 0)
        top.addWidget(self.search_button, 0)
        top.addWidget(self.filter_btn, 0)
        top.addWidget(self.progress, 1)
        main_layout.addLayout(top)

        # ===== 테이블 =====
        self.table = QTableWidget(0, 10)
        self.table.setObjectName("Card")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels([
            "썸네일", "제목", "조회수", "구독자수", "업로드 날짜", "자막",
            "영상 링크", "형태", "채널명", "숨김:자막(전체)"
        ])

        h = self.table.horizontalHeader()
        h.setStretchLastSection(False)
        h.setDefaultSectionSize(150)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 컬럼 폭/모드
        h.setSectionResizeMode(self.COL_THUMB, QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_THUMB, self.THUMB_W)

        h.setSectionResizeMode(self.COL_TITLE, QHeaderView.Interactive)
        self.table.setColumnWidth(self.COL_TITLE, self.TITLE_MIN_W)

        h.setSectionResizeMode(self.COL_VIEWS, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_SUBS,  QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_DATE,  QHeaderView.ResizeToContents)

        h.setSectionResizeMode(self.COL_CAPSN, QHeaderView.Interactive)
        self.table.setColumnWidth(self.COL_CAPSN, self.CAP_SNIPPET_W)

        h.setSectionResizeMode(self.COL_VURL,  QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_VURL, self.VURL_W)

        h.setSectionResizeMode(self.COL_FORM,  QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_FORM, self.FORM_W)

        h.setSectionResizeMode(self.COL_CH,    QHeaderView.ResizeToContents)

        self.table.setColumnHidden(self.COL_CAPFULL, True)
        h.setMinimumSectionSize(60)

        self.table.setSortingEnabled(True)
        h.setSortIndicatorShown(True)
        h.sectionClicked.connect(self.on_header_clicked)

        # ===== 우측 자막 미리보기 =====
        self.detail_text = QTextEdit()
        self.detail_text.setObjectName("Card")
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("선택한 행의 자막 전체를 표시합니다.")
        self.detail_text.setLineWrapMode(QTextEdit.WidgetWidth)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_text)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1200, 260])
        main_layout.addWidget(splitter)

        # ===== Export =====
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.export_html_btn = QPushButton("<HTML 저장>"); self.export_html_btn.setProperty("type", "outline")
        self.export_excel_btn = QPushButton("<엑셀 저장>"); self.export_excel_btn.setProperty("type", "outline")
        self.export_html_btn.clicked.connect(self.export_html)
        self.export_excel_btn.clicked.connect(self.export_excel)
        bottom.addWidget(self.export_html_btn); bottom.addWidget(self.export_excel_btn)
        main_layout.addLayout(bottom)

        # 이벤트
        self.table.cellClicked.connect(self.on_table_click)

    # ---------- 이벤트 ----------
    def on_search(self):
        keyword = self.keyword_input.text().strip()
        try:
            count = int(self.count_input.text().strip() or "50")
        except ValueError:
            count = 50
        if not keyword:
            QMessageBox.warning(self, "입력 확인", "키워드를 입력하세요."); return

        logger.info(f"[UI] 검색 버튼: q='{keyword}', count={count}")

        # 기존 로더 정리
        for loader in self.image_loaders:
            if loader.isRunning():
                loader.terminate()
        self.image_loaders.clear()

        # 테이블 초기화 + UI 잠금 + 진행바 시작
        self.table.setSortingEnabled(False)   # 삽입 중 정렬 OFF
        self.table.setRowCount(0)
        self.items_raw = []
        self._seen_links.clear()              # UI 단 중복 추적도 초기화
        self._set_busy(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        # 워커 가동
        self.worker = SearchWorker(keyword, count, workers=10)
        self.worker.progress.connect(self._on_progress)
        self.worker.one.connect(self._on_worker_one)
        self.worker.done.connect(self._on_worker_done)
        self.worker.error.connect(self._on_search_error)
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        if total <= 0:
            self.progress.setRange(0, 0); return
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(current)

    def _on_worker_one(self, item: dict):
        # UI 레벨 중복 방지(고유키=video_link, 비어있으면 수용)
        vlink = item.get("video_link", "")
        if vlink and vlink in self._seen_links:
            return
        if vlink:
            self._seen_links.add(vlink)

        self.items_raw.append(item)
        if self._filter_match(item, self.active_filter):
            self._insert_row(item)

    def _on_worker_done(self):
        if self.progress.maximum() > 0:
            self.progress.setValue(self.progress.maximum())
        QTimer.singleShot(500, lambda: self.progress.setVisible(False))
        self._set_busy(False)
        self._restore_sorting()

    def _on_search_error(self, msg: str):
        logger.error(f"[UI] 수집 오류: {msg}")
        self.progress.setVisible(False)
        self._set_busy(False)
        self.table.setSortingEnabled(True)
        QMessageBox.critical(self, "수집 오류", msg)

    # ---------- 필터 ----------
    def open_filter_dialog(self):
        dlg = FilterDialog(self, init=self.active_filter)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            self.active_filter = dlg.result
            items = [it for it in self.items_raw if self._filter_match(it, self.active_filter)]
            self._render_rows(items)
            self._restore_sorting()

    @staticmethod
    def _filter_match(it: dict, f: dict) -> bool:
        idx = f.get("form_idx", 0)  # 0 전체 / 1 롱폼 / 2 숏폼
        is_shorts = bool(it.get("is_shorts"))
        if idx == 1 and is_shorts:     # 롱폼만
            return False
        if idx == 2 and not is_shorts: # 숏폼만
            return False

        v = int(it.get("views", 0) or 0)
        s = int(it.get("subscribers", 0) or 0)
        minv = f.get("min_views"); maxv = f.get("max_views")
        mins = f.get("min_subs");  maxs = f.get("max_subs")
        if minv is not None and v < minv: return False
        if maxv is not None and v > maxv: return False
        if mins is not None and s < mins: return False
        if maxs is not None and s > maxs: return False
        return True

    def on_header_clicked(self, col: int):
        numeric_desc_default = {self.COL_VIEWS, self.COL_SUBS}
        if self._last_sort_col == col:
            self._last_sort_order = Qt.DescendingOrder if self._last_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._last_sort_col = col
            self._last_sort_order = Qt.DescendingOrder if col in numeric_desc_default else Qt.AscendingOrder
        self.table.sortItems(col, self._last_sort_order)
        self.table.horizontalHeader().setSortIndicator(col, self._last_sort_order)

    # ---------- 렌더 ----------
    def _render_rows(self, items: list[dict]):
        # 기존 썸네일 로더 중지
        for loader in self.image_loaders:
            if loader.isRunning():
                loader.terminate()
        self.image_loaders.clear()

        # 정렬 비활성화 후 채우기
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        # 재렌더 시에도 중복 방지: 이 테이블에서만 쓰는 임시 set
        temp_seen_links: set[str] = set()

        for it in items:
            vlink = it.get("video_link", "")
            if vlink and vlink in temp_seen_links:
                continue
            if vlink:
                temp_seen_links.add(vlink)
            self._insert_row(it)

        # 제목 최소 폭 보정
        self._ensure_title_min()

    def _restore_sorting(self):
        self.table.setSortingEnabled(True)
        if self._last_sort_col is not None:
            self.table.sortItems(self._last_sort_col, self._last_sort_order)
            self.table.horizontalHeader().setSortIndicator(self._last_sort_col, self._last_sort_order)

    def _insert_row(self, item: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 116)

        # 0 썸네일(라벨만 먼저)
        thumb_label = QLabel("로딩중…")
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("border: 1px solid #e6e8eb; background:#111; color:#999;")
        self.table.setCellWidget(row, self.COL_THUMB, thumb_label)
        self.table.setColumnWidth(self.COL_THUMB, self.THUMB_W)

        # 1 제목
        self.table.setItem(row, self.COL_TITLE, QTableWidgetItem(item.get("title", "")))

        # 2 조회수
        self.table.setItem(row, self.COL_VIEWS, NumericItem(int(item.get("views", 0) or 0)))

        # 3 구독자수
        self.table.setItem(row, self.COL_SUBS, NumericItem(int(item.get("subscribers", 0) or 0)))

        # 4 업로드 날짜
        self.table.setItem(row, self.COL_DATE, DateItem(item.get("upload_date", "")))

        # 5 자막(스니펫)
        full_caption = item.get("caption", "") or ""
        snippet = (full_caption[:180] + "…") if len(full_caption) > 180 else full_caption
        cap_item = QTableWidgetItem(snippet)

        self.table.setItem(row, self.COL_CAPSN, cap_item)

        # 6 영상 링크 (UserRole에 동일 값 저장)
        vlink = item.get("video_link", "")
        v_item = QTableWidgetItem(vlink)
        v_item.setData(Qt.UserRole, vlink)
        v_item.setForeground(Qt.blue)
        v_item.setToolTip("클릭하여 영상 보기")
        self.table.setItem(row, self.COL_VURL, v_item)

        # 7 형태
        form_txt = item.get("form", "") or ("숏폼" if item.get("is_shorts") else "롱폼")
        self.table.setItem(row, self.COL_FORM, QTableWidgetItem(form_txt))

        # 8 채널명
        self.table.setItem(row, self.COL_CH, QTableWidgetItem(item.get("channel", "")))

        # 9 숨김: 자막 전체
        self.table.setItem(row, self.COL_CAPFULL, QTableWidgetItem(full_caption))

        # 썸네일 비동기 로딩(키=영상 링크)
        loader = ImageLoader(vlink, item.get("thumbnail", ""))
        loader.imageLoaded.connect(self.set_thumbnail)  # set_thumbnail(key, pixmap)
        self.image_loaders.append(loader)
        loader.start()

        # 하이라이트
        self._colorize_row(row)

        # 제목 최소 폭 보정
        self._ensure_title_min()

    # ---- 현재 테이블에서 key(영상 링크)에 해당하는 "행" 찾기
    def _row_for_key(self, key: str) -> int | None:
        if not key:
            return None
        for r in range(self.table.rowCount()):
            it = self.table.item(r, self.COL_VURL)
            if not it:
                continue
            if it.data(Qt.UserRole) == key or it.text() == key:
                return r
        return None

    # ---- 이미지 세터: key(영상 링크)로 현재 행을 찾아 세팅
    def set_thumbnail(self, key: str, pixmap: QPixmap):
        row = self._row_for_key(key)
        if row is None:
            return  # 필터로 사라졌거나 테이블 갱신된 경우
        lab = self.table.cellWidget(row, self.COL_THUMB)
        if lab:
            lab.setPixmap(pixmap)
            lab.setText("")
            lab.setScaledContents(True)

    def on_table_click(self, row, col):
        # 링크: 6=영상
        if col == self.COL_VURL:
            item = self.table.item(row, col)
            if item:
                url = item.data(Qt.UserRole) or item.text()
                if url:
                    try:
                        QDesktopServices.openUrl(QUrl(url))
                    except Exception:
                        try:
                            webbrowser.open(url)
                        except Exception:
                            pass
        # 자막 미리보기
        cap_full = self.table.item(row, self.COL_CAPFULL)
        self.detail_text.setPlainText(cap_full.text() if cap_full else "")

    # ---------- 유틸 ----------
    def _set_busy(self, busy: bool):
        self.search_button.setEnabled(not busy)
        self.keyword_input.setEnabled(not busy)
        self.count_input.setEnabled(not busy)
        self.filter_btn.setEnabled(not busy)

    def _ensure_title_min(self):
        try:
            cur = self.table.columnWidth(self.COL_TITLE)
            if cur < self.TITLE_MIN_W:
                self.table.setColumnWidth(self.COL_TITLE, self.TITLE_MIN_W)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._ensure_title_min)

    def _colorize_row(self, row: int):
        def _ival(c):
            try:
                return int((self.table.item(row, c).text() or "0").replace(",", ""))
            except Exception:
                return 0

        views = _ival(self.COL_VIEWS); subs = _ival(self.COL_SUBS)
        views_item = self.table.item(row, self.COL_VIEWS)
        subs_item  = self.table.item(row, self.COL_SUBS)

        if views_item:
            if views >= 5_000_000: views_item.setBackground(QColor(255, 48, 48, 70))
            elif views >= 1_000_000: views_item.setBackground(QColor(255, 48, 48, 38))
            elif views >= 100_000:   views_item.setBackground(QColor(255, 48, 48, 18))

        if subs_item:
            if subs >= 1_000_000: subs_item.setBackground(QColor(255, 48, 48, 34))
            elif subs >= 100_000: subs_item.setBackground(QColor(255, 48, 48, 18))

    # 저장 유틸
    def _collect_rows(self):
        rows = []
        for r in range(self.table.rowCount()):
            rows.append({
                "title": self.table.item(r, self.COL_TITLE).text() if self.table.item(r, self.COL_TITLE) else "",
                "views": self.table.item(r, self.COL_VIEWS).text() if self.table.item(r, self.COL_VIEWS) else "",
                "subscribers": self.table.item(r, self.COL_SUBS).text() if self.table.item(r, self.COL_SUBS) else "",
                "upload_date": self.table.item(r, self.COL_DATE).text() if self.table.item(r, self.COL_DATE) else "",
                "caption": self.table.item(r, self.COL_CAPFULL).text() if self.table.item(r, self.COL_CAPFULL) else "",
                "video_link": self.table.item(r, self.COL_VURL).text() if self.table.item(r, self.COL_VURL) else "",
                "form": self.table.item(r, self.COL_FORM).text() if self.table.item(r, self.COL_FORM) else "",
                "channel": self.table.item(r, self.COL_CH).text() if self.table.item(r, self.COL_CH) else "",
            })
        return rows

    # -------------- 여기부터 XlsxWriter로 변경 --------------
    def export_excel(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "알림", "저장할 데이터가 없습니다."); return
        path, _ = QFileDialog.getSaveFileName(self, "엑셀 저장", "youtube_results.xlsx", "Excel 파일 (*.xlsx)")
        if not path: return

        try:
            import xlsxwriter
        except Exception:
            QMessageBox.critical(self, "오류", "xlsxwriter가 없습니다. 설치: pip install xlsxwriter")
            return

        # 숫자 안전 파서
        def _to_int_safe(x):
            try:
                s = str(x or "").strip()
                if s == "":
                    return None  # 빈칸으로 남기고 싶으면 None 사용
                s = s.replace(",", "")
                if s.lower().endswith("k"):
                    return int(float(s[:-1]) * 1000)
                if s.lower().endswith("m"):
                    return int(float(s[:-1]) * 1000000)
                if s.lower().endswith("b"):
                    return int(float(s[:-1]) * 1000000000)
                import re
                digits = re.sub(r"[^\d\-]", "", s)
                if digits == "" or digits == "-":
                    return None
                return int(digits)
            except Exception:
                return None

        try:
            workbook = xlsxwriter.Workbook(path)
            worksheet = workbook.add_worksheet("Sheet1")

            # 기본 포맷(숫자/텍스트)
            fmt_text = workbook.add_format({'text_wrap': False, 'valign': 'top'})
            fmt_number = workbook.add_format({'num_format': '0', 'valign': 'top'})  # 정수 포맷

            headers = ["title","views","subscribers","upload_date","caption","video_link","form","channel"]
            for ci, h in enumerate(headers):
                worksheet.write(0, ci, h, fmt_text)
                if h == "title":
                    worksheet.set_column(ci, ci, 60)
                elif h == "caption":
                    worksheet.set_column(ci, ci, 60)
                elif h == "video_link":
                    worksheet.set_column(ci, ci, 40)
                else:
                    worksheet.set_column(ci, ci, 15)

            FIXED_HEIGHT = 16.5
            for ri, r in enumerate(rows, start=1):
                worksheet.set_row(ri, FIXED_HEIGHT)
                worksheet.write(ri, 0, r.get("title", "") or "", fmt_text)

                v = _to_int_safe(r.get("views", ""))
                if v is None:
                    worksheet.write(ri, 1, "", fmt_text)
                else:
                    worksheet.write_number(ri, 1, v, fmt_number)

                s = _to_int_safe(r.get("subscribers", ""))
                if s is None:
                    worksheet.write(ri, 2, "", fmt_text)
                else:
                    worksheet.write_number(ri, 2, s, fmt_number)

                worksheet.write(ri, 3, r.get("upload_date", "") or "", fmt_text)
                worksheet.write(ri, 4, r.get("caption", "") or "", fmt_text)
                worksheet.write(ri, 5, r.get("video_link", "") or "", fmt_text)
                worksheet.write(ri, 6, r.get("form", "") or "", fmt_text)
                worksheet.write(ri, 7, r.get("channel", "") or "", fmt_text)

            workbook.close()
            QMessageBox.information(self, "완료", f"엑셀 저장 완료\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"엑셀 저장 실패(xlsxwriter): {e}")
    # -------------- 변경 끝 --------------

    def export_html(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "알림", "저장할 데이터가 없습니다."); return
        path, _ = QFileDialog.getSaveFileName(self, "HTML 저장", "youtube_results.html", "HTML 파일 (*.html)")
        if not path: return
        html = ["<html><head><meta charset='utf-8'></head><body><table border='1' cellspacing='0' cellpadding='6'>"]
        html.append("<tr><th>제목</th><th>조회수</th><th>구독자수</th><th>업로드</th><th>자막</th><th>영상 링크</th><th>형태</th><th>채널</th></tr>")
        for r in rows:
            html.append(
                f"<tr>"
                f"<td>{r['title']}</td>"
                f"<td>{r['views']}</td>"
                f"<td>{r['subscribers']}</td>"
                f"<td>{r['upload_date']}</td>"
                f"<td>{r['caption']}</td>"
                f"<td><a href='{r['video_link']}'>{r['video_link']}</a></td>"
                f"<td>{r['form']}</td>"
                f"<td>{r['channel']}</td>"
                f"</tr>"
            )
        html.append("</table></body></html>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(html))
        QMessageBox.information(self, "완료", f"HTML 저장 완료\n{path}")
