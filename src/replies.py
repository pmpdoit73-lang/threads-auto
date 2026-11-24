"""내 쓰레드 글에 달린 새 댓글 → 반말 답글을 써서 올린다.

AUTO_MODE = True (자동 모드):
  - 단순 공감·칭찬·경험 나눔 댓글 → 확인 없이 다음 회차(약 20분 뒤)에 자동으로 올림.
    텔레그램엔 알림만 옴 (올리기 전엔 '🚫 올리지 말기', 올린 뒤엔 '🗑 답글 삭제' 버튼).
  - 질문·가격/구매 문의·불만·민감한 댓글 → 예전처럼 ✅를 눌러야 올림.
  - 뜻이 애매한 댓글 → 답글도 알림도 없이 그냥 넘김 (IGNORE_VAGUE).
AUTO_MODE = False (승인 모드): 모든 답글을 ✅를 눌러야 올림 (예전 방식).

poll.py가 20분마다 부른다. 상태는 state/replies.json 하나에 저장.
"""

import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import draft
import telegram
import threads_api
import writer

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "replies.json"

POSTS_TO_CHECK = 10            # 최근 글 몇 개의 댓글을 볼지 (하루 4개 → 약 2.5일치)
FIRST_RUN_WINDOW = timedelta(hours=48)  # 처음 켰을 때는 최근 48시간 댓글만
MAX_NEW_PER_RUN = 8            # 한 번에 텔레그램으로 보낼 새 댓글 수
MAX_POST_PER_RUN = 3           # 한 번에 올릴 답글 수 (몰아서 올리면 스팸처럼 보임)
DAILY_LIMIT = 40               # 하루에 올릴 답글 수 상한
GAP_SECONDS = (20, 60)         # 같은 회차 안에서 답글 사이 쉬는 시간 (초, 랜덤)
EXPIRE_AFTER = timedelta(days=3)  # 이만큼 지난 대기 댓글은 정리
# 자동 모드 스위치. 예전처럼 전부 승인받고 올리려면 False로 바꾸면 끝.
AUTO_MODE = True
IGNORE_VAGUE = True            # 뜻이 애매한 댓글은 텔레그램에 안 보내고 조용히 넘김
AUTO_MAX_LEN = 120             # 이보다 긴 답글은 자동으로 안 올리고 확인받음
# 이런 말이 들어간 댓글은 AI가 괜찮다고 해도 무조건 확인받음 (질문·구매 문의·불만·민감)
ASK_RE = re.compile(
    r"[?？]|얼마|가격|어디서|어디꺼|어디 거|구매|구입|파나요|팔아|링크|제품명|모델명|브랜드|정보 ?좀|알려 ?줘|알려주|"
    r"뭐(예요|에요|야|임|죠|지)|어떻게|왜|맞나|맞아요|되나|"
    r"광고|홍보|뒷광고|협찬|사기|거짓|틀[렸린리]|잘못|아닌[데가지]|아니던데|아니에요|아니죠|별로|실망|환불|고장|불량|위험|다쳤|화재|불나|병원|아파",
)
URL_RE = re.compile(r"\S*(https?://|www\.)\S*|\S+\.(com|kr|net|co)\b\S*", re.I)

STATUS_LABEL = {
    "pending": "⏳ 대기 중",
    "approved": "✅ 승인됨 (곧 올라가요)",
    "auto": "⏰ 약 20분 뒤 자동으로 올라가요",
    "sent": "🎉 답글 올림",
    "deleted": "🗑 답글 삭제함",
    "skipped": "⏭ 무시함",
    "failed": "⚠️ 올리기 실패",
    "expired": "⌛ 오래돼서 정리함",
    "ignored": "🙈 애매해서 그냥 넘김",
}


# ---------- 저장 ----------

def load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"seen": [], "items": {}}


def save(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    state["seen"] = state["seen"][-2000:]  # 너무 길어지지 않게
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _now():
    return datetime.now(draft.KST)


def _parse(ts):
    """쓰레드 시간 '2026-11-06T05:58:21+0000' → datetime."""
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


# ---------- 새 댓글 찾기 ----------

def _my_username():
    return threads_api._get("me", fields="username").get("username", "")


def _already_answered(comment_id, me):
    """그 댓글에 내가(앱이든 손으로든) 이미 답을 달았는지."""
    try:
        sub = threads_api._get(f"{comment_id}/replies", fields="id,username").get("data", [])
    except RuntimeError:
        return False
    return any(x.get("username") == me for x in sub)


def find_new(state, me):
    first_run = not state["seen"]
    seen = set(state["seen"])
    found = []
    posts = threads_api._get("me/threads", fields="id,text", limit=POSTS_TO_CHECK).get("data", [])
    for p in posts:
        try:
            rows = threads_api._get(f"{p['id']}/replies", fields="id,text,username,timestamp").get("data", [])
        except RuntimeError as e:
            print(f"[replies] {p['id']} 댓글 읽기 실패: {e}")
            continue
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            state["seen"].append(r["id"])
            if r.get("username") == me or not (r.get("text") or "").strip():
                continue  # 내 댓글(쿠팡·인스타 홍보)·사진만 있는 댓글은 건너뜀
            when = _parse(r.get("timestamp"))
            if first_run and when and _now() - when > FIRST_RUN_WINDOW:
                continue
            if _already_answered(r["id"], me):
                continue
            found.append({"id": r["id"], "post_id": p["id"], "post_text": (p.get("text") or "")[:300],
                          "user": r.get("username", ""), "text": r["text"][:500],
                          "commented_at": r.get("timestamp", "")})
    return found


# ---------- 답글 초안 ----------

def _recent_sent(state, n=30):
    sent = [x for x in state["items"].values() if x.get("status") == "sent"]
    sent.sort(key=lambda x: x.get("sent_at", ""))
    return [x["reply"] for x in sent[-n:]]


def _clean(text):
    """링크가 섞이면 지운다 (답글에 링크 = 스팸 신호)."""
    return re.sub(r"\s{2,}", " ", URL_RE.sub("", text)).strip()


def _can_auto(c, r):
    """확인 없이 올려도 되는 댓글인지. AI 판단 + 글자 규칙 두 겹으로 막는다."""
    return (AUTO_MODE and r.get("auto_ok") and not r["skip"]
            and c["reply"] and len(c["reply"]) <= AUTO_MAX_LEN
            and not ASK_RE.search(c["text"]))


def draft_replies(state, comments):
    results = writer.write_replies(comments, _recent_sent(state))
    by_id = {r["id"]: r for r in results}
    for c in comments:
        r = by_id.get(c["id"], {"skip": True, "reason": "초안을 못 만들었어요", "reply": ""})
        c.update(reply=_clean(r["reply"]), suggest_skip=r["skip"], reason=r["reason"],
                 status="pending", created_at=_now().isoformat())
        if IGNORE_VAGUE and r.get("vague") and not ASK_RE.search(c["text"]):
            c["status"], c["reason"] = "ignored", "뜻이 애매한 댓글"
        elif _can_auto(c, r):
            c["status"], c["auto_ok"] = "auto", True
        state["items"][c["id"]] = c


# ---------- 텔레그램 ----------

def caption(c):
    head = "🤖 자동 답글" if c.get("auto_ok") else "💬 새 댓글"
    lines = [f"{head} · {STATUS_LABEL[c['status']]}",
             f"📝 내 글: {c['post_text'][:40].splitlines()[0] if c['post_text'] else '(사진 글)'}…",
             f"👤 @{c['user']}: {c['text']}", ""]
    if c.get("suggest_skip"):
        lines.append(f"🤖 답 안 하는 걸 추천해요: {c.get('reason', '')}")
    lines.append(f"✍️ 답글 초안:\n{c['reply'] or '(없음)'}")
    if c["status"] == "pending":
        lines += ["", "고치고 싶으면 이 메시지에 '답장'으로 새 답글을 보내 주세요."]
    elif c["status"] == "auto":
        lines += ["", "그냥 두면 자동으로 올라가요. 싫으면 🚫, 고치고 싶으면 '답장'으로 새 답글을 보내 주세요."]
    if c.get("error"):
        lines += ["", f"⚠️ {c['error'][:200]}"]
    return "\n".join(lines)


def keyboard(c):
    cid = c["id"]
    if c["status"] == "pending":
        row = [{"text": "✅ 답글 올리기", "callback_data": f"c|{cid}|ok"},
               {"text": "🔄 다시 쓰기", "callback_data": f"c|{cid}|redo"},
               {"text": "⏭ 무시", "callback_data": f"c|{cid}|skip"}]
        return [row] if c["reply"] else [row[1:]]
    if c["status"] == "approved":
        return [[{"text": "↩️ 승인 취소", "callback_data": f"c|{cid}|undo"}]]
    if c["status"] == "auto":
        return [[{"text": "🚫 올리지 말기", "callback_data": f"c|{cid}|skip"},
                 {"text": "⏸ 확인하고 올릴게", "callback_data": f"c|{cid}|undo"}]]
    if c["status"] == "sent" and c.get("reply_id"):
        return [[{"text": "🗑 답글 삭제", "callback_data": f"c|{cid}|del"}]]
    if c["status"] == "failed":
        return [[{"text": "🔁 다시 올리기", "callback_data": f"c|{cid}|ok"},
                 {"text": "⏭ 무시", "callback_data": f"c|{cid}|skip"}]]
    return []


def send(c):
    quiet = _now().hour < 7 or c["status"] == "auto"  # 자동 답글은 소리 없이 알림만
    msg = telegram.send_text(caption(c), keyboard(c), silent=quiet)
    c["message_id"] = msg["message_id"]


def refresh(c):
    if c.get("message_id"):
        telegram.edit_draft({"message_id": c["message_id"], "has_photo": False}, caption(c), keyboard(c))


# ---------- 버튼·답장 처리 (poll.py가 부름) ----------

def handle_button(data):
    """callback_data 'c|댓글ID|동작' 처리 → 버튼 위에 띄울 짧은 글."""
    _, cid, action = data.split("|")
    state = load()
    c = state["items"].get(cid)
    if not c:
        return "이 댓글을 찾을 수 없어요"
    if action == "del":
        if c["status"] != "sent" or not c.get("reply_id"):
            return f"지울 답글이 없어요 ({STATUS_LABEL[c['status']]})"
        try:
            threads_api.delete(c["reply_id"])
        except Exception as e:
            print(f"[replies] 답글 삭제 실패: {e}")
            return "삭제 실패. 쓰레드 앱에서 직접 지워 주세요"
        c["status"], c["deleted_at"] = "deleted", _now().isoformat()
        save(state)
        refresh(c)
        return "답글을 지웠어요"
    if c["status"] in ("sent", "skipped", "expired", "deleted", "ignored"):
        return f"이미 처리된 댓글이에요 ({STATUS_LABEL[c['status']]})"
    if action == "ok":
        if not c["reply"]:
            return "답글 초안이 없어요. 🔄 다시 쓰기를 눌러 주세요"
        c["status"], note = "approved", "승인! 곧 올릴게요"
        c.pop("error", None)
    elif action == "undo" and c["status"] in ("approved", "auto"):
        c["status"], note = "pending", "자동 게시 멈춤. 확인하고 ✅를 눌러 주세요" if c["status"] == "auto" else "승인 취소"
    elif action == "skip":
        c["status"], note = "skipped", "이 댓글은 넘어갈게요"
    elif action == "redo":
        r = writer.write_replies([c], _recent_sent(state) + [c["reply"]], force=True)[0]
        c.update(reply=_clean(r["reply"]), suggest_skip=False, reason="", status="pending")
        note = "새로 썼어요"
    else:
        return "알 수 없는 버튼이에요"
    save(state)
    refresh(c)
    return note


def find_by_message(message_id):
    for c in load()["items"].values():
        if c.get("message_id") == message_id:
            return c
    return None


def set_text(message_id, text):
    """댓글 메시지에 답장으로 보낸 글 → 그 답글 초안을 바꾼다. 처리했으면 True."""
    state = load()
    c = next((x for x in state["items"].values() if x.get("message_id") == message_id), None)
    if not c:
        return False
    if c["status"] not in ("pending", "approved", "failed", "auto"):
        telegram.send_text(f"✏️ 이미 처리된 댓글이에요 ({STATUS_LABEL[c['status']]})")
        return True
    text = text.strip()
    if URL_RE.search(text):
        telegram.send_text("✏️ 답글에 링크가 있으면 스팸으로 볼 수 있어서 못 넣어요. 링크 빼고 다시 보내 주세요.")
        return True
    c.update(reply=text[:500], suggest_skip=False, reason="", status="pending")
    save(state)
    refresh(c)
    telegram.send_text("✏️ 답글을 바꿨어요. 위 메시지에서 ✅ 답글 올리기를 눌러 주세요.")
    return True


# ---------- 한 회차 실행 ----------

def _sent_today(state):
    today = _now().date().isoformat()
    return sum(1 for x in state["items"].values()
               if x.get("status") == "sent" and x.get("sent_at", "").startswith(today))


def post_approved(state, me):
    # 자동 모드를 끄면 'auto'로 기다리던 답글은 확인 대기로 돌림
    if not AUTO_MODE:
        for x in state["items"].values():
            if x["status"] == "auto":
                x["status"] = "pending"
                refresh(x)
    queue = sorted((x for x in state["items"].values() if x["status"] in ("approved", "auto")),
                   key=lambda x: x.get("commented_at", ""))
    room = min(MAX_POST_PER_RUN, DAILY_LIMIT - _sent_today(state))
    for i, c in enumerate(queue[:max(room, 0)]):
        if i:
            time.sleep(random.randint(*GAP_SECONDS))
        if _already_answered(c["id"], me):  # 그 사이 손으로 답했으면 두 번 달지 않음
            c["status"], c["error"] = "skipped", "이미 직접 답글을 다셨네요"
        else:
            try:
                c["reply_id"] = threads_api.post(c["reply"], reply_to_id=c["id"])
                c["status"], c["sent_at"] = "sent", _now().isoformat()
                c.pop("error", None)
                print(f"[replies] @{c['user']} 댓글에 답글 올림")
            except Exception as e:
                c["status"], c["error"] = "failed", str(e)
                print(f"[replies] 답글 실패: {e}")
        save(state)
        refresh(c)
    if room <= 0 and queue:
        print(f"[replies] 오늘 답글 {DAILY_LIMIT}개를 채워서 내일 올림")


def expire_old(state):
    for c in state["items"].values():
        made = datetime.fromisoformat(c["created_at"]) if c.get("created_at") else None
        if c["status"] == "pending" and made and _now() - made > EXPIRE_AFTER:
            c["status"] = "expired"
            try:
                refresh(c)
            except Exception:
                pass
    # 끝난 지 오래된 항목은 지워서 파일을 가볍게 (seen에는 남아 다시 안 잡힘)
    old = [k for k, c in state["items"].items()
           if c["status"] in ("sent", "skipped", "expired", "deleted", "ignored")
           and c.get("created_at") and _now() - datetime.fromisoformat(c["created_at"]) > timedelta(days=30)]
    for k in old:
        del state["items"][k]


def run():
    state = load()
    me = _my_username()
    post_approved(state, me)
    new = find_new(state, me)
    save(state)  # 본 댓글은 먼저 저장 (초안 만들다 멈춰도 같은 댓글을 계속 잡지 않게)
    if new:
        batch = new[:MAX_NEW_PER_RUN]
        draft_replies(state, batch)
        for c in batch:
            if c["status"] == "ignored":
                print(f"[replies] @{c['user']} 댓글은 애매해서 넘김: {c['text'][:30]}")
                continue
            send(c)
            save(state)
        print(f"[replies] 새 댓글 {len(batch)}개 처리")
        for c in new[MAX_NEW_PER_RUN:]:  # 너무 많으면 다음 회차로 넘김
            state["seen"].remove(c["id"])
    expire_old(state)
    save(state)
