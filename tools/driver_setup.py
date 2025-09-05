import os, json, sys
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

VENDOR = "OneInsight"
APP = "UnifiedCrawler"


def _ensure_dirs():
    progdata = os.getenv("PROGRAMDATA") or "/usr/local/share"
    base = os.path.join(progdata, VENDOR, APP)
    os.makedirs(base, exist_ok=True)
    drivers_dir = os.path.join(base, "drivers")
    os.makedirs(drivers_dir, exist_ok=True)
    return base, drivers_dir


def main():
    print("ChromeDriver 설치/업데이트를 시작합니다...")
    base, drivers_dir = _ensure_dirs()
    path = ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install()
    print(f"다운로드 완료: {path}")
    driver_json = os.path.join(base, "driver_path.json")
    with open(driver_json, "w", encoding="utf-8") as f:
        json.dump({"chromedriver_path": path}, f, ensure_ascii=False, indent=2)
    print(f"경로 기록: {driver_json}")
    print("\n환경변수로 지정하려면:")
    print(f"  Windows: setx CHROMEDRIVER_PATH \"{path}\"")
    print(f"  PowerShell: [Environment]::SetEnvironmentVariable('CHROMEDRIVER_PATH','{path}','User')")
    print("\n완료되었습니다.")


if __name__ == "__main__":
    sys.exit(main())
