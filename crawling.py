import os, re, sys, time, random, json
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, urlunparse, urlencode, parse_qs

import pandas as pd  # 일부 유틸에서 사용
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

APP_TITLE = "커뮤니티 크롤러 (최근 일+시간 + 화면 표시)"
USER_HOME = os.path.expanduser("~")
DEFAULT_DESKTOP = os.path.join(USER_HOME, "Desktop")

MAX_PAGES_SOFT = 300
STALE_PAGE_LIMIT = 3

# ---------- 공통 유틸 ----------
def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_dir_for_file(path: str):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)

def default_xlsx_path():
    return os.path.join(DEFAULT_DESKTOP, f"크롤링_결과_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

def to_int_or_none(text):
    try:
        return int(re.sub(r"[^\d]", "", str(text)))
    except Exception:
        return None

def add_or_replace_query_param(url: str, key: str, value) -> str:
    parts = list(urlparse(url))
    q = parse_qs(parts[4], keep_blank_values=True)
    q[key] = [str(value)]
    parts[4] = urlencode(q, doseq=True)
    return urlunparse(parts)

def rsleep(min_s=0.1, max_s=0.5):
    time.sleep(random.uniform(min_s, max_s))

# ---------- 드라이버 초기화 ----------
def _load_driver_path_from_json():
    candidates = []
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(base_dir, "driver_path.json"))

    progdata = os.getenv("PROGRAMDATA") or "/usr/local/share"
    common_dir = os.path.join(progdata, "OneInsight", "UnifiedCrawler")
    candidates.append(os.path.join(common_dir, "driver_path.json"))

    home = os.path.expanduser("~")
    home_dir = os.path.join(home, ".unifiedcrawler")
    candidates.append(os.path.join(home_dir, "driver_path.json"))

    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    d = data.get("chromedriver_path")
                    if d and os.path.exists(d):
                        return d
        except Exception:
            continue
    return None


def initialize_driver(show_browser: bool):
    """외부에서 설치된 ChromeDriver만 사용."""
    options = Options()
    if not show_browser:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    env_path = os.environ.get("CHROMEDRIVER_PATH")
    if env_path and os.path.exists(env_path):
        service = Service(env_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(25)
        return driver

    json_path = _load_driver_path_from_json()
    if json_path and os.path.exists(json_path):
        service = Service(json_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(25)
        return driver

    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    local_driver = os.path.join(base_dir, "chromedriver.exe" if os.name == "nt" else "chromedriver")
    if os.path.exists(local_driver):
        service = Service(local_driver)
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(25)
        return driver

    raise RuntimeError(
        "ChromeDriver를 찾을 수 없습니다.\n"
        "1) 드라이버 설치기를 먼저 실행하세요.\n"
        "2) 또는 CHROMEDRIVER_PATH 환경변수에 경로를 지정하세요.\n"
        "3) 또는 실행 폴더에 chromedriver(.exe)를 두세요."
    )

# ---------- 날짜 파싱 ----------
_DOT_DT_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})$")

def parse_dt_dot(text: str):
    if not text:
        return None
    m = _DOT_DT_RE.match(text.strip())
    if not m:
        return None
    y, M, d, h, mi = map(int, m.groups())
    try:
        return datetime(y, M, d, h, mi)
    except ValueError:
        return None

_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

def parse_dt_hhmm_today(text: str):
    if not text:
        return None
    m = _HHMM_RE.match(text.strip())
    if not m:
        return None
    h, mi = map(int, m.groups())
    now = datetime.now()
    try:
        return datetime(now.year, now.month, now.day, h, mi)
    except ValueError:
        return None

def parse_dt_dc_flexible(text: str):
    if not text:
        return None
    s = text.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?$", s)
    if m:
        y, M, d, h, mi, sec = m.groups()
        try:
            return datetime(int(y), int(M), int(d), int(h), int(mi), int(sec or '0'))
        except ValueError:
            return None
    hh = parse_dt_hhmm_today(s)
    if hh:
        return hh
    return None

# ---------- FMKorea ----------
FM_LINK_PATTERNS = [
    re.compile(r"/\d{5,}$"),
    re.compile(r"[?&]document_srl=\d+")
]

def fmk_collect_links_by_user_selector(driver):
    sel = '.pc_voted_count.pc_voted_count_plus.pc_voted_count_short'
    cand = driver.find_elements(By.CSS_SELECTOR, sel)
    links, seen = [], set()
    for el in cand:
        href = el.get_attribute('href')
        if href and href not in seen:
            seen.add(href)
            links.append(href)
    return links

def collect_links_fallback_regex(driver):
    base = driver.current_url
    links, seen = [], set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        href = a.get_attribute("href")
        if not href:
            continue
        abs_href = urljoin(base, href)
        if any(p.search(abs_href) for p in FM_LINK_PATTERNS):
            if abs_href not in seen:
                seen.add(abs_href)
                links.append(abs_href)
    return links

def fmk_get_content(link, driver):
    driver.get(link); rsleep()
    try:
        wait = WebDriverWait(driver, 5)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".np_18px_span")))
        poten_elements = driver.find_elements(By.CSS_SELECTOR, "h1.np_18px > span.STAR-BEST_T")
        title_elements = driver.find_elements(By.CSS_SELECTOR, ".np_18px_span")
        title_text = title_elements[0].text.strip() if title_elements else "제목 없음"
        title = f"포텐: {title_text}" if poten_elements and title_elements else title_text
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".date.m_no")))
        date_elem = driver.find_element(By.CSS_SELECTOR, ".date.m_no")
        date_text = date_elem.text.strip()
        wait.until(EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '조회 수')]/b")))
        views_elem = driver.find_element(By.XPATH, "//span[contains(text(), '조회 수')]/b")
        views_text = views_elem.text.strip()
        views = to_int_or_none(views_text)
    except Exception as e:
        print("Error extracting content from", link, ":", e)
        title, date_text, views = "제목 없음", "", None
    return title, date_text, views

def crawl_fmkorea(list_url, cutoff, show_browser, log):
    rows = []
    driver = initialize_driver(show_browser)
    try:
        page = 1
        stale_pages = 0
        while page <= MAX_PAGES_SOFT:
            current_url = add_or_replace_query_param(list_url, "page", page)
            log(f"[FMK] 목록 로드 page={page} | {current_url}")
            driver.get(current_url); rsleep()

            links = fmk_collect_links_by_user_selector(driver)
            if not links:
                links = collect_links_fallback_regex(driver)
            log(f"[FMK] 후보 링크 {len(links)}개")
            if not links:
                stale_pages += 1
                if stale_pages >= STALE_PAGE_LIMIT:
                    log("[FMK] 링크 없음/오래된 페이지 연속 → 종료")
                    break
                page += 1
                continue
            else:
                stale_pages = 0

            found_older_post = False
            for href in links:
                title_text, date_text, views = fmk_get_content(href, driver); rsleep()
                post_time = parse_dt_dot(date_text)
                if not post_time:
                    log(f"[FMK] 날짜 파싱 실패 → 건너뜀: {date_text} | {href}")
                    continue
                rows.append({
                    "Site": "FMKorea",
                    "Title": title_text,
                    "Date": date_text,
                    "DateISO": post_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "Views": views,
                    "Link": href
                })
                if post_time < cutoff:
                    found_older_post = True
            if found_older_post:
                log("[FMK] 오래된 글 감지 → 이 페이지 전부 수집 후 종료")
                break
            page += 1
    finally:
        driver.quit()
    return rows

# ---------- DCInside ----------
def crawl_dcinside(list_url, cutoff, show_browser, log):
    rows = []
    driver = initialize_driver(show_browser)
    log(f"[DC] cutoff = {cutoff:%Y-%m-%d %H:%M:%S}")
    try:
        stale_pages = 0
        for page in range(1, MAX_PAGES_SOFT + 1):
            url = add_or_replace_query_param(list_url, "page", page)
            log(f"[DC] 목록 page={page} | {url}")
            driver.get(url); rsleep()
            base = driver.current_url

            trs = driver.find_elements(By.CSS_SELECTOR, "tr.ub-content.us-post")
            log(f"[DC] 행 {len(trs)}")
            if not trs:
                stale_pages += 1
                if stale_pages >= STALE_PAGE_LIMIT:
                    log("[DC] 연속 없음 → 종료")
                    break
                continue
            stale_pages = 0

            if page >= 2:
                try:
                    d0 = trs[0].find_element(By.CSS_SELECTOR, "td.gall_date")
                    title_attr = (d0.get_attribute("title") or "").strip()
                    cell_text = (d0.text or "").strip()
                    first_txt = title_attr or cell_text
                    first_dt = None
                    if title_attr:
                        try:
                            first_dt = datetime.strptime(title_attr, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            try:
                                first_dt = datetime.strptime(title_attr, "%Y-%m-%d %H:%M")
                            except ValueError:
                                first_dt = None
                    if first_dt is None and cell_text:
                        m = re.match(r"^(\d{1,2}):(\d{2})$", cell_text)
                        if m:
                            h, mi = map(int, m.groups())
                            now = datetime.now()
                            first_dt = datetime(now.year, now.month, now.day, h, mi)
                        else:
                            m = re.match(r"^(\d{2})\.(\d{2})$", cell_text)
                            if m:
                                M, d2 = map(int, m.groups())
                                now = datetime.now()
                                first_dt = datetime(now.year, M, d2, 0, 0)
                    if first_dt and first_dt < cutoff:
                        log(f"[DC] page={page} 첫 글 {first_txt} < cutoff → 종료")
                        break
                except Exception:
                    pass

            found_recent = False
            for tr in trs:
                try:
                    a = tr.find_element(By.CSS_SELECTOR, "td.gall_tit a[href]")
                    href = urljoin(base, a.get_attribute("href"))
                    title = a.text.strip() or (a.get_attribute("title") or "").strip()

                    d = tr.find_element(By.CSS_SELECTOR, "td.gall_date")
                    title_attr = (d.get_attribute("title") or "").strip()
                    cell_text = (d.text or "").strip()

                    dt = None
                    date_text = ""
                    if title_attr:
                        try:
                            dt = datetime.strptime(title_attr, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            try:
                                dt = datetime.strptime(title_attr, "%Y-%m-%d %H:%M")
                            except ValueError:
                                dt = None
                        date_text = title_attr
                    else:
                        m = re.match(r"^(\d{1,2}):(\d{2})$", cell_text)
                        if m:
                            h, mi = map(int, m.groups())
                            now = datetime.now()
                            dt = datetime(now.year, now.month, now.day, h, mi)
                            date_text = f"{now.year}-{now.month:02d}-{now.day:02d} {h:02d}:{mi:02d}"
                        else:
                            m = re.match(r"^(\d{2})\.(\d{2})$", cell_text)
                            if m:
                                M, d2 = map(int, m.groups())
                                now = datetime.now()
                                dt = datetime(now.year, M, d2, 0, 0)
                                date_text = f"{now.year}-{M:02d}-{d2:02d} 00:00"

                    v = tr.find_element(By.CSS_SELECTOR, "td.gall_count")
                    views = to_int_or_none(v.text)

                    if dt and dt >= cutoff:
                        rows.append({
                            "Site": "DCInside",
                            "Title": title or "제목 없음",
                            "Date": date_text or (title_attr or cell_text),
                            "DateISO": dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "Views": views,
                            "Link": href,
                        })
                        found_recent = True
                except Exception as e:
                    log(f"[DC] 행 파싱 실패: {e}")

            if not found_recent:
                stale_pages += 1
                if stale_pages >= STALE_PAGE_LIMIT:
                    log("[DC] 최근 글 없음 연속 → 종료")
                    break
            else:
                stale_pages = 0
    finally:
        driver.quit()
    return rows

# ---------- TheQoo ----------
_DOT_FULL_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})$")
_DOT_Y2_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")
_DOT_MD_RE = re.compile(r"^(\d{2})\.(\d{2})$")

def parse_dt_theqoo(text: str):
    if not text:
        return None
    s = text.strip()
    m = _DOT_FULL_RE.match(s)
    if m:
        y, M, d, h, mi = map(int, m.groups())
        try:
            return datetime(y, M, d, h, mi)
        except ValueError:
            return None
    m = _DOT_Y2_RE.match(s)
    if m:
        yy, M, d = map(int, m.groups())
        y = 2000 + yy
        try:
            return datetime(y, M, d, 0, 0)
        except ValueError:
            return None
    m = _DOT_MD_RE.match(s)
    if m:
        M, d = map(int, m.groups())
        now = datetime.now()
        try:
            return datetime(now.year, M, d, 0, 0)
        except ValueError:
            return None
    m = _HHMM_RE.match(s)
    if m:
        h, mi = map(int, m.groups())
        now = datetime.now()
        try:
            return datetime(now.year, now.month, now.day, h, mi)
        except ValueError:
            return None
    return None

def theqoo_collect_detail_links(driver):
    base = driver.current_url
    links, seen = [], set()
    title_tds = driver.find_elements(By.CSS_SELECTOR, "td.title")
    for td in title_tds:
        try:
            tr = td.find_element(By.XPATH, "./ancestor::tr[1]")
            try:
                no_strong = tr.find_element(By.CSS_SELECTOR, "td.no strong")
                if "공지" in (no_strong.text or "").strip():
                    continue
            except Exception:
                pass
            a = td.find_element(By.CSS_SELECTOR, "a[href]:not(.replyNum)")
            href = urljoin(base, a.get_attribute("href"))
            if href not in seen:
                seen.add(href)
                links.append(href)
        except Exception:
            continue
    return links

def theqoo_parse_detail(driver, url):
    driver.get(url); rsleep()
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
    title = ""
    for sel in ["h1.title", ".title h1", ".title", "h1", "h2"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els and els[0].text.strip():
            title = els[0].text.strip()
            break
    if not title:
        title = "제목 없음"
    date_text = ""
    for sel in [".side.fr span", ".date", ".regdate", ".time", "time[datetime]"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            t = (els[0].get_attribute("datetime") or els[0].text or "").strip()
            if t:
                date_text = t
                break
    if not date_text:
        m = re.search(r"\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}", driver.page_source)
        if m:
            date_text = m.group(0)
    views = None
    try:
        cnt = driver.find_element(By.CSS_SELECTOR, ".count_container")
        raw = (cnt.get_attribute("innerText") or cnt.text or "").strip()
        nums = re.findall(r"\d{1,3}(?:,\d{3})*|\d+", raw)
        if nums:
            views = to_int_or_none(nums[0])
    except NoSuchElementException:
        pass
    if views is None:
        all_nums = re.findall(r"\d{1,3}(?:,\d{3})*|\d+", driver.page_source)
        if all_nums:
            views = max((to_int_or_none(n) for n in all_nums), default=None)
    dt = parse_dt_dot(date_text) or parse_dt_theqoo(date_text)
    return {
        "Site": "TheQoo",
        "Title": title,
        "Date": date_text,
        "DateISO": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
        "Views": views,
        "Link": url,
        "_dt": dt
    }

def crawl_theqoo(list_url, cutoff, show_browser, log):
    rows = []
    driver = initialize_driver(show_browser)
    try:
        page = 1
        stale_pages = 0
        while page <= MAX_PAGES_SOFT:
            page_url = add_or_replace_query_param(list_url, "page", page)
            log(f"[TQ] 목록 로드: page={page} | {page_url}")
            driver.get(page_url); rsleep()
            links = theqoo_collect_detail_links(driver)
            log(f"[TQ] 상세 후보(공지 제외) {len(links)}개")
            if not links:
                stale_pages += 1
                if stale_pages >= STALE_PAGE_LIMIT:
                    log("[TQ] 링크 없음/오래된 페이지 연속 → 종료")
                    break
                page += 1
                continue
            else:
                stale_pages = 0
            found_older = False
            for i, href in enumerate(links, 1):
                try:
                    post = theqoo_parse_detail(driver, href); rsleep()
                    dt = post["_dt"]
                    rows.append({
                        "Site": post["Site"],
                        "Title": post["Title"],
                        "Date": post["Date"],
                        "DateISO": post["DateISO"],
                        "Views": post["Views"],
                        "Link": post["Link"]
                    })
                    if dt and dt < cutoff:
                        found_older = True
                    if i % 10 == 0 or i == len(links):
                        log(f"[TQ] 진행 {i}/{len(links)} (누적 {len(rows)})")
                except Exception as e:
                    log(f"[TQ] 상세 파싱 실패: {e}")
            if found_older:
                log("[TQ] 오래된 글 감지 → 이 페이지 전부 수집 후 종료")
                break
            page += 1
    finally:
        driver.quit()
    return rows
