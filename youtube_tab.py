# youtube_tab.py — Data API + 'API 키 설정' UI 포함판
# (자막 제거 + 별점 컬럼 + 길이(재생시간) 컬럼 추가 + 필터에 별점 선택 + 디자인 개선)
import webbrowser
from urllib.request import urlopen
import math

import xlsxwriter
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QPixmap, QDesktopServices, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox,
    QHeaderView, QProgressBar, QComboBox, QDialog, QFormLayout,
    QDialogButtonBox, QAbstractItemView, QCheckBox, QFrame
)

import logging
import youtube_api_util as ytu

logger = logging.getLogger("ytcrawl")

# ===== 별 등급 안내(대중적 설명, 임계값/공식은 노출 X) =====
STARS_PUBLIC_HELP = (
    "별점 안내\n"
    "• ⭐ : 채널 규모 대비 반응이 낮은 편\n"
    "• ⭐⭐ : 약간 아쉬움\n"
    "• ⭐⭐⭐ : 보통 이상, 준수함\n"
    "• ⭐⭐⭐⭐ : 반응이 매우 좋은 편\n"
    "• ⭐⭐⭐⭐⭐ : 탁월한 반응\n"
    "※ 채널 구독자 수가 없으면 별점은 N/A"
)

# ===== 유틸: 길이 포맷 =====
def format_duration(seconds: int) -> str:
    try:
        s = max(0, int(seconds or 0))
    except Exception:
        s = 0
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"

# ===== 이미지 비동기 로더 =====
class ImageLoader(QThread):
    imageLoaded = Signal(str, QPixmap)  # key=video_link, pixmap
    def __init__(self, key: str, url: str):
        super().__init__()
        self.key = key
        self.url = url
    def run(self):
        try:
            with urlopen(self.url) as response:
                data = response.read()
            pixmap = QPixmap(); pixmap.loadFromData(data)
            scaled = pixmap.scaled(200, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.imageLoaded.emit(self.key, scaled)
        except Exception as e:
            logger.exception(f"[IMG] 이미지 로드 실패: key={self.key}, url={self.url} :: {e}")

# ===== 정렬 정확도를 위한 아이템 =====
class NumericItem(QTableWidgetItem):
    def __init__(self, value):
        try: ival = int(str(value).replace(",", ""))
        except Exception: ival = 0
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

class PerfItem(QTableWidgetItem):
    """표시 텍스트는 별(예: '⭐⭐⭐'), 비교는 내부 지표(float)로 수행"""
    def __init__(self, stars: str, perf_val: float):
        super().__init__(stars)
        self._val = perf_val
    def __lt__(self, other):
        try:
            a = self._val
            b = other._val if isinstance(other, PerfItem) else float('nan')
            if a != a: a = float("-inf")  # NaN은 가장 낮게
            if b != b: b = float("-inf")
            return a < b
        except Exception:
            return super().__lt__(other)

class DurationItem(QTableWidgetItem):
    """표시는 'H:MM:SS' 또는 'M:SS', 비교는 초 단위 정수"""
    def __init__(self, seconds: int):
        sec = max(0, int(seconds or 0))
        super().__init__(format_duration(sec))
        self._sec = sec
    def __lt__(self, other):
        try:
            a = self._sec
            b = other._sec if isinstance(other, DurationItem) else 0
            return a < b
        except Exception:
            return super().__lt__(other)

# ===== 필터 대화창 =====
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

        # 별점 체크박스(1~5 + N/A)
        self.cb_star = {i: QCheckBox("⭐"*i) for i in range(1, 6)}
        for cb in self.cb_star.values():
            cb.setChecked(True)
            cb.setToolTip("이 별점의 영상만 보기 포함/제외")
        self.cb_star_na = QCheckBox("N/A 포함"); self.cb_star_na.setChecked(True)

        # 초기값 복원
        if init:
            self.form_combo.setCurrentIndex(init.get("form_idx", 0))
            for w, k in ((self.min_views, "min_views_text"), (self.max_views, "max_views_text"),
                         (self.min_subs, "min_subs_text"), (self.max_subs, "max_subs_text")):
                if init.get(k): w.setText(init[k])
            star_allow = set(init.get("star_allow", [1,2,3,4,5]))
            for i in range(1,6):
                self.cb_star[i].setChecked(i in star_allow)
            self.cb_star_na.setChecked(bool(init.get("star_include_na", True)))

        form = QFormLayout(self)
        form.addRow("형식", self.form_combo)
        form.addRow("조회수 최소", self.min_views)
        form.addRow("조회수 최대", self.max_views)
        form.addRow("구독자 최소", self.min_subs)
        form.addRow("구독자 최대", self.max_subs)

        # 별점 선택 가로 배치
        star_row = QHBoxLayout()
        for i in range(1,6):
            star_row.addWidget(self.cb_star[i])
        star_row.addWidget(self.cb_star_na)
        star_row.addStretch(1)
        form.addRow("별점", star_row)

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
        if t.endswith("억"):   return int(float(t[:-1]) * 100_000_000)
        if t.endswith("만"):   return int(float(t[:-1]) * 10_000)
        if t.endswith("천"):   return int(float(t[:-1]) * 1_000)
        return int(float(t))

    def accept(self):
        star_allow = [i for i in range(1,6) if self.cb_star[i].isChecked()]
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
            "star_allow": star_allow if star_allow else [1,2,3,4,5],  # 최소 1개 이상 유지
            "star_include_na": self.cb_star_na.isChecked(),
        }
        super().accept()

# ===== API 키 설정 대화창 =====
class ApiKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YouTube API 키 설정")
        self.setModal(True)

        self.key_edit = QLineEdit(); self.key_edit.setPlaceholderText("여기에 API 키를 붙여넣으세요")
        self.show_chk = QCheckBox("키 표시"); self.show_chk.stateChanged.connect(self.on_toggle_show)

        try:
            cur = ytu.peek_effective_key()
            if cur: self.key_edit.setText(cur)
        except Exception:
            pass

        self.status_label = QLabel("상태: -")

        btn_load = QPushButton("파일에서 불러오기…"); btn_load.clicked.connect(self.on_load_file)
        btn_test = QPushButton("검증"); btn_test.setProperty("type", "outline"); btn_test.clicked.connect(self.on_validate)
        btn_save = QPushButton("저장"); btn_save.setProperty("type", "primary"); btn_save.clicked.connect(self.on_save)
        btn_close = QPushButton("닫기"); btn_close.clicked.connect(self.reject)

        # 카드 스타일 컨테이너
        outer = QVBoxLayout(self)
        card = QFrame(); card.setObjectName("Card")
        inner = QFormLayout(card)
        inner.addRow("API 키", self.key_edit)
        inner.addRow("", self.show_chk)
        inner.addRow("검증 결과", self.status_label)
        outer.addWidget(card)

        row = QHBoxLayout()
        row.addWidget(btn_load); row.addStretch(); row.addWidget(btn_test); row.addWidget(btn_save); row.addWidget(btn_close)
        outer.addLayout(row)

    def on_toggle_show(self, _):
        self.key_edit.setEchoMode(QLineEdit.Normal if self.show_chk.isChecked() else QLineEdit.PasswordEchoOnEdit)

    def on_load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "youtube_api_key.txt 선택", "", "Text file (*.txt);;All files (*)")
        if not path: return
        try:
            txt = open(path, "r", encoding="utf-8").read().strip()
            if not txt: QMessageBox.warning(self, "알림", "파일에 키가 없습니다."); return
            self.key_edit.setText(txt)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"파일 읽기 실패: {e}")

    def on_validate(self):
        key = self.key_edit.text().strip()
        ok, msg = ytu.validate_api_key(key)
        if ok:
            self.status_label.setText("상태: ✅ 유효한 키")
            QMessageBox.information(self, "검증", "유효한 키입니다.")
        else:
            self.status_label.setText(f"상태: ❌ {msg}")
            QMessageBox.warning(self, "검증 실패", f"키가 유효하지 않습니다.\n{msg}")

    def on_save(self):
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "알림", "키를 입력하세요."); return
        ok, msg = ytu.validate_api_key(key)
        if not ok:
            QMessageBox.warning(self, "검증 실패", f"키가 유효하지 않습니다.\n{msg}")
            return
        try:
            path = ytu.save_api_key_to_disk(key)
            QMessageBox.information(self, "저장 완료", f"키 저장 완료\n{path}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"저장 실패: {e}")

# ===== 검색 워커 (Data API) =====
class SearchWorker(QThread):
    progress = Signal(int, int)  # (current, total)
    one = Signal(dict)
    done = Signal()
    error = Signal(str)
    def __init__(self, keyword: str, count: int):
        super().__init__()
        self.keyword = keyword; self.count = count
    def run(self):
        try:
            logger.info(f"[UI-SEARCH] 시작: q='{self.keyword}', want={self.count}")
            ids = ytu.search_video_ids(self.keyword, self.count)
            total = len(ids); self.progress.emit(0, total)
            if total == 0: self.done.emit(); return
            done_cnt = 0
            for info in ytu.iter_videos_info(ids):
                if info: self.one.emit(info)
                done_cnt += 1; self.progress.emit(done_cnt, total)
            self.done.emit(); logger.info("[UI-SEARCH] 완료")
        except Exception as e:
            logger.exception(f"[UI-SEARCH] 전체 실패 :: {e}")
            self.error.emit(str(e))

# ===== 메인 위젯 =====
class YouTubeSearchWidget(QWidget):
    # 컬럼 인덱스
    COL_THUMB = 0
    COL_TITLE = 1
    COL_VIEWS = 2
    COL_SUBS  = 3
    COL_DATE  = 4
    COL_DUR   = 5   # 새로 추가: 길이
    COL_STARS = 6
    COL_VURL  = 7
    COL_FORM  = 8
    COL_CH    = 9
    COL_PERF  = 10  # 숨김: 내부지수(숫자)

    THUMB_W     = 176
    TITLE_MIN_W = 420

    def __init__(self):
        super().__init__()
        self.image_loaders = []
        self.worker = None
        self.items_raw = []
        self._last_sort_col = None
        self._last_sort_order = Qt.AscendingOrder

        self.active_filter = {
            "form_idx": 0,
            "min_views": None, "max_views": None,
            "min_subs": None,  "max_subs": None,
            "min_views_text": "", "max_views_text": "",
            "min_subs_text":  "", "max_subs_text":  "",
            "star_allow": [1,2,3,4,5],
            "star_include_na": True,
        }
        self._seen_links: set[str] = set()

        self._build_ui()
        self.refresh_api_key_status()

    # ----- 내부 지표/별점 변환 -----
    @staticmethod
    def _metric_score(views: int, subs: int) -> float:
        if subs <= 0: return float('nan')
        return (views / subs) * 14.285714

    @staticmethod
    def _metric_to_stars(val: float) -> str:
        if val != val: return "N/A"  # NaN
        if val < 12:   return "⭐"
        if val < 16:   return "⭐⭐"
        if val < 26:   return "⭐⭐⭐"
        if val < 200:  return "⭐⭐⭐⭐"
        return "⭐⭐⭐⭐⭐"

    @staticmethod
    def _metric_to_star_count(val: float) -> int:
        if val != val: return 0  # N/A → 0
        if val < 12:   return 1
        if val < 16:   return 2
        if val < 26:   return 3
        if val < 200:  return 4
        return 5

    # ----- UI 구성 -----
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16); main_layout.setSpacing(12)

        # API 키 상태 카드
        api_card = QFrame(); api_card.setObjectName("Card")
        api_row = QHBoxLayout(api_card); api_row.setContentsMargins(12, 10, 12, 10)
        self.lbl_api = QLabel("API 키: 확인 중…")
        self.lbl_api.setStyleSheet("padding:6px 10px; border-radius:10px; background:#f1f5f9; color:#111;")
        self.btn_api = QPushButton("API 키 설정…"); self.btn_api.setProperty("type", "outline")
        self.btn_api.clicked.connect(self.open_api_dialog)
        api_row.addWidget(QLabel("YouTube API")); api_row.addSpacing(6)
        api_row.addWidget(self.lbl_api); api_row.addStretch(); api_row.addWidget(self.btn_api)
        main_layout.addWidget(api_card)

        # 검색 컨트롤 카드
        ctrl_card = QFrame(); ctrl_card.setObjectName("Card")
        top = QHBoxLayout(ctrl_card); top.setContentsMargins(12, 10, 12, 10); top.setSpacing(8)
        self.keyword_input = QLineEdit(); self.keyword_input.setPlaceholderText("키워드 입력")
        self.count_input = QLineEdit();   self.count_input.setPlaceholderText("개수 (예: 50)")
        self.search_button = QPushButton("검색"); self.search_button.setProperty("type", "primary")
        self.search_button.clicked.connect(self.on_search)
        self.filter_btn = QPushButton("필터/정렬…"); self.filter_btn.setProperty("type", "outline")
        self.filter_btn.clicked.connect(self.open_filter_dialog)
        self.progress = QProgressBar(); self.progress.setVisible(False); self.progress.setFixedHeight(14)
        self.progress.setFormat("%p%  (%v/%m)"); self.progress.setRange(0, 100); self.progress.setValue(0)

        top.addWidget(QLabel("키워드")); top.addWidget(self.keyword_input, 2)
        top.addWidget(self.count_input, 0)
        top.addWidget(self.search_button, 0)
        top.addWidget(self.filter_btn, 0)
        top.addWidget(self.progress, 1)
        main_layout.addWidget(ctrl_card)

        # 테이블
        self.table = QTableWidget(0, 11)
        self.table.setObjectName("Card")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels([
            "썸네일", "제목", "조회수", "구독자수", "업로드 날짜", "길이", "별점",
            "영상 링크", "형태", "채널명", "내부지수(숨김)"
        ])

        h = self.table.horizontalHeader()
        h.setStretchLastSection(False)
        h.setDefaultSectionSize(150)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        h.setSectionResizeMode(self.COL_THUMB, QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_THUMB, self.THUMB_W)

        h.setSectionResizeMode(self.COL_TITLE, QHeaderView.Interactive)
        self.table.setColumnWidth(self.COL_TITLE, self.TITLE_MIN_W)

        h.setSectionResizeMode(self.COL_VIEWS, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_SUBS,  QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_DATE,  QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_DUR,   QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_STARS, QHeaderView.ResizeToContents)

        h.setSectionResizeMode(self.COL_VURL,  QHeaderView.Fixed); self.table.setColumnWidth(self.COL_VURL, 200)
        h.setSectionResizeMode(self.COL_FORM,  QHeaderView.Fixed); self.table.setColumnWidth(self.COL_FORM, 70)
        h.setSectionResizeMode(self.COL_CH,    QHeaderView.ResizeToContents)

        self.table.setColumnHidden(self.COL_PERF, True)
        h.setMinimumSectionSize(60)

        self.table.setSortingEnabled(True)
        h.setSortIndicatorShown(True)
        h.sectionClicked.connect(self.on_header_clicked)

        # 별점 헤더 툴팁(대중적 설명)
        stars_hdr = self.table.horizontalHeaderItem(self.COL_STARS)
        if stars_hdr: stars_hdr.setToolTip(STARS_PUBLIC_HELP)

        main_layout.addWidget(self.table)

        # Export 카드
        export_card = QFrame(); export_card.setObjectName("Card")
        bottom = QHBoxLayout(export_card); bottom.setContentsMargins(12, 10, 12, 10)
        bottom.addStretch()
        self.export_html_btn = QPushButton("<HTML 저장>"); self.export_html_btn.setProperty("type", "outline")
        self.export_excel_btn = QPushButton("<엑셀 저장>"); self.export_excel_btn.setProperty("type", "outline")
        self.export_html_btn.clicked.connect(self.export_html)
        self.export_excel_btn.clicked.connect(self.export_excel)
        bottom.addWidget(self.export_html_btn); bottom.addWidget(self.export_excel_btn)
        main_layout.addWidget(export_card)

        self.table.cellClicked.connect(self.on_table_click)

    # ----- API 키 -----
    def _style_api_label(self, ok: bool):
        if ok:
            self.lbl_api.setText("API 키: 설정됨")
            self.lbl_api.setStyleSheet("padding:6px 10px; border-radius:10px; background:rgba(16,185,129,.15); color:#065f46;")
        else:
            self.lbl_api.setText("API 키: 미설정")
            self.lbl_api.setStyleSheet("padding:6px 10px; border-radius:10px; background:#fef3c7; color:#92400e;")

    def refresh_api_key_status(self):
        info = ytu.api_key_info()
        if info.get("found") == "1":
            loc = info.get("location") or ""
            masked = info.get("masked") or ""
            self._style_api_label(True)
            self.lbl_api.setToolTip(f"{masked}\n{loc}" if loc else masked)
            self.search_button.setEnabled(True)
        else:
            self._style_api_label(False)
            self.lbl_api.setToolTip("상단의 [API 키 설정…] 버튼으로 등록하세요.")
            self.search_button.setEnabled(False)

    def open_api_dialog(self):
        dlg = ApiKeyDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_api_key_status()

    # ----- 이벤트 -----
    def on_search(self):
        if not ytu.peek_effective_key():
            QMessageBox.information(self, "API 키 필요", "YouTube API 키가 필요합니다. 키를 등록해 주세요.")
            self.open_api_dialog()
            if not ytu.peek_effective_key(): return

        keyword = self.keyword_input.text().strip()
        try: count = int(self.count_input.text().strip() or "50")
        except ValueError: count = 50
        if not keyword:
            QMessageBox.warning(self, "입력 확인", "키워드를 입력하세요."); return

        logger.info(f"[UI] 검색 버튼: q='{keyword}', count={count}")

        for loader in self.image_loaders:
            if loader.isRunning(): loader.terminate()
        self.image_loaders.clear()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.items_raw = []
        self._seen_links.clear()
        self._set_busy(True)
        self.progress.setVisible(True); self.progress.setRange(0, 0)

        self.worker = SearchWorker(keyword, count)
        self.worker.progress.connect(self._on_progress)
        self.worker.one.connect(self._on_worker_one)
        self.worker.done.connect(self._on_worker_done)
        self.worker.error.connect(self._on_search_error)
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        if total <= 0: self.progress.setRange(0, 0); return
        if self.progress.maximum() != total: self.progress.setRange(0, total)
        self.progress.setValue(current)

    def _on_worker_one(self, item: dict):
        vlink = item.get("video_link", "")
        if vlink and vlink in self._seen_links: return
        if vlink: self._seen_links.add(vlink)

        self.items_raw.append(item)
        if self._filter_match(item, self.active_filter):
            self._insert_row(item)

    def _on_worker_done(self):
        if self.progress.maximum() > 0: self.progress.setValue(self.progress.maximum())
        QTimer.singleShot(500, lambda: self.progress.setVisible(False))
        self._set_busy(False); self._restore_sorting()

    def _on_search_error(self, msg: str):
        logger.error(f"[UI] 수집 오류: {msg}")
        self.progress.setVisible(False)
        self._set_busy(False); self.table.setSortingEnabled(True)
        QMessageBox.critical(self, "수집 오류", msg)

    # ----- 필터 -----
    def open_filter_dialog(self):
        dlg = FilterDialog(self, init=self.active_filter)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            self.active_filter = dlg.result
            items = [it for it in self.items_raw if self._filter_match(it, self.active_filter)]
            self._render_rows(items); self._restore_sorting()

    def _filter_match(self, it: dict, f: dict) -> bool:
        idx = f.get("form_idx", 0)
        is_shorts = bool(it.get("is_shorts"))
        if idx == 1 and is_shorts:     return False
        if idx == 2 and not is_shorts: return False

        v = int(it.get("views", 0) or 0)
        s = int(it.get("subscribers", 0) or 0)
        minv = f.get("min_views"); maxv = f.get("max_views")
        mins = f.get("min_subs");  maxs = f.get("max_subs")
        if minv is not None and v < minv: return False
        if maxv is not None and v > maxv: return False
        if mins is not None and s < mins: return False
        if maxs is not None and s > maxs: return False

        # 별점 필터
        perf = self._metric_score(v, s)
        star_cnt = self._metric_to_star_count(perf)  # 0=NA
        allow = set(f.get("star_allow", [1,2,3,4,5]))
        include_na = bool(f.get("star_include_na", True))
        if star_cnt == 0:
            return include_na
        return star_cnt in allow

    def on_header_clicked(self, col: int):
        numeric_desc_default = {self.COL_VIEWS, self.COL_SUBS, self.COL_STARS, self.COL_PERF, self.COL_DUR}
        if self._last_sort_col == col:
            self._last_sort_order = Qt.DescendingOrder if self._last_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._last_sort_col = col
            self._last_sort_order = Qt.DescendingOrder if col in numeric_desc_default else Qt.AscendingOrder
        self.table.sortItems(col, self._last_sort_order)
        self.table.horizontalHeader().setSortIndicator(col, self._last_sort_order)

    # ----- 렌더 -----
    def _render_rows(self, items: list[dict]):
        for loader in self.image_loaders:
            if loader.isRunning(): loader.terminate()
        self.image_loaders.clear()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        temp_seen: set[str] = set()
        for it in items:
            vlink = it.get("video_link", "")
            if vlink and vlink in temp_seen: continue
            if vlink: temp_seen.add(vlink)
            self._insert_row(it)

        self._ensure_title_min()

    def _insert_row(self, item: dict):
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setRowHeight(row, 116)

        # 0 썸네일
        thumb_label = QLabel("로딩중…"); thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("border: 1px solid #e6e8eb; background:#111; color:#999;")
        self.table.setCellWidget(row, self.COL_THUMB, thumb_label)
        self.table.setColumnWidth(self.COL_THUMB, self.THUMB_W)

        # 1 제목
        self.table.setItem(row, self.COL_TITLE, QTableWidgetItem(item.get("title", "")))

        # 2 조회수
        views = int(item.get("views", 0) or 0)
        self.table.setItem(row, self.COL_VIEWS, NumericItem(views))

        # 3 구독자수
        subs = int(item.get("subscribers", 0) or 0)
        self.table.setItem(row, self.COL_SUBS, NumericItem(subs))

        # 4 업로드 날짜
        self.table.setItem(row, self.COL_DATE, DateItem(item.get("upload_date", "")))

        # 5 길이(초→포맷), 정렬은 초 기준
        dur_sec = int(item.get("duration_sec", 0) or 0)
        self.table.setItem(row, self.COL_DUR, DurationItem(dur_sec))

        # 6 별점 (지표 기반)
        perf = self._metric_score(views, subs)
        stars = self._metric_to_stars(perf)
        stars_item = PerfItem(stars, perf)
        stars_item.setToolTip(
            STARS_PUBLIC_HELP + ("\n\n(이 영상은 별점 N/A)" if perf != perf else "\n\n이 별점은 채널 규모 대비 반응을 간단히 표현합니다.")
        )
        self.table.setItem(row, self.COL_STARS, stars_item)

        # 7 영상 링크
        vlink = item.get("video_link", "")
        v_item = QTableWidgetItem(vlink)
        v_item.setData(Qt.UserRole, vlink)
        v_item.setForeground(Qt.blue)
        v_item.setToolTip("클릭하여 영상 열기")
        self.table.setItem(row, self.COL_VURL, v_item)

        # 8 형태
        form_txt = item.get("form", "") or ("숏폼" if item.get("is_shorts") else "롱폼")
        self.table.setItem(row, self.COL_FORM, QTableWidgetItem(form_txt))

        # 9 채널명
        self.table.setItem(row, self.COL_CH, QTableWidgetItem(item.get("channel", "")))

        # 10 내부지수(숨김)
        perf_txt = "" if perf != perf else f"{perf:.2f}"
        self.table.setItem(row, self.COL_PERF, QTableWidgetItem(perf_txt))

        # 썸네일 비동기 로딩
        loader = ImageLoader(vlink, item.get("thumbnail", ""))
        loader.imageLoaded.connect(self.set_thumbnail)
        self.image_loaders.append(loader); loader.start()

        self._colorize_row(row); self._ensure_title_min()

    # ----- 링크 클릭 -----
    def on_table_click(self, row, col):
        if col == self.COL_VURL:
            item = self.table.item(row, col)
            if item:
                url = item.data(Qt.UserRole) or item.text()
                if url:
                    try: QDesktopServices.openUrl(QUrl(url))
                    except Exception:
                        try: webbrowser.open(url)
                        except Exception: pass

    # ----- 유틸 -----
    def _row_for_key(self, key: str) -> int | None:
        if not key: return None
        for r in range(self.table.rowCount()):
            it = self.table.item(r, self.COL_VURL)
            if not it: continue
            if it.data(Qt.UserRole) == key or it.text() == key:
                return r
        return None

    def set_thumbnail(self, key: str, pixmap: QPixmap):
        row = self._row_for_key(key)
        if row is None: return
        lab = self.table.cellWidget(row, self.COL_THUMB)
        if lab:
            lab.setPixmap(pixmap); lab.setText(""); lab.setScaledContents(True)

    def _set_busy(self, busy: bool):
        self.search_button.setEnabled(not busy and bool(ytu.peek_effective_key()))
        self.keyword_input.setEnabled(not busy)
        self.count_input.setEnabled(not busy)
        self.filter_btn.setEnabled(not busy)
        self.btn_api.setEnabled(not busy)

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
            try: return int((self.table.item(row, c).text() or "0").replace(",", ""))
            except Exception: return 0
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

    def _collect_rows(self):
        rows = []
        for r in range(self.table.rowCount()):
            rows.append({
                "title": self.table.item(r, self.COL_TITLE).text() if self.table.item(r, self.COL_TITLE) else "",
                "views": self.table.item(r, self.COL_VIEWS).text() if self.table.item(r, self.COL_VIEWS) else "",
                "subscribers": self.table.item(r, self.COL_SUBS).text() if self.table.item(r, self.COL_SUBS) else "",
                "upload_date": self.table.item(r, self.COL_DATE).text() if self.table.item(r, self.COL_DATE) else "",
                "duration": self.table.item(r, self.COL_DUR).text() if self.table.item(r, self.COL_DUR) else "",
                "stars": self.table.item(r, self.COL_STARS).text() if self.table.item(r, self.COL_STARS) else "",
                "video_link": self.table.item(r, self.COL_VURL).text() if self.table.item(r, self.COL_VURL) else "",
                "form": self.table.item(r, self.COL_FORM).text() if self.table.item(r, self.COL_FORM) else "",
                "channel": self.table.item(r, self.COL_CH).text() if self.table.item(r, self.COL_CH) else "",
            })
        return rows

    # ----- 저장 -----
    def export_excel(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "알림", "저장할 데이터가 없습니다."); return
        path, _ = QFileDialog.getSaveFileName(self, "엑셀 저장", "youtube_results.xlsx", "Excel 파일 (*.xlsx)")
        if not path: return

        try:
            workbook = xlsxwriter.Workbook(path)
            worksheet = workbook.add_worksheet("Sheet1")

            fmt_text = workbook.add_format({'text_wrap': False, 'valign': 'top'})
            fmt_number = workbook.add_format({'num_format': '0', 'valign': 'top'})

            headers = ["title","views","subscribers","upload_date","duration","stars","video_link","form","channel"]
            for ci, h in enumerate(headers):
                worksheet.write(0, ci, h, fmt_text)
                if h in ("title",):
                    worksheet.set_column(ci, ci, 60)
                elif h == "video_link":
                    worksheet.set_column(ci, ci, 40)
                else:
                    worksheet.set_column(ci, ci, 15)

            FIXED_HEIGHT = 16.5
            import re
            def _to_int_safe(x):
                try:
                    s = str(x or "").strip()
                    if s == "": return None
                    s = s.replace(",", "")
                    if s.lower().endswith("k"): return int(float(s[:-1]) * 1000)
                    if s.lower().endswith("m"): return int(float(s[:-1]) * 1000000)
                    if s.lower().endswith("b"): return int(float(s[:-1]) * 1000000000)
                    digits = re.sub(r"[^\d\-]", "", s)
                    if digits in ("", "-"): return None
                    return int(digits)
                except Exception:
                    return None

            for ri, r in enumerate(rows, start=1):
                worksheet.set_row(ri, FIXED_HEIGHT)
                worksheet.write(ri, 0, r.get("title", "") or "", fmt_text)

                v = _to_int_safe(r.get("views", ""))
                worksheet.write_number(ri, 1, v, fmt_number) if v is not None else worksheet.write(ri, 1, "", fmt_text)

                s = _to_int_safe(r.get("subscribers", ""))
                worksheet.write_number(ri, 2, s, fmt_number) if s is not None else worksheet.write(ri, 2, "", fmt_text)

                worksheet.write(ri, 3, r.get("upload_date", "") or "", fmt_text)
                worksheet.write(ri, 4, r.get("duration", "") or "", fmt_text)
                worksheet.write(ri, 5, r.get("stars", "") or "", fmt_text)
                worksheet.write(ri, 6, r.get("video_link", "") or "", fmt_text)
                worksheet.write(ri, 7, r.get("form", "") or "", fmt_text)
                worksheet.write(ri, 8, r.get("channel", "") or "", fmt_text)

            workbook.close()
            QMessageBox.information(self, "완료", f"엑셀 저장 완료\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"엑셀 저장 실패(xlsxwriter): {e}")

    def export_html(self):
        rows = self._collect_rows()
        if not rows:
            QMessageBox.information(self, "알림", "저장할 데이터가 없습니다."); return
        path, _ = QFileDialog.getSaveFileName(self, "HTML 저장", "youtube_results.html", "HTML 파일 (*.html)")
        if not path: return
        html = ["<html><head><meta charset='utf-8'></head><body><table border='1' cellspacing='0' cellpadding='6'>"]
        html.append("<tr><th>제목</th><th>조회수</th><th>구독자수</th><th>업로드</th><th>길이</th><th>별점</th><th>영상 링크</th><th>형태</th><th>채널</th></tr>")
        for r in rows:
            html.append(
                f"<tr>"
                f"<td>{r['title']}</td>"
                f"<td>{r['views']}</td>"
                f"<td>{r['subscribers']}</td>"
                f"<td>{r['upload_date']}</td>"
                f"<td>{r['duration']}</td>"
                f"<td>{r['stars']}</td>"
                f"<td><a href='{r['video_link']}'>{r['video_link']}</a></td>"
                f"<td>{r['form']}</td>"
                f"<td>{r['channel']}</td>"
                f"</tr>"
            )
        html.append("</table></body></html>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(html))
        QMessageBox.information(self, "완료", f"HTML 저장 완료\n{path}")
