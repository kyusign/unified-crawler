from __future__ import annotations
import os
import sys
import time
from pathlib import Path
import faulthandler

from app_paths import log_dir

# 로그는 사용자 폴더 쪽에 고정(배포 exe 옆/임시폴더가 아님)
_LOG_DIR = log_dir()
_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = _LOG_DIR / "boot.log"

def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        try:
            sys.stderr.write(line)
        except Exception:
            pass

def runtime_is_frozen() -> bool:
    """여러 휴리스틱으로 배포 실행(EXE) 여부를 감지."""
    try:
        if os.environ.get("UC_FORCE_FROZEN") == "1":
            return True

        if bool(getattr(sys, "frozen", False)):
            return True
        if hasattr(sys, "_MEIPASS"):  # PyInstaller 관성 지원
            return True

        try:
            if globals().get("__compiled__", None) is not None:
                return True
        except Exception:
            pass

        try:
            import builtins as _bi
            if getattr(_bi, "__compiled__", None) is True:
                return True
        except Exception:
            pass

        try:
            exe_name = os.path.basename(sys.executable).lower()
            if exe_name.endswith(".exe") and not exe_name.startswith(("python", "py")):
                return True
        except Exception:
            pass

        return False
    except Exception:
        return False

def install():
    """Call this at the very top of your main script (before importing PySide6)."""
    try:
        LOG_PATH.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        fh = open(LOG_PATH, "a", encoding="utf-8")
        faulthandler.enable(fh)
    except Exception:
        pass

    # FROZEN 판정
    is_frozen_sys = bool(getattr(sys, "frozen", False))
    has_meipass   = hasattr(sys, "_MEIPASS")
    try:
        import builtins as _bi
        has_compiled_attr = hasattr(_bi, "__compiled__")
        compiled_val_bi   = getattr(_bi, "__compiled__", None)
    except Exception:
        has_compiled_attr = False
        compiled_val_bi   = None
    compiled_val_mod = globals().get("__compiled__", None)
    is_frozen = runtime_is_frozen()

    # ⚠ 핵심 변경: qt.conf 무력화 플래그는 DEV에서만 기본 on, FROZEN에서는 off
    try:
        if is_frozen:
            # Nuitka 번들의 내부 qt.conf가 필요할 수 있으므로 제거
            if os.environ.pop("PYSIDE_DISABLE_INTERNAL_QT_CONF", None) is not None:
                log("Unset PYSIDE_DISABLE_INTERNAL_QT_CONF for FROZEN")
        else:
            os.environ.setdefault("PYSIDE_DISABLE_INTERNAL_QT_CONF", "1")
    except Exception as e:
        log(f"PYSIDE flag adjust failed: {e!r}")

    # 진단 로그
    try:
        log("=== BOOT START ===")
        log(f"Python: {sys.version.replace(os.linesep, ' ')}")
        try:
            log(f"Exe: {sys.executable}")
        except Exception:
            log("Exe: <unknown>")
        try:
            log(f"CWD: {os.getcwd()}")
        except Exception:
            log("CWD: <unknown>")

        log(f"sys.frozen present: {is_frozen_sys}")
        log(f"has _MEIPASS: {has_meipass}")
        log(f"builtins.__compiled__ present: {has_compiled_attr} value: {compiled_val_bi!r}")
        log(f"module __compiled__ value: {compiled_val_mod!r}")
        try:
            log(f"exe basename: {os.path.basename(sys.executable).lower()}")
        except Exception:
            pass
        log(f"Derived is_frozen: {is_frozen}")

        log("env (filtered):")
        for k in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH",
                  "PYSIDE_DISABLE_INTERNAL_QT_CONF", "QT_DEBUG_PLUGINS", "PATH"):
            v = os.environ.get(k)
            if v:
                log(f"  {k}={v}")

        log("sys.path:")
        for p in sys.path:
            try:
                log(f"  - {p}")
            except Exception:
                pass

        log(f"MODE: {'FROZEN' if is_frozen else 'DEV'}")
    except Exception as e:
        try:
            log(f"BOOT DIAG FAILED: {e!r}")
        except Exception:
            pass

if __name__ == "__main__":
    install()
