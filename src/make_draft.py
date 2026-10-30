"""초안을 만들어 버튼과 함께 텔레그램으로 보낸다.

실행: python src/make_draft.py
"""

import os
import sys
import traceback
from datetime import datetime

import draft
import telegram


def main():
    redo = os.environ.get("REDO_ID", "").strip()
    if redo:  # 이미 보낸 초안을 다른 이슈로 다시 쓰기 (🆕 버튼과 같음), REDO_MODE=text면 주제는 두고 글만
        d = draft.load(redo)
        if os.environ.get("REDO_MODE", "").strip() == "text":
            draft.retext(d)
        else:
            draft.rewrite(d)
        draft.send(d)
        print(f"[make_draft] 초안 {redo} 새 이슈로 다시 보냄")
        return
    force = os.environ.get("FORCE") == "1"  # Actions 탭에서 수동 실행하면 바로 만듦
    slot = draft.slot_to_fill(datetime.now(draft.KST), force)
    if not slot:
        print("[make_draft] 지금 채울 회차가 없어요 (이미 초안이 있거나 아직 이름)")
        return
    d = draft.create(slot)
    draft.send(d)
    print(f"[make_draft] 초안 {d['id']} 전송 완료 (게시 예정 {d['publish_at']})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[make_draft] 실패: {e}")
        # Actions 로그를 못 볼 때를 위해 오류 내용을 저장소에 남김 (비밀값은 안 들어감)
        os.makedirs("state", exist_ok=True)
        with open("state/last_draft_error.txt", "w", encoding="utf-8") as f:
            f.write(f"{datetime.now(draft.KST).isoformat()}\n{traceback.format_exc()}")
        try:
            telegram.send_text(f"⚠️ 초안 만들기 실패: {e}")
        except Exception:
            pass
        sys.exit(1)
