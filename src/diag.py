"""텔레그램 연결 점검: 버튼 신호가 왜 안 들어오는지 기록한다 (비밀값은 기록하지 않음)."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import telegram

out = {"checked_at": datetime.now(timezone.utc).isoformat()}
_t = os.environ.get("TELEGRAM_BOT_TOKEN", "")
out["token_shape"] = {  # 토큰 값은 남기지 않고 모양만 기록
    "length": len(_t), "stripped_length": len(_t.strip()), "colons": _t.count(":"),
    "first_part_is_digits": _t.strip().split(":")[0].isdigit(),
    "has_space_inside": " " in _t.strip(),
    "part_lengths": [len(x) for x in _t.strip().split(":")],
    "first_part_kind": ("digits" if _t.strip().split(":")[0].isdigit() else
                        "has_digits_and_letters" if any(c.isdigit() for c in _t.strip().split(":")[0]) else "letters_only"),
    "has_slash_or_dot": any(c in _t for c in "/."), "starts_with_bot": _t.strip().lower().startswith("bot"),
}
_th = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
out["threads_token_shape"] = {"length": len(_th), "starts_with_TH": _th.startswith("TH"),
                              "colons": _th.count(":"), "has_slash_or_dot": any(c in _th for c in "/."),
                              "first_part_is_digits": _th.split(":")[0].isdigit()}
if _th:
    try:
        import threads_api
        me = threads_api._get("me", fields="username")
        out["threads_login_ok"] = me.get("username")
    except Exception as e:
        out["threads_login_error"] = str(e)[:200]
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
