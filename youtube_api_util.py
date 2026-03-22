# youtube_api_util.py — YouTube Data API v3 helper (키 저장/검증/검색/정보 수집)
import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Dict, Tuple, Optional

import httplib2
import certifi

from app_paths import app_support_dir
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError, UnknownApiNameOrVersion

# exe 환경에서 httplib2가 certifi 번들을 사용하도록 강제
os.environ.setdefault("HTTPLIB2_CA_CERTS", certifi.where())

# 저장 위치: 라이선스와 동일 폴더 체계 재사용
APP_DIR = app_support_dir()
API_KEY_PATH = APP_DIR / "youtube_api_key.txt"

# -------- 파일 I/O --------
def save_api_key_to_disk(key: str) -> str:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with API_KEY_PATH.open("w", encoding="utf-8") as f:
        f.write((key or "").strip())
    return str(API_KEY_PATH)

def peek_effective_key() -> Optional[str]:
    k = os.environ.get("YT_API_KEY")
    if k:
        return k.strip()
    try:
        with API_KEY_PATH.open("r", encoding="utf-8") as f:
            t = f.read().strip()
            return t or None
    except Exception:
        return None

def api_key_info() -> Dict[str, str]:
    k = peek_effective_key()
    if not k:
        return {"found": "0"}
    masked = (k[:4] + "*" * max(0, len(k) - 8) + k[-4:]) if len(k) >= 8 else "********"
    return {"found": "1", "location": str(API_KEY_PATH), "masked": masked}

# -------- 클라이언트 --------
def _client(key: Optional[str] = None):
    """
    Google API 클라이언트를 반환.
    exe 환경에서 Discovery 로딩이 SSL/인증서 문제로 깨질 수 있으므로 httplib2 + certifi를 사용.
    cache_discovery=False 로 Discovery 캐시 사용을 비활성화하여 exe 배포 환경의 캐시 이슈를 회피.
    """
    key = key or peek_effective_key()
    if not key:
        raise RuntimeError("YouTube API 키가 없습니다.")

    insecure = os.environ.get("UC_INSECURE_SSL", "0") == "1"  # 개발/프록시용 플래그
    if insecure:
        http = httplib2.Http(timeout=15, disable_ssl_certificate_validation=True)
    else:
        http = httplib2.Http(timeout=15, ca_certs=certifi.where())

    # Discovery 캐시를 사용하지 않도록 cache_discovery=False 설정 (exe 환경 안정화)
    return build("youtube", "v3", developerKey=key, http=http, cache_discovery=False)

def validate_api_key(key: str) -> Tuple[bool, str]:
    """
    키 유효성 체크.
    True, "" 이면 유효. False, 메시지 이면 실패 원인(간단 문구)
    """
    try:
        yt = _client(key)  # Discovery 로딩 시도
        yt.search().list(part="id", q="test", maxResults=1, type="video").execute()
        return True, ""
    except UnknownApiNameOrVersion:
        # Discovery 문서 로딩 자체가 실패한 경우 (네트워크/SSL/방화벽 이슈)
        return False, (
            "YouTube 서비스 정의(Discovery) 로딩에 실패했습니다.\n"
            "네트워크/방화벽/SSL 인증서 환경을 확인해 주세요."
        )
    except HttpError as e:
        try:
            data = e.error_details if hasattr(e, "error_details") else e._get_reason()
        except Exception:
            data = str(e)
        return False, str(data)
    except Exception as e:
        return False, str(e)

# -------- 검색 --------
def search_video_ids(query: str, max_results: int = 50) -> List[str]:
    """
    query로 검색하여 video id 리스트 반환 (최대 max_results).
    pageToken을 따라가며 최대 max_results 개수만큼 수집.
    """
    yt = _client()
    region = os.environ.get("UC_SEARCH_REGION")  # 예: "KR", "US"
    lang   = os.environ.get("UC_SEARCH_LANG")    # 예: "ko", "en"

    ids: List[str] = []
    token = None
    while len(ids) < max_results:
        try:
            req = yt.search().list(
                part="id",
                q=query,
                type="video",
                maxResults=min(50, max_results - len(ids)),
                pageToken=token or None,
                regionCode=region or None,
                relevanceLanguage=lang or None,
                safeSearch="none",
                videoEmbeddable="any",
            )
            resp = req.execute()
        except HttpError:
            # 호출자(상위)에서 예외 처리하도록 재발생
            raise
        items = resp.get("items") or []
        for it in items:
            vid = (it.get("id") or {}).get("videoId")
            if vid:
                ids.append(vid)
        token = resp.get("nextPageToken")
        if not token:
            break
    return ids

# -------- 도우미 --------
def _parse_iso8601_duration(d: str) -> int:
    # PT#H#M#S 형식 -> 초
    if not d or not d.startswith("P"):
        return 0
    h = m = s = 0
    mobj = re.match(r"^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", d)
    if mobj:
        if mobj.group(1): h = int(mobj.group(1))
        if mobj.group(2): m = int(mobj.group(2))
        if mobj.group(3): s = int(mobj.group(3))
    return h*3600 + m*60 + s

def _dt_to_local_str(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""

# -------- 세부 정보 반복자 --------
def iter_videos_info(ids: List[str]) -> Generator[Dict, None, None]:
    """
    반환 dict 키:
    thumbnail, title, video_link, channel, channel_link,
    views, likes, comments, subscribers, upload_date, duration_sec, is_shorts, form
    """
    if not ids:
        return
    yt = _client()

    # 50개씩 배치 처리
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        vresp = yt.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(batch)
        ).execute()

        videos = vresp.get("items") or []
        # 채널 ID 수집: 채널별 구독자 조회를 위해
        ch_ids = []
        for v in videos:
            snip = v.get("snippet") or {}
            ch_id = snip.get("channelId")
            if ch_id:
                ch_ids.append(ch_id)
        ch_ids = list(dict.fromkeys(ch_ids))  # 고유화(순서 유지)

        subs_map: Dict[str, int] = {}
        if ch_ids:
            cresp = yt.channels().list(
                part="statistics",
                id=",".join(ch_ids)
            ).execute()
            for c in (cresp.get("items") or []):
                cid = c.get("id")
                st  = c.get("statistics") or {}
                subs_map[cid] = int(st.get("subscriberCount") or 0)

        for v in videos:
            vid = v.get("id") or ""
            snip = v.get("snippet") or {}
            stat = v.get("statistics") or {}
            cont = v.get("contentDetails") or {}

            title = snip.get("title") or ""
            ch_title = snip.get("channelTitle") or ""
            ch_id = snip.get("channelId") or ""
            channel_link = f"https://www.youtube.com/channel/{ch_id}" if ch_id else ""
            video_link = f"https://www.youtube.com/watch?v={vid}" if vid else ""
            thumb = (snip.get("thumbnails") or {}).get("medium") or {}
            thumbnail = thumb.get("url") or f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"

            views = int(stat.get("viewCount") or 0)
            likes = int(stat.get("likeCount") or 0)        # API가 제공하는 경우만
            comments = int(stat.get("commentCount") or 0)  # 댓글이 막힌 경우 0/없음

            upload_date = _dt_to_local_str(snip.get("publishedAt") or "")
            dur_sec = _parse_iso8601_duration(cont.get("duration") or "")
            is_shorts = bool(dur_sec and dur_sec <= 61)
            form = "숏폼" if is_shorts else "롱폼"

            subs = subs_map.get(ch_id, 0)

            yield {
                "thumbnail": thumbnail,
                "title": title,
                "video_link": video_link,
                "channel": ch_title,
                "channel_link": channel_link,
                "views": views,
                "likes": likes,
                "comments": comments,
                "subscribers": subs,
                "upload_date": upload_date,
                "duration_sec": dur_sec,
                "is_shorts": is_shorts,
                "form": form,
            }
