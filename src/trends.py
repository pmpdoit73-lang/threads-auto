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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (threads-auto)"}
TIMEOUT = 15


MAX_AGE_HOURS = 36  # 이보다 오래된 뉴스는 빼서 '지나간 이슈'를 막음
HT = "{https://trends.google.com/trending/rss}"


def _age_label(pub):
    """발행 시각 → '3시간 전' 같은 표시. 너무 오래됐으면 None."""
    if not pub:
        return ""
    try:
        when = parsedate_to_datetime(pub)
    except (TypeError, ValueError):
        return ""
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if hours > MAX_AGE_HOURS:
        return None
    return f"{max(int(hours), 0)}시간 전"


def _rss_titles(url, limit):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    titles = []
    for item in root.iter("item"):
        title = item.findtext("title")
        age = _age_label(item.findtext("pubDate"))
        if not title or age is None:
            continue
        line = html.unescape(title.strip())
        news = item.findtext(f"{HT}news_item/{HT}news_item_title")  # 구글 트렌드: 관련 기사 제목
        if news:
            line += f" ← {html.unescape(news.strip())}"
        traffic = item.findtext(f"{HT}approx_traffic")
        if traffic:
            line += f" [검색 {traffic}]"
        titles.append(f"{line} ({age})" if age else line)
        if len(titles) >= limit:
            break
    return titles


def google_trends(limit=20):
    return _rss_titles("https://trends.google.com/trending/rss?geo=KR", limit)


def google_news(limit=20):
    titles = _rss_titles("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", limit)
    # "제목 - 언론사" 형태에서 언론사 이름을 뗀다
    return [re.sub(r"\s+-\s+[^-()]+(?= \(\d+시간 전\)$|$)", "", t) for t in titles]


NAVER_QUERIES = ["가전 신제품", "가전 리콜", "살림템", "주방용품", "생활용품 출시", "깜짝"]  # 프로필 주제 + 깜짝 이슈


def naver_news(limit=8):
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not (client_id and client_secret):
        return []
    result, seen = [], set()
    for query in NAVER_QUERIES:
        try:
            resp = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                params={"query": query, "display": limit, "sort": "date"},
                headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[trends] 네이버 '{query}' 실패: {e}")
            continue
        for i in resp.json().get("items", []):
            age = _age_label(i.get("pubDate"))
            title = re.sub(r'<[^>]+>', '', html.unescape(i['title']))
            if age is None or title in seen:
                continue
            seen.add(title)
            result.append(f"{title} ({age})")
    return result


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
