"""초안을 만들어 버튼과 함께 텔레그램으로 보낸다.

실행: python src/make_draft.py
"""

import sys

import draft
import telegram


def main():
    d = draft.create()
    draft.send(d)
    print(f"[make_draft] 초안 {d['id']} 전송 완료 (게시 예정 {d['publish_at']})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[make_draft] 실패: {e}")
        try:
            telegram.send_text(f"⚠️ 초안 만들기 실패: {e}")
        except Exception:
            pass
        sys.exit(1)
