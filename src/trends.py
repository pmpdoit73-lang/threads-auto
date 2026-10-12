"""오늘의 핫이슈 후보를 여러 출처에서 모은다.

- 구글 트렌드 (한국 급상승 검색어, 키 불필요)
- 구글 뉴스 한국판 주요 뉴스 (키 불필요)
- 네이버 뉴스 검색 (NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 있을 때만)
- 유튜브 인기 동영상 (YOUTUBE_API_KEY 있을 때만)

한 출처가 실패해도 나머지로 계속 진행한다.
"""

import html
import os
import re
import xml.etree.ElementTree as ET

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (threads-auto)"}
TIMEOUT = 15


def _rss_titles(url, limit):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    titles = []
    for item in root.iter("item"):
        title = item.findtext("title")
        if title:
            titles.append(html.unescape(title.strip()))
        if len(titles) >= limit:
            break
    return titles


def google_trends(limit=20):
    return _rss_titles("https://trends.google.com/trending/rss?geo=KR", limit)


def google_news(limit=20):
    titles = _rss_titles("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", limit)
    # "제목 - 언론사" 형태에서 언론사 이름을 뗀다
    return [re.sub(r"\s+-\s+[^-]+$", "", t) for t in titles]


def naver_news(limit=20):
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not (client_id and client_secret):
        return []
    resp = requests.get(
        "https://openapi.naver.com/v1/search/news.json",
        params={"query": "생활 물가 날씨", "display": limit, "sort": "date"},
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return [re.sub(r"<[^>]+>", "", html.unescape(i["title"])) for i in resp.json().get("items", [])]


def youtube_popular(limit=20):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return []
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet", "chart": "mostPopular", "regionCode": "KR",
                "maxResults": limit, "key": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return [i["snippet"]["title"] for i in resp.json().get("items", [])]


SOURCES = {
    "구글 트렌드": google_trends,
    "구글 뉴스": google_news,
    "네이버 뉴스": naver_news,
    "유튜브 인기": youtube_popular,
}


def collect():
    """{출처 이름: [제목, ...]} 를 돌려준다. 실패한 출처는 빠진다."""
    result = {}
    for name, fn in SOURCES.items():
        try:
            items = fn()
        except Exception as e:  # 한 출처 실패가 전체를 멈추지 않게
            print(f"[trends] {name} 실패: {e}")
            continue
        if items:
            result[name] = items
    if not result:
        raise RuntimeError("핫이슈 출처를 하나도 가져오지 못했어요.")
    return result
