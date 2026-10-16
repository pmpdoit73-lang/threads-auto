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
        "angle": {"type": "string", "description": "살림 시선으로 어떻게 풀었는지 한 줄"},
        "hooks": {"type": "array", "items": {"type": "string"},
                  "description": "서로 다른 유형의 첫 줄 후킹 후보 3개"},
        "text": {"type": "string", "description": "가장 센 후킹으로 시작하는 쓰레드 본문 (100~150자, 3~5줄)"},
        "image_prompt": {"type": "string", "description": "사진 생성용 영어 프롬프트. 내가 집에서 폰으로 직접 찍은 듯한 평범한 실사 장면 묘사 (구체적인 물건·장소·상황 위주, 삐딱한 구도·대충 찍은 느낌, 예쁜 연출·광고 사진 느낌 금지). 사람 얼굴·글자·로고 없이"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
        "product_keyword": {"type": "string", "description": "쿠팡에서 검색할 한국어 상품 키워드"},
        "benchmark_note": {"type": "string",
                           "description": "조회수 높았던 글에서 무엇을 가져왔는지 한 줄 (참고 글이 없으면 빈 문자열)"},
    },
    "required": ["issue", "angle", "hooks", "text", "image_prompt", "photo_query", "product_keyword",
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
          "내용·문장은 절대 베끼지 말고, 페르소나와 금지 주제(정치·범죄·연예 가십 등)는 그대로 지켜.\n"
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
        "1. 금지 주제를 빼고, 살림·생활과 이어지면서 '어? 나도 해당되나?' 싶어 꼭 읽고 싶어질 이슈 하나를 골라.\n"
        "   (놀라운 숫자, 돈·손해, 계절 변화, 다들 궁금해하는 것일수록 좋음)\n"
        "2. 서로 다른 유형의 첫 줄 후킹 3개를 만들고, 스크롤을 가장 확실히 멈출 하나를 골라.\n"
        "3. 그 후킹으로 시작해 글 흐름대로 100~150자, 3~5줄 글을 써.\n"
        "4. 글과 어울리는 사진 프롬프트, 사진 검색어, 쿠팡 상품 검색 키워드도 정해."
        + _external_text(external)
        + _benchmark_text(benchmarks)
    )

    return _ask(user_msg, SCHEMA)


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
