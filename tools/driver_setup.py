# tools/driver_setup.py
import os, sys, json, shutil, stat
from pathlib import Path

def _programdata_base():
    # Windows: %PROGRAMDATA% (없으면 /usr/local/share)
    progdata = os.getenv("PROGRAMDATA") or "/usr/local/share"
    base = Path(progdata) / "OneInsight" / "UnifiedCrawler"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _copy_driver_to(base_dir: Path, src_path: str) -> str:
    drivers_dir = base_dir / "drivers"
    drivers_dir.mkdir(parents=True, exist_ok=True)
    # 파일명 결정
    exe_name = "chromedriver.exe" if os.name == "nt" else "chromedriver"
    dst = drivers_dir / exe_name

    # 기존 파일 있으면 지우기(권한 문제 대비)
    try:
        if dst.exists():
            dst.chmod(dst.stat().st_mode | stat.S_IWRITE)
            dst.unlink()
    except Exception:
        pass

    shutil.copy2(src_path, dst)
    try:
        # 실행권한 (윈도우는 무시)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR)
    except Exception:
        pass
    return str(dst)

def main():
    print("ChromeDriver 설치/업데이트를 시작합니다...")
    base_dir = _programdata_base()

    # 1) webdriver-manager 로 맞는 버전 다운로드
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        from webdriver_manager.core.os_manager import ChromeType
    except Exception:
        print("오류: webdriver-manager가 없습니다. 먼저 'pip install webdriver-manager'를 실행하세요.")
        sys.exit(1)

    # cache 재사용, 설치된 크롬에 맞춰 자동 선택
    driver_path = ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()
    print(f"- 다운로드 완료: {driver_path}")

    # 2) 표준 위치로 복사
    final_path = _copy_driver_to(base_dir, driver_path)
    print(f"- 배치 완료: {final_path}")

    # 3) driver_path.json 기록
    json_path = base_dir / "driver_path.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"chromedriver_path": final_path}, f, ensure_ascii=False, indent=2)
    print(f"- 경로 기록: {json_path}")

    print("\n[완료] 이제 '원초적인사이트 프로그램.exe'를 실행하세요.")
    print("문제 발생 시: 1) 크롬 업데이트 후 재실행  2) 관리자 권한으로 실행  3) 방화벽/프록시 확인")

if __name__ == "__main__":
    main()
