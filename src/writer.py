"""Claude로 이슈를 고르고, 2초 후킹으로 시작하는 살림 고수 글을 쓴다."""

import base64
import json
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
PERSONA = (Path(__file__).resolve().parent.parent / "prompts" / "persona.md").read_text(encoding="utf-8")

SCHEMA = {
    "type": "object",
    "properties": {
        "issue": {"type": "string", "description": "고른 이슈 원문 제목"},
        "angle": {"type": "string", "description": "어떤 점이 충격적이고, 우리 집과 어떻게 이었는지 한 줄"},
        "subject": {"type": "string",
                    "description": "이 사건의 주인공(누가/무엇이)을 본문에 쓴 그대로 짧게. 예: 테슬라 로드스터, 일본 기상청"},
        "hooks": {"type": "array", "items": {"type": "string"},
                  "description": "서로 다른 유형의 첫 줄 후킹 후보 3개"},
        "text": {"type": "string", "description": "가장 센 후킹으로 시작하는 쓰레드 본문 (100~150자, 3~5줄)"},
        "image_prompt": {"type": "string", "description": "사진 생성용 영어 프롬프트. 내가 집에서 폰으로 직접 찍은 듯한 평범한 실사 장면 묘사 (구체적인 물건·장소·상황 위주, 삐딱한 구도·대충 찍은 느낌, 예쁜 연출·광고 사진 느낌 금지). 사람 얼굴·글자·로고 없이"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
        "product_keyword": {"type": "string", "description": "쿠팡에서 검색할 한국어 상품 키워드"},
        "benchmark_note": {"type": "string",
                           "description": "조회수 높았던 글에서 무엇을 가져왔는지 한 줄 (참고 글이 없으면 빈 문자열)"},
    },
    "required": ["issue", "angle", "subject", "hooks", "text", "image_prompt", "photo_query", "product_keyword",
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
          "내용·문장은 절대 베끼지 말고, 페르소나와 금지 주제(정치·연예 가십·피해자 조롱 등)는 그대로 지켜.\n"
          "낮았던 글과 닮은 형식은 피해. 무엇을 가져왔는지 benchmark_note에 한 줄로 적어."
    )


def write_post(trends, recent_issues=(), benchmarks=None, external=None):
    """trends: {출처: [제목...]}, recent_issues: 최근에 다룬 이슈(중복 방지)."""
    lines = []
    for source, titles in trends.items():
        lines.append(f"## {source}")
        lines.extend(f"- {t}" for t in titles)
    trend_text = "\n".join(lines)
    recent = "\n".join(f"- {r}" for r in recent_issues) or "(없음)"

    user_msg = (
        "아래는 오늘 한국에서 뜨는 이슈 목록이야.\n\n"
        f"{trend_text}\n\n"
        f"최근에 이미 다룬 이슈 (피해서 골라):\n{recent}\n\n"
        "1. 금지 주제를 빼고, 제목만 봐도 '헉, 진짜?' 소리가 나오는 충격적인 사건·사고·깜짝 뉴스 하나를 골라.\n"
        "   (예: 황당한 사고, 믿기 힘든 적발·사기, 역대급 숫자, 상상도 못 한 반전, '우리 동네도?' 싶은 일)\n"
        "   평범한 날씨·물가·생활 정보, 가족 사연, 경제 지표처럼 놀라움이 약한 뉴스는 고르지 마.\n"
        "   반드시 오늘·어제 실제로 일어난 '새 소식'이어야 해 (괄호 안 'N시간 전'이 작을수록, 검색량이 클수록 우선).\n"
        "   달걀 번호·세탁 요령처럼 언제 써도 되는 상식, 계절 일반론, 며칠 지난 이야기는 고르지 마.\n"
        "   (놀라운 숫자, 돈·손해, 다들 지금 검색하는 것일수록 좋음)\n"
        "   첫 줄에서 '오늘/방금/어제 ~했대'처럼 그 소식 자체를 바로 꺼내서 '지금 터진 일'이라는 느낌을 줘.\n"
        "2. 서로 다른 유형의 첫 줄 후킹 3개를 만들고, 스크롤을 가장 확실히 멈출 하나를 골라.\n"
        "3. 그 후킹으로 시작해 글 흐름대로 100~150자, 3~5줄 글을 써.\n"
        "   - 구체성: 읽는 사람이 '뭐가?' 하고 되묻지 않게 핵심 사실(무슨 제품·누가·어디·얼마)을 분명히 넣어.\n"
        "     예: '액정 160만원' 대신 '아이폰 17 프로 맥스 액정 수리비 160만원'. 이슈 제목에 없는 사실은 지어내지 마.\n"
        "   - 주어 필수: 첫 줄에 '누가/무엇이'(예: '테슬라 로드스터가', '일본 기상청이')를 꼭 쓰고, 그 문장이 무슨 일인지 혼자 읽어도 알게 해.\n"
        "     '차가', '이게', '그 사람이'처럼 뭉뚱그린 주어나 주어 생략은 금지. 기사 제목을 모르는 사람이 첫 두 줄만 읽고 무슨 일인지 알아야 해.\n"
        "   - 후킹: 첫 줄은 가장 충격적인 사실 하나만. 둘째 줄은 답을 바로 주지 말고 궁금증을 한 번 더 키워 ('근데 진짜 소름인 건…').\n"
        "   - 감정: 읽자마자 '헉', '어떡해', '말도 안 돼' 같은 느낌이 바로 오게. 생활 팁·훈계로 끝내지 마.\n"
        "   - 공감: '우리 집이었으면?', '나였으면?' 하는 짧은 한 줄로 내 일처럼 느끼게 해.\n"
        "   - 마지막 줄 질문은 누구나 바로 답할 수 있게 ('너네 같으면 어떻게 해?').\n"
        "4. 글과 어울리는 사진 프롬프트, 사진 검색어, 쿠팡 상품 검색 키워드도 정해."
        + _external_text(external)
        + _benchmark_text(benchmarks)
    )

    post = _ask(user_msg, SCHEMA)
    if not _subject_ok(post):  # 첫 두 줄에 주어가 없으면 한 번 더 쓰게 한다
        print(f"[writer] 첫 두 줄에 주어 '{post.get('subject')}' 없음 → 다시 씀")
        post = _ask(user_msg + "\n\n주의: 지난번엔 첫 두 줄에 주어(누가/무엇이)가 빠져서 무슨 일인지 몰랐어. "
                    "첫 줄에 subject를 그대로 넣어서 다시 써.", SCHEMA)
    return post


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
        "같은 이슈로 다시 써 줘. 지난번 첫 줄과 다른 유형의 후킹 3개를 만들고,\n"
        "가장 센 하나로 시작해 글 흐름대로 100~150자, 3~5줄로 써. 지난번 문장은 되풀이하지 마."
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
