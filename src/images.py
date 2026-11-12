"""사진 준비: Gemini 생성 → 실패하면 Pexels 무료 사진.

get_checked_image는 사진마다 Claude가 '글의 물건과 맞는지' 검수하고,
안 맞으면 더 구체적인 프롬프트로 다시 만들거나 다른 무료 사진을 찾는다.
"""

import base64
import os

import requests

GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
TIMEOUT = 90


def gemini_image(prompt, must_show=""):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 없음")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": (
            "A candid, unedited smartphone snapshot taken by an ordinary Korean person at home "
            "(shot on a Galaxy/iPhone main camera). Must look like a real photo, NOT AI art, NOT a render, "
            "NOT an illustration, NOT a stock or studio product photo. "
            "Natural everyday indoor light or window light. Careless one-handed framing: "
            "the camera is visibly tilted about 5-15 degrees, the subject is off-center and partly cropped at an edge, "
            "shot from a casual high angle as if looking down while standing, mild phone-camera noise and true-to-life colors, real lived-in clutter "
            "in an ordinary Korean apartment, realistic textures and small imperfections. "
            "No dramatic lighting, no bokeh-heavy look, no oversaturation, no perfect symmetry. "
            "Square 1:1, no text, no logos, no watermarks, no human faces. "
            + (f"THE MAIN OBJECT, clearly visible and easy to recognize, MUST be exactly: {must_show}. "
               "Do NOT replace it with a similar-looking but different object. " if must_show else "")
            + "Subject: " + prompt
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


def pexels_photos(query, count=5):
    """검색 결과 여러 장의 (사진 주소, 작가) 목록."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError("PEXELS_API_KEY 없음")
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        params={"query": query, "per_page": count, "orientation": "square"},
        headers={"Authorization": key},
        timeout=30,
    )
    resp.raise_for_status()
    return [(p["src"]["large"], p.get("photographer", "")) for p in resp.json().get("photos", [])]


def download(url):
    img = requests.get(url, timeout=30)
    img.raise_for_status()
    return img.content


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


# ---------- 글과 사진이 맞는지 검수 ----------

GEMINI_TRIES = 3   # 제미나이: 처음 + 고쳐서 다시 2번
PEXELS_CHECKS = 5  # 무료 사진: 최대 5장까지 검수


def _verify(data, subject, subject_en, text):
    """검수 결과 dict. 검수 자체가 안 되면(키 없음·오류) None."""
    if not subject:
        return None
    try:
        import writer  # Claude 호출은 writer에 모여 있음
        v = writer.check_photo(data, subject, subject_en, text)
        print(f"[images] 검수: {'일치' if v['match'] else '불일치'} — 사진 속 '{v['seen']}' ({v['reason']})")
        return v
    except Exception as e:
        print(f"[images] 사진 검수 실패, 검수 없이 진행: {e}")
        return None


def _try_gemini(d, tries):
    prompt, must = d["image_prompt"], d.get("subject_en") or d.get("subject", "")
    for i in range(tries):
        try:
            data = gemini_image(prompt, must_show=must)
        except Exception as e:
            print(f"[images] Gemini 실패: {e}")
            return
        v = yield data, "제미나이 생성"  # 검수 결과를 돌려받음
        if not v:
            return
        # 안 맞으면 무엇이 잘못 나왔는지 알려 주고 더 구체적으로 다시
        prompt = (f"{d['image_prompt']} IMPORTANT: a previous attempt wrongly showed {v['seen']}. "
                  f"{v['fix']} The photo must clearly show {must}.")


def _try_pexels(d, limit):
    queries = list(dict.fromkeys(q for q in (d.get("photo_query"), d.get("subject_en")) if q))
    seen, checked = set(), 0
    for q in queries:
        try:
            found = pexels_photos(q)
        except Exception as e:
            print(f"[images] Pexels 실패 ({q}): {e}")
            continue
        for url, author in found:
            if url in seen or checked >= limit:
                continue
            seen.add(url)
            checked += 1
            try:
                yield download(url), f"Pexels 무료 사진 (작가: {author})"
            except Exception as e:
                print(f"[images] Pexels 사진 받기 실패: {e}")


def get_checked_image(d, prefer_free=False):
    """(사진, 설명, 검수결과). 검수결과: True 일치 / False 끝내 불일치 / None 검수 못 함.

    d는 초안 dict (subject, subject_en, text, image_prompt, photo_query 사용).
    """
    subject, subject_en, text = d.get("subject", ""), d.get("subject_en", ""), d.get("text", "")
    sources = [_try_pexels(d, PEXELS_CHECKS), _try_gemini(d, GEMINI_TRIES)]
    if not prefer_free:
        sources.reverse()
    first = None  # 끝내 맞는 사진이 없을 때 쓸 첫 사진
    for source in sources:
        try:
            data, note = next(source)
            while True:
                v = _verify(data, subject, subject_en, text)
                if v is None:
                    return data, note, None
                if v["match"]:
                    return data, f"{note} · ✅ 글과 일치 확인", True
                if first is None:
                    first = (data, f"{note} · ⚠️ 검수 불일치: 사진에 '{v['seen']}'이(가) 보여요", False)
                data, note = source.send(v)
        except StopIteration:
            pass
    if first:
        return first
    return None, "사진 준비 실패", None
