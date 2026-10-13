"""사진을 인터넷 주소(URL)로 올린다.

쓰레드 API는 사진 파일을 직접 받지 않고 공개 URL만 받는다.
게시할 때만 잠깐 필요하므로 72시간 뒤 자동 삭제되는 무료 임시 저장소(litterbox)를 쓴다.
"""

import requests


def upload_temp(image_bytes, filename="post.png"):
    resp = requests.post(
        "https://litterbox.catbox.moe/resources/internals/api.php",
        data={"reqtype": "fileupload", "time": "72h"},
        files={"fileToUpload": (filename, image_bytes)},
        timeout=60,
    )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("https://"):
        raise RuntimeError(f"사진 업로드 실패: {url[:200]}")
    return url
