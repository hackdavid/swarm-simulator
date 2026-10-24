"""Run only the agent swarm (no grid) and record speed, reliability and output quality per LLM route.

  SWARM_LLM_PROVIDER=mubit .venv/bin/python scripts/bench_swarm.py --agents 8 --platform drone --tag mubit-1
"""
import argparse, asyncio, json, os, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.platforms import defaults  # noqa: E402
from server.swarm import Swarm, claude_config  # noqa: E402
from server.weather import PRESETS as LOCATIONS, fetch_year, summarise  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="drone", choices=["drone", "robot"])
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--location", default="london")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    cfg = claude_config()
    if not cfg:
        sys.exit("no LLM route configured (check SWARM_LLM_PROVIDER / keys)")
    loc = next(l for l in LOCATIONS if l["id"] == a.location)
    w = await fetch_year(loc["lat"], loc["lon"])
    events: list[dict] = []
    t0 = time.time()

    async def emit(ev):
        ev["t"] = round(time.time() - t0, 2)
        events.append(ev)

    sw = Swarm(a.platform, defaults(a.platform), w, summarise(w), loc, a.agents, emit)
    await sw.run()
    wall = time.time() - t0
    done = [e for e in events if e["type"] == "agent" and e["status"] == "done"]
    ae = [e for e in events if e["type"] == "agent_event"]
    errs = [e["text"] for e in ae if e["kind"] == "error"]
    first_tool = {}
    for e in ae:
        if e["kind"] == "tool_call":
            first_tool.setdefault(e["id"], e["t"])
    secs = sorted(d["seconds"] for d in done)
    out = {
        "tag": a.tag, "provider": cfg["provider"], "model": cfg["model"], "platform": a.platform, "agents": a.agents,
        "wall_s": round(wall, 1), "agent_s_median": secs[len(secs) // 2] if secs else None, "agent_s_max": secs[-1] if secs else None,
        "first_tool_s_median": sorted(first_tool.values())[len(first_tool) // 2] if first_tool else None,
        "llm_agents_ok": sum(1 for d in done if d["backend"] == "claude-agent-sdk"),
        "fallbacks": sum(1 for d in done if "fallback" in d["backend"]),
        "tool_calls": Counter(e["tool"] for e in ae if e["kind"] == "tool_call"),
        "verified_cases": len(sw.cases), "physics_trials": sw.physics_trials,
        "tokens": sw.tokens, "cost_usd": round(sw.cost_usd, 4), "errors": errs[:8],
    }
    d = Path(__file__).resolve().parents[1] / "data" / "bench"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{int(t0)}_{cfg['provider']}_{a.tag or a.platform}.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, default=str))


asyncio.run(main())
