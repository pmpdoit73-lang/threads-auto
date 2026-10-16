"""쓰레드 인기글을 가져올 수 있는지 시험 (결과만 저장, 비밀값 기록 안 함)."""

import json
from pathlib import Path

import threads_api

out = {}
for q in ["살림", "생활꿀팁", "주부"]:
    for fields in ["id,text,timestamp,username,permalink,like_count,reply_count,repost_count,quote_count",
                   "id,text,timestamp,username,permalink"]:
        try:
            r = threads_api._get("keyword_search", q=q, search_type="TOP", fields=fields, limit=25)
            out[f"search:{q}"] = {"fields": fields, "count": len(r.get("data", [])),
                                  "sample": r.get("data", [])[:25]}
            break
        except Exception as e:
            out[f"search:{q}:err:{fields[:20]}"] = str(e)[:300]

mine = []
try:
    posts = threads_api._get("me/threads", fields="id,text,timestamp,permalink", limit=25).get("data", [])
    for p in posts:
        try:
            ins = threads_api._get(f"{p['id']}/insights", metric="views,likes,replies,reposts,quotes")
            p["metrics"] = {m["name"]: m["values"][0]["value"] if m.get("values") else m.get("total_value", {}).get("value")
                            for m in ins.get("data", [])}
        except Exception as e:
            p["metrics_err"] = str(e)[:200]
        mine.append(p)
except Exception as e:
    out["mine_err"] = str(e)[:300]
out["mine"] = mine
Path(__file__).resolve().parent.parent.joinpath("state", "probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps({k: (v if k != "mine" else len(v)) for k, v in out.items() if not k.startswith("search:") or "err" in k}, ensure_ascii=False))
