# diag_bootstrap.py
"""
Diagnostic bootstrap for PySide6/Nuitka packaging.

- Call install() as the very first code in your main script (before importing PySide6).
- Writes boot.log next to this file.
- Resolves Qt plugin paths for DEV (site-packages) and FROZEN (dist/EXE).
- Adds DLL search dirs on Windows.
- **EARLY** Shiboken pre-load guard runs before anything else to avoid
  "PyState_AddModule: module ... already added".
"""
from __future__ import annotations
import os
import sys
import time
import traceback
from pathlib import Path
import faulthandler
import importlib, importlib.machinery, importlib.util

LOG_PATH = Path(__file__).resolve().parent / "boot.log"

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

def _early_shiboken_preload():
    """
    가장 먼저 호출되어 Shiboken 네이티브 확장을 '한 번만' 초기화하고,
    이후 다른 경로/이름으로 재초기화되지 않도록 sys.modules에 별칭을 등록합니다.
    """
    try:
        # dist/EXE 위치와 스크립트 위치를 우선 탐색
        try:
            exe_dir = Path(sys.executable).resolve().parent
        except Exception:
            exe_dir = Path(os.getcwd()).resolve()

        search_dirs = [
            exe_dir,
            exe_dir / "shiboken6",
            exe_dir / "PySide6",
            Path(__file__).resolve().parent,
        ]

        candidates = []
        patterns = ("Shiboken*.pyd", "Shiboken*.dll", "shiboken*.pyd", "shiboken*.dll")
        for d in search_dirs:
            try:
                for pat in patterns:
                    candidates += list(d.rglob(pat))
            except Exception:
                pass

        target = None
        if candidates:
            # 가장 먼저 찾은 네이티브 확장 파일 채택
            target = candidates[0]

        if target and target.exists():
            loader = importlib.machinery.ExtensionFileLoader("shiboken6.Shiboken", str(target))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            # 여러 이름으로 미리 등록 → 이후 중복 초기화 방지
            for key in ("Shiboken", "shiboken6.Shiboken", "shiboken6.abi3", "shiboken6"):
                sys.modules.setdefault(key, module)
            log(f"[EARLY] Shiboken preloaded from: {target}")
            return

        # 파일 기반 선로딩 실패 시, 일반 import 시도
        try:
            mod = importlib.import_module("shiboken6.Shiboken")
            for key in ("Shiboken", "shiboken6.Shiboken", "shiboken6.abi3"):
                sys.modules.setdefault(key, mod)
            log("[EARLY] Shiboken loaded via importlib fallback")
        except Exception as e:
            log(f"[EARLY] Shiboken import fallback failed: {e!r}")
    except Exception as e:
        log(f"[EARLY] Shiboken preload unexpected failure: {e!r}")

def install():
    """Call this at the very top of your main script (before importing PySide6)."""
    # --- start clean log ---
    try:
        LOG_PATH.unlink(missing_ok=True)
    except Exception:
        try:
            if LOG_PATH.exists():
                LOG_PATH.unlink()
        except Exception:
            pass

    # 치명 크래시까지 파일로 받기
    try:
        fh = open(LOG_PATH, "a", encoding="utf-8")
        faulthandler.enable(fh)
    except Exception:
        pass

    log("=== BOOT START ===")
    log(f"Python: {sys.version.replace(os.linesep, ' ')}")
    log(f"Exe: {sys.executable}")
    log(f"CWD: {os.getcwd()}")
    log("faulthandler enabled")

    # ---------- (1) 가장 먼저 Shiboken 선로딩 가드 ----------
    _early_shiboken_preload()

    # ---------- (2) DEV/FROZEN 모드에 따라 Qt 플러그인 경로 설정 ----------
    try:
        is_frozen = bool(getattr(sys, "frozen", False))
    except Exception:
        is_frozen = False

    qt_plugins: Path | None = None
    base: Path | None = None

    if is_frozen:
        try:
            exe_dir = Path(sys.executable).resolve().parent
        except Exception:
            exe_dir = Path(os.getcwd()).resolve()
        base = exe_dir
        qt_plugins = base / "PySide6" / "qt-plugins"
        if not qt_plugins.exists():
            alt = base / "PySide6" / "plugins"
            if alt.exists():
                qt_plugins = alt
    else:
        # DEV: site-packages 내 PySide6 위치에서 plugins 찾기
        try:
            import PySide6  # 위치 확인만 (실패해도 치명 아님)
            site_pyside = Path(PySide6.__file__).resolve().parent
        except Exception:
            site_pyside = Path(sys.executable).resolve().parent
        base = site_pyside
        for cand in (site_pyside / "plugins", site_pyside / "Qt" / "plugins", site_pyside / "qt-plugins"):
            if cand.exists():
                qt_plugins = cand
                break
        if qt_plugins is None:
            qt_plugins = site_pyside / "plugins"  # 존재하지 않을 수도 있지만 기록용

    platforms = qt_plugins / "platforms" if qt_plugins is not None else None

    # 존재하는 경로에만 세팅
    os.environ.pop("QT_PLUGIN_PATH", None)
    if platforms and platforms.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms)
    os.environ.setdefault("PYSIDE_DISABLE_INTERNAL_QT_CONF", "1")
    # 필요 시 외부에서 QT_DEBUG_PLUGINS=1 설정

    log(f"MODE: {'FROZEN' if is_frozen else 'DEV'}")
    log(f"RESOLVED base={base}")
    log(f"QT_PLUGINS={qt_plugins} exists={qt_plugins.exists() if qt_plugins else False}")
    log(f"QT_PLATFORMS={platforms} exists={platforms.exists() if platforms else False}")

    # DLL 검색 경로 보강(존재할 때만)
    if hasattr(os, "add_dll_directory"):
        for p in filter(None, {
            base,
            base / "PySide6" if base else None,
            base / "PySide6" / "Qt" / "bin" if base else None,
            qt_plugins,
            platforms,
        }):
            try:
                if p.exists():
                    os.add_dll_directory(str(p))
                    log(f"add_dll_directory: {p}")
            except Exception as e:
                log(f"add_dll_directory failed: {p} :: {e!r}")

    # 진단용 덤프
    log("sys.path:")
    for p in sys.path:
        try:
            log(f"  - {p}")
        except Exception:
            pass
    log("env (filtered):")
    for k in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH", "PYSIDE_DISABLE_INTERNAL_QT_CONF", "QT_DEBUG_PLUGINS", "PATH"):
        v = os.environ.get(k)
        if v:
            log(f"  {k}={v}")

if __name__ == "__main__":
    install()
