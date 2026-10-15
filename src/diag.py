"""텔레그램 연결 점검: 버튼 신호가 왜 안 들어오는지 기록한다 (비밀값은 기록하지 않음)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import telegram

out = {"checked_at": datetime.now(timezone.utc).isoformat()}
try:
    info = telegram._call("getWebhookInfo")
    out["webhook_set"] = bool(info.get("url"))
    out["pending_update_count"] = info.get("pending_update_count")
    out["last_error_message"] = info.get("last_error_message")
    out["allowed_updates"] = info.get("allowed_updates")
except Exception as e:
    out["webhook_error"] = str(e)
try:
    ups = telegram._call("getUpdates", data={"timeout": 0, "limit": 100})  # 오프셋 없이 보기만 함
    out["updates_waiting"] = len(ups)
    out["updates"] = [{"update_id": u["update_id"], "kinds": [k for k in u if k != "update_id"],
                       "date": (u.get("callback_query", {}).get("message", {}) or u.get("message", {})).get("date")}
                      for u in ups[-10:]]
except Exception as e:
    out["updates_error"] = str(e)
Path(__file__).resolve().parent.parent.joinpath("state", "diag.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print(out)
