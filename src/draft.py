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
import media
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


def used_topics(days=30, exclude_id=None):
    """최근 N일 동안 올렸거나 올릴 글의 (날짜, 물건, 주제). 실패·건너뛴 글은 사람들이 못 봤으니 뺌."""
    since = (datetime.now(KST) - timedelta(days=days)).strftime("%Y%m%d")
    result = []
    for f in sorted(DRAFT_DIR.glob("*.json")):
        if f.stem[:8] < since or f.stem == exclude_id:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("status") in ("published", "pending", "approved") and d.get("subject"):
            result.append((d.get("publish_at", "")[:10], d["subject"], d.get("issue", "")))
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
    used = used_topics(exclude_id=d.get("id"))
    post = writer.write_post(collected, list(recent_issues()) + list(avoid), benchmarks, external, used)
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
    if d.get("media"):  # 영상·인용 글은 사진 없이, 쿠팡 후보가 있으면 쿠팡 첫 댓글
        return "coupang" if d.get("products") else "text"
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


# ---------- 영상·인용 붙이기 ----------

EXTRA_DELAY = timedelta(hours=1)   # 영상을 보내고 이만큼 뒤에 자동 게시
EXTRA_GAP = timedelta(hours=1)     # 예약 글·다른 초안과 이만큼은 떨어뜨림 (조회수 나눠 먹지 않게)
EXTRA_HOURS = (6, 23)              # 버튼 확인이 도는 시간 (06:00~23:40) 안에서만


def extra_time(now):
    """추가 초안을 올릴 시간: 1시간 뒤부터, 예약 글·다른 초안과 1시간 넘게 떨어진 가장 빠른 때."""
    busy = list(upcoming_slots(now)) + [publish_time(d) for d in open_drafts()]
    t = (now + EXTRA_DELAY).replace(second=0, microsecond=0)
    t += timedelta(minutes=-t.minute % 10)  # 10분 단위로
    for _ in range(100):
        if not EXTRA_HOURS[0] <= t.hour < EXTRA_HOURS[1]:  # 밤이면 다음 날 아침으로
            t = (t + timedelta(days=1 if t.hour >= EXTRA_HOURS[1] else 0)).replace(hour=EXTRA_HOURS[0], minute=20)
            continue
        clash = [b for b in busy if abs(b - t) < EXTRA_GAP]
        if not clash:
            return t
        t = max(clash) + EXTRA_GAP
    return t


def create_extra(item):
    """gil이 보낸 영상·링크로 예약 글과 따로 추가 초안을 만든다."""
    now = datetime.now(KST)
    d = {
        "id": now.strftime("%Y%m%d-%H%M") + "v",
        "created_at": now.isoformat(),
        "publish_at": extra_time(now).isoformat(),
        "status": "pending",
        "product": 0,
        "extra": True,
    }
    attach(d, item)
    return d


def attach(d, item):
    """영상·인용 링크·사진으로 이 초안의 글을 쓴다."""
    about, credit = media.split_memo(item.get("memo", ""))
    files = album_files(item)
    images = [telegram.download_file(f["file_id"]) for f in files if f["type"] == "photo"]
    videos = sum(f["type"] == "video" for f in files)
    post = writer.write_for_media(about, item["kind"], used_topics(exclude_id=d.get("id")), bench_store.load(),
                                  images, videos)
    d.update(post)
    if item["kind"] == "photo":  # 사진은 보통 사진 글처럼 저장 (텔레그램 미리보기·게시가 그대로 됨)
        if images:
            path(d["id"], "png").write_bytes(images[0])
            d["has_photo"] = True
        d["album"] = files  # 2개 이상이면 게시 때 텔레그램에서 다시 받아 넘겨 보기 글로
        d["media_group_id"] = item.get("media_group_id")
        d["image_note"] = album_note(files)
    else:
        d["media"] = item
    d["credit"] = credit
    d.pop("edited_by_hand", None)
    # 영상·사진 모두 gil이 적은 제품명으로 먼저, 없으면 Claude가 정한 키워드로 찾음
    keywords = [about, post["product_keyword"]]
    try:
        d["products"] = coupang.search_products(keywords[0]) or coupang.search_products(keywords[1])
    except Exception as e:
        print(f"[draft] 쿠팡 검색 실패: {e}")
        d["products"] = []
    d["product"] = 0
    d["format"] = default_format(d)
    save(d)


def album_files(item):
    """gil이 보낸 사진 글의 파일 목록 (한 장이면 그 한 장)."""
    if item["kind"] != "photo":
        return []
    return item.get("files") or [{"type": "photo", "file_id": item["file_id"]}]


def album_note(files):
    photos = sum(f["type"] == "photo" for f in files)
    videos = len(files) - photos
    if len(files) == 1:
        return "gil이 보낸 사진"
    return "gil이 보낸 " + " + ".join(x for x in (f"사진 {photos}장" if photos else "",
                                                f"영상 {videos}개" if videos else "") if x) + " (넘겨 보기)"


def add_to_album(d, files):
    """나중에 도착한 같은 묶음 사진·영상을 초안에 더한다."""
    album = d["album"]
    known = {f["file_id"] for f in album}
    album += [f for f in files if f["file_id"] not in known]
    d["album"] = album[:20]
    d["image_note"] = album_note(d["album"])
    save(d)


def detach(d):
    """영상·인용을 빼고 원래처럼 사진 글로 다시 쓴다."""
    d.pop("media", None)
    d.pop("credit", None)
    rewrite(d)


def final_text(d):
    """실제로 올릴 본문 (출처 줄이 있으면 끝에 붙임)."""
    return f"{d['text']}\n\n{d['credit']}" if d.get("credit") else d["text"]


def new_photo(d):
    _fill_photo(d, prefer_free=d.get("image_note", "").startswith("제미나이"))
    save(d)


# ---------- 텔레그램 표시 ----------

def wants_photo(d):
    return d["format"] in ("both", "photo") and (d.get("has_photo") or d.get("album")) and not d.get("media")


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
        *([media.label(d["media"])] if d.get("media") else [f"🖼 사진: {d.get('image_note', '')}"]),
        *([f"🙏 {d['credit']}"] if d.get("credit") else []),
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
    if d.get("media"):
        rows = [[_btn(d, "🛒 쿠팡 댓글", "f", "coupang", d["format"] == "coupang"),
                 _btn(d, "📝 댓글 없이", "f", "text", d["format"] == "text")]]
        products = d.get("products") or []
        if products:
            rows.append([_btn(d, f"상품 {i + 1}", "p", str(i), d.get("product", 0) == i)
                         for i in range(len(products))])
        return rows + [
            [_btn(d, "🔁 글만 다시", "a", "retext")]
            + ([] if d.get("extra") else [_btn(d, "🎬 영상 빼기", "a", "nomedia")]),
            [_btn(d, "✅ 승인", "a", "ok"), _btn(d, "🚀 지금 게시", "a", "now")],
            [_btn(d, "⏭ 건너뛰기", "a", "skip")],
        ]
    if d.get("extra"):  # gil이 보낸 사진 글: 사진은 그대로, 쿠팡만 고름
        rows = [[_btn(d, FORMATS["both"], "f", "both", d["format"] == "both"),
                 _btn(d, FORMATS["photo"], "f", "photo", d["format"] == "photo")]]
        products = d.get("products") or []
        if products:
            rows.append([_btn(d, f"상품 {i + 1}", "p", str(i), d.get("product", 0) == i)
                         for i in range(len(products))])
        return rows + [
            [_btn(d, "🔁 글만 다시", "a", "retext")],
            [_btn(d, "✅ 승인", "a", "ok"), _btn(d, "🚀 지금 게시", "a", "now")],
            [_btn(d, "⏭ 건너뛰기", "a", "skip")],
        ]
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
    photo = None if d.get("media") else photo_bytes(d)  # 영상 글엔 예전 사진을 안 보여 줌
    quiet = datetime.now(KST).hour < 7  # 새벽에는 알림 소리 없이
    msg = telegram.send_draft(caption(d), photo, keyboard(d), silent=quiet)
    d["message"] = {"message_id": msg["message_id"], "has_photo": bool(photo)}
    save(d)


def refresh(d):
    """보낸 메시지의 상태·버튼만 바꾼다."""
    if d.get("message"):
        telegram.edit_draft(d["message"], caption(d), keyboard(d))
