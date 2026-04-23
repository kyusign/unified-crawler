# YouTubeCollector macOS build

Build the app on a Mac. PyInstaller does not produce a macOS `.app` from Windows.

## 1. Prepare Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

## 2. Install dependencies

```bash
python -m pip install -r requirements-app.txt
python -m pip install pyinstaller
```

## 3. Build the app

From the project root:

```bash
python packaging/build.py --onedir --clean --package-zip
```

Output:

- `dist/YouTubeCollector.app`
- `dist/YouTubeCollector.zip`

Optional one-file build:

```bash
python packaging/build.py --onefile --clean
```

## 4. First run locations

- API key file:
  - `~/Library/Application Support/YouTubeCollector/youtube_api_key.txt`
- Boot log:
  - `~/Library/Logs/YouTubeCollector/boot.log`

## Notes

- The app is now YouTube-only. Community crawling, Selenium, and ChromeDriver are not part of this build path.
- If Gatekeeper warns on first launch, allow the app from System Settings and run it again.

## GitHub Actions

The repository now includes [build-mac.yml](/c:/Users/yesun/mac_crawler 수정/.github/workflows/build-mac.yml).

- Push to `main` or start the workflow manually with `workflow_dispatch`.
- It builds two distributable zip files on GitHub-hosted macOS runners:
  - `YouTubeCollector-macos-arm64.zip`
  - `YouTubeCollector-macos-x86_64.zip`
- Those zip files are the files you hand to users.
- Each zip includes `YouTubeCollector.app` and `사용설명서_YouTubeCollector.md`.
- After a user unzips on macOS, they can move `YouTubeCollector.app` to Applications and run it.
