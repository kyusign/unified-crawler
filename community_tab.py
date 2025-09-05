# community_tab.py
import os
from datetime import datetime, timedelta

import pandas as pd
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, 
    QComboBox, QSpinBox, QCheckBox, QFileDialog, QTextEdit, QMessageBox
)

# 기존 crawling.py의 크롤링 함수들을 그대로 사용합니다.
# (tkinter App는 __main__에서만 실행되므로 import만으로 창이 뜨지 않음)
import crawling as community
from licensing.license_manager import (
    verify_license, verify_license_from_anywhere, save_license_to_disk
)

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

class CrawlerThread(QThread):
    log_line = Signal(str)
    done = Signal(str, int)   # out_path, row_count
    warn = Signal(str)
    fail = Signal(str)

    def __init__(self, comm, url, days, hours, out_path, show_browser):
        super().__init__()
        self.comm = comm
        self.url = url
        self.days = days
        self.hours = hours
        self.out_path = out_path
        self.show_browser = show_browser

    def run(self):
        try:
            total_hours = self.days * 24 + self.hours
            cutoff = datetime.now() - timedelta(hours=total_hours)

            def _log(msg: str):
                self.log_line.emit(f"{ts()} | {msg}")

            self.log_line.emit(
                f"실행: {self.comm} | 최근 {self.days}일 {self.hours}시간 (총 {total_hours}시간) "
                f"| 화면보기={self.show_browser} | cutoff={cutoff:%Y-%m-%d %H:%M}"
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

            df = pd.DataFrame(rows)
            want_cols = [c for c in ["Site", "Title", "Date", "Views", "Link"] if c in df.columns]
            df = df[want_cols]

            community.ensure_dir_for_file(self.out_path)
            df.to_excel(self.out_path, index=False)

            # (선택) 수집 범위 로그
            dts = []
            for r in rows:
                iso = r.get("DateISO")
                if iso:
                    try:
                        dts.append(datetime.strptime(iso, "%Y-%m-%d %H:%M:%S"))
                    except Exception:
                        pass
            if dts:
                self.log_line.emit(f"수집된 시각 범위: {min(dts):%Y-%m-%d %H:%M:%S} ~ {max(dts):%Y-%m-%d %H:%M:%S}")

            self.log_line.emit(f"완료! 저장: {self.out_path} | 수집 {len(df)}건")
            self.done.emit(self.out_path, len(df))

        except Exception as e:
            self.fail.emit(str(e))

class CommunityCrawlerWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.license_ok = False
        self._build_ui()
        self._auto_verify()

    # ---------------- UI ----------------
    def _build_ui(self):
        lay = QVBoxLayout(self)

        # (A) 라이선스 영역
        licRow = QHBoxLayout()
        self.lic_edit = QLineEdit()
        self.lic_edit.setPlaceholderText("라이선스 키를 입력하거나 license.dat로 저장해두세요")
        self.lic_btn = QPushButton("인증")
        self.lic_btn.clicked.connect(self.on_verify_license)
        self.lic_status = QLabel("상태: 미인증")
        self.lic_status.setStyleSheet("color:#B00020;")  # 붉은색

        licRow.addWidget(QLabel("라이선스"))
        licRow.addWidget(self.lic_edit, 1)
        licRow.addWidget(self.lic_btn)
        licRow.addWidget(self.lic_status)
        lay.addLayout(licRow)

        # (B) 크롤러 입력 폼
        line1 = QHBoxLayout()
        self.comm = QComboBox(); self.comm.addItems(["FMKorea", "DCInside", "TheQoo"])
        self.url = QLineEdit(); self.url.setPlaceholderText("목록 URL 입력")
        line1.addWidget(QLabel("커뮤니티")); line1.addWidget(self.comm, 0)
        line1.addWidget(QLabel("목록 URL")); line1.addWidget(self.url, 1)
        lay.addLayout(line1)

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

        line3 = QHBoxLayout()
        default_path = os.path.join(community.DEFAULT_DESKTOP, f"크롤링_결과_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        self.out_path = QLineEdit(default_path)
        btn_browse = QPushButton("찾아보기…")
        btn_browse.clicked.connect(self.pick_out_path)
        line3.addWidget(QLabel("엑셀 저장 경로")); line3.addWidget(self.out_path, 1); line3.addWidget(btn_browse)
        lay.addLayout(line3)

        # 실행 버튼
        line4 = QHBoxLayout()
        self.btn_run = QPushButton("실행")
        self.btn_run.clicked.connect(self.on_run)
        line4.addWidget(self.btn_run)
        line4.addStretch()
        lay.addLayout(line4)

        # 로그
        lay.addWidget(QLabel("로그"))
        self.log = QTextEdit(); self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)

        tail = QLabel("원초적인사이트 데이터수집 프로그램")
        lay.addWidget(tail)

        self._update_run_enabled()

    # ------------- 라이선스 -------------
    def _auto_verify(self):
        ok, payload_or_msg = verify_license_from_anywhere()
        if ok and "community" in payload_or_msg.get("features", []):
            self.license_ok = True
            owner = payload_or_msg.get("name") or payload_or_msg.get("email", "")
            exp = payload_or_msg.get("exp", "")
            self.lic_status.setText(f"상태: 인증됨 (만료 {exp}) – {owner}")
            self.lic_status.setStyleSheet("color:#1B5E20;")
        else:
            self.license_ok = False
            self.lic_status.setText("상태: 미인증")
            self.lic_status.setStyleSheet("color:#B00020;")
        self._update_run_enabled()

    def on_verify_license(self):
        lic = self.lic_edit.text().strip()
        if not lic:
            QMessageBox.warning(self, "알림", "라이선스 키를 입력하세요.")
            return
        ok, info_or_msg = verify_license(lic)
        if ok and "community" in info_or_msg.get("features", []):
            self.license_ok = True
            exp = info_or_msg.get("exp", "")
            owner = info_or_msg.get("name") or info_or_msg.get("email", "")
            self.lic_status.setText(f"상태: 인증됨 (만료 {exp}) – {owner}")
            self.lic_status.setStyleSheet("color:#1B5E20;")
            save_license_to_disk(lic)
            QMessageBox.information(self, "성공", "라이선스 인증에 성공했습니다.")
        else:
            self.license_ok = False
            msg = info_or_msg if isinstance(info_or_msg, str) else "권한 부족"
            self.lic_status.setText("상태: 미인증")
            self.lic_status.setStyleSheet("color:#B00020;")
            QMessageBox.critical(self, "오류", f"라이선스 인증 실패: {msg}")
        self._update_run_enabled()

    def _update_run_enabled(self):
        self.btn_run.setEnabled(self.license_ok)

    # -------------- 동작 ---------------
    def pick_out_path(self):
        path, _ = QFileDialog.getSaveFileName(self, "엑셀 저장 경로", self.out_path.text(), "Excel 파일 (*.xlsx)")
        if path:
            self.out_path.setText(path)

    def append_log(self, msg: str):
        self.log.append(msg)

    def on_run(self):
        if not self.license_ok:
            QMessageBox.critical(self, "오류", "라이선스 인증 후 이용해 주세요.")
            return

        comm = self.comm.currentText().strip()
        url = self.url.text().strip()
        days = int(self.days.value())
        hours = int(self.hours.value())
        show = self.show_browser.isChecked()
        outp = self.out_path.text().strip()

        if not url:
            QMessageBox.warning(self, "입력 확인", "목록 URL을 입력하세요.")
            return

        total_hours = days * 24 + hours
        if total_hours < 1:
            QMessageBox.warning(self, "입력 확인", "총 시간이 1시간 이상이어야 합니다.")
            return

        host = community.urlparse(url).netloc.lower()
        if comm == "FMKorea" and "fmkorea.com" not in host:
            QMessageBox.critical(self, "오류", "선택한 커뮤니티와 URL이 일치하지 않습니다.")
            return
        if comm == "DCInside" and "dcinside.com" not in host:
            QMessageBox.critical(self, "오류", "선택한 커뮤니티와 URL이 일치하지 않습니다.")
            return
        if comm == "TheQoo" and "theqoo.net" not in host:
            QMessageBox.critical(self, "오류", "선택한 커뮤니티와 URL이 일치하지 않습니다.")
            return

        self.btn_run.setEnabled(False)
        self.append_log(f"{ts()} | 작업 시작")

        self.thread = CrawlerThread(comm, url, days, hours, outp, show)
        self.thread.log_line.connect(self.append_log)
        self.thread.done.connect(self.on_done)
        self.thread.warn.connect(self.on_warn)
        self.thread.fail.connect(self.on_fail)
        self.thread.finished.connect(lambda: self.btn_run.setEnabled(True))
        self.thread.start()

    def on_done(self, out_path: str, count: int):
        QMessageBox.information(self, "완료", f"저장 완료\n{out_path}\n총 {count}건")

    def on_warn(self, msg: str):
        self.append_log(f"{ts()} | {msg}")
        QMessageBox.information(self, "알림", msg)

    def on_fail(self, msg: str):
        self.append_log(f"{ts()} | 오류: {msg}")
        QMessageBox.critical(self, "오류", msg)
