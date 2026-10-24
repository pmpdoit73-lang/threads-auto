"""새 계정 프로필 사진 후보 3장을 Gemini로 만들어 텔레그램으로 보낸다 (한 번만 쓰는 도구)."""

import base64
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
import telegram  # noqa: E402
from images import GEMINI_IMAGE_MODEL, TIMEOUT  # noqa: E402

COMMON = (
    "Square 1:1 profile picture for a Korean home-living tips account (honey tips for housekeeping). "
    "Looks like a real, bright, clean smartphone photo, not an ad, not AI art, not an illustration. "
    "Soft natural window daylight, warm and friendly, tidy. The main subject sits in the center and fills it, "
    "so it still reads clearly inside a small circle crop. No text, no letters, no logos, no watermarks, no people, no faces. Scene: "
)

CANDIDATES = [
    ("① 꿀단지와 살림템", "a small glass jar of golden honey with a wooden honey dipper on a white Korean kitchen counter, "
     "a neatly folded white kitchen towel, a small spray bottle and a lemon around it"),
    ("② 반짝이는 주방", "a spotless white Korean apartment kitchen sink and counter, a shiny stainless pot, "
     "a yellow sponge and a small honey jar, everything very neat and gleaming"),
    ("③ 살림 바구니", "a woven basket viewed from slightly above, filled with everyday household items: "
     "a microfiber cloth, a small brush, a measuring cup, a jar of baking soda and a small honey jar, on a light wooden table"),
]


def make(scene):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": COMMON + scene}]}]}
    resp = requests.post(url, params={"key": os.environ["GEMINI_API_KEY"]}, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    for cand in resp.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    raise RuntimeError("Gemini 응답에 이미지가 없음")


def main():
    telegram.send_text("🖼 새 계정 프로필 사진 후보예요. 마음에 드는 사진을 길게 눌러 저장한 뒤 쓰레드 프로필에 올리세요.")
    for label, scene in CANDIDATES:
        try:
            telegram.send_draft(f"프로필 사진 {label}", photo=make(scene))
        except Exception as e:
            print(f"[profile_pic] {label} 실패: {e}")
            telegram.send_text(f"프로필 사진 {label} 만들기 실패")


if __name__ == "__main__":
    main()
