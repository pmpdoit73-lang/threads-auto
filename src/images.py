"""사진 준비: Gemini 생성 → 실패하면 Pexels 무료 사진.

결과는 (사진 바이트, 출처 설명) 튜플. 둘 다 실패하면 (None, 이유).
"""

import base64
import os

import requests

GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
TIMEOUT = 90


def gemini_image(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": (
            "Photorealistic, warm natural light, cozy Korean home atmosphere, "
            "square 1:1, no text, no logos, no faces. " + prompt
        )}]}],
    }
    resp = requests.post(url, params={"key": key}, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    for cand in resp.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    raise RuntimeError("Gemini 응답에 이미지가 없음")


def pexels_photo(query):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY 없음")
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": 1, "orientation": "square"},
        headers={"Authorization": key},
        timeout=30,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        raise RuntimeError(f"Pexels 검색 결과 없음: {query}")
    photo = photos[0]
    img = requests.get(photo["src"]["large"], timeout=30)
    img.raise_for_status()
    return img.content, photo.get("photographer", "")


def get_image(image_prompt, photo_query):
    try:
        return gemini_image(image_prompt), "제미나이 생성"
    except Exception as e:
        print(f"[images] Gemini 실패, 무료 사진으로 대체: {e}")
    try:
        data, author = pexels_photo(photo_query)
        return data, f"Pexels 무료 사진 (작가: {author})"
    except Exception as e:
        print(f"[images] Pexels 실패: {e}")
        return None, "사진 준비 실패"
