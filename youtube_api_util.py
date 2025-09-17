# youtube_api_util.py — requests 기반 YouTube Data API v3 클라이언트 + API 키 관리/검증 UI 연동
# 필요: requests (pip install requests)
from __future__ import annotations
import os, time, random, logging, re
from typing import List, Dict, Generator, Optional, Tuple
import requests

logger = logging.getLogger("ytcrawl")

# ====== 옵션 ======
FAST_MODE        = os.environ.get("UC_FAST", "0") == "1"
SKIP_SUBSCRIBERS = FAST_MODE or (os.environ.get("UC_SKIP_SUBSCRIBERS", "0") == "1")

_default_min = 0.0 if FAST_MODE else 0.02
_default_max = 0.0 if FAST_MODE else 0.07
RATE_MIN = float(os.environ.get("UC_RATE_MIN", str(_default_min)))
RATE_MAX = float(os.environ.get("UC_RATE_MAX", str(_default_max)))

SEARCH_REGION = os.environ.get("UC_SEARCH_REGION", "KR")
SEARCH_LANG   = os.environ.get("UC_SEARCH_LANG", "ko")

HTTP_TIMEOUT = 10

# ====== HTTP 세션 ======
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CommunityCrawler/1.0 (+local)",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
})

# ====== 키 저장 위치 ======
def _app_dir() -> str:
    return os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "CommunityCrawler")

def _default_key_path() -> str:
    # 앱 디렉터리 권장 위치
    return os.path.join(_app_dir(), "youtube_api_key.txt")

# ====== 내부 상태 ======
_API_KEY: Optional[str] = None           # 런타임에서 set_runtime_api_key()로 넣은 키
_API_KEY_SOURCE: Optional[str] = None    # "runtime" | "env:UC_YT_API_KEY" | "env:YT_API_KEY" | f"file:{path}"

_BASE = "https://www.googleapis.com/youtube/v3"

# ====== 유틸 ======
def _rate_sleep():
    if RATE_MAX <= 0: return
    lo = min(RATE_MIN, RATE_MAX); hi = max(RATE_MIN, RATE_MAX)
    time.sleep(lo + random.random() * (hi - lo))

def _parse_iso8601_duration(dur: str) -> int:
    if not dur or not isinstance(dur, str):
        return 0
    days = 0
    m = re.match(r"^P(?:(\d+)D)?(?:T.*)?$", dur)
    if m and m.group(1): days = int(m.group(1))
    tm = re.search(r"T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", dur)
    h = int(tm.group(1)) if tm and tm.group(1) else 0
    m_ = int(tm.group(2)) if tm and tm.group(2) else 0
    s = int(tm.group(3)) if tm and tm.group(3) else 0
    return days * 86400 + h * 3600 + m_ * 60 + s

def _safe_int(x, default=0):
    try:
        if x is None: return default
        if isinstance(x, (int, float)): return int(x)
        s = str(x).replace(",", "").strip()
        return int(float(s))
    except Exception:
        return default

def _handle_api_error(resp: requests.Response):
    try:
        data = resp.json()
        err = data.get("error", {})
        msg = err.get("message") or str(data)
        reason = None
        if "errors" in err and isinstance(err["errors"], list) and err["errors"]:
            reason = err["errors"][0].get("reason")
        return msg, reason
    except Exception:
        return resp.text, None

# ====== API 키 로드/설정/저장 ======
def peek_effective_key() -> Optional[str]:
    """
    예외 없이 '있으면' 키 문자열을 반환. (런타임 > env > 파일 경로 순으로 탐색)
    """
    # 1) runtime
    if _API_KEY:
        return _API_KEY
    # 2) env
    for env in ("UC_YT_API_KEY", "YT_API_KEY"):
        v = os.environ.get(env)
        if v and v.strip():
            return v.strip()
    # 3) file: 우선순위 — CWD/youtube_api_key.txt, 앱 디렉터리, 홈
    candidates = [
        os.path.join(os.getcwd(), "youtube_api_key.txt"),
        _default_key_path(),
        os.path.join(os.path.expanduser("~"), "youtube_api_key.txt"),
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                t = open(p, "r", encoding="utf-8").read().strip()
                if t:
                    return t
        except Exception:
            pass
    return None

def api_key_info() -> Dict[str, str]:
    """
    현재 유효한 키가 어디에서 감지되는지 설명용 정보 반환.
    """
    # runtime
    if _API_KEY:
        return {"found": "1", "source": "runtime", "location": "(메모리)", "masked": _mask_key(_API_KEY)}
    # env
    for env in ("UC_YT_API_KEY", "YT_API_KEY"):
        v = os.environ.get(env)
        if v and v.strip():
            return {"found": "1", "source": f"env:{env}", "location": "(환경변수)", "masked": _mask_key(v.strip())}
    # file
    candidates = [
        os.path.join(os.getcwd(), "youtube_api_key.txt"),
        _default_key_path(),
        os.path.join(os.path.expanduser("~"), "youtube_api_key.txt"),
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                t = open(p, "r", encoding="utf-8").read().strip()
                if t:
                    return {"found": "1", "source": "file", "location": p, "masked": _mask_key(t)}
        except Exception:
            pass
    return {"found": "0", "source": "", "location": "", "masked": ""}

def _mask_key(k: str) -> str:
    k = k.strip()
    if len(k) <= 8: return "*" * len(k)
    return k[:4] + "*" * (len(k)-8) + k[-4:]

def set_runtime_api_key(key: str):
    """
    앱 실행 중 메모리에 키를 설정(우선순위 1위). 저장은 별도 save_api_key_to_disk() 호출.
    """
    global _API_KEY, _API_KEY_SOURCE
    _API_KEY = (key or "").strip() or None
    _API_KEY_SOURCE = "runtime" if _API_KEY else None

def save_api_key_to_disk(key: str) -> str:
    """
    키를 앱 디렉터리에 youtube_api_key.txt로 저장하고, 런타임 키도 갱신.
    """
    key = (key or "").strip()
    if not key:
        raise ValueError("빈 키는 저장할 수 없습니다.")
    path = _default_key_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    set_runtime_api_key(key)
    return path

def delete_saved_api_key_file() -> bool:
    """
    앱 디렉터리의 youtube_api_key.txt를 삭제(있으면).
    """
    path = _default_key_path()
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False

def _get_api_key_or_raise() -> str:
    """
    실제 API 호출 시 사용. 없으면 친절한 에러로 raise.
    우선순위: runtime > env > file
    """
    global _API_KEY, _API_KEY_SOURCE
    if _API_KEY:
        return _API_KEY
    # env
    for env in ("UC_YT_API_KEY", "YT_API_KEY"):
        v = os.environ.get(env)
        if v and v.strip():
            _API_KEY = v.strip()
            _API_KEY_SOURCE = f"env:{env}"
            return _API_KEY
    # file
    k = peek_effective_key()
    if k:
        _API_KEY = k
        _API_KEY_SOURCE = "file"
        return _API_KEY
    raise RuntimeError(
        "YouTube API 키가 설정되지 않았습니다.\n"
        "메뉴에서 [API 키 설정]을 눌러 키를 입력/저장하거나,\n"
        "환경변수 UC_YT_API_KEY / YT_API_KEY를 설정하세요."
    )

# ====== HTTP 호출 ======
def _request_with_key(path: str, params: dict, key: str, timeout: float = HTTP_TIMEOUT):
    url = f"{_BASE}/{path}"
    p = dict(params); p["key"] = key
    r = SESSION.get(url, params=p, timeout=timeout)
    return r

def _request_with_retry(path: str, params: dict, max_retries: int = 4):
    url = f"{_BASE}/{path}"
    params = dict(params)
    params["key"] = _get_api_key_or_raise()
    backoff = 0.5
    for attempt in range(max_retries):
        try:
            _rate_sleep()
            r = SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            else:
                msg, reason = _handle_api_error(r)
                if reason in ("quotaExceeded","dailyLimitExceeded","rateLimitExceeded") or "quota" in (msg or "").lower():
                    raise RuntimeError(f"YouTube API 쿼터 오류: {msg}")
                if 500 <= r.status_code < 600:
                    time.sleep(backoff); backoff *= 1.8; continue
                raise RuntimeError(f"YouTube API 오류: {r.status_code} {msg}")
        except requests.exceptions.RequestException as e:
            time.sleep(backoff); backoff *= 1.8
            continue
    r = SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        msg, _ = _handle_api_error(r)
        raise RuntimeError(f"YouTube API 최종 실패: {r.status_code} {msg}")
    return r.json()

# ====== 공개: 키 검증 ======
def validate_api_key(key: str) -> Tuple[bool, str]:
    """
    주어진 키가 유효한지 *저비용*으로 검증.
    - videos.list(part=id&id=dQw4w9WgXcQ) 호출: 비용 1 유닛 수준
    """
    k = (key or "").strip()
    if not k:
        return False, "키가 비어 있습니다."
    try:
        r = _request_with_key("videos", {"part": "id", "id": "dQw4w9WgXcQ"}, k, timeout=7)
        if r.status_code == 200:
            return True, "정상"
        msg, reason = _handle_api_error(r)
        return False, f"{r.status_code} {msg}"
    except Exception as e:
        return False, str(e)

# ====== 공개: 검색/정보 ======
def search_video_ids(keyword: str, max_results: int) -> List[str]:
    ids: List[str] = []
    seen = set()
    page_token = None
    while len(ids) < max_results:
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "maxResults": min(50, max_results - len(ids)),
            "regionCode": SEARCH_REGION,
            "relevanceLanguage": SEARCH_LANG,
            "order": "relevance",
        }
        if page_token:
            params["pageToken"] = page_token
        res = _request_with_retry("search", params)
        for item in res.get("items", []):
            vid = (item.get("id") or {}).get("videoId", "")
            if vid and vid not in seen:
                seen.add(vid); ids.append(vid)
                if len(ids) >= max_results: break
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return ids

def iter_videos_info(video_ids: List[str]) -> Generator[dict, None, None]:
    if not video_ids: return
    ch_stats: Dict[str, int] = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(chunk),
            "maxResults": len(chunk),
        }
        res = _request_with_retry("videos", params)
        items = res.get("items", [])

        # channel stats
        ch_ids = []
        for it in items:
            ch = (it.get("snippet") or {}).get("channelId", "")
            if ch and ch not in ch_stats and ch not in ch_ids:
                ch_ids.append(ch)

        if ch_ids and not SKIP_SUBSCRIBERS:
            for j in range(0, len(ch_ids), 50):
                cres = _request_with_retry("channels", {"part": "statistics", "id": ",".join(ch_ids[j:j+50])})
                for ch_item in cres.get("items", []):
                    cid = ch_item.get("id", "")
                    stats = ch_item.get("statistics") or {}
                    if stats.get("hiddenSubscriberCount"):
                        ch_stats[cid] = 0
                    else:
                        ch_stats[cid] = _safe_int(stats.get("subscriberCount"), 0)

        for it in items:
            vid = it.get("id") or ""
            sn = it.get("snippet") or {}
            cd = it.get("contentDetails") or {}
            st = it.get("statistics") or {}

            title = sn.get("title") or ""
            ch_name = sn.get("channelTitle") or ""
            ch_id = sn.get("channelId") or ""
            published_at = (sn.get("publishedAt") or "").replace("T", " ").replace("Z", "")
            duration = _parse_iso8601_duration(cd.get("duration") or "")
            views = _safe_int(st.get("viewCount"), 0)

            thumbs = sn.get("thumbnails") or {}
            thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
            if not thumb:
                thumb = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"

            subs = ch_stats.get(ch_id, 0) if not SKIP_SUBSCRIBERS else 0
            is_shorts = bool(duration and duration <= 61)

            info = {
                "thumbnail": thumb,
                "title": title,
                "video_link": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                "channel": ch_name,
                "channel_link": f"https://www.youtube.com/channel/{ch_id}" if ch_id else "",
                "views": views,
                "subscribers": subs,
                "upload_date": published_at,
                "caption": "",           # 정책상 제3자 자막 본문 제공 불가
                "duration_sec": duration,
                "is_shorts": is_shorts,
                "form": "숏폼" if is_shorts else "롱폼",
            }
            yield info
