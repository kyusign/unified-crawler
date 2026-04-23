# YouTubeCollector macOS 사용자 실행 설명서

이 문서는 사용자가 `YouTubeCollector`를 macOS에서 처음 실행할 때 따라 하면 되는 순서입니다.

## 1. 먼저 내 맥 종류 확인하기

배포 파일은 맥 종류에 따라 2개로 나뉩니다.

- M1/M2/M3/M4 맥: `YouTubeCollector-macos-arm64.zip`
- Intel 맥: `YouTubeCollector-macos-x86_64.zip`

내 맥 종류 확인 방법:

1. 맥 화면 왼쪽 위의 `Apple 로고`를 클릭합니다.
2. 메뉴에서 `이 Mac에 관하여`를 클릭합니다.
3. 새 창에서 `칩` 또는 `프로세서` 항목을 확인합니다.
4. `칩: Apple M1`, `Apple M2`, `Apple M3`, `Apple M4`처럼 보이면 `Apple Silicon` 맥입니다. 이 경우 `YouTubeCollector-macos-arm64.zip`을 사용합니다.
5. `프로세서: Intel ...`처럼 보이면 `Intel` 맥입니다. 이 경우 `YouTubeCollector-macos-x86_64.zip`을 사용합니다.

정리:

```text
칩에 Apple M1/M2/M3/M4 표시됨  -> YouTubeCollector-macos-arm64.zip
프로세서에 Intel 표시됨        -> YouTubeCollector-macos-x86_64.zip
```

## 2. zip 파일을 어디에 두고 압축 해제하나요?

가장 쉬운 방법은 `다운로드` 폴더에서 진행하는 것입니다.

1. 받은 zip 파일을 맥의 `다운로드` 폴더에 둡니다.
2. Finder를 엽니다.
3. 왼쪽 메뉴에서 `다운로드`를 클릭합니다.
4. 받은 파일을 찾습니다.
5. 파일 이름은 아래 둘 중 하나입니다.

```text
YouTubeCollector-macos-arm64.zip
YouTubeCollector-macos-x86_64.zip
```

6. zip 파일을 더블클릭합니다.
7. 압축이 풀리면 같은 `다운로드` 폴더 안에 `YouTubeCollector.app`가 생깁니다.

주의: Windows에서 zip을 풀었다가 다시 압축하지 마세요. macOS 앱 실행 권한이나 앱 구조가 깨질 수 있습니다. 사용자는 반드시 맥에서 zip을 직접 압축 해제해야 합니다.

## 3. 앱을 응용 프로그램 폴더로 이동하기

압축 해제 후 바로 실행해도 되지만, 사용자가 계속 쓸 앱이면 `응용 프로그램` 폴더로 옮기는 것이 좋습니다.

1. Finder에서 `다운로드` 폴더를 엽니다.
2. `YouTubeCollector.app`를 찾습니다.
3. Finder 왼쪽 메뉴에서 `응용 프로그램`을 찾습니다.
4. `YouTubeCollector.app`를 마우스로 잡고 `응용 프로그램`으로 끌어다 놓습니다.
5. 이동이 끝나면 왼쪽 메뉴의 `응용 프로그램`을 클릭합니다.
6. `YouTubeCollector.app`가 보이는지 확인합니다.

만약 Finder 왼쪽 메뉴에 `응용 프로그램`이 안 보이면:

1. Finder 상단 메뉴에서 `이동`을 클릭합니다.
2. `응용 프로그램`을 클릭합니다.
3. 열린 폴더로 `YouTubeCollector.app`를 끌어다 놓습니다.

## 4. 앱 처음 실행하기

1. Finder를 엽니다.
2. 왼쪽 메뉴에서 `응용 프로그램`을 클릭합니다.
3. `YouTubeCollector.app`를 찾습니다.
4. 처음에는 더블클릭하지 말고, `YouTubeCollector.app`를 오른쪽 클릭합니다.
5. 메뉴에서 `열기`를 클릭합니다.
6. 확인 창이 뜨면 다시 `열기`를 클릭합니다.

처음 실행은 `오른쪽 클릭 > 열기`로 하는 것이 좋습니다. macOS가 인터넷에서 받은 앱을 더블클릭 실행보다 엄격하게 막는 경우가 있기 때문입니다.

## 5. 보안 경고가 나올 때

현재 앱은 내부 배포용 빌드입니다. Apple Developer ID 서명과 notarization이 적용되지 않았기 때문에 macOS 보안 경고가 나올 수 있습니다.

경고가 나올 때 실행 허용 방법:

1. `YouTubeCollector.app`를 실행합니다.
2. `확인되지 않은 개발자` 또는 `열 수 없음` 같은 경고가 나오면 창을 닫습니다.
3. 화면 왼쪽 위 `Apple 로고`를 클릭합니다.
4. `시스템 설정`을 클릭합니다.
5. 왼쪽 메뉴에서 `개인정보 보호 및 보안`을 클릭합니다.
6. 아래쪽 `보안` 영역을 찾습니다.
7. `YouTubeCollector.app 사용이 차단되었습니다` 같은 문구 옆의 `그래도 열기` 또는 `열기` 버튼을 클릭합니다.
8. 맥 로그인 암호를 입력하라는 창이 나오면 암호를 입력합니다.
9. 다시 확인 창이 나오면 `열기`를 클릭합니다.

이 과정을 한 번만 하면 다음부터는 보통 더블클릭으로 실행할 수 있습니다.

## 6. 앱에서 API 키 입력하기

앱이 열리면 YouTube Data API 키를 입력해야 검색이 됩니다.

1. 앱 상단의 `API 키` 버튼을 클릭합니다.
2. YouTube Data API 키를 입력합니다.
3. `검증` 버튼이 있으면 눌러서 키가 정상인지 확인합니다.
4. `저장` 버튼을 클릭합니다.
5. 창을 닫고 검색 화면으로 돌아갑니다.

API 키는 아래 위치에 저장됩니다.

```text
~/Library/Application Support/YouTubeCollector/youtube_api_key.txt
```

## 7. 검색하고 결과 저장하기

1. `검색어` 칸에 찾고 싶은 키워드를 입력합니다.
2. `개수` 칸에 가져올 영상 수를 입력합니다. 예: `50`
3. `검색` 버튼을 클릭합니다.
4. 결과 표에 영상 목록이 표시될 때까지 기다립니다.
5. 표에서 제목, 조회수, 좋아요, 댓글, 구독자 수, 업로드일, 영상 길이, 쇼츠 여부, 채널명, 링크를 확인합니다.
6. 영상 링크를 열고 싶으면 결과 표의 링크 칸을 더블클릭합니다.
7. 결과를 저장하려면 `엑셀 저장` 또는 `HTML 저장`을 클릭합니다.
8. 저장 위치를 선택하고 저장합니다.

## 8. 사용자가 받을 안내문 예시

아래 문구를 그대로 사용자에게 보내면 됩니다.

```text
맥 종류에 맞는 파일을 받으세요.

- M1/M2/M3/M4 맥: YouTubeCollector-macos-arm64.zip
- Intel 맥: YouTubeCollector-macos-x86_64.zip

맥 종류 확인 방법:
Apple 로고 > 이 Mac에 관하여를 누르세요.
칩에 Apple M1/M2/M3/M4가 나오면 arm64 파일을 받으면 됩니다.
프로세서에 Intel이 나오면 x86_64 파일을 받으면 됩니다.

실행 방법:
1. zip 파일을 다운로드 폴더에 둡니다.
2. zip 파일을 더블클릭해서 압축을 풉니다.
3. 나온 YouTubeCollector.app를 응용 프로그램 폴더로 옮깁니다.
4. 응용 프로그램 폴더에서 YouTubeCollector.app를 오른쪽 클릭합니다.
5. 열기를 누릅니다.
6. 보안 경고가 나오면 시스템 설정 > 개인정보 보호 및 보안에서 그래도 열기를 누릅니다.
7. 앱이 열리면 API 키 버튼을 눌러 YouTube Data API 키를 입력합니다.
8. 검색어와 개수를 입력하고 검색을 누릅니다.
```

## 9. 문제 해결

앱이 열리지 않을 때:

- zip 파일을 macOS에서 직접 압축 해제했는지 확인합니다.
- Windows에서 다시 압축한 파일은 사용하지 마세요.
- Apple Silicon 맥에는 `arm64` 파일을 사용했는지 확인합니다.
- Intel 맥에는 `x86_64` 파일을 사용했는지 확인합니다.
- 처음 실행은 더블클릭이 아니라 `오른쪽 클릭 > 열기`로 시도합니다.
- 그래도 안 되면 `시스템 설정 > 개인정보 보호 및 보안 > 그래도 열기`를 확인합니다.

검색이 실패할 때:

- API 키를 입력했는지 확인합니다.
- Google Cloud에서 `YouTube Data API v3`가 활성화되어 있는지 확인합니다.
- API 키 사용량 한도 또는 할당량이 초과되지 않았는지 확인합니다.
- 검색어를 바꿔서 다시 시도합니다.

로그 파일 위치:

```text
~/Library/Logs/YouTubeCollector/boot.log
```

## 참고 링크

- Apple 공식 안내: https://support.apple.com/guide/mac-help/mh40616/mac
- YouTube Data API 시작 안내: https://developers.google.com/youtube/v3/getting-started
- YouTube Data API Reference: https://developers.google.com/youtube/v3/docs
