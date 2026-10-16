"""20분마다 실행: 텔레그램 버튼 눌림을 반영하고, 시간이 된 초안을 쓰레드에 올린다.

실행: python src/poll.py
"""

import sys
from datetime import datetime
from pathlib import Path

import benchmarks
import draft
import hosting
import telegram
import threads_api
import writer

OFFSET_FILE = Path(__file__).resolve().parent.parent / "state" / "telegram_offset.txt"


def _bot_id():
    return telegram.bot_id()


def read_offset():
    """저장된 위치를 읽는다. 봇이 바뀌었으면 처음(0)부터."""
    try:
        text = OFFSET_FILE.read_text().strip()
        if ":" not in text:  # 예전 형식(봇 번호 없음)은 지금 봇 것으로 봄
            return int(text)
        bot, value = text.split(":")
        return int(value) if bot == _bot_id() else 0
    except (FileNotFoundError, ValueError):
        return 0


def write_offset(value):
    OFFSET_FILE.parent.mkdir(exist_ok=True)
    OFFSET_FILE.write_text(f"{_bot_id()}:{value}")


def bot_changed():
    """봇을 새로 바꿨는지 (저장된 봇 번호와 다르면 바뀐 것)."""
    try:
        text = OFFSET_FILE.read_text().strip()
    except FileNotFoundError:
        return False
    return ":" in text and text.split(":")[0] != _bot_id()


def resend_open_drafts():
    """봇을 바꾸면 옛 봇 메시지의 버튼은 새 봇에 안 닿으니, 열린 초안을 새 봇으로 다시 보낸다."""
    for d in draft.open_drafts():
        if d["status"] in ("pending", "approved"):
            draft.send(d)
            print(f"[poll] 새 봇으로 {d['id']} 다시 보냄")


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
        return "새 이슈로 새로 썼어요"
    elif value == "retext":
        draft.retext(d)
        draft.send(d)
        return "같은 이슈로 글만 새로 썼어요"
    elif value == "photo":
        draft.new_photo(d)
        draft.send(d)
        return "사진을 바꿨어요"
    else:
        return "알 수 없는 버튼이에요"

    draft.save(d)
    draft.refresh(d)
    return msg


def find_by_message(message_id):
    for d in draft.open_drafts():
        if (d.get("message") or {}).get("message_id") == message_id:
            return d
    return None


def handle_text(message):
    """초안 메시지에 답장으로 보낸 글 → 그 초안의 글을 바꾼다."""
    target = (message.get("reply_to_message") or {}).get("message_id")
    if not target:
        return  # 그냥 보낸 대화는 무시
    d = find_by_message(target)
    if not d:
        telegram.send_text("✏️ 이 메시지는 지금 고칠 수 있는 초안이 아니에요. 가장 최근 초안 메시지에 답장해 주세요.")
        return
    try:
        draft.set_text(d, message.get("text", ""))
    except ValueError as e:
        telegram.send_text(f"✏️ 글을 못 바꿨어요: {e}")
        return
    draft.send(d)
    print(f"[poll] {d['id']} 글을 직접 고친 글로 바꿈")


def handle_snapshot(message):
    """그냥 보낸 사진 → 벤치마킹할 인기글 스냅샷으로 읽어 저장한다."""
    if message.get("photo"):
        file_id = max(message["photo"], key=lambda p: p.get("file_size", 0))["file_id"]
    else:  # 사진을 '파일'로 보낸 경우
        file_id = message["document"]["file_id"]
    image = telegram.download_file(file_id)
    info = writer.read_snapshot(image, message.get("caption", ""))
    if not info["is_post"] or not info["text"].strip():
        telegram.send_text("📊 쓰레드 글 화면이 아닌 것 같아요. 글 본문과 조회수가 보이게 캡처해서 다시 보내 주세요.")
        return
    total = benchmarks.add(info)
    views = f"{info['views']:,}" if info["views"] >= 0 else "안 보임"
    rules = "\n".join(f"• {r}" for r in info["format_rules"])
    telegram.send_text(
        f"📊 벤치마킹 글 저장 ({total}개째)\n\n"
        f"👀 조회 {views} · ❤️ {info['likes']} · 💬 {info['replies']}\n"
        f"🎣 후킹: {info['hook_type']}\n"
        f"💡 잘된 이유: {info['why_it_works']}\n\n"
        f"다음 초안부터 이 형식을 참고할게요:\n{rules}"
    )
    print(f"[poll] 벤치마킹 글 저장: 조회 {views}")


def process_buttons():
    offset = read_offset()
    updates = telegram.get_updates(offset)
    allowed = str(telegram._chat_id())
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message")
        if msg:
            if str(msg.get("from", {}).get("id")) == allowed and (msg.get("photo") or
                    (msg.get("document") or {}).get("mime_type", "").startswith("image/")):
                try:
                    handle_snapshot(msg)
                except Exception as e:
                    print(f"[poll] 스냅샷 읽기 실패: {e}")
                    telegram.send_text(f"📊 스냅샷 읽기 실패: {str(e)[:150]}")
            elif str(msg.get("from", {}).get("id")) == allowed and msg.get("text"):
                try:
                    handle_text(msg)
                except Exception as e:
                    print(f"[poll] 글 고치기 실패: {e}")
                    telegram.send_text(f"✏️ 글 고치기 실패: {str(e)[:150]}")
            write_offset(offset)
            continue
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
        if bot_changed():
            resend_open_drafts()
            write_offset(0)
        process_buttons()
        process_schedule()
    except Exception as e:
        print(f"[poll] 실패: {e}")
        try:
            telegram.send_text(f"⚠️ 버튼 처리 중 오류: {e}")
        except Exception:
            pass
        sys.exit(1)
