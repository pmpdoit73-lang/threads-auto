"""Claude로 이슈를 고르고, 2초 후킹으로 시작하는 살림 고수 글을 쓴다."""

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
PERSONA = (Path(__file__).resolve().parent.parent / "prompts" / "persona.md").read_text(encoding="utf-8")

SCHEMA = {
    "type": "object",
    "properties": {
        "issue": {"type": "string", "description": "고른 이슈 원문 제목"},
        "angle": {"type": "string", "description": "어떤 손해·몰랐던 점을 짚었는지 한 줄"},
        "category": {"type": "string", "enum": ["살림템·가전", "주방", "청소·세탁·정리", "날씨·계절·난방", "최근 이슈"],
                     "description": "글 주제 분류. 보일러·전기장판·패딩·난방·날씨 얘기면 '날씨·계절·난방'"},
        "subject": {"type": "string",
                    "description": "글의 주인공인 가전·물건 이름을 본문에 쓴 그대로 짧게. 예: 에어프라이어, 드럼세탁기"},
        "hooks": {"type": "array", "items": {"type": "string"},
                  "description": "후킹 문법별 첫 줄 후보 5개, 각 끝에 (점수/10) 표시"},
        "text": {"type": "string", "description": "가장 센 후킹으로 시작하는 쓰레드 본문 (100~150자, 3~5줄)"},
        "image_prompt": {"type": "string", "description": "사진 생성용 영어 프롬프트. 내가 집에서 폰으로 직접 찍은 듯한 평범한 실사 장면 묘사 (구체적인 물건·장소·상황 위주, 삐딱한 구도·대충 찍은 느낌, 예쁜 연출·광고 사진 느낌 금지). 사람 얼굴·글자·로고 없이"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
        "product_keyword": {"type": "string", "description": "쿠팡에서 검색할 한국어 상품 키워드"},
        "benchmark_note": {"type": "string",
                           "description": "조회수 높았던 글에서 무엇을 가져왔는지 한 줄 (참고 글이 없으면 빈 문자열)"},
    },
    "required": ["issue", "angle", "category", "subject", "hooks", "text", "image_prompt", "photo_query", "product_keyword",
                 "benchmark_note"],
    "additionalProperties": False,
}


def _benchmark_text(benchmarks):
    """조회수 높은 글·낮은 글을 프롬프트용 글로 만든다."""
    if not benchmarks or len(benchmarks) < 4:
        return ""
    top, low = benchmarks[:5], benchmarks[-3:]
    fmt = lambda p: f"[조회 {p['views']} · 좋아요 {p['likes']} · 댓글 {p['replies']}]\n{p['text'][:300]}"
    return (
        "\n\n## 벤치마킹: 내 쓰레드에서 조회수가 높았던 글\n"
        + "\n\n".join(fmt(p) for p in top)
        + "\n\n## 조회수가 낮았던 글 (피할 패턴)\n"
        + "\n\n".join(fmt(p) for p in low)
        + "\n\n벤치마킹 규칙: 높았던 글의 첫 줄 방식, 줄 나눔, 길이, 말 끝맺음, 질문 넣는 방식처럼 '형식'만 가져와.\n"
          "내용·문장은 절대 베끼지 말고, 페르소나와 주제(가전·주방·생활 팁)·금지 사항은 그대로 지켜.\n"
          "낮았던 글과 닮은 형식은 피해. 무엇을 가져왔는지 benchmark_note에 한 줄로 적어."
    )


def write_post(trends, recent_issues=(), benchmarks=None, external=None, used=()):
    """trends: {출처: [제목...]}, recent_issues: 최근에 다룬 이슈(중복 방지)."""
    lines = []
    for source, titles in trends.items():
        lines.append(f"## {source}")
        lines.extend(f"- {t}" for t in titles)
    trend_text = "\n".join(lines)
    recent = "\n".join(f"- {r}" for r in recent_issues) or "(없음)"
    used_text = "\n".join(f"- {day} {subject}: {issue}" for day, subject, issue in used) or "(없음)"

    user_msg = (
        "아래는 오늘 한국 뉴스·검색 목록이야. 소재 참고용이야.\n\n"
        f"{trend_text}\n\n"
        f"최근에 이미 다룬 글 (주제·물건·분류가 겹치지 않게 골라):\n{recent}\n\n"
        f"최근 30일 동안 이미 올린 글 전체 (같은 물건의 같은 팁은 절대 다시 쓰지 마. 같은 물건이면 2주 안엔 아예 고르지 마):\n{used_text}\n\n"
        "주의: 요즘 글이 '필터·거름망·물때 청소'에 몰려 있어. 청소 말고 다른 각도도 골고루 골라 — "
        "몰랐던 숨은 버튼·기능, 전기요금·물값 아끼는 설정, 보관·정리법, 흔한 사용 실수, 고장 오해, 살림템 활용법.\n\n"
        "1. 주제를 이 순서로 골라 (페르소나 '다루는 주제' 참고):\n"
        "   ① 프로필('가성비있고 신박한 아이템을 리뷰합니다')에 맞는 살림템·가전 숨은 기능·주방·청소세탁 정보.\n"
        "      목록에 가전 신제품·리콜·요금·새 제도 소식이 있으면 계기로 삼고, 없어도 '이거 몰랐네' 싶은 정보면 돼.\n"
        "   ② ①로 쓸 만한 게 정말 없으면, 오늘·어제 화제가 된 깜짝 놀랄 최근 이슈 하나 (category='최근 이슈').\n"
        "   ③ 날씨·계절·난방(보일러·전기장판·패딩·한파 등)은 최근 글에 이미 있으면 절대 고르지 마. 요즘 너무 많이 썼어.\n"
        "   - 최근 글과 같은 물건(subject)이나 같은 분류가 연달아 나오지 않게 골라.\n"
        "   - issue 칸에는 고른 주제나 계기가 된 뉴스 제목을 한 줄로 적어.\n"
        "2. 페르소나의 '후킹 문법' 5가지(열린 고리, 셀프 디스 실수담, 발견감, 틀린 추측 질문)로 서로 다른 첫 줄 후킹 5개를 만들어.\n"
        "   각 후킹을 스스로 채점해: 첫 줄만 보고 '그래서 뭔데?' 하고 다음 줄을 안 읽고는 못 배기면 높은 점수.\n"
        "   첫 줄에 이유·방법(정답)이 들어 있으면 0점. 가장 높은 하나를 골라.\n"
        "3. 그 후킹으로 시작해 '글 흐름'대로 100~150자, 4~5줄 글을 써.\n"
        "   - 정답(이유·방법)은 셋째 줄부터 공개. 첫째·둘째 줄에서 답을 말하면 실패야.\n"
        "   - 주어 필수: 첫 줄에 어떤 가전·물건 얘기인지 이름을 꼭 써 ('에어프라이어', '드럼세탁기'). subject 칸에 그 이름을 적어.\n"
        "   - 구체성: 공개하는 방법에 숫자(온도·시간·횟수·금액)를 넣어. 확실하지 않은 숫자는 지어내지 마.\n"
        "   - 말투: 가르치는 명령조 대신 '나 이러고 있었네', '난 이제 이렇게 해' 같은 고백·경험 말투, 말줄임표·ㅋㅋ 자연스럽게.\n"
        "   - 안전: 제조사 설명과 다르거나 화재·감전 위험이 있는 방법은 절대 쓰지 마.\n"
        "   - 마지막 줄은 누구나 답할 열린 질문이나 살짝 틀린 추측으로 댓글을 부르게 ('나만 몰랐어?', '너네도 이랬어?ㅋㅋ').\n"
        "4. 쿠팡 상품 검색 키워드는 글에 나온 가전·주방용품이나 팁에 쓰는 물건으로 정해.\n"
        "5. 글과 어울리는 사진 프롬프트, 사진 검색어도 정해."
        + _external_text(external)
        + _benchmark_text(benchmarks)
    )

    post = _ask(user_msg, SCHEMA)
    if _too_much_weather(post, recent_issues):  # 날씨·난방 쏠림 막기
        print(f"[writer] 날씨·난방 주제가 또 나옴 ({post.get('subject')}) → 다시 씀")
        post = _ask(user_msg + "\n\n주의: 날씨·계절·난방 주제는 최근에 너무 많이 썼어. 이번엔 절대 쓰지 말고 "
                    "프로필 주제(살림템·가전 기능·주방·청소세탁)나 최근 이슈로 골라.", SCHEMA)
    repeat = _repeated(post, used)
    if repeat:  # 최근에 올린 물건이 또 나오면 다시 쓴다
        print(f"[writer] 최근에 쓴 물건이 또 나옴 ({post.get('subject')} ← {repeat}) → 다시 씀")
        post = _ask(user_msg + f"\n\n주의: '{post.get('subject')}'은(는) {repeat}에 이미 올렸어. "
                    "최근 30일 목록에 없는 다른 물건으로 골라.", SCHEMA)
    if not _subject_ok(post):  # 첫 두 줄에 주어가 없으면 한 번 더 쓰게 한다
        print(f"[writer] 첫 두 줄에 주어 '{post.get('subject')}' 없음 → 다시 씀")
        post = _ask(user_msg + "\n\n주의: 지난번엔 첫 두 줄에 주어(누가/무엇이)가 빠져서 무슨 일인지 몰랐어. "
                    "첫 줄에 subject를 그대로 넣어서 다시 써.", SCHEMA)
    return post


WEATHER_WORDS = ("날씨", "난방", "보일러", "전기장판", "온수매트", "패딩", "한파", "히터", "난로", "추위", "서리", "기온")


def _too_much_weather(post, recent_issues, window=3):
    """이번 글이 날씨·난방인데 최근 글 몇 개에 이미 날씨·난방이 있으면 True."""
    this = post.get("category") == "날씨·계절·난방" or any(w in post.get("subject", "") for w in WEATHER_WORDS)
    recent = list(recent_issues)[-window:]
    return this and any(any(w in r for w in WEATHER_WORDS) for r in recent)


def _norm(text):
    return "".join(text.split())


def _repeated(post, used, days=14):
    """이번 글의 물건(subject)이 최근 N일 안에 올린 글과 같으면 그 날짜를, 아니면 ''."""
    subject = _norm(post.get("subject", ""))
    if len(subject) < 2:
        return ""
    since = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=days)).strftime("%Y-%m-%d")
    for day, old, _issue in used:
        old = _norm(old)
        if day >= since and old and (subject == old or (min(len(subject), len(old)) >= 3 and (subject in old or old in subject))):
            return day
    return ""


def _subject_ok(post):
    """subject(주인공 이름)가 본문 첫 두 줄 안에 들어 있는지."""
    subject = post.get("subject", "").replace(" ", "")
    head = "".join(post.get("text", "").splitlines()[:2]).replace(" ", "")
    words = [w for w in post.get("subject", "").split() if len(w) >= 2]
    return bool(subject) and (subject in head or any(w in head for w in words))


TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "hooks": SCHEMA["properties"]["hooks"],
        "text": SCHEMA["properties"]["text"],
    },
    "required": ["hooks", "text"],
    "additionalProperties": False,
}


def rewrite_text(issue, angle, old_text):
    """같은 이슈로 후킹과 문장만 새로 쓴다."""
    user_msg = (
        f"이슈: {issue}\n"
        f"살림 시선: {angle}\n\n"
        f"지난번 글:\n{old_text}\n\n"
        "같은 주제로 글만 다시 써 줘. 페르소나의 '후킹 문법'(열린 고리, 셀프 디스 실수담, 발견감, 틀린 추측 질문)으로\n"
        "첫 줄 후보 5개를 만들고 스스로 채점해. 첫 줄만 보고 다음 줄을 안 읽고는 못 배기면 높은 점수,\n"
        "첫 줄에 이유·방법(정답)이 들어 있으면 0점. 가장 높은 하나로 시작해 '글 흐름'대로 100~150자, 4~5줄로 써.\n"
        "정답은 셋째 줄부터 공개하고, 첫 줄에 가전·물건 이름은 꼭 넣어. 지난번 문장은 되풀이하지 마."
    )
    return _ask(user_msg, TEXT_SCHEMA)


def _ask(user_msg, schema):
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=PERSONA,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 이번 글쓰기를 거절했어요.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


SNAP_SCHEMA = {
    "type": "object",
    "properties": {
        "is_post": {"type": "boolean", "description": "쓰레드(SNS) 글 화면이 맞는지"},
        "author": {"type": "string", "description": "작성자 아이디 (안 보이면 빈 문자열)"},
        "text": {"type": "string", "description": "본문 글자 그대로 (줄바꿈 유지, 댓글 제외)"},
        "views": {"type": "integer", "description": "조회수 (안 보이면 -1, '1.2만'은 12000)"},
        "likes": {"type": "integer", "description": "좋아요 수 (안 보이면 -1)"},
        "replies": {"type": "integer", "description": "댓글 수 (안 보이면 -1)"},
        "reposts": {"type": "integer", "description": "리포스트 수 (안 보이면 -1)"},
        "hook_type": {"type": "string", "description": "첫 줄 후킹 유형 (숫자 충격/반전/손해 경고/질문/비밀 공개/공감/기타)"},
        "why_it_works": {"type": "string", "description": "이 글이 잘 퍼진 이유를 형식 관점에서 1~2문장"},
        "format_rules": {"type": "array", "items": {"type": "string"},
                         "description": "다른 글에 옮겨 쓸 수 있는 형식 규칙 2~4개 (줄 수, 첫 줄 길이, 끝맺음 등)"},
    },
    "required": ["is_post", "author", "text", "views", "likes", "replies", "reposts",
                 "hook_type", "why_it_works", "format_rules"],
    "additionalProperties": False,
}


def read_snapshot(image_bytes, note=""):
    """쓰레드 인기글 스냅샷(사진)을 읽어 글·숫자·잘된 이유를 뽑는다."""
    media = "image/png" if image_bytes[:4] == b"\x89PNG" else "image/jpeg"
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": "이건 벤치마킹할 쓰레드 인기글 스냅샷이야. 화면에 보이는 대로 읽고 분석해 줘."
                                     + (f"\n보낸 사람 메모: {note}" if note else "")},
        ]}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SNAP_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _external_text(external):
    """gil이 보내 준 다른 계정 인기글 스냅샷 분석을 프롬프트용 글로 만든다."""
    if not external:
        return ""
    picks = sorted(external, key=lambda x: x.get("views", -1), reverse=True)[:6]
    parts = []
    for x in picks:
        views = f"조회 {x['views']:,}" if x.get("views", -1) >= 0 else "조회 ?"
        parts.append(f"[{views} · 좋아요 {x.get('likes', '?')} · 후킹: {x.get('hook_type', '')}]\n"
                     f"{x['text'][:300]}\n→ 잘된 이유: {x.get('why_it_works', '')}\n"
                     f"→ 형식 규칙: {' / '.join(x.get('format_rules', []))}")
    return ("\n\n## 벤치마킹: 다른 계정에서 조회수가 높았던 글 (gil이 직접 고른 것, 가장 중요)\n"
            + "\n\n".join(parts)
            + "\n\n이 글들의 '형식 규칙'과 후킹 방식을 우선 따라 해. 내용·문장은 절대 베끼지 마.")
