"""10분마다 실행: 텔레그램 버튼 눌림을 반영하고, 시간이 된 초안을 쓰레드에 올린다.

실행: python src/poll.py
"""

import sys
from datetime import datetime
from pathlib import Path

import draft
import hosting
import telegram
import threads_api

OFFSET_FILE = Path(__file__).resolve().parent.parent / "state" / "telegram_offset.txt"


def read_offset():
    try:
        return int(OFFSET_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def write_offset(value):
    OFFSET_FILE.parent.mkdir(exist_ok=True)
    OFFSET_FILE.write_text(str(value))


# ---------- 게시 ----------

def publish(d):
    image_url = None
    if draft.wants_photo(d):
        image_url = hosting.upload_temp(draft.photo_bytes(d), f"{d['id']}.png")
    post_id = threads_api.post(d["text"], image_url=image_url)
    d["threads_id"] = post_id
    d["permalink"] = threads_api.permalink(post_id)

    if draft.wants_coupang(d):
        product = draft.chosen_product(d)
        comment = f"{product['url']}\n\n{draft.COUPANG_NOTICE}"
        d["reply_id"] = threads_api.post(comment, reply_to_id=post_id)
    d["status"] = "published"
    d["published_at"] = datetime.now(draft.KST).isoformat()


def try_publish(d):
    d.pop("error", None)
    try:
        publish(d)
        print(f"[poll] {d['id']} 게시 완료: {d.get('permalink')}")
    except Exception as e:
        print(f"[poll] {d['id']} 게시 실패: {e}")
        d["status"] = "failed"
        d["error"] = str(e)
    draft.save(d)
    draft.refresh(d)


# ---------- 버튼 처리 ----------

def handle(callback):
    try:
        draft_id, kind, value = callback["data"].split("|")
    except ValueError:
        return "알 수 없는 버튼이에요"
    d = draft.load(draft_id)
    if not d:
        return "초안을 찾을 수 없어요"
    if d["status"] == "failed" and value not in ("now", "skip"):
        return "게시 실패한 초안은 🔁 다시 게시 또는 ⏭ 건너뛰기만 돼요"
    if d["status"] not in ("pending", "approved", "failed"):
        return f"이미 처리된 초안이에요 ({draft.STATUS_LABEL[d['status']]})"

    if kind == "f":
        if value in ("both", "photo") and not d.get("has_photo"):
            return "사진이 없어요. 🖼 다른 사진을 먼저 눌러 주세요"
        if value in ("both", "coupang") and not d.get("products"):
            return "쿠팡 후보가 없어요"
        d["format"] = value
        msg = f"{draft.FORMATS[value]} 선택"
    elif kind == "p":
        d["product"] = int(value)
        msg = f"상품 {int(value) + 1} 선택"
    elif value == "ok":
        d["status"] = "approved"
        msg = "승인! 예약 시간에 올릴게요"
    elif value == "undo":
        d["status"] = "pending"
        msg = "승인 취소"
    elif value == "skip":
        d["status"] = "skipped"
        msg = "이번 회차는 건너뛸게요"
    elif value == "now":
        try_publish(d)
        return "게시 완료!" if d["status"] == "published" else "게시 실패, 메시지를 확인해 주세요"
    elif value == "rewrite":
        draft.rewrite(d)
        draft.send(d)
        return "새로 썼어요"
    elif value == "photo":
        draft.new_photo(d)
        draft.send(d)
        return "사진을 바꿨어요"
    else:
        return "알 수 없는 버튼이에요"

    draft.save(d)
    draft.refresh(d)
    return msg


def process_buttons():
    offset = read_offset()
    updates = telegram.get_updates(offset)
    allowed = str(telegram._chat_id())
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        cb = u.get("callback_query")
        if not cb:
            continue
        if str(cb.get("from", {}).get("id")) != allowed:  # 다른 사람이 누른 버튼은 무시
            continue
        try:
            note = handle(cb)
        except Exception as e:
            print(f"[poll] 버튼 처리 실패: {e}")
            note = f"처리 실패: {str(e)[:150]}"
        telegram.answer(cb["id"], note)
        write_offset(offset)  # 한 건 처리할 때마다 저장해서 중간에 멈춰도 중복 처리 안 되게
    write_offset(offset)


# ---------- 시간 확인 ----------

def process_schedule():
    now = datetime.now(draft.KST)
    for d in draft.open_drafts():
        if draft.publish_time(d) > now:
            continue
        if d["status"] == "approved":
            try_publish(d)
        else:  # 시간까지 승인 안 됨 → 건너뜀
            d["status"] = "skipped"
            draft.save(d)
            draft.refresh(d)
            print(f"[poll] {d['id']} 승인 없이 시간이 지나 건너뜀")


if __name__ == "__main__":
    try:
        process_buttons()
        process_schedule()
    except Exception as e:
        print(f"[poll] 실패: {e}")
        try:
            telegram.send_text(f"⚠️ 버튼 처리 중 오류: {e}")
        except Exception:
            pass
        sys.exit(1)
