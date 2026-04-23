# youtube_tab.py — Data API + 'API 키 설정 & 라이선스 필수' UI
# (추천도 관련 기능/열/필터/내부지수 완전 제거 + 길이 컬럼 + 좋아요/댓글 + 간결 안내 + 디자인/안정성 유지)
import webbrowser
from urllib.request import urlopen
import xlsxwriter
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QSignalBlocker
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

# ===== 공통 유틸 =====
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

# ========== 공통 카드형 안내 다이얼로그 (간결·깔끔) ==========
class InfoDialog(QDialog):
    def __init__(self, title: str, lines: list[str], parent=None, ok_text="확인"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        root = QVBoxLayout(self); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(10)
        card = QFrame(); card.setObjectName("Card")
        inner = QVBoxLayout(card); inner.setContentsMargins(16, 14, 16, 14); inner.setSpacing(8)
        ttl = QLabel(title); ttl.setStyleSheet("font-weight:700; font-size:15px;")
        inner.addWidget(ttl)
        for t in lines:
            lab = QLabel(t); lab.setWordWrap(True); lab.setStyleSheet("color:#374151;")
            inner.addWidget(lab)
        root.addWidget(card)
        btns = QHBoxLayout(); btns.addStretch()
        ok = QPushButton(ok_text); ok.setProperty("type","primary"); ok.clicked.connect(self.accept)
        btns.addWidget(ok); root.addLayout(btns)

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

# ===== 정렬 정확도를 위한 아이템들 =====
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

# ===== 필터 대화창 (추천도 UI 제거) =====
class FilterDialog(QDialog):
    def __init__(self, parent=None, init: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("필터/정렬")
        self.setModal(True)

        self.form_combo = QComboBox()
        self.form_combo.addItems(["형식: 전체", "형식: 롱폼", "형식: 숏폼"])

        self.min_views = QLineEdit(); self.min_views.setPlaceholderText("조회수 ≥ (예: 100k / 10만)")
        self.max_views = QLineEdit(); self.max_views.setPlaceholderText("조회수 ≤ (빈칸=무제한)")
        self.min_subs  = QLineEdit(); self.min_subs.setPlaceholderText("구독자 ≥ (예: 50k / 5만)")
        self.max_subs  = QLineEdit(); self.max_subs.setPlaceholderText("구독자 ≤ (빈칸=무제한)")

        # 초기값 복원
        if init:
            self.form_combo.setCurrentIndex(init.get("form_idx", 0))
            for w, k in (
                (self.min_views, "min_views_text"), (self.max_views, "max_views_text"),
                (self.min_subs, "min_subs_text"),   (self.max_subs, "max_subs_text")
            ):
                if init.get(k): w.setText(init[k])

        # 카드 UI
        outer = QVBoxLayout(self); outer.setContentsMargins(12, 12, 12, 12); outer.setSpacing(10)
        card = QFrame(); card.setObjectName("Card")
        form = QFormLayout(card); form.setContentsMargins(16, 14, 16, 14)
        form.addRow("형식", self.form_combo)
        form.addRow("조회수 최소", self.min_views)
        form.addRow("조회수 최대", self.max_views)
        form.addRow("구독자 최소", self.min_subs)
        form.addRow("구독자 최대", self.max_subs)
        outer.addWidget(card)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        outer.addWidget(btns)

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

        outer = QVBoxLayout(self); outer.setContentsMargins(12, 12, 12, 12); outer.setSpacing(10)
        card = QFrame(); card.setObjectName("Card")
        inner = QFormLayout(card); inner.setContentsMargins(16, 14, 16, 14)
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
    summary = Signal(int, int)   # (found, requested)  ← 부족 결과 안내
    done = Signal()
    error = Signal(str)
    def __init__(self, keyword: str, count: int):
        super().__init__()
        self.keyword = keyword; self.count = count
    def run(self):
        try:
            logger.info(f"[UI-SEARCH] 시작: q='{self.keyword}', want={self.count}")
            ids = ytu.search_video_ids(self.keyword, self.count)
            total = len(ids)
            self.progress.emit(0, total)
            self.summary.emit(total, self.count)  # 요약 전달
            if total == 0:
                self.done.emit(); return
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
    # 컬럼 인덱스 (추천도/내부지수 제거로 재정의)
    COL_THUMB = 0
    COL_TITLE = 1
    COL_VIEWS = 2
    COL_LIKES = 3
    COL_COMMS = 4
    COL_SUBS  = 5
    COL_DATE  = 6
    COL_DUR   = 7   # 길이
    COL_VURL  = 8
    COL_FORM  = 9
    COL_CH    = 10

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
        }
        self._seen_links: set[str] = set()
        self._build_ui()
        self.refresh_api_key_status()

    # ----- UI 구성 -----
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16); main_layout.setSpacing(12)

        # 상단 카드: API 상태 + 검색 컨트롤 (한 장으로 깔끔하게)
        top_card = QFrame(); top_card.setObjectName("Card")
        top_lay  = QHBoxLayout(top_card); top_lay.setContentsMargins(12, 10, 12, 10); top_lay.setSpacing(8)

        self.lbl_api = QLabel("API 키: 확인 중…")
        self.lbl_api.setStyleSheet("padding:6px 10px; border-radius:10px; background:#f1f5f9; color:#111;")
        self.btn_api = QPushButton("API 키 설정…"); self.btn_api.setProperty("type", "outline")
        self.btn_api.clicked.connect(self.open_api_dialog)

        # 우측: 키워드 / 개수 / 검색 / 필터 / 진행
        self.keyword_input = QLineEdit(); self.keyword_input.setPlaceholderText("키워드 입력")
        self.count_input   = QLineEdit(); self.count_input.setPlaceholderText("개수 (예: 50)")
        self.search_button = QPushButton("검색"); self.search_button.setProperty("type", "primary")
        self.search_button.clicked.connect(self.on_search)
        self.filter_btn    = QPushButton("필터/정렬…"); self.filter_btn.setProperty("type", "outline")
        self.filter_btn.clicked.connect(self.open_filter_dialog)
        self.progress = QProgressBar(); self.progress.setVisible(False); self.progress.setFixedHeight(14)
        self.progress.setFormat("%p%  (%v/%m)"); self.progress.setRange(0, 100); self.progress.setValue(0)

        left = QHBoxLayout(); left.addWidget(QLabel("YouTube API")); left.addSpacing(6); left.addWidget(self.lbl_api); left.addWidget(self.btn_api)
        left.addStretch()
        right = QHBoxLayout()
        right.addWidget(QLabel("키워드")); right.addWidget(self.keyword_input, 2)
        right.addWidget(self.count_input, 0)
        right.addWidget(self.search_button, 0)
        right.addWidget(self.filter_btn, 0)
        right.addWidget(self.progress, 1)

        top_lay.addLayout(left, 3); top_lay.addLayout(right, 7)
        main_layout.addWidget(top_card)

        # 테이블 (열 개수 11)
        self.table = QTableWidget(0, 11)
        self.table.setObjectName("Card")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels([
            "썸네일", "제목", "조회수", "좋아요수", "댓글수", "구독자수", "업로드 날짜", "길이",
            "영상 링크", "형태", "채널명"
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
        h.setSectionResizeMode(self.COL_LIKES, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_COMMS, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_SUBS,  QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_DATE,  QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_DUR,   QHeaderView.ResizeToContents)

        h.setSectionResizeMode(self.COL_VURL,  QHeaderView.Fixed); self.table.setColumnWidth(self.COL_VURL, 200)
        h.setSectionResizeMode(self.COL_FORM,  QHeaderView.Fixed); self.table.setColumnWidth(self.COL_FORM, 70)
        h.setSectionResizeMode(self.COL_CH,    QHeaderView.ResizeToContents)

        h.setMinimumSectionSize(60)

        self.table.setSortingEnabled(True)
        h.setSortIndicatorShown(True)
        h.sectionClicked.connect(self.on_header_clicked)

        main_layout.addWidget(self.table)

        # Export (심플 버튼만)
        bottom = QHBoxLayout(); bottom.addStretch()
        self.export_html_btn = QPushButton("<HTML 저장>"); self.export_html_btn.setProperty("type", "outline")
        self.export_excel_btn = QPushButton("<엑셀 저장>"); self.export_excel_btn.setProperty("type", "outline")
        self.export_html_btn.clicked.connect(self.export_html)
        self.export_excel_btn.clicked.connect(self.export_excel)
        bottom.addWidget(self.export_html_btn); bottom.addWidget(self.export_excel_btn)
        main_layout.addLayout(bottom)

        self.table.cellClicked.connect(self.on_table_click)

    def _update_license_ui(self):
        """
        ✅ 검색 버튼은 항상 활성화.
        API 키 체크는 on_search()에서 처리합니다.
        """
        self.search_button.setEnabled(True)

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
            self._update_license_ui()
        else:
            self._style_api_label(False)
            self.lbl_api.setToolTip("상단의 [API 키 설정…] 버튼으로 등록하세요.")
            self._update_license_ui()

    def open_api_dialog(self):
        dlg = ApiKeyDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_api_key_status()

    # ----- 이벤트 -----
    def on_search(self):
        # 1) API 키 체크
        if not ytu.peek_effective_key():
            QMessageBox.information(self, "API 키 필요", "YouTube API 키가 필요합니다. 키를 등록해 주세요.")
            self.open_api_dialog()
            if not ytu.peek_effective_key(): return

        # 2) 입력값
        keyword = self.keyword_input.text().strip()
        try:
            count = int(self.count_input.text().strip() or "50")
        except ValueError:
            count = 50
        if not keyword:
            QMessageBox.warning(self, "입력 확인", "키워드를 입력하세요."); return

        logger.info(f"[UI] 검색 버튼: q='{keyword}', count={count}")

        # 기존 로더 종료
        for loader in self.image_loaders:
            try:
                if loader.isRunning(): loader.terminate()
            except Exception:
                pass
        self.image_loaders.clear()

        with QSignalBlocker(self.table):
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0)
        self.items_raw = []
        self._seen_links.clear()
        self._set_busy(True)
        self.progress.setVisible(True); self.progress.setRange(0, 0)

        self.worker = SearchWorker(keyword, count)
        self.worker.progress.connect(self._on_progress)
        self.worker.summary.connect(self._on_search_summary)   # 부족 결과 안내
        self.worker.one.connect(self._on_worker_one)
        self.worker.done.connect(self._on_worker_done)
        self.worker.error.connect(self._on_search_error)
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        if total <= 0: self.progress.setRange(0, 0); return
        if self.progress.maximum() != total: self.progress.setRange(0, total)
        self.progress.setValue(current)

    def _on_search_summary(self, found: int, requested: int):
        # 요청 대비 확보량이 부족하면 간결 안내
        if found < requested:
            msg = [
                f"요청: {requested:,}개 / 실제: {found:,}개",
                "이 키워드로 공개된 영상이 적거나, 유튜브가 더 보여줄 결과가 없어요.",
                "tip) 키워드를 넓히거나 다른 표현을 시도해 보세요.",
            ]
            InfoDialog("결과가 적어요", msg, self).exec()

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
        self._set_busy(False)
        self._restore_sorting()

    def _on_search_error(self, msg: str):
        logger.error(f"[UI] 수집 오류: {msg}")
        self.progress.setVisible(False)
        self._set_busy(False)
        with QSignalBlocker(self.table):
            self.table.setSortingEnabled(True)
        InfoDialog("수집 오류", [msg], self).exec()

    # ----- 필터 -----
    def open_filter_dialog(self):
        try:
            dlg = FilterDialog(self, init=self.active_filter)
            if dlg.exec() == QDialog.Accepted and dlg.result:
                self.active_filter = dlg.result
                items = [it for it in self.items_raw if self._filter_match(it, self.active_filter)]
                self._render_rows(items)
                self._restore_sorting()
        except Exception as e:
            logger.exception("필터 적용 중 예외")
            InfoDialog("필터 적용 중 오류", [str(e)], self).exec()

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

        return True

    def on_header_clicked(self, col: int):
        numeric_desc_default = {self.COL_VIEWS, self.COL_LIKES, self.COL_COMMS, self.COL_SUBS, self.COL_DUR}
        if self._last_sort_col == col:
            self._last_sort_order = Qt.DescendingOrder if self._last_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._last_sort_col = col
            self._last_sort_order = Qt.DescendingOrder if col in numeric_desc_default else Qt.AscendingOrder
        try:
            self.table.sortItems(col, self._last_sort_order)
            self.table.horizontalHeader().setSortIndicator(col, self._last_sort_order)
        except Exception:
            pass

    # ----- 렌더 -----
    def _render_rows(self, items: list[dict]):
        for loader in self.image_loaders:
            try:
                if loader.isRunning(): loader.terminate()
            except Exception:
                pass
        self.image_loaders.clear()

        with QSignalBlocker(self.table):
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
        row = self.table.rowCount()
        self.table.insertRow(row)
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

        # 3 좋아요수
        likes = int(item.get("likes", 0) or 0)
        self.table.setItem(row, self.COL_LIKES, NumericItem(likes))

        # 4 댓글수
        comms = int(item.get("comments", 0) or 0)
        self.table.setItem(row, self.COL_COMMS, NumericItem(comms))

        # 5 구독자수
        subs = int(item.get("subscribers", 0) or 0)
        self.table.setItem(row, self.COL_SUBS, NumericItem(subs))

        # 6 업로드 날짜
        self.table.setItem(row, self.COL_DATE, DateItem(item.get("upload_date", "")))

        # 7 길이(초→포맷), 정렬은 초 기준
        dur_sec = int(item.get("duration_sec", 0) or 0)
        self.table.setItem(row, self.COL_DUR, DurationItem(dur_sec))

        # 8 영상 링크
        vlink = item.get("video_link", "")
        v_item = QTableWidgetItem(vlink)
        v_item.setData(Qt.UserRole, vlink)
        v_item.setForeground(Qt.blue)
        v_item.setToolTip("클릭하여 영상 열기")
        self.table.setItem(row, self.COL_VURL, v_item)

        # 9 형태
        form_txt = item.get("form", "") or ("숏폼" if item.get("is_shorts") else "롱폼")
        self.table.setItem(row, self.COL_FORM, QTableWidgetItem(form_txt))

        # 10 채널명
        self.table.setItem(row, self.COL_CH, QTableWidgetItem(item.get("channel", "")))

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

    def _restore_sorting(self):
        try:
            self.table.setSortingEnabled(True)
            if self._last_sort_col is not None:
                self.table.sortItems(self._last_sort_col, self._last_sort_order)
                self.table.horizontalHeader().setSortIndicator(self._last_sort_col, self._last_sort_order)
        except Exception:
            pass

    def _collect_rows(self):
        rows = []
        for r in range(self.table.rowCount()):
            rows.append({
                "title": self.table.item(r, self.COL_TITLE).text() if self.table.item(r, self.COL_TITLE) else "",
                "views": self.table.item(r, self.COL_VIEWS).text() if self.table.item(r, self.COL_VIEWS) else "",
                "likes": self.table.item(r, self.COL_LIKES).text() if self.table.item(r, self.COL_LIKES) else "",
                "comments": self.table.item(r, self.COL_COMMS).text() if self.table.item(r, self.COL_COMMS) else "",
                "subscribers": self.table.item(r, self.COL_SUBS).text() if self.table.item(r, self.COL_SUBS) else "",
                "upload_date": self.table.item(r, self.COL_DATE).text() if self.table.item(r, self.COL_DATE) else "",
                "duration": self.table.item(r, self.COL_DUR).text() if self.table.item(r, self.COL_DUR) else "",
                "video_link": self.table.item(r, self.COL_VURL).text() if self.table.item(r, self.COL_VURL) else "",
                "form": self.table.item(r, self.COL_FORM).text() if self.table.item(r, self.COL_FORM) else "",
                "channel": self.table.item(r, self.COL_CH).text() if self.table.item(r, self.COL_CH) else "",
            })
        return rows

    # ----- 저장 -----
    def export_excel(self):
        rows = self._collect_rows()
        if not rows:
            InfoDialog("안내", ["저장할 데이터가 없습니다."], self).exec(); return
        path, _ = QFileDialog.getSaveFileName(self, "엑셀 저장", "youtube_results.xlsx", "Excel 파일 (*.xlsx)")
        if not path: return

        try:
            workbook = xlsxwriter.Workbook(path)
            worksheet = workbook.add_worksheet("Sheet1")

            fmt_text = workbook.add_format({'text_wrap': False, 'valign': 'top'})
            fmt_number = workbook.add_format({'num_format': '0', 'valign': 'top'})

            headers = ["title","views","likes","comments","subscribers","upload_date","duration","video_link","form","channel"]
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

                v  = _to_int_safe(r.get("views", ""));       worksheet.write_number(ri, 1, v,  fmt_number) if v  is not None else worksheet.write(ri, 1,  "", fmt_text)
                lk = _to_int_safe(r.get("likes", ""));       worksheet.write_number(ri, 2, lk, fmt_number) if lk is not None else worksheet.write(ri, 2, "", fmt_text)
                cm = _to_int_safe(r.get("comments", ""));    worksheet.write_number(ri, 3, cm, fmt_number) if cm is not None else worksheet.write(ri, 3, "", fmt_text)
                s  = _to_int_safe(r.get("subscribers", "")); worksheet.write_number(ri, 4, s,  fmt_number) if s  is not None else worksheet.write(ri, 4, "", fmt_text)

                worksheet.write(ri, 5, r.get("upload_date", "") or "", fmt_text)
                worksheet.write(ri, 6, r.get("duration", "") or "", fmt_text)
                worksheet.write(ri, 7, r.get("video_link", "") or "", fmt_text)
                worksheet.write(ri, 8, r.get("form", "") or "", fmt_text)
                worksheet.write(ri, 9, r.get("channel", "") or "", fmt_text)

            workbook.close()
            InfoDialog("완료", [f"엑셀 저장 완료\n{path}"], self).exec()
        except Exception as e:
            InfoDialog("오류", [f"엑셀 저장 실패(xlsxwriter): {e}"], self).exec()

    def export_html(self):
        rows = self._collect_rows()
        if not rows:
            InfoDialog("안내", ["저장할 데이터가 없습니다."], self).exec(); return
        path, _ = QFileDialog.getSaveFileName(self, "HTML 저장", "youtube_results.html", "HTML 파일 (*.html)")
        if not path: return
        html = ["<html><head><meta charset='utf-8'></head><body><table border='1' cellspacing='0' cellpadding='6'>"]
        html.append("<tr><th>제목</th><th>조회수</th><th>좋아요수</th><th>댓글수</th><th>구독자수</th><th>업로드</th><th>길이</th><th>영상 링크</th><th>형태</th><th>채널</th></tr>")
        for r in rows:
            html.append(
                f"<tr>"
                f"<td>{r['title']}</td>"
                f"<td>{r['views']}</td>"
                f"<td>{r['likes']}</td>"
                f"<td>{r['comments']}</td>"
                f"<td>{r['subscribers']}</td>"
                f"<td>{r['upload_date']}</td>"
                f"<td>{r['duration']}</td>"
                f"<td><a href='{r['video_link']}'>{r['video_link']}</a></td>"
                f"<td>{r['form']}</td>"
                f"<td>{r['channel']}</td>"
                f"</tr>"
            )
        html.append("</table></body></html>")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(html))
            InfoDialog("완료", [f"HTML 저장 완료\n{path}"], self).exec()
        except Exception as e:
            InfoDialog("오류", [f"HTML 저장 실패: {e}"], self).exec()
