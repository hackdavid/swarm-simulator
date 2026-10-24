"""Flight-ops go/no-go review: one recurring, single-turn Mubit call per run.

Same instructions every time, so Mubit groups the calls into one task. Replies rated in the Mubit console
become the kept examples its adapter is trained on; once the adapter is live, later reviews of the same
route are answered by it. History is kept per route so the UI can show how the answer changed.
"""
import json
import os
import time
from pathlib import Path

import httpx

from .swarm import MUBIT_BASE_URL

HISTORY = Path(__file__).resolve().parents[1] / "data" / "reviews.jsonl"

INSTRUCTIONS = """You are the flight-operations reviewer for a drone and ground-robot operator.
You get the engineering-screening summary of one mission route: pass rate over a real year of hourly weather,
the dominant failure modes, the ranked engineering fixes, the route's people-risk estimate and the airspace it crosses.
Decide whether the operator may schedule this mission.
Reply with JSON only, no prose around it:
{"verdict": "GO" | "GO WITH CONDITIONS" | "NO-GO",
 "reasons": [up to 3 short strings citing numbers from the summary],
 "conditions": [operational conditions or limits the crew must apply, may be empty],
 "fix_first": the single engineering fix to apply first, or null}"""


def review_model() -> str:
    return os.environ.get("SWARM_REVIEW_MODEL") or "claude-haiku-4-5"


def _parse(text: str) -> dict:
    t = text.strip()
    a, b = t.find("{"), t.rfind("}")
    try:
        return json.loads(t[a:b + 1])
    except Exception:
        return {"verdict": "UNPARSED", "reasons": [t[:300]], "conditions": [], "fix_first": None}


def history(route_key: str, n: int = 5) -> list[dict]:
    if not HISTORY.exists():
        return []
    rows = [json.loads(line) for line in HISTORY.read_text().splitlines() if line.strip()]
    return [r for r in rows if r.get("route_key") == route_key][-n:]


async def review(summary: dict, route_key: str) -> dict:
    key = os.environ.get("MUBIT_API_KEY")
    if not key:
        return {"ok": False, "error": "MUBIT_API_KEY is not set: the review runs only through Mubit.ai"}
    prev = history(route_key, 1)
    body = {"model": review_model(), "max_tokens": 400, "system": INSTRUCTIONS,
            "messages": [{"role": "user", "content": json.dumps(summary, separators=(",", ":"))}]}
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(os.environ.get("MUBIT_BASE_URL", MUBIT_BASE_URL) + "/v1/messages", json=body,
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Mubit unreachable: {type(e).__name__}"}
    rid = r.headers.get("x-middleware-request-id")
    if r.status_code != 200:
        return {"ok": False, "error": f"Mubit {r.status_code}: {r.text[:200]}", "request_id": rid}
    d = r.json()
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    out = {"ok": True, "route_key": route_key, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "request_id": rid,
           "model_asked": body["model"], "model_served": d.get("model"), "seconds": round(time.time() - t0, 1),
           "summary": summary, **_parse(text)}
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(out) + "\n")
    out["previous"] = prev[0] if prev else None
    return out
