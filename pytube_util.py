# pytube_util.py  (speed-optimized)
# - pytube + playerResponse 우선, 부족하면 yt-dlp로 "필요한 항목만" 보강
# - yt-dlp 인스턴스는 스레드별(thread-local) 재사용
# - 네트워크 호출마다 짧은 랜덤 지연(환경변수로 조절 가능)
#   · UC_FAST=1                : 빠른 모드(자막/구독자 생략, 딜레이 최소화)
#   · UC_SKIP_CAPTION=1        : 자막 수집 생략
#   · UC_SKIP_SUBSCRIBERS=1    : 채널 구독자 수 생략
#   · UC_RATE_MIN / UC_RATE_MAX: 딜레이 범위(초), 기본 0.02 ~ 0.07

from pytube import YouTube, Search
import requests
import re
import os
import html
import json
import logging
import time
import random
import threading
from logging.handlers import RotatingFileHandler

try:
    from yt_dlp import YoutubeDL
except Exception:
    YoutubeDL = None

# ===================== 설정/로깅 =====================
LOG_PATH = "yt_debug.log"
logger = logging.getLogger("ytcrawl")

ENABLE_FILE_LOG    = os.environ.get("UC_FILE_LOG", "0") == "1"
ENABLE_CONSOLE_LOG = os.environ.get("UC_CONSOLE_LOG", "0") == "1"

FAST_MODE          = os.environ.get("UC_FAST", "0") == "1"
SKIP_CAPTION       = FAST_MODE or (os.environ.get("UC_SKIP_CAPTION", "0") == "1")
SKIP_SUBSCRIBERS   = FAST_MODE or (os.environ.get("UC_SKIP_SUBSCRIBERS", "0") == "1")

# 기본 딜레이(FAST면 더 짧게)
_default_min = 0.005 if FAST_MODE else 0.02
_default_max = 0.02  if FAST_MODE else 0.07
RATE_MIN = float(os.environ.get("UC_RATE_MIN", str(_default_min)))
RATE_MAX = float(os.environ.get("UC_RATE_MAX", str(_default_max)))

if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if ENABLE_FILE_LOG:
        try:
            _fh = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            _fh.setLevel(logging.DEBUG)
            _fh.setFormatter(_fmt)
            logger.addHandler(_fh)
        except Exception:
            pass
    if ENABLE_CONSOLE_LOG:
        _ch = logging.StreamHandler()
        _ch.setLevel(logging.INFO)
        _ch.setFormatter(_fmt)
        logger.addHandler(_ch)

def _rate_sleep():
    try:
        lo = min(RATE_MIN, RATE_MAX)
        hi = max(RATE_MIN, RATE_MAX)
        time.sleep(lo + random.random() * (hi - lo))
    except Exception:
        pass

# ===================== HTTP 세션 =====================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.cookies.set("CONSENT", "YES+cb.20210328-17-p0.en+FX+123")
SESSION.cookies.set("SOCS", "CAI")
HTTP_TIMEOUT = 7

# ===================== 보조 유틸 =====================
def extract_caption_text(xml_captions: str):
    if not xml_captions:
        return []
    p_tags = re.findall(r'<p[^>]*>(.*?)</p>', xml_captions, re.DOTALL)
    texts = []
    for p_content in p_tags:
        if not p_content.strip():
            continue
        if "<s" in p_content:
            s_texts = re.findall(r'<s[^>]*>(.*?)</s>', p_content, re.DOTALL)
            if s_texts:
                merged = "".join(s_texts)
                merged = re.sub(r"<br\s*/?>", "\n", merged)
                merged = re.sub(r"<[^>]+>", "", merged)
                merged = html.unescape(merged).strip()
                if merged:
                    texts.append(merged)
        else:
            clean_text = re.sub(r"<br\s*/?>", "\n", p_content)
            clean_text = re.sub(r"<[^>]+>", "", clean_text)
            clean_text = html.unescape(clean_text).strip()
            if clean_text:
                texts.append(clean_text)
    if not texts:
        text_tags = re.findall(r"<text[^>]*>(.*?)</text>", xml_captions, re.DOTALL)
        for t in text_tags:
            clean = re.sub(r"<br\s*/?>", "\n", t)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = html.unescape(clean).strip()
            if clean:
                texts.append(clean)
    return texts

def vtt_to_text(vtt: str) -> str:
    if not vtt:
        return ""
    lines = []
    for raw in vtt.splitlines():
        line = raw.strip("\ufeff").strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT") or line.startswith("NOTE") or " --> " in line:
            continue
        if re.fullmatch(r"\d{1,6}", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = html.unescape(line).strip()
        if line:
            lines.append(line)
    # 간단 중복 제거
    out, prev = [], None
    for l in lines:
        if l != prev:
            out.append(l)
        prev = l
    return "\n".join(out)

def _fetch(url: str, timeout: int = HTTP_TIMEOUT) -> str | None:
    try:
        _rate_sleep()
        r = SESSION.get(url, timeout=timeout)
        if r.ok and r.text:
            return r.text
    except Exception as e:
        logger.debug(f"[HTTP] GET 실패: {url} :: {e}")
    return None

def _extract_json_object(text: str, token: str) -> dict | None:
    try:
        i = text.find(token)
        if i < 0: return None
        j = text.find("{", i)
        if j < 0: return None
        depth = 0; in_str = False; esc = False
        for k, ch in enumerate(text[j:], start=j):
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
            else:
                if ch == '"': in_str = True
                elif ch == "{": depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[j:k+1])
    except Exception:
        pass
    return None

def _safe_int(x, default=0):
    try:
        if x is None: return default
        if isinstance(x, (int, float)): return int(x)
        s = str(x).replace(",", "").strip()
        return int(float(s))
    except Exception:
        return default

# ===================== 구독자 파싱/캐시 =====================
_CHANNEL_SUBS_CACHE: dict[str, int] = {}

def _parse_subs_text_to_int(text: str) -> int:
    if not text: return 0
    t = re.sub(r"[\s,]", "", text.strip())
    t = re.sub(r"^구독자", "", t); t = re.sub(r"명$", "", t)
    m = re.match(r"^([\d\.]+)([BMK])$", t, re.I)
    if m:
        val = float(m.group(1)); unit = m.group(2).upper()
        mult = 1_000_000_000 if unit == "B" else (1_000_000 if unit == "M" else 1_000)
        return int(val * mult)
    m = re.match(r"^([\d\.]+)(억|만|천)$", t)
    if m:
        val = float(m.group(1)); suf = m.group(2)
        mult = 100_000_000 if suf == "억" else (10_000 if suf == "만" else 1_000)
        return int(val * mult)
    m = re.search(r"(\d+)", t)
    return int(m.group(1)) if m else 0

def _extract_runs_text(obj: dict) -> str | None:
    if not isinstance(obj, dict): return None
    if obj.get("simpleText"): return obj["simpleText"]
    runs = obj.get("runs")
    if isinstance(runs, list):
        return "".join(str(x.get("text","")) for x in runs).strip() or None
    return None

def _extract_owner_subs_from_watch_data(data: dict) -> str | None:
    try:
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                vor = cur.get("videoOwnerRenderer")
                if isinstance(vor, dict):
                    t = _extract_runs_text(vor.get("subscriberCountText", {}))
                    if t: return t
                for v in cur.values():
                    if isinstance(v, (dict, list)): stack.append(v)
            elif isinstance(cur, list):
                for v in cur:
                    if isinstance(v, (dict, list)): stack.append(v)
    except Exception:
        pass
    return None

def _extract_handle_from_browse_endpoint(data: dict, channel_id: str) -> str | None:
    try:
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                be = cur.get("browseEndpoint")
                if isinstance(be, dict) and be.get("browseId") == channel_id:
                    h = be.get("canonicalBaseUrl")
                    if isinstance(h, str) and h.startswith("/@"): return h
                for v in cur.values():
                    if isinstance(v, (dict, list)): stack.append(v)
            elif isinstance(cur, list):
                for v in cur:
                    if isinstance(v, (dict, list)): stack.append(v)
    except Exception:
        pass
    return None

def _extract_subs_from_header_or_meta(data: dict) -> str | None:
    try:
        header = data.get("header", {})
        for key in ("c4TabbedHeaderRenderer","pageHeaderRenderer","interactiveTabbedHeaderRenderer"):
            hdr = header.get(key, {})
            t = _extract_runs_text(hdr.get("subscriberCountText", {}))
            if t: return t
        meta = data.get("metadata", {}).get("channelMetadataRenderer", {})
        t = _extract_runs_text(meta.get("subscriberCountText", {}))
        if t: return t
    except Exception:
        pass
    return None

def get_channel_subscribers(channel_id: str, hint_video_id: str | None = None) -> int:
    if SKIP_SUBSCRIBERS: return 0
    if not channel_id: return 0
    if channel_id in _CHANNEL_SUBS_CACHE: return _CHANNEL_SUBS_CACHE[channel_id]

    # WATCH 우선
    watch = f"https://www.youtube.com/watch?v={hint_video_id}&hl=ko&gl=KR&persist_hl=1&persist_gl=1" if hint_video_id else None
    if watch:
        html_text = _fetch(watch)
        data = _extract_json_object(html_text or "", "ytInitialData")
        if isinstance(data, dict):
            t = _extract_owner_subs_from_watch_data(data) or _extract_subs_from_header_or_meta(data)
            if t:
                subs = _parse_subs_text_to_int(t)
                _CHANNEL_SUBS_CACHE[channel_id] = subs
                return subs

    # 채널 루트/ABOUT
    base = f"https://www.youtube.com/channel/{channel_id}"
    for url in (
        f"{base}?hl=ko&gl=KR&persist_gl=1&persist_hl=1",
        f"{base}/about?hl=ko&gl=KR&persist_gl=1&persist_hl=1",
        f"{base}?hl=en&gl=US&persist_gl=1&persist_hl=1",
        f"{base}/about?hl=en&gl=US&persist_gl=1&persist_hl=1",
    ):
        html_text = _fetch(url)
        data = _extract_json_object(html_text or "", "ytInitialData")
        if isinstance(data, dict):
            t = _extract_subs_from_header_or_meta(data)
            if t:
                subs = _parse_subs_text_to_int(t)
                _CHANNEL_SUBS_CACHE[channel_id] = subs
                return subs

    _CHANNEL_SUBS_CACHE[channel_id] = 0
    return 0

# ===================== yt-dlp(스레드별 재사용) =====================
_YDL_LOCAL = threading.local()
_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "extract_flat": False,
    "cachedir": False,
    "http_headers": HEADERS,
    "writesubtitles": True,
    "writeautomaticsub": True,
    "subtitleslangs": ["ko","a.ko","en","a.en"],
    "subtitlesformat": "srv3/best",
}

def _get_ydl():
    if YoutubeDL is None:
        return None
    ydl = getattr(_YDL_LOCAL, "ydl", None)
    if ydl is None:
        ydl = YoutubeDL(_YDL_OPTS)
        _YDL_LOCAL.ydl = ydl
    return ydl

def _ydl_extract(video_url: str) -> dict | None:
    ydl = _get_ydl()
    if ydl is None:
        return None
    try:
        _rate_sleep()
        return ydl.extract_info(video_url, download=False)
    except Exception:
        return None

def _pick_caption_from_ydl(info: dict) -> tuple[str | None, str | None]:
    def _first(tracks: list[dict]):
        if not tracks: return None
        prefer = {"srv3":0,"ttml":1,"vtt":2}
        tracks = sorted(tracks, key=lambda t: prefer.get((t.get("ext") or "").lower(), 9))
        for t in tracks:
            url = t.get("url"); ext = (t.get("ext") or "").lower()
            if url: return url, ext or "srv3"
        return None

    sub = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    t = _first(sub.get("ko") or sub.get("ko-KR") or [])
    if t: return t[0], t[1]
    t = _first(auto.get("ko") or auto.get("ko-KR") or [])
    if t: return t[0], t[1]
    t = _first(sub.get("en") or sub.get("en-US") or [])
    if t: return (t[0] + ("&tlang=ko" if "tlang=" not in t[0] else "")), t[1]
    t = _first(auto.get("en") or auto.get("en-US") or [])
    if t: return (t[0] + ("&tlang=ko" if "tlang=" not in t[0] else "")), t[1]
    return None, None

def _fetch_caption_text(url: str, ext: str) -> str | None:
    try:
        _rate_sleep()
        r = SESSION.get(url, timeout=HTTP_TIMEOUT)
        if not (r.ok and r.text): return None
        txt = r.text
        ext = (ext or "").lower()
        if "srv3" in ext or "<p" in txt or "<text" in txt:
            lines = extract_caption_text(txt)
            return "\n".join(lines) if lines else ""
        return vtt_to_text(txt)
    except Exception:
        return None

# ===================== 메인: 비디오 정보 =====================
def get_video_info(video_id: str):
    video_url     = f"https://www.youtube.com/watch?v={video_id}"
    watch_url_qs  = f"{video_url}&hl=ko&gl=KR&persist_hl=1&persist_gl=1"
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    info = {
        "thumbnail": thumbnail_url,
        "title": "",
        "video_link": video_url,
        "channel": "",
        "channel_link": "",
        "views": 0,
        "subscribers": 0 if not SKIP_SUBSCRIBERS else 0,
        "upload_date": "",
        "caption": "" if SKIP_CAPTION else None,  # SKIP이면 즉시 빈 문자열
        "duration_sec": 0,
        "is_shorts": False,
        "form": "롱폼",
    }

    # 1) pytube 기반
    yt = None
    try:
        yt = YouTube(video_url)
    except Exception:
        yt = None

    if yt:
        try:
            if not info["title"]:
                try: info["title"] = yt.title or ""
                except Exception: pass
            if not info["channel"]:
                try: info["channel"] = yt.author or ""
                except Exception: pass
            if not info["channel_link"]:
                try:
                    cid = yt.channel_id or ""
                    if cid: info["channel_link"] = f"https://www.youtube.com/channel/{cid}"
                except Exception: pass
            if info["views"] in (None, 0):
                try: info["views"] = _safe_int(yt.views, 0)
                except Exception: pass
            if not info["upload_date"]:
                try:
                    if yt.publish_date:
                        info["upload_date"] = yt.publish_date.strftime("%Y-%m-%d %H:%M:%S")
                except Exception: pass
            if info["duration_sec"] in (None, 0):
                try: info["duration_sec"] = _safe_int(yt.length, 0)
                except Exception: pass
        except Exception:
            pass

    # 2) watch HTML / playerResponse 보강
    watch_html = getattr(yt, "watch_html", None) if yt else None
    if not watch_html:
        watch_html = _fetch(watch_url_qs)

    pr = _extract_json_object(watch_html or "", "ytInitialPlayerResponse") or {}
    if pr:
        try:
            vd = pr.get("videoDetails", {}) if isinstance(pr, dict) else {}
            micro = pr.get("microformat", {}).get("playerMicroformatRenderer", {})
            if not info["title"]:
                info["title"] = html.unescape(vd.get("title") or micro.get("title") or "")
            if not info["channel"]:
                info["channel"] = html.unescape(vd.get("author") or "")
            if not info["channel_link"]:
                cid = vd.get("channelId") or ""
                if cid: info["channel_link"] = f"https://www.youtube.com/channel/{cid}"
            if not info["views"]:
                vc = vd.get("viewCount") or micro.get("viewCount")
                info["views"] = _safe_int(vc, 0)
            if not info["duration_sec"]:
                info["duration_sec"] = _safe_int(vd.get("lengthSeconds"), 0)
            if not info["upload_date"]:
                up = micro.get("publishDate") or micro.get("uploadDate") or ""
                if up and re.match(r"^\d{4}-\d{2}-\d{2}$", up):
                    info["upload_date"] = f"{up} 00:00:00"
        except Exception:
            pass

    # 3) 쇼츠 판별
    try:
        is_shorts = False
        if info["duration_sec"] and info["duration_sec"] <= 61:
            is_shorts = True
        else:
            if watch_html and (f'"/shorts/{video_id}"' in watch_html or
                               '"isShortsEligible":true' in watch_html or
                               '"isShortsAudioPost":true' in watch_html):
                is_shorts = True
        info["is_shorts"] = is_shorts
        info["form"] = "숏폼" if is_shorts else "롱폼"
    except Exception:
        info["is_shorts"] = False
        info["form"] = "롱폼"

    # 4) 자막 (pytube/playerResponse → 실패 시에만 yt-dlp)
    if not SKIP_CAPTION and info["caption"] is None:
        # playerResponse captionTracks 우선
        try:
            tr = pr.get("captions", {}).get("playerCaptionsTracklistRenderer", {})
            tracks = tr.get("captionTracks", []) if isinstance(tr, dict) else []
            if tracks:
                def pick():
                    manu_ko = [t for t in tracks if t.get("languageCode")=="ko" and t.get("kind")!="asr"]
                    auto_ko = [t for t in tracks if t.get("languageCode")=="ko"]
                    manu_en = [t for t in tracks if t.get("languageCode")=="en" and t.get("kind")!="asr"]
                    auto_en = [t for t in tracks if t.get("languageCode")=="en"]
                    if manu_ko: return manu_ko[0], False
                    if auto_ko: return auto_ko[0], False
                    if manu_en: return manu_en[0], True
                    if auto_en: return auto_en[0], True
                    return tracks[0], True
                track, need_tr = pick()
                base = track.get("baseUrl")
                if base:
                    url = base
                    if "fmt=" not in url: url += "&fmt=srv3"
                    if need_tr: url += "&tlang=ko"
                    _rate_sleep()
                    r = SESSION.get(url, timeout=HTTP_TIMEOUT)
                    if r.ok and r.text:
                        lines = extract_caption_text(r.text)
                        info["caption"] = "\n".join(lines) if lines else ""
        except Exception:
            pass

        # 여전히 없으면 yt‑dlp 한 번만 호출
        if not info["caption"]:
            ydl_info = _ydl_extract(info["video_link"])
            if isinstance(ydl_info, dict):
                cap_url, cap_ext = _pick_caption_from_ydl(ydl_info)
                if cap_url:
                    txt = _fetch_caption_text(cap_url, cap_ext or "")
                    if txt is not None:
                        info["caption"] = txt

    # 5) yt‑dlp **조건부** 보강 (필요할 때만)
    need_ydl = (
        (not info["views"]) or
        (not info["duration_sec"]) or
        (not info["upload_date"]) or
        (not info["channel_link"])
    )
    if need_ydl:
        ydl_info = _ydl_extract(info["video_link"])
        if isinstance(ydl_info, dict):
            try:
                if not info["title"]:
                    info["title"] = ydl_info.get("title") or info["title"]
                if not info["channel"]:
                    info["channel"] = ydl_info.get("uploader") or ydl_info.get("channel") or info["channel"]
                if not info["channel_link"]:
                    cid = ydl_info.get("channel_id") or ydl_info.get("channelid")
                    if cid:
                        info["channel_link"] = f"https://www.youtube.com/channel/{cid}"
                    else:
                        cu = ydl_info.get("channel_url") or ydl_info.get("uploader_url")
                        if cu: info["channel_link"] = cu
                if not info["views"]:
                    info["views"] = _safe_int(ydl_info.get("view_count"), info["views"])
                if not info["duration_sec"]:
                    info["duration_sec"] = _safe_int(ydl_info.get("duration"), info["duration_sec"])
                if not info["upload_date"]:
                    up = ydl_info.get("upload_date") or ""
                    if up and re.match(r"^\d{8}$", up):
                        info["upload_date"] = f"{up[:4]}-{up[4:6]}-{up[6:]} 00:00:00"
            except Exception:
                pass

    # 6) 구독자 수
    try:
        if not SKIP_SUBSCRIBERS:
            cid = None
            if info["channel_link"].startswith("https://www.youtube.com/channel/"):
                cid = info["channel_link"].split("/channel/")[-1]
            if not cid and isinstance(pr, dict):
                cid = pr.get("videoDetails", {}).get("channelId")
            if cid:
                info["subscribers"] = get_channel_subscribers(cid, hint_video_id=video_id)
            else:
                info["subscribers"] = 0
    except Exception:
        info["subscribers"] = 0

    # 누락 기본값 보정
    for k in ("title","channel","upload_date"):
        if info[k] is None: info[k] = ""
    for k in ("views","subscribers","duration_sec"):
        if info[k] is None: info[k] = 0
    if info["caption"] is None: info["caption"] = ""

    return info

# ===================== 검색(페이지네이션) =====================
def get_keyword_videos(keyword, max_results=5):
    logger.info(f"[SEARCH] 시작: q='{keyword}', want={max_results}")
    s = Search(keyword)

    try:
        while len(s.results) < max_results:
            prev = len(s.results)
            try:
                _rate_sleep()
                s.get_next_results()
                if len(s.results) == prev:
                    break
            except Exception:
                break
    except Exception:
        pass

    results = s.results[:max_results]
    vids = []
    for v in results:
        vid = getattr(v, "video_id", None)
        if vid:
            vids.append(vid)

    out = []
    for vid in vids:
        try:
            out.append(get_video_info(vid))
        except Exception:
            pass
    return out

if __name__ == "__main__":
    for video_id in ["Atko_kZmEx8", "dQw4w9WgXcQ"]:
        i = get_video_info(video_id)
        print("제목 :", i["title"])
        print("채널 :", i["channel"])
        print("조회수 :", i["views"])
        print("구독자 :", i["subscribers"])
        print("업로드 :", i["upload_date"])
        print("길이(초) :", i["duration_sec"])
        print("형식 :", i["form"])
        print("자막 길이 :", len(i["caption"] or ""))
        print("=" * 60)
