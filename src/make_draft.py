"""1단계: 초안을 만들어 텔레그램으로 보낸다. (쓰레드에는 아직 게시하지 않음)

실행: python src/make_draft.py
      python src/make_draft.py --dry-run   ← 텔레그램 대신 화면에 출력
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import coupang
import images
import telegram
import trends
import writer

KST = timezone(timedelta(hours=9))
DRAFT_DIR = Path(__file__).resolve().parent.parent / "drafts"


def recent_issues(n=10):
    files = sorted(DRAFT_DIR.glob("*.json"))[-n:]
    return [json.loads(f.read_text(encoding="utf-8"))["issue"] for f in files]


def build_caption(draft, image_note, products):
    now = datetime.now(KST)
    slot = "08:00" if now.hour < 12 else "20:00"
    lines = [
        f"📝 {now:%m/%d} {slot} 게시 예정 초안",
        "",
        draft["text"],
        f"({len(draft['text'])}자)",
        "",
        f"🔥 이슈: {draft['issue']}",
        f"🏠 시선: {draft['angle']}",
        f"🖼 사진: {image_note}",
        "",
        f"🛒 쿠팡 후보 ('{draft['product_keyword']}')",
    ]
    if products:
        for i, p in enumerate(products, 1):
            price = f"{p['price']:,}원" if isinstance(p["price"], int) else ""
            lines.append(f"{i}. {p['name'][:40]} {price}")
    else:
        lines.append("(후보 없음)")
    lines += ["", "※ 1단계 테스트라 버튼과 실제 게시는 아직 없어요."]
    return "\n".join(lines)


def main(dry_run=False):
    collected = trends.collect()
    print(f"[main] 이슈 수집: { {k: len(v) for k, v in collected.items()} }")

    draft = writer.write_post(collected, recent_issues())
    print(f"[main] 글 작성: {draft['text']}")

    photo, image_note = images.get_image(draft["image_prompt"], draft["photo_query"])

    try:
        products = coupang.search_products(draft["product_keyword"])
    except Exception as e:
        print(f"[main] 쿠팡 검색 실패: {e}")
        products = []

    caption = build_caption(draft, image_note, products)

    DRAFT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M")
    record = {**draft, "image_note": image_note, "products": products, "created_at": stamp}
    (DRAFT_DIR / f"{stamp}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    if photo:
        (DRAFT_DIR / f"{stamp}.png").write_bytes(photo)

    if dry_run:
        print("\n" + caption)
        return
    telegram.send_draft(caption, photo)
    print("[main] 텔레그램 전송 완료")


if __name__ == "__main__":
    try:
        main(dry_run="--dry-run" in sys.argv)
    except Exception as e:
        print(f"[main] 실패: {e}")
        if "--dry-run" not in sys.argv:
            try:
                telegram.send_text(f"⚠️ 초안 만들기 실패: {e}")
            except Exception:
                pass
        sys.exit(1)
