# pytube_util.py
import os, re, time, random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from yt_dlp import YoutubeDL
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

# --- 검색/상세 추출 옵션(빠르고 안정적으로) ---
YDL_SEARCH = {
    "quiet": True, "skip_download": True, "extract_flat": True,
    "noplaylist": True, "socket_timeout": 10,
}
YDL_DETAIL = {
    "quiet": True, "skip_download": True, "noplaylist": True,
    "socket_timeout": 10,
}

# 병렬 스레드 수 (기본 12, 필요 시 환경변수로 조절: YT_META_WORKERS=20)
MAX_WORKERS = int(os.environ.get("YT_META_WORKERS", "12"))

# 자막 캐시(다시 보기 초고속)
CACHE_DIR = os.path.join(
    os.getenv("LOCALAPPDATA") or os.path.expanduser("~"),
    "OneInsight", "UnifiedCrawler", "cache", "transcripts"
)
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://www.youtube.com/",
}

def _is_video_id(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z_-]{11}", s or ""))

def get_caption_for_url(video_url: str, allow_non_ko: bool = True) -> str:
    """
    Transcript API만 사용. 한국어 우선, 없으면 번역.
    cookies.txt 자동 적용(제한 영상 대비). 캐시 저장.
    실패 시 이유 마커도 반환.
    """
    vid = _extract_id_from_url(video_url or "")
    if not vid:
        return "[NO_ID]"
    # 캐시
    cp = _cache_path(vid)
    try:
        if os.path.exists(cp):
            with open(cp, "r", encoding="utf-8") as f:
                cached = f.read()
                if cached:
                    return cached
    except Exception:
        pass

    cookies_txt = _load_cookies_text()

    try:
        # 1) 한국어/자동한국어
        try:
            segs = YouTubeTranscriptApi.get_transcript(
                vid, languages=['ko','ko-KR','a.ko'], cookies=cookies_txt
            )
        except (NoTranscriptFound, TranscriptsDisabled):
            segs = None

        # 2) 번역 폴백(영문/일본어/중국어 등 → ko)
        if not segs:
            tlist = YouTubeTranscriptApi.list_transcripts(vid, cookies=cookies_txt)
            order = [
                # (생성여부무관, 대상 언어들)
                (False, ['en','en-US','en-GB']),
                (False, ['ja']),
                (False, ['zh-Hans','zh-Hant','zh']),
                (False, ['es','es-419']),
            ]
            got = None
            # 수동 자막 우선 번역
            for _, langs in order:
                try:
                    tr = tlist.find_transcript(langs)
                    try:
                        got = tr.translate('ko').fetch()
                    except Exception:
                        if allow_non_ko:
                            got = tr.fetch()
                    if got: break
                except Exception:
                    continue
            # 그래도 없으면 자동 자막 번역
            if not got:
                for _, langs in order:
                    try:
                        tr = tlist.find_generated_transcript(langs)
                        try:
                            got = tr.translate('ko').fetch()
                        except Exception:
                            if allow_non_ko:
                                got = tr.fetch()
                        if got: break
                    except Exception:
                        continue
            segs = got

        if not segs:
            text = "(자막 없음)"  # 진짜 없는 케이스
        else:
            text = "\n".join(s.get('text','') for s in segs if s.get('text','').strip())

    except Exception as e:
        # 자동화 차단/권한/네트워크 등
        msg = str(e)
        if "Too Many Requests" in msg or "429" in msg:
            text = "[COOLDOWN:429]"
        elif "Forbidden" in msg or "403" in msg:
            text = "[FORBIDDEN:403]"
        else:
            text = "[ERROR] " + msg[:200]

    # 캐시 저장
    try:
        with open(cp, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    return text
def _load_cookies_text() -> str | None:
    """cookies.txt 내용 로드: ENV(YTDLP_COOKIES/ YT_COOKIES) → exe폴더 → 스크립트폴더 → CWD → 홈"""
    for env in ("YTDLP_COOKIES", "YT_COOKIES"):
        p = os.environ.get(env)
        if p and os.path.exists(p):
            try:
                return open(p, "r", encoding="utf-8").read()
            except Exception:
                pass
    bases = []
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None
    if exe_dir: bases.append(exe_dir)
    bases += [os.path.dirname(os.path.abspath(__file__)), os.getcwd(), os.path.expanduser("~")]
    for base in bases:
        for name in ("cookies.txt", "yt_cookies.txt"):
            path = os.path.join(base, name)
            if os.path.exists(path):
                try:
                    return open(path, "r", encoding="utf-8").read()
                except Exception:
                    pass
    return None

def _extract_id_from_url(url: str) -> str | None:
    # 더 강하게: shorts/embed/youtu.be/파라미터 등 모두 커버
    m = re.search(
        r'(?:v=|/shorts/|/embed/|youtu\.be/)([0-9A-Za-z_-]{11})',
        url
    )
    return m.group(1) if m else (url if _is_video_id(url) else None)


def _fmt_upload_date(ud):
    if not ud: return ""
    try:  return datetime.strptime(ud, "%Y%m%d").strftime("%Y-%m-%d 00:00:00")
    except: return str(ud)

def _build_row(info: dict):
    vid = info.get("id","")
    url = info.get("webpage_url") or (f"https://www.youtube.com/watch?v={vid}" if _is_video_id(vid) else "")
    thumb = info.get("thumbnail") or (f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if _is_video_id(vid) else "")
    return {
        "thumbnail": thumb,
        "title": info.get("title",""),
        "video_link": url,
        "channel": info.get("channel") or info.get("uploader",""),
        "channel_link": f"https://www.youtube.com/channel/{info.get('channel_id','')}" if info.get("channel_id") else "",
        "views": info.get("view_count") or 0,
        "subscribers": info.get("channel_follower_count") or 0,
        "upload_date": _fmt_upload_date(info.get("upload_date")),
        "caption": ""  # 검색 단계에서는 자막 미로딩(지연 로딩)
    }

def _extract_detail(ref: str) -> dict:
    """단건 상세(제목/조회수 등). 빠르게 하려고 경미한 지연+jitter."""
    time.sleep(random.uniform(0.02, 0.12))
    url = ref if str(ref).startswith("http") else f"https://www.youtube.com/watch?v={ref}"
    with YoutubeDL(YDL_DETAIL) as ydl:
        info = ydl.extract_info(url, download=False)
    return _build_row(info)

def get_keyword_videos(keyword: str, max_results: int = 50, with_captions: bool = False, **_ignored):
    """
    검색 → 영상ID만 선별 → 상세를 병렬로 빠르게 가져옴.
    기본 50개까지 한 번에 가능.
    """
    # 1) 검색(한 번 호출로 N개 받음)
    with YoutubeDL(YDL_SEARCH) as ydl:
        res = ydl.extract_info(f"ytsearch{max_results}:{keyword}", download=False)
    entries = (res or {}).get("entries") or []

    # 2) 영상 ID만 수집 (채널/플리 제거)
    ids = []
    for e in entries:
        vid = e.get("id") or ""
        if _is_video_id(vid):
            ids.append(vid)
        else:
            url = e.get("url") or ""
            m = re.search(r"v=([0-9A-Za-z_-]{11})", url)
            if m: ids.append(m.group(1))
        if len(ids) >= max_results: break
    if not ids: return []

    # 3) 상세를 병렬로(기본 12스레드; 필요 시 YT_META_WORKERS로 올리기)
    rows = []
    def worker(v):
        try:
            return _extract_detail(v)
        except Exception:
            # 실패해도 표는 채움
            return {
                "thumbnail": f"https://img.youtube.com/vi/{v}/hqdefault.jpg",
                "title": "(불러오기 실패)",
                "video_link": f"https://www.youtube.com/watch?v={v}",
                "channel": "", "channel_link": "",
                "views": 0, "subscribers": 0, "upload_date": "", "caption": ""
            }

    max_workers = min(MAX_WORKERS, len(ids))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for row in ex.map(worker, ids):
            rows.append(row)
    return rows

# -------------------- 자막: Transcript API 단일 경로 --------------------
def _cache_path(video_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{video_id}.txt")

def get_caption_for_url(video_url: str) -> str:
    """
    유튜브 Transcript API만 사용. 한국어 우선, 없으면 번역.
    디스크 캐시로 재요청 최소화.
    """
    vid = _extract_id_from_url(video_url)
    if not vid:
        return ""

    # 0) 캐시
    cp = _cache_path(vid)
    try:
        if os.path.exists(cp):
            with open(cp, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass

    text = ""
    try:
        # 1) 한국어/자동한국어 우선
        try:
            segs = YouTubeTranscriptApi.get_transcript(vid, languages=['ko', 'a.ko'])
        except (NoTranscriptFound, TranscriptsDisabled):
            segs = None

        # 2) 없다면 다른 언어 → 한국어로 번역
        if not segs:
            tlist = YouTubeTranscriptApi.list_transcripts(vid)
            # 수동 자막 먼저 번역 시도
            for tr in tlist:
                if not getattr(tr, "is_generated", False):
                    try:
                        segs = tr.translate('ko').fetch(); break
                    except Exception:
                        pass
            # 그래도 없으면 자동 자막 번역
            if not segs:
                for tr in tlist:
                    try:
                        segs = tr.translate('ko').fetch(); break
                    except Exception:
                        pass

        if segs:
            text = "\n".join(s.get('text','') for s in segs if s.get('text','').strip())
    except Exception:
        text = ""

    # 3) 캐시 저장
    try:
        with open(cp, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    return text
