"""Claude로 이슈를 고르고, 2초 후킹으로 시작하는 살림 고수 글을 쓴다."""

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
        "image_prompt": {"type": "string", "description": "사진 생성용 영어 프롬프트. 사람 얼굴·글자·로고 없이"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
        "product_keyword": {"type": "string", "description": "쿠팡에서 검색할 한국어 상품 키워드"},
    },
    "required": ["issue", "angle", "hooks", "text", "image_prompt", "photo_query", "product_keyword"],
    "additionalProperties": False,
}


def write_post(trends, recent_issues=()):
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
