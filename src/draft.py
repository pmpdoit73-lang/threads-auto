"""초안 한 건의 생성·저장·텔레그램 표시를 담당한다.

초안은 drafts/<id>.json 과 drafts/<id>.png 로 저장소에 기록된다.
status: pending(선택 대기) → approved(승인) → published(게시 완료)
        또는 skipped(건너뜀) / failed(게시 실패)
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import benchmarks as bench_store
import coupang
import images
import telegram
import threads_api
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
    result = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        result.append(f"[{d.get('category', '')}] {d.get('subject', '')} | {d.get('issue', '')}")
    return result


# ---------- 시간 ----------

SLOTS = [(7, 0), (11, 0), (18, 0), (21, 0)]  # 하루 게시 시간 (한국 시간)
DRAFT_AHEAD = timedelta(hours=10)     # 게시 몇 시간 전부터 초안을 만들지 (07시 회차는 전날 22시)


def upcoming_slots(now, days=2):
    """지금 이후 게시 시간들을 가까운 순서로."""
    base = now.replace(second=0, microsecond=0)
    result = []
    for day in range(days):
        for hour, minute in SLOTS:
            t = base.replace(hour=hour, minute=minute) + timedelta(days=day)
            if t > now:
                result.append(t)
    return result


def next_slot(now):
    """지금 이후 가장 가까운 게시 시간."""
    return upcoming_slots(now)[0]


def slot_to_fill(now, force=False):
    """초안이 아직 없는 가장 가까운 게시 시간. 너무 먼 시간이면 None.

    초안 만들기는 하루 여러 번 돌고, 돌 때마다 비어 있는 회차만 채운다
    (이미 있으면 아무것도 안 함). 한 번 빠져도 다음 실행이 메운다.
    force=True(수동 실행)이면 시간 제한 없이 만든다.
    """
    taken = set()
    for p in DRAFT_DIR.glob("*.json"):
        at = json.loads(p.read_text(encoding="utf-8")).get("publish_at")
        if at:
            taken.add(datetime.fromisoformat(at))
    for slot in upcoming_slots(now):
        if slot in taken:
            continue
        if force or slot - now <= DRAFT_AHEAD:
            return slot
        return None
    return next_slot(now) if force else None


def publish_time(d):
    return datetime.fromisoformat(d["publish_at"])


# ---------- 내용 만들기 ----------

def _fill_content(d, avoid=()):
    collected = trends.collect()
    print(f"[draft] 이슈 수집: { {k: len(v) for k, v in collected.items()} }")
    try:
        benchmarks = threads_api.my_posts_with_views()
        print(f"[draft] 벤치마킹용 내 글 {len(benchmarks)}개 (최고 조회 {benchmarks[0]['views'] if benchmarks else 0})")
    except Exception as e:
        print(f"[draft] 조회수 가져오기 실패, 벤치마킹 없이 씀: {e}")
        benchmarks = None
    external = bench_store.load()
    print(f"[draft] gil이 보낸 벤치마킹 글 {len(external)}개")
    post = writer.write_post(collected, list(recent_issues()) + list(avoid), benchmarks, external)
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


NO_COUPANG_HOURS = {7, 18}  # 하루 첫째(07시)·셋째(18시) 글은 쿠팡 링크 없이


def default_format(d):
    if d.get("publish_at") and datetime.fromisoformat(d["publish_at"]).hour in NO_COUPANG_HOURS:
        return "photo" if d.get("has_photo") else "text"
    if d.get("has_photo") and d.get("products"):
        return "both"
    if d.get("has_photo"):
        return "photo"
    if d.get("products"):
        return "coupang"
    return "text"


def create(slot):
    now = datetime.now(KST)
    d = {
        "id": now.strftime("%Y%m%d-%H%M"),
        "created_at": now.isoformat(),
        "publish_at": slot.isoformat(),
        "status": "pending",
        "product": 0,
    }
    _fill_content(d)
    d["format"] = default_format(d)
    save(d)
    return d


def rewrite(d):
    """같은 시간대에 다른 이슈로 다시 쓴다."""
    rejected = d.get("rejected_issues", []) + [d.get("issue", "")]
    d["rejected_issues"] = [x for x in rejected if x][-10:]
    others = [x for p in DRAFT_DIR.glob("*.json")
              for x in json.loads(p.read_text(encoding="utf-8")).get("rejected_issues", [])]
    _fill_content(d, avoid=list(dict.fromkeys(d["rejected_issues"] + others)))  # 다른 초안에서 거절한 이슈도 피함
    d["format"] = default_format(d)
    d["product"] = 0
    save(d)


def retext(d):
    """이슈·사진·상품은 그대로 두고 글만 새로 쓴다."""
    d.update(writer.rewrite_text(d.get("issue", ""), d.get("angle", ""), d["text"]))
    d.pop("edited_by_hand", None)
    save(d)


THREADS_LIMIT = 500  # 쓰레드 본문 최대 글자 수


def set_text(d, text):
    """gil이 텔레그램 답장으로 보낸 글로 바꾼다."""
    text = text.strip()
    if not text:
        raise ValueError("빈 글이에요")
    if len(text) > THREADS_LIMIT:
        raise ValueError(f"쓰레드는 {THREADS_LIMIT}자까지예요 (지금 {len(text)}자)")
    d["text"] = text
    d["edited_by_hand"] = True
    save(d)


def new_photo(d):
    _fill_photo(d, prefer_free=d.get("image_note", "").startswith("제미나이"))
    save(d)


# ---------- 텔레그램 표시 ----------

def wants_photo(d):
    return d["format"] in ("both", "photo") and d.get("has_photo")


def wants_coupang(d):
    return d["format"] in ("both", "coupang") and d.get("products")


INSTA_HOURS = {7, 18}  # 쿠팡 없는 07·18시 글엔 인스타 홍보 첫 댓글
INSTA_URL = "https://www.instagram.com/salim.kkultip/"
INSTA_COMMENTS = [  # 매번 같은 문장이면 광고처럼 보여서 날마다 돌려 씀
    "살림템 직접 써보는 영상은 인스타에 올리고 있어 📷",
    "말로만 하면 감이 안 오지? 영상은 인스타에 올려놨어 📷",
    "이런 살림 꿀팁 영상으로 보고 싶으면 인스타로 와 📷",
]


def wants_insta(d):
    return publish_time(d).hour in INSTA_HOURS and not wants_coupang(d)


def insta_comment(d):
    when = publish_time(d)
    line = INSTA_COMMENTS[(when.toordinal() * 2 + (when.hour > 12)) % len(INSTA_COMMENTS)]
    return f"{line}\n{INSTA_URL}"


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
        f"({len(d['text'])}자{', 직접 고친 글' if d.get('edited_by_hand') else ''})",
        "",
        f"🔥 이슈: {d.get('issue', '')}",
        *([f"📊 벤치마킹: {d['benchmark_note']}"] if d.get("benchmark_note") else []),
        f"🖼 사진: {d.get('image_note', '')}",
        f"📦 형태: {FORMATS[d['format']]}",
        *(["📷 첫 댓글: 인스타 홍보"] if wants_insta(d) else []),
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
        lines += ["", "그대로 두면 예정 시간에 자동으로 올라가요. 올리기 싫으면 ⏭ 건너뛰기를 눌러 주세요.",
                  "형태와 상품은 버튼으로 바꿀 수 있어요.",
                  "✏️ 글을 직접 고치려면 이 메시지에 '답장'으로 고친 글을 보내 주세요.",
                  "(버튼은 20분마다 확인해요)"]
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
        [_btn(d, "🔁 같은 이슈로 다시", "a", "retext"), _btn(d, "🆕 새 이슈로", "a", "rewrite")],
        [_btn(d, "🖼 다른 사진", "a", "photo")],
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
    quiet = datetime.now(KST).hour < 7  # 새벽에는 알림 소리 없이
    msg = telegram.send_draft(caption(d), photo, keyboard(d), silent=quiet)
    d["message"] = {"message_id": msg["message_id"], "has_photo": bool(photo)}
    save(d)


def refresh(d):
    """보낸 메시지의 상태·버튼만 바꾼다."""
    if d.get("message"):
        telegram.edit_draft(d["message"], caption(d), keyboard(d))
