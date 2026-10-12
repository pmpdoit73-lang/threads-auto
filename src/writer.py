"""Claude로 이슈를 고르고, 살림 고수 말투로 100자 글을 쓴다."""

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
        "text": {"type": "string", "description": "쓰레드 본문 (80~120자)"},
        "image_prompt": {"type": "string", "description": "사진 생성용 영어 프롬프트. 사람 얼굴·글자·로고 없이"},
        "photo_query": {"type": "string", "description": "무료 사진 검색용 영어 키워드 2~3단어"},
        "product_keyword": {"type": "string", "description": "쿠팡에서 검색할 한국어 상품 키워드"},
    },
    "required": ["issue", "angle", "text", "image_prompt", "photo_query", "product_keyword"],
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
        "1. 금지 주제를 빼고, 살림·생활과 자연스럽게 연결되면서 사람들이 많이 볼 이슈 하나를 골라.\n"
        "2. 그 이슈를 살림 고수 시선의 경험담으로 80~120자 글로 써.\n"
        "3. 글과 어울리는 사진 프롬프트, 사진 검색어, 쿠팡 상품 검색 키워드도 정해."
    )

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=PERSONA,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 이번 이슈 목록으로는 글쓰기를 거절했어요.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
