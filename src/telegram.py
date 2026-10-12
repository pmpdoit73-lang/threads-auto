"""텔레그램으로 초안을 보낸다."""

import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024


def _call(method, **kwargs):
    url = API.format(token=os.environ["TELEGRAM_BOT_TOKEN"], method=method)
    resp = requests.post(url, timeout=30, **kwargs)
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"텔레그램 {method} 실패: {body.get('description')}")
    return body["result"]


def send_draft(caption, photo=None):
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    if photo:
        if len(caption) <= CAPTION_LIMIT:
            return _call("sendPhoto", data={"chat_id": chat_id, "caption": caption},
                         files={"photo": ("draft.png", photo)})
        _call("sendPhoto", data={"chat_id": chat_id}, files={"photo": ("draft.png", photo)})
    return _call("sendMessage", data={"chat_id": chat_id, "text": caption,
                                      "disable_web_page_preview": "true"})


def send_text(text):
    return _call("sendMessage", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text})
