"""텔레그램 봇: 초안 전송, 버튼, 버튼 눌림 확인."""

import json
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


def _chat_id():
    return os.environ["TELEGRAM_CHAT_ID"]


def send_text(text, keyboard=None, silent=False):
    data = {"chat_id": _chat_id(), "text": text, "disable_web_page_preview": "true",
            "disable_notification": str(silent).lower()}
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    return _call("sendMessage", data=data)


def send_draft(caption, photo=None, keyboard=None, silent=False):
    """초안을 보내고 버튼이 달린 메시지를 돌려준다."""
    caption = caption[:CAPTION_LIMIT]
    if not photo:
        return send_text(caption, keyboard, silent)
    data = {"chat_id": _chat_id(), "caption": caption, "disable_notification": str(silent).lower()}
    if keyboard:
        data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    return _call("sendPhoto", data=data, files={"photo": ("draft.png", photo)})


def edit_draft(message, caption, keyboard=None):
    """이미 보낸 초안의 글자와 버튼을 바꾼다."""
    markup = json.dumps({"inline_keyboard": keyboard or []})
    base = {"chat_id": _chat_id(), "message_id": message["message_id"], "reply_markup": markup}
    try:
        if message.get("has_photo"):
            _call("editMessageCaption", data={**base, "caption": caption[:CAPTION_LIMIT]})
        else:
            _call("editMessageText", data={**base, "text": caption, "disable_web_page_preview": "true"})
    except RuntimeError as e:
        if "not modified" not in str(e):  # 같은 내용으로 다시 고치면 나는 오류는 무시
            raise


def answer(callback_id, text=""):
    try:
        _call("answerCallbackQuery", data={"callback_query_id": callback_id, "text": text})
    except RuntimeError:
        pass  # 오래된 버튼은 응답 기한이 지나 실패할 수 있음


def get_updates(offset):
    return _call("getUpdates", data={"offset": offset, "timeout": 0,
                                     "allowed_updates": json.dumps(["callback_query"])})

