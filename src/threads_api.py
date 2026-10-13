"""Meta Threads API로 글을 올리고 첫 댓글을 단다."""

import os
import time

import requests

BASE = "https://graph.threads.net/v1.0"
TIMEOUT = 30


def _token():
    return os.environ["THREADS_ACCESS_TOKEN"]


def _post(path, **params):
    resp = requests.post(f"{BASE}/{path}", data={**params, "access_token": _token()}, timeout=TIMEOUT)
    body = resp.json()
    if resp.status_code != 200 or "error" in body:
        raise RuntimeError(f"쓰레드 API 오류 ({path}): {body.get('error', body)}")
    return body


def _get(path, **params):
    resp = requests.get(f"{BASE}/{path}", params={**params, "access_token": _token()}, timeout=TIMEOUT)
    body = resp.json()
    if resp.status_code != 200 or "error" in body:
        raise RuntimeError(f"쓰레드 API 오류 ({path}): {body.get('error', body)}")
    return body


def _wait_ready(container_id, tries=10):
    """컨테이너(올릴 준비물)가 처리 완료될 때까지 기다린다."""
    for _ in range(tries):
        status = _get(container_id, fields="status,error_message")
        if status.get("status") == "FINISHED":
            return
        if status.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"쓰레드 준비 실패: {status.get('error_message')}")
        time.sleep(6)
    raise RuntimeError("쓰레드 준비가 너무 오래 걸려요")


def _publish(container_id):
    _wait_ready(container_id)
    return _post("me/threads_publish", creation_id=container_id)["id"]


def post(text, image_url=None, reply_to_id=None):
    """글(또는 댓글)을 올리고 게시물 ID를 돌려준다."""
    params = {"text": text}
    if image_url:
        params.update(media_type="IMAGE", image_url=image_url)
    else:
        params["media_type"] = "TEXT"
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    container = _post("me/threads", **params)["id"]
    return _publish(container)


def permalink(post_id):
    try:
        return _get(post_id, fields="permalink").get("permalink", "")
    except RuntimeError:
        return ""
