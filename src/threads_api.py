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


def _publish(container_id, tries=4, wait_tries=10):
    _wait_ready(container_id, wait_tries)
    for i in range(tries):
        try:
            return _post("me/threads_publish", creation_id=container_id)["id"]
        except RuntimeError as e:  # 'Media Not Found'는 준비가 덜 된 것이라 잠시 뒤 다시 하면 됨
            if "Media Not Found" not in str(e) or i == tries - 1:
                raise
            time.sleep(15)


def post(text, image_url=None, reply_to_id=None, video_url=None, quote_post_id=None, link_url=None):
    """글(또는 댓글)을 올리고 게시물 ID를 돌려준다.

    video_url: 영상 글, quote_post_id: 다른 글 인용, link_url: 글 아래 링크 카드 (글만 있을 때)
    """
    params = {"text": text}
    if video_url:
        params.update(media_type="VIDEO", video_url=video_url)
    elif image_url:
        params.update(media_type="IMAGE", image_url=image_url)
    else:
        params["media_type"] = "TEXT"
        if link_url:
            params["link_attachment"] = link_url
    if quote_post_id:
        params["quote_post_id"] = quote_post_id
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    container = _post("me/threads", **params)["id"]
    return _publish(container, wait_tries=50 if video_url else 10)  # 영상은 처리가 오래 걸려 최대 5분 기다림


def post_carousel(text, items):
    """사진·영상 여러 개를 넘겨 보는 글 하나로 올린다. items: [("photo"|"video", 공개 URL), ...] 2~20개."""
    children = []
    for kind, url in items[:20]:
        params = ({"media_type": "VIDEO", "video_url": url} if kind == "video"
                  else {"media_type": "IMAGE", "image_url": url})
        children.append(_post("me/threads", is_carousel_item="true", **params)["id"])
    has_video = any(kind == "video" for kind, _ in items)
    for child in children:  # 묶기 전에 하나하나 준비가 끝나야 함
        _wait_ready(child, 50 if has_video else 10)
    container = _post("me/threads", media_type="CAROUSEL", children=",".join(children), text=text)["id"]
    return _publish(container)


def permalink(post_id):
    try:
        return _get(post_id, fields="permalink").get("permalink", "")
    except RuntimeError:
        return ""


def my_posts_with_views(limit=50):
    """내 계정 글과 조회수를 가져온다 (조회수 많은 순)."""
    posts = _get("me/threads", fields="id,text,timestamp,permalink", limit=limit).get("data", [])
    result = []
    for p in posts:
        if not p.get("text"):
            continue
        try:
            ins = _get(f"{p['id']}/insights", metric="views,likes,replies,reposts")
            m = {x["name"]: (x.get("values") or [{}])[0].get("value", 0) for x in ins.get("data", [])}
        except RuntimeError:
            continue
        result.append({"text": p["text"], "views": m.get("views", 0), "likes": m.get("likes", 0),
                       "replies": m.get("replies", 0), "reposts": m.get("reposts", 0),
                       "date": p.get("timestamp", "")[:10]})
    return sorted(result, key=lambda x: (x["views"], x["likes"]), reverse=True)
