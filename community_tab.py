from datetime import datetime, timedelta
import os

import pandas as pd
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QFileDialog, QTextEdit, QMessageBox, QDialog
)

import crawling as community
from licensing.license_manager import (
    verify_license_text, load_license_from_disk, save_license_to_disk,
    sign_license_with_private_pem, watermark_excel
)


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CrawlerThread(QThread):
    log_line = Signal(str)
    done = Signal(str, int)
    warn = Signal(str)
    fail = Signal(str)

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

            df = pd.DataFrame(rows)
            cols = [c for c in ["Site", "Title", "Date", "Views", "Link"] if c in df.columns]
            df = df[cols]
            community.ensure_dir_for_file(self.out_path)
            df.to_excel(self.out_path, index=False)
            watermark_excel(self.out_path, self.lic_payload)

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

            self.log_line.emit(f"완료! 저장: {self.out_path} | 수집 {len(df)}건")
            self.done.emit(self.out_path, len(df))
        except Exception as e:
            self.fail.emit(str(e))


class AdminIssueDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("라이선스 발급(관리자)")
        self.setModal(True)
        self.parent = parent

        self.priv_edit = QLineEdit()
        self.user_edit = QLineEdit()
        self.dev_edit = QLineEdit()
        self.exp_edit = QLineEdit(datetime.now().strftime("%Y-%m-%d"))

        lay = QVBoxLayout(self)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("개인키"))
        row1.addWidget(self.priv_edit, 1)
        btn_priv = QPushButton("찾기")
        btn_priv.clicked.connect(self.pick_priv)
        row1.addWidget(btn_priv)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("구매자"))
        row2.addWidget(self.user_edit)
        lay.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("기기ID(공용은 비움)"))
        row3.addWidget(self.dev_edit)
        lay.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("만료일"))
        row4.addWidget(self.exp_edit)
        lay.addLayout(row4)

        btns = QHBoxLayout()
        issue = QPushButton("발급")
        issue.clicked.connect(self.issue)
        close = QPushButton("닫기")
        close.clicked.connect(self.close)
        btns.addWidget(issue)
        btns.addWidget(close)
        lay.addLayout(btns)

    def pick_priv(self):
        path, _ = QFileDialog.getOpenFileName(self, "private.pem 선택", "", "PEM file (*.pem)")
        if path:
            self.priv_edit.setText(path)

    def issue(self):
        priv = self.priv_edit.text().strip()
        user = self.user_edit.text().strip()
        dev = self.dev_edit.text().strip()
        exp = self.exp_edit.text().strip()
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
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self.pick_out_path)
        line3.addWidget(QLabel("엑셀 저장 경로")); line3.addWidget(self.out_path, 1); line3.addWidget(browse)
        lay.addLayout(line3)

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

        lay.addWidget(QLabel("로그"))
        self.log = QTextEdit(); self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)

        tail = QLabel("원초적인사이트 데이터수집 프로그램")
        lay.addWidget(tail)

        self._update_run_enabled()

    def _check_license_on_start(self):
        txt = load_license_from_disk()
        if txt:
            ok, msg, payload = verify_license_text(txt)
            if ok:
                self.license_payload = payload
                exp = payload.get("exp")
                label = "라이선스 OK" + (f" (만료: {exp})" if exp else "")
                self.lbl_license.setText(label)
            else:
                self.lbl_license.setText(f"라이선스 오류: {msg}")
        else:
            self.lbl_license.setText("라이선스 없음 — [라이선스 불러오기]")
        self._update_run_enabled()

    def on_license_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "라이선스 파일(.lic) 선택", "", "License file (*.lic)")
        if not path:
            return
        txt = open(path, "r", encoding="utf-8").read()
        ok, msg, payload = verify_license_text(txt)
        if not ok:
            QMessageBox.critical(self, "라이선스 오류", msg)
            return
        save_license_to_disk(txt)
        self.license_payload = payload
        exp = payload.get("exp")
        label = "라이선스 OK" + (f" (만료: {exp})" if exp else "")
        self.lbl_license.setText(label)
        QMessageBox.information(self, "라이선스", "라이선스 등록 완료")
        self._update_run_enabled()

    def _require_license(self):
        if self.license_payload:
            return True
        QMessageBox.warning(self, "라이선스", "라이선스를 먼저 등록해주세요.")
        return False

    def _update_run_enabled(self):
        self.btn_run.setEnabled(self.license_payload is not None)

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
        if not self._require_license():
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
        if days < 0 or hours < 0 or hours > 23:
            QMessageBox.warning(self, "입력 확인", "일은 0 이상, 시간은 0~23 범위로 입력해 주세요.")
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
        self.thread = CrawlerThread(comm, url, days, hours, outp, show, self.license_payload)
        self.thread.log_line.connect(self.append_log)
        self.thread.done.connect(lambda p,c: QMessageBox.information(self, "완료", f"저장 완료\n{p}\n총 {c}건"))
        self.thread.warn.connect(lambda m: (self.append_log(f"{ts()} | {m}"), QMessageBox.information(self, "알림", m)))
        self.thread.fail.connect(lambda m: (self.append_log(f"{ts()} | 오류: {m}"), QMessageBox.critical(self, "오류", m)))
        self.thread.finished.connect(lambda: self.btn_run.setEnabled(True))
        self.thread.start()
