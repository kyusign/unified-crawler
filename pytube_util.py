from pytube import YouTube, Search
import requests
import re


def extract_caption_text(xml_captions):
    """YouTube 자막 XML에서 텍스트만 추출"""
    p_tags = re.findall(r'<p[^>]*>(.*?)</p>', xml_captions, re.DOTALL)
    texts = []
    for p_content in p_tags:
        if not p_content.strip():
            continue
        if '<s' in p_content:
            s_texts = re.findall(r'<s[^>]*>(.*?)</s>', p_content)
            if s_texts:
                texts.append(''.join(s_texts))
        else:
            clean_text = re.sub(r'<[^>]+>', '', p_content)
            clean_text = clean_text.strip()
            if clean_text:
                texts.append(clean_text)
    return texts

def get_video_info(video_id):
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    yt = YouTube(video_url)
    video_info = {
        "thumbnail": thumbnail_url,
        "title": yt.title,
        "video_link": video_url,
        "channel": yt.author,
        "channel_link": f"https://www.youtube.com/channel/{yt.channel_id}",
        "views": yt.views,
        "subscribers": 0,
        "upload_date": yt.publish_date.strftime("%Y-%m-%d %H:%M:%S"),
        "caption": None
    }
    captions = yt.captions
    if len(captions.keys()) > 0:
        if 'ko' in captions.keys():
            xml_caption = captions['ko'].xml_captions
        else:
            if 'a.ko' in captions.keys():
                xml_caption = captions['a.ko'].xml_captions
            else:
                _first_cap = list(captions.keys())[0].code
                _tlang_ko_cap_url = captions[_first_cap].url + "&tlang=ko"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
                res = requests.get(_tlang_ko_cap_url, headers=headers)
                xml_caption = res.text
    else:
        xml_caption = None
    full_text = ""
    if xml_caption:
        texts = extract_caption_text(xml_caption)
        full_text = "\n".join(texts)
    video_info["caption"] = full_text
    return video_info

def get_keyword_videos(keyword, max_results=5):
    search = Search(keyword)
    search_results = search.results[:max_results]
    video_infos = []
    for video in search_results:
        video_id = video.video_id
        video_info = get_video_info(video_id)
        video_infos.append(video_info)
    return video_infos
