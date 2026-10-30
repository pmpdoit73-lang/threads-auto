"""gil이 봇에 보낸 영상·링크를 받아 두었다가 초안에 붙인다.

받는 것 (텔레그램 봇에 그냥 보내기, 한 줄 메모 필수):
  - 쓰레드 게시물 링크 → 그 글을 '인용'해서 우리 글을 올림 (영상은 원래 주인 글로 보임)
  - 구글 드라이브·드롭박스 공유 링크, mp4 주소 → 영상을 받아서 우리 글과 함께 올림
  - 영상 파일 (20MB 이하) → 그대로 올림
허락받은 영상만 보내기. 메모에 '출처: OO' 줄을 쓰면 글 끝에 그대로 붙는다.

받으면 예약 글(07·11·18·21시)과 따로 '추가 초안'이 하나 만들어지고,
예약 글과 1시간 넘게 떨어진 시간(보통 1시간 뒤)에 자동으로 올라간다.
"""

import re
from urllib.parse import parse_qs, urlparse

import requests

import telegram
import threads_api

MAX_MB = 200       # 임시 저장소가 받아 주는 크기 안으로
TELEGRAM_MB = 20   # 텔레그램 봇이 내려받을 수 있는 최대 크기
URL_RE = re.compile(r"https?://\S+")
THREADS_POST_RE = re.compile(r"threads\.(?:com|net)/@[^/]+/post/([A-Za-z0-9_-]+)")


# ---------- 메시지 읽기 ----------

def parse_link(text):
    """메시지에서 링크와 메모를 나눈다. 링크가 없으면 None."""
    m = URL_RE.search(text or "")
    if not m:
        return None
    url = m.group(0).rstrip(").,>")
    memo = (text[:m.start()] + text[m.end():]).strip()
    shortcode = THREADS_POST_RE.search(url)
    if shortcode:
        clean = url.split("?")[0]
        return {"kind": "quote", "url": clean, "shortcode": shortcode.group(1), "memo": memo}
    return {"kind": "video", "url": url, "memo": memo}


def split_memo(memo):
    """메모를 (물건 설명, 출처 줄)로 나눈다."""
    about, credit = [], []
    for line in (memo or "").splitlines():
        (credit if line.strip().startswith("출처") else about).append(line.strip())
    return " ".join(x for x in about if x), "\n".join(x for x in credit if x)


# ---------- 쓰레드 인용 ----------

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def shortcode_to_id(shortcode):
    """링크 속 글 번호(문자)를 숫자 번호로 바꾼다 (인스타그램과 같은 방식)."""
    n = 0
    for ch in shortcode[:11]:
        n = n * 64 + ALPHABET.index(ch)
    return str(n)


def resolve_quote_id(shortcode):
    """쓰레드 API로 인용할 글 번호를 찾는다. 못 찾으면 None (그땐 링크 카드로 올림)."""
    candidate = shortcode_to_id(shortcode)
    try:
        threads_api._get(candidate, fields="id")
        return candidate
    except Exception as e:
        print(f"[media] 인용할 글 번호 확인 실패, 링크 카드로 올릴게요: {e}")
        return None


# ---------- 영상 받기 ----------

def direct_url(url):
    """공유 링크를 파일 자체로 바로 가는 주소로 바꾼다."""
    u = urlparse(url)
    if "drive.google.com" in u.netloc:
        m = re.search(r"/d/([A-Za-z0-9_-]+)", u.path)
        file_id = m.group(1) if m else (parse_qs(u.query).get("id") or [""])[0]
        if file_id:
            return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    if "dropbox.com" in u.netloc:
        return re.sub(r"([?&])dl=0", r"\1dl=1", url) if "dl=0" in url else url + ("&" if u.query else "?") + "dl=1"
    return url


def _check_video(data):
    if len(data) < 1000 or b"ftyp" not in data[:64]:
        raise RuntimeError("영상 파일(mp4·mov)이 아니에요. 공유 링크가 '링크가 있는 모든 사용자'로 열려 있는지 확인해 주세요")
    return data


def download(url):
    """링크에서 영상을 내려받는다."""
    with requests.get(direct_url(url), stream=True, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0 (threads-auto)"}) as resp:
        resp.raise_for_status()
        chunks, size = [], 0
        for chunk in resp.iter_content(1 << 20):
            size += len(chunk)
            if size > MAX_MB << 20:
                raise RuntimeError(f"영상이 {MAX_MB}MB보다 커요. 조금 줄여서 보내 주세요")
            chunks.append(chunk)
    return _check_video(b"".join(chunks))


def fetch(item):
    """줄 서 있던 영상의 내용을 가져온다."""
    if item.get("file_id"):
        return _check_video(telegram.download_file(item["file_id"]))
    return download(item["url"])


def probe(url):
    """받은 링크가 정말 영상인지 앞부분만 받아 확인한다."""
    with requests.get(direct_url(url), stream=True, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0 (threads-auto)", "Range": "bytes=0-4095"}) as resp:
        resp.raise_for_status()
        head = next(resp.iter_content(4096), b"")
    if b"ftyp" not in head[:64]:
        raise RuntimeError("영상 파일(mp4·mov)이 아니에요. 공유 설정이 '링크가 있는 모든 사용자'인지 확인해 주세요")


def label(item):
    """텔레그램에 보여 줄 짧은 설명."""
    if item["kind"] == "quote":
        how = "인용 게시" if item.get("quote_id") else "링크 카드 (인용 번호를 못 찾음)"
        return f"🔗 {how}: {item['url']}"
    where = "텔레그램 영상" if item.get("file_id") else item["url"][:60]
    return f"🎬 영상: {where}"
