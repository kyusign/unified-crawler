# community_tab.py
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path
import xlsxwriter  # 경량 엑셀 라이브러리

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QFileDialog, QTextEdit, QMessageBox,
    QDialog, QFrame
)

import crawling as community
from licensing.license_manager import (
    verify_license_text, load_license_from_disk, save_license_to_disk,
    sign_license_with_private_pem
    # watermark_excel  # (openpyxl 제거에 따라 사용 안 함)
)


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------- 엑셀 저장(워터마크/라이선스 기록 포함) ----------
def _write_xlsx_with_license(path: str, rows: list[dict], col_order: list[str], lic_payload: dict | None):
    # 디렉터리 보장
    out_dir = os.path.dirname(path) or "."
    os.makedirs(out_dir, exist_ok=True)

    wb = xlsxwriter.Workbook(path)
    ws = wb.add_worksheet("results")

    # 서식
    hdr_fmt   = wb.add_format({"bold": True, "bg_color": "#F0F3F8", "border": 1})
    num_fmt   = wb.add_format({"num_format": "#,##0", "valign": "top"})     # 정수형
    link_fmt  = wb.add_format({"font_color": "blue", "underline": 1, "valign": "top"})
    text_wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    text_fmt  = wb.add_format({"valign": "top"})

    # 모든 행의 기본 높이 16.5로 고정
    ws.set_default_row(16.5)

    # 헤더
    for c, h in enumerate(col_order):
        ws.write(0, c, h, hdr_fmt)

    # 안전한 정수 변환기
    def _to_int(s):
        try:
            if s is None:
                return 0
            ss = str(s).strip()
            if ss == "":
                return 0
            ss = ss.replace(",", "")
            low = ss.lower()
            if low.endswith("k"):
                return int(float(low[:-1]) * 1000)
            if low.endswith("m"):
                return int(float(low[:-1]) * 1_000_000)
            import re
            digits = re.sub(r"[^\d\-]", "", ss)
            if digits in ("", "-"):
                return 0
            return int(digits)
        except Exception:
            return 0

    # 데이터
    for r, row in enumerate(rows, start=1):
        for c, key in enumerate(col_order):
            val = row.get(key, "")
            k = key.lower()
            if k in ("views", "조회수", "subscribers", "구독자수"):
                try:
                    ws.write_number(r, c, _to_int(val), num_fmt)
                except Exception:
                    ws.write(r, c, val, text_fmt)
            elif k in ("link", "링크", "video_link", "영상 링크"):
                url = str(val or "").strip()
                if url:
                    try:
                        ws.write_url(r, c, url, link_fmt, url)
                    except Exception:
                        ws.write(r, c, url, text_fmt)
                else:
                    ws.write(r, c, "", text_fmt)
            elif k in ("title", "제목", "caption", "자막"):
                ws.write(r, c, val, text_wrap)
            else:
                ws.write(r, c, val, text_fmt)

    # 보기
    ws.freeze_panes(1, 0)
    try:
        ws.autofilter(0, 0, len(rows), len(col_order) - 1)
    except Exception:
        pass

    # 컬럼 폭
    for idx, name in enumerate(col_order):
        n = name.lower()
        if n in ("site", "사이트"):
            ws.set_column(idx, idx, 12)
        elif n in ("title", "제목"):
            ws.set_column(idx, idx, 60)
        elif n in ("date", "날짜", "upload_date"):
            ws.set_column(idx, idx, 20)
        elif n in ("views", "조회수", "subscribers", "구독자수"):
            ws.set_column(idx, idx, 12)
        elif n in ("link", "링크", "video_link", "영상 링크"):
            ws.set_column(idx, idx, 48)
        else:
            ws.set_column(idx, idx, 16)

    # 헤더/데이터 행 높이 명시 적용(안정성 보강)
    try:
        ws.set_row(0, 16.5, hdr_fmt)
        for r in range(1, len(rows) + 1):
            ws.set_row(r, 16.5)
    except Exception:
        pass

    # 간단 워터마크(헤더 텍스트) + LICENSE 숨김 시트
    user = (lic_payload or {}).get("user") or (lic_payload or {}).get("name") or ""
    dev  = (lic_payload or {}).get("dev")  or (lic_payload or {}).get("device") or ""
    exp  = (lic_payload or {}).get("exp")  or ""
    if user or dev or exp:
        try:
            ws.set_header(f"&C Licensed to {user}" + (f"  (exp: {exp})" if exp else ""))
        except Exception:
            pass
        try:
            lic_ws = wb.add_worksheet("LICENSE")
            lic_ws.hide()
            lic_ws.write_row(0, 0, ["key", "value"], hdr_fmt)
            lic_ws.write(1, 0, "user");   lic_ws.write(1, 1, user)
            lic_ws.write(2, 0, "device"); lic_ws.write(2, 1, dev)
            lic_ws.write(3, 0, "exp");    lic_ws.write(3, 1, exp)
            lic_ws.write(4, 0, "issued_at"); lic_ws.write(4, 1, ts())
        except Exception:
            pass

    wb.close()


# --------- 크롤러 쓰레드 ----------
class CrawlerThread(QThread):
    log_line = Signal(str)
    done     = Signal(str, int)
    warn     = Signal(str)
    fail     = Signal(str)

    def __init__(self, comm, url, days, hours, out_path, show_browser, lic_payload):
        super().__init__()
        self.comm = comm
        self.url = url
        self.days = days
        self.hours = hours
        self.out_path = out_path
        self.show_browser = show_browser
        self.lic_payload = lic_payload

    def run(self):
        try:
            total_hours = self.days * 24 + self.hours
            cutoff = datetime.now() - timedelta(hours=total_hours)

            def _log(m):
                self.log_line.emit(f"{ts()} | {m}")

            self.log_line.emit(
                f"실행: {self.comm} | 최근 {self.days}일 {self.hours}시간 (총 {total_hours}시간) | "
                f"화면보기={self.show_browser} | cutoff={cutoff:%Y-%m-%d %H:%M}"
            )

            if self.comm == "FMKorea":
                rows = community.crawl_fmkorea(self.url, cutoff, self.show_browser, _log)
            elif self.comm == "DCInside":
                rows = community.crawl_dcinside(self.url, cutoff, self.show_browser, _log)
            elif self.comm == "TheQoo":
                rows = community.crawl_theqoo(self.url, cutoff, self.show_browser, _log)
            else:
                self.fail.emit("지원하지 않는 커뮤니티입니다.")
                return

            if not rows:
                self.warn.emit("수집 결과가 없습니다.")
                return

            # 컬럼 결정
            keys_present = set()
            for r in rows:
                try:
                    keys_present.update(r.keys())
                except Exception:
                    pass
            default_cols = ["Site", "Title", "Date", "Views", "Link"]
            cols = [c for c in default_cols if c in keys_present] or (list(rows[0].keys()) if rows else [])
            if not cols:
                self.fail.emit("출력 가능한 컬럼이 없습니다.")
                return

            community.ensure_dir_for_file(self.out_path)
            _write_xlsx_with_license(self.out_path, rows, cols, self.lic_payload)

            # 수집된 시각 범위 로그
            dts = []
            for r in rows:
                iso = r.get("DateISO")
                if iso:
                    try:
                        dts.append(datetime.strptime(iso, "%Y-%m-%d %H:%M:%S"))
                    except Exception:
                        pass
            if dts:
                self.log_line.emit(
                    f"수집된 시각 범위: {min(dts):%Y-%m-%d %H:%M:%S} ~ {max(dts):%Y-%m-%d %H:%M:%S}"
                )

            self.log_line.emit(f"완료! 저장: {self.out_path} | 수집 {len(rows)}건")
            self.done.emit(self.out_path, len(rows))
        except Exception as e:
            self.fail.emit(str(e))


# --------- 라이선스 발급 다이얼로그(관리자) ----------
class AdminIssueDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("라이선스 발급(관리자)")
        self.setModal(True)
        self.parent = parent

        self.priv_edit = QLineEdit()
        self.user_edit = QLineEdit()
        self.dev_edit  = QLineEdit()
        self.exp_edit  = QLineEdit(datetime.now().strftime("%Y-%m-%d"))

        lay = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("개인키")); row1.addWidget(self.priv_edit, 1)
        btn_priv = QPushButton("찾기"); btn_priv.clicked.connect(self.pick_priv)
        row1.addWidget(btn_priv); lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("구매자")); row2.addWidget(self.user_edit); lay.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("기기ID(공용은 비움)")); row3.addWidget(self.dev_edit); lay.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("만료일")); row4.addWidget(self.exp_edit); lay.addLayout(row4)

        btns = QHBoxLayout()
        issue = QPushButton("발급"); issue.clicked.connect(self.issue)
        close = QPushButton("닫기"); close.clicked.connect(self.close)
        btns.addWidget(issue); btns.addWidget(close); lay.addLayout(btns)

    def pick_priv(self):
        path, _ = QFileDialog.getOpenFileName(self, "private.pem 선택", "", "PEM file (*.pem)")
        if path:
            self.priv_edit.setText(path)

    def issue(self):
        priv = self.priv_edit.text().strip()
        user = self.user_edit.text().strip()
        dev  = self.dev_edit.text().strip()
        exp  = self.exp_edit.text().strip()
        if not (os.path.exists(priv) and user and exp):
            QMessageBox.warning(self, "확인", "개인키/구매자/만료일은 필수입니다.")
            return
        try:
            datetime.strptime(exp, "%Y-%m-%d")
        except ValueError:
            QMessageBox.critical(self, "오류", "만료일 형식이 올바르지 않습니다.")
            return
        out_path, _ = QFileDialog.getSaveFileName(self, "라이선스 저장", "license.lic", "License file (*.lic)")
        if not out_path:
            return
        try:
            lic_text = sign_license_with_private_pem(priv, user, dev, exp)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(lic_text)
            QMessageBox.information(self, "완료", f"라이선스 발급 완료\n{out_path}")
            self.parent.append_log(
                f"{ts()} | [ADMIN] 라이선스 발급: {user} / {dev or '<shared>'} / {exp} -> {out_path}"
            )
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "오류", str(e))


# --------- 라이선스 필요 안내 다이얼로그 ----------
class LicenseRequiredDialog(QDialog):
    """라이선스 미등록 시 띄우는 안내 팝업 (테마 Card 스타일 적용)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("라이선스 등록 안내")
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        card = QFrame(); card.setObjectName("Card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(24, 24, 18, 18)
        inner.setSpacing(12)

        icon = QLabel("🔒"); icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 42px;")

        title = QLabel("라이선스를 등록해 주세요")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")

        desc = QLabel(
            "이 기능을 사용하려면 라이선스가 필요합니다.\n"
            "아래 [지금 등록하기] 버튼을 눌러 .lic 파일을 선택해 주세요."
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#4b5563;")

        btns = QHBoxLayout(); btns.addStretch()
        btn_cancel   = QPushButton("나중에"); btn_cancel.setProperty("type", "ghost")
        btn_register = QPushButton("지금 등록하기"); btn_register.setProperty("type", "primary")
        btns.addWidget(btn_cancel); btns.addWidget(btn_register)

        inner.addWidget(icon)
        inner.addWidget(title)
        inner.addWidget(desc)
        inner.addLayout(btns)

        root.addWidget(card)

        btn_cancel.clicked.connect(self.reject)
        btn_register.clicked.connect(self.accept)


# --------- 메인 위젯 ----------
class CommunityCrawlerWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.license_payload = None
        self._build_ui()
        self._check_license_on_start()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        self.lbl_license = QLabel("라이선스: 확인 중...")
        lay.addWidget(self.lbl_license)

        # 커뮤니티 / URL
        line1 = QHBoxLayout()
        self.comm = QComboBox(); self.comm.addItems(["FMKorea", "DCInside", "TheQoo"])
        self.url  = QLineEdit(); self.url.setPlaceholderText("목록 URL 입력")
        line1.addWidget(QLabel("커뮤니티")); line1.addWidget(self.comm, 0)
        line1.addWidget(QLabel("목록 URL")); line1.addWidget(self.url, 1)
        lay.addLayout(line1)

        # 기간 / 화면보기
        line2 = QHBoxLayout()
        self.days = QSpinBox(); self.days.setRange(0, 365); self.days.setValue(1)
        self.hours = QSpinBox(); self.hours.setRange(0, 23); self.hours.setValue(0)
        self.show_browser = QCheckBox("크롤링 화면 보기(브라우저 표시)")
        line2.addWidget(QLabel("최근")); line2.addWidget(self.days); line2.addWidget(QLabel("일"))
        line2.addSpacing(8)
        line2.addWidget(self.hours); line2.addWidget(QLabel("시간"))
        line2.addSpacing(20)
        line2.addWidget(self.show_browser); line2.addStretch()
        lay.addLayout(line2)

        # 저장 경로
        line3 = QHBoxLayout()
        default_path = os.path.join(community.DEFAULT_DESKTOP, f"크롤링_결과_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        self.out_path = QLineEdit(default_path)
        browse = QPushButton("찾아보기…"); browse.clicked.connect(self.pick_out_path)
        line3.addWidget(QLabel("엑셀 저장 경로")); line3.addWidget(self.out_path, 1); line3.addWidget(browse)
        lay.addLayout(line3)

        # 버튼들
        line4 = QHBoxLayout()
        self.btn_license = QPushButton("라이선스 불러오기")
        self.btn_license.clicked.connect(self.on_license_load)
        self.btn_run = QPushButton("실행")
        self.btn_run.clicked.connect(self.on_run)
        admin = QPushButton("라이선스 발급(관리자)")
        admin.clicked.connect(self.on_admin_issue)
        line4.addWidget(self.btn_license)
        line4.addWidget(self.btn_run)
        line4.addWidget(admin)
        line4.addStretch()
        lay.addLayout(line4)

        # 로그
        lay.addWidget(QLabel("로그"))
        self.log = QTextEdit(); self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)

        tail = QLabel("원초적인사이트 데이터수집 프로그램")
        lay.addWidget(tail)

        self._update_run_enabled()

    def _check_license_on_start(self):
        # 1) 표준 저장 위치 읽기
        txt = load_license_from_disk()

        # 2) exe 옆 license.lic 자동 인식(배포 편의)
        if not txt:
            try:
                cand = (Path(sys.executable).resolve().parent / "license.lic") if getattr(sys, "frozen", False) \
                       else (Path.cwd() / "license.lic")
                if cand.exists():
                    txt = cand.read_text(encoding="utf-8")
            except Exception:
                txt = None

        if txt:
            ok, msg, payload = verify_license_text(txt)
            if ok:
                self.license_payload = payload
                try: save_license_to_disk(txt)
                except Exception: pass
                exp = payload.get("exp")
                self.lbl_license.setText("라이선스 OK" + (f" (만료: {exp})" if exp else ""))
            else:
                self.lbl_license.setText(f"라이선스 오류: {msg}")
        else:
            self.lbl_license.setText("라이선스 없음 — [라이선스 불러오기]")

        self._update_run_enabled()

    def on_license_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "라이선스 파일(.lic) 선택", "", "License file (*.lic)")
        if not path:
            return
        try:
            txt = open(path, "r", encoding="utf-8").read()
        except Exception as e:
            QMessageBox.critical(self, "오류", f"파일 읽기 실패: {e}")
            return

        ok, msg, payload = verify_license_text(txt)
        if not ok:
            QMessageBox.critical(self, "라이선스 오류", msg)
            return

        try:
            save_license_to_disk(txt)
        except Exception:
            pass

        self.license_payload = payload
        exp = payload.get("exp")
        self.lbl_license.setText("라이선스 OK" + (f" (만료: {exp})" if exp else ""))
        QMessageBox.information(self, "라이선스", "라이선스 등록 완료")
        self._update_run_enabled()

    def _update_run_enabled(self):
        # 버튼은 항상 활성화, 라이선스 없으면 툴팁 안내
        self.btn_run.setEnabled(True)
        self.btn_run.setToolTip("" if self.license_payload else "라이선스를 등록하면 실행할 수 있습니다.")

    def pick_out_path(self):
        path, _ = QFileDialog.getSaveFileName(self, "엑셀 저장 경로", self.out_path.text(), "Excel 파일 (*.xlsx)")
        if path:
            self.out_path.setText(path)

    def append_log(self, m: str):
        self.log.append(m)

    def on_admin_issue(self):
        dlg = AdminIssueDialog(self)
        dlg.exec()

    def on_run(self):
        # 라이선스 없으면 예쁜 팝업 → 등록 유도
        if not self.license_payload:
            dlg = LicenseRequiredDialog(self)
            if dlg.exec() == QDialog.Accepted:
                self.on_license_load()
            if not self.license_payload:
                return

        # ↓↓↓ 기존 로직 ↓↓↓
        comm  = self.comm.currentText().strip()
        url   = self.url.text().strip()
        days  = int(self.days.value())
        hours = int(self.hours.value())
        show  = self.show_browser.isChecked()
        outp  = self.out_path.text().strip()

        if not url:
            QMessageBox.warning(self, "입력 확인", "목록 URL을 입력하세요."); return
        if days < 0 or hours < 0 or hours > 23:
            QMessageBox.warning(self, "입력 확인", "일은 0 이상, 시간은 0~23 범위로 입력해 주세요."); return
        total_hours = days * 24 + hours
        if total_hours < 1:
            QMessageBox.warning(self, "입력 확인", "총 시간이 1시간 이상이어야 합니다."); return

        host = community.urlparse(url).netloc.lower()
        if comm == "FMKorea" and "fmkorea.com" not in host:
            QMessageBox.critical(self, "오류", "선택한 커뮤니티와 URL이 일치하지 않습니다."); return
        if comm == "DCInside" and "dcinside.com" not in host:
            QMessageBox.critical(self, "오류", "선택한 커뮤니티와 URL이 일치하지 않습니다."); return
        if comm == "TheQoo" and "theqoo.net" not in host:
            QMessageBox.critical(self, "오류", "선택한 커뮤니티와 URL이 일치하지 않습니다."); return

        self.btn_run.setEnabled(False)
        self.append_log(f"{ts()} | 작업 시작")

        self.thread = CrawlerThread(comm, url, days, hours, outp, show, self.license_payload)
        self.thread.log_line.connect(self.append_log)
        self.thread.done.connect(lambda p,c: QMessageBox.information(self, "완료", f"저장 완료\n{p}\n총 {c}건"))
        self.thread.warn.connect(lambda m: (self.append_log(f"{ts()} | {m}"), QMessageBox.information(self, "알림", m)))
        self.thread.fail.connect(lambda m: (self.append_log(f"{ts()} | 오류: {m}"), QMessageBox.critical(self, "오류", m)))
        self.thread.finished.connect(lambda: self.btn_run.setEnabled(True))
        self.thread.start()
