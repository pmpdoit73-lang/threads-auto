"""사진을 인터넷 주소(URL)로 올린다.

쓰레드 API는 사진 파일을 직접 받지 않고 공개 URL만 받는다.
무료 사진 저장소 몇 곳을 차례로 시도해서, 처음 성공한 곳의 주소를 쓴다.

실행: python src/hosting.py  → 저장소마다 시험 업로드 결과를 보여 줌
"""

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (threads-auto)"}
TIMEOUT = 60


def _litterbox(image_bytes, filename):
    resp = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                         headers=HEADERS, timeout=TIMEOUT,
                         data={"reqtype": "fileupload", "time": "72h"},
                         files={"fileToUpload": (filename, image_bytes, "image/png")})
    resp.raise_for_status()
    return resp.text.strip()


def _uguu(image_bytes, filename):
    resp = requests.post("https://uguu.se/upload", headers=HEADERS, timeout=TIMEOUT,
                         files={"files[]": (filename, image_bytes, "image/png")})
    resp.raise_for_status()
    return resp.json()["files"][0]["url"]


def _tmpfiles(image_bytes, filename):
    resp = requests.post("https://tmpfiles.org/api/v1/upload", headers=HEADERS, timeout=TIMEOUT,
                         files={"file": (filename, image_bytes, "image/png")})
    resp.raise_for_status()
    url = resp.json()["data"]["url"]
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)  # 사진 자체로 바로 가는 주소


HOSTS = [("litterbox", _litterbox), ("uguu", _uguu), ("tmpfiles", _tmpfiles)]


def upload_temp(image_bytes, filename="post.png"):
    errors = []
    for name, upload in HOSTS:
        try:
            url = upload(image_bytes, filename)
            if url.startswith("https://"):
                print(f"[hosting] {name} 업로드 성공: {url}")
                return url
            errors.append(f"{name}: {url[:100]}")
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")
    raise RuntimeError("사진 업로드 실패 (" + " / ".join(errors) + ")")


if __name__ == "__main__":
    import base64
    # 1x1 픽셀 PNG
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    for name, upload in HOSTS:
        try:
            print(name, "→", upload(png, "test.png"))
        except Exception as e:
            print(name, "실패:", e)
