"""gil이 텔레그램으로 보낸 인기글 스냅샷 분석을 모아 둔다."""

import json
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "state" / "benchmarks.json"
KEEP = 30  # 최근 30개까지만 보관


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def add(item):
    items = load()
    item["added_at"] = datetime.now().isoformat(timespec="seconds")
    items.append(item)
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(items[-KEEP:], ensure_ascii=False, indent=1), encoding="utf-8")
    return len(items[-KEEP:])
