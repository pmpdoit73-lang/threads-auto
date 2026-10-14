"""초안 한 건의 생성·저장·텔레그램 표시를 담당한다.

초안은 drafts/<id>.json 과 drafts/<id>.png 로 저장소에 기록된다.
status: pending(선택 대기) → approved(승인) → published(게시 완료)
        또는 skipped(건너뜀) / failed(게시 실패)
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import coupang
import images
import telegram
import trends
import writer

KST = timezone(timedelta(hours=9))
DRAFT_DIR = Path(__file__).resolve().parent.parent / "drafts"

FORMATS = {
    "both": "📷+🛒 사진+쿠팡",
    "photo": "📷 사진만",
    "coupang": "🛒 쿠팡만",
    "text": "📝 글만",
}
STATUS_LABEL = {
    "pending": "⏳ 선택 대기 중",
    "approved": "✅ 승인됨 (예약 시간에 게시)",
    "published": "🎉 게시 완료",
    "skipped": "⏭ 건너뜀",
    "failed": "⚠️ 게시 실패",
}

COUPANG_NOTICE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


# ---------- 저장 ----------

def path(draft_id, ext="json"):
    return DRAFT_DIR / f"{draft_id}.{ext}"


def load(draft_id):
    p = path(draft_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(d):
    DRAFT_DIR.mkdir(exist_ok=True)
    path(d["id"]).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def photo_bytes(d):
    p = path(d["id"], "png")
    return p.read_bytes() if d.get("has_photo") and p.exists() else None


def open_drafts():
    """아직 게시·건너뛰기 전인 초안들."""
    result = []
    for p in sorted(DRAFT_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("status") in ("pending", "approved"):
            result.append(d)
    return result


def recent_issues(n=10):
    files = sorted(DRAFT_DIR.glob("*.json"))[-n:]
    return [json.loads(f.read_text(encoding="utf-8")).get("issue", "") for f in files]


# ---------- 시간 ----------

def next_slot(now):
    """지금 이후 가장 가까운 게시 시간 (08:00 또는 20:00)."""
    today = now.replace(minute=0, second=0, microsecond=0)
    for candidate in (today.replace(hour=8), today.replace(hour=20),
                      today.replace(hour=8) + timedelta(days=1)):
        if candidate > now:
            return candidate


def publish_time(d):
    return datetime.fromisoformat(d["publish_at"])


# ---------- 내용 만들기 ----------

def _fill_content(d, avoid=()):
    collected = trends.collect()
    print(f"[draft] 이슈 수집: { {k: len(v) for k, v in collected.items()} }")
    post = writer.write_post(collected, list(recent_issues()) + list(avoid))
    print(f"[draft] 글 작성: {post['text']}")
    d.update(post)
    try:
        d["products"] = coupang.search_products(post["product_keyword"])
    except Exception as e:
        print(f"[draft] 쿠팡 검색 실패: {e}")
        d["products"] = []
    _fill_photo(d)


def _fill_photo(d, prefer_free=False):
    if prefer_free:
        data, note = None, ""
        try:
            data, author = images.pexels_photo(d["photo_query"])
            note = f"Pexels 무료 사진 (작가: {author})"
        except Exception as e:
            print(f"[draft] Pexels 실패, 제미나이로 다시: {e}")
        if not data:
            data, note = images.get_image(d["image_prompt"], d["photo_query"])
    else:
        data, note = images.get_image(d["image_prompt"], d["photo_query"])
    d["image_note"] = note
    d["has_photo"] = bool(data)
    if data:
        path(d["id"], "png").write_bytes(data)


def default_format(d):
    if d.get("has_photo") and d.get("products"):
        return "both"
    if d.get("has_photo"):
        return "photo"
    if d.get("products"):
        return "coupang"
    return "text"


def create():
    now = datetime.now(KST)
    d = {
        "id": now.strftime("%Y%m%d-%H%M"),
        "created_at": now.isoformat(),
        "publish_at": next_slot(now).isoformat(),
        "status": "pending",
        "product": 0,
    }
    _fill_content(d)
    d["format"] = default_format(d)
    save(d)
    return d


def rewrite(d):
    """같은 시간대에 다른 이슈로 다시 쓴다."""
    _fill_content(d, avoid=[d.get("issue", "")])
    d["format"] = default_format(d)
    d["product"] = 0
    save(d)


def new_photo(d):
    _fill_photo(d, prefer_free=d.get("image_note", "").startswith("제미나이"))
    save(d)


# ---------- 텔레그램 표시 ----------

def wants_photo(d):
    return d["format"] in ("both", "photo") and d.get("has_photo")


def wants_coupang(d):
    return d["format"] in ("both", "coupang") and d.get("products")


def chosen_product(d):
    products = d.get("products") or []
    return products[d.get("product", 0)] if products else None


def caption(d):
    when = publish_time(d)
    lines = [
        f"📝 {when:%m/%d} {when:%H:%M} 게시 예정",
        f"상태: {STATUS_LABEL[d['status']]}",
        "",
        d["text"],
        f"({len(d['text'])}자)",
        "",
        f"🔥 이슈: {d.get('issue', '')}",
        f"🖼 사진: {d.get('image_note', '')}",
        f"📦 형태: {FORMATS[d['format']]}",
    ]
    products = d.get("products") or []
    if products:
        lines += ["", "🛒 쿠팡 후보"]
        for i, p in enumerate(products):
            mark = "👉" if i == d.get("product", 0) else "  "
            price = f"{p['price']:,}원" if isinstance(p.get("price"), int) else ""
            lines.append(f"{mark} {i + 1}. {p['name'][:38]} {price}")
    if d.get("permalink"):
        lines += ["", f"🔗 {d['permalink']}"]
    if d.get("error"):
        lines += ["", f"⚠️ {d['error'][:200]}"]
    if d["status"] == "pending":
        lines += ["", "형태와 상품을 고르고 ✅승인을 눌러 주세요.",
                  "(버튼 반영까지 최대 10분 걸릴 수 있어요)"]
    return "\n".join(lines)


def _btn(d, label, kind, value, selected=False):
    return {"text": ("✔ " if selected else "") + label, "callback_data": f"{d['id']}|{kind}|{value}"}


def keyboard(d):
    if d["status"] == "failed":
        return [[_btn(d, "🔁 다시 게시", "a", "now"), _btn(d, "⏭ 건너뛰기", "a", "skip")]]
    if d["status"] == "approved":
        return [[_btn(d, "🚀 지금 게시", "a", "now"), _btn(d, "↩️ 승인 취소", "a", "undo")]]
    if d["status"] != "pending":
        return []
    rows = [
        [_btn(d, FORMATS["both"], "f", "both", d["format"] == "both"),
         _btn(d, FORMATS["photo"], "f", "photo", d["format"] == "photo")],
        [_btn(d, FORMATS["coupang"], "f", "coupang", d["format"] == "coupang"),
         _btn(d, FORMATS["text"], "f", "text", d["format"] == "text")],
    ]
    products = d.get("products") or []
    if products:
        rows.append([_btn(d, f"상품 {i + 1}", "p", str(i), d.get("product", 0) == i)
                     for i in range(len(products))])
    rows += [
        [_btn(d, "✍️ 다시 쓰기", "a", "rewrite"), _btn(d, "🖼 다른 사진", "a", "photo")],
        [_btn(d, "✅ 승인", "a", "ok"), _btn(d, "🚀 지금 게시", "a", "now")],
        [_btn(d, "⏭ 건너뛰기", "a", "skip")],
    ]
    return rows


def send(d):
    """초안을 새 메시지로 보낸다 (처음, 다시 쓰기, 다른 사진)."""
    old = d.get("message")
    if old:
        try:
            telegram.edit_draft(old, "↓ 아래 새 초안으로 바뀌었어요", [])
        except RuntimeError as e:
            print(f"[draft] 옛 메시지 정리 실패: {e}")
    photo = photo_bytes(d)
    msg = telegram.send_draft(caption(d), photo, keyboard(d))
    d["message"] = {"message_id": msg["message_id"], "has_photo": bool(photo)}
    save(d)


def refresh(d):
    """보낸 메시지의 상태·버튼만 바꾼다."""
    if d.get("message"):
        telegram.edit_draft(d["message"], caption(d), keyboard(d))
