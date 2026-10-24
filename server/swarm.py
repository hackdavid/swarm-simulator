"""Swarm of parallel failure-hunting agents.

Live backend: Claude Agent SDK (the Claude Code agent loop) with three in-process
MCP tools bound to the real weather record and the physics engine. If no Claude
credentials are configured, or an agent errors, a clearly labelled deterministic
agent runs the same tool loop so the demo never stalls.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import tempfile
import time
from typing import Any, Awaitable, Callable

from .fixes import FIXES
from .physics import MODES, TERRAINS, evaluate_scenario
from .roster import ROLES
from .weather import find_hours

Emit = Callable[[dict], Awaitable[None]]

DRONE_FIELDS = {
    "wind_ms": "mean wind at cruise altitude (m/s)", "gust_ms": "peak gust at cruise altitude (m/s)",
    "rain_mmh": "rain rate (mm/h)", "snow_cmh": "snowfall (cm/h)", "temp_c": "air temperature (°C)",
    "humidity_pct": "relative humidity (%)", "pressure_hpa": "surface pressure (hPa)",
    "visibility_km": "visibility (km)", "payload_kg": "payload mass carried (kg)",
}
ROBOT_FIELDS = {**DRONE_FIELDS, "wind_ms": "mean wind at ground (m/s)", "gust_ms": "peak gust at ground (m/s)",
                "slope_deg": "terrain slope (deg)", "friction": "surface friction coefficient (0.05-1)",
                "mud_depth_cm": "mud/standing water depth (cm)", "snow_depth_cm": "lying snow depth (cm)",
                "obstacle_cm": "obstacle/kerb height (cm)"}


MUBIT_BASE_URL = "https://api.mubit.ai/anthropic"


def claude_config(provider: str | None = None) -> dict | None:
    """LLM route for the Claude Agent SDK agents: "direct" or "mubit" (default from SWARM_LLM_PROVIDER)."""
    if os.environ.get("SWARM_BACKEND") == "mock":
        return None
    provider = (provider or os.environ.get("SWARM_LLM_PROVIDER") or "direct").strip().lower()
    base_env = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1"}
    if provider == "mubit":
        key = os.environ.get("MUBIT_API_KEY")
        if not key:
            return None
        model = os.environ.get("SWARM_MUBIT_MODEL") or "claude-sonnet-5-5"
        small = os.environ.get("SWARM_MUBIT_SMALL_MODEL") or "claude-haiku-4-5"
        # Mubit refuses calls that also carry a provider key, so the key goes in ANTHROPIC_AUTH_TOKEN only.
        env = {**base_env, "ANTHROPIC_BASE_URL": os.environ.get("MUBIT_BASE_URL", MUBIT_BASE_URL), "ANTHROPIC_AUTH_TOKEN": key,
               "ANTHROPIC_API_KEY": "", "ANTHROPIC_DEFAULT_HAIKU_MODEL": small, "ANTHROPIC_SMALL_FAST_MODEL": small,
               "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"}
        return {"env": env, "model": model, "provider": "mubit"}
    base = os.environ.get("ANTHROPIC_BASE_URL")
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    model = os.environ.get("SWARM_MODEL") or os.environ.get("ANTHROPIC_MODEL")
    if not key and os.environ.get("PW_LLM_API_KEY"):
        key = os.environ["PW_LLM_API_KEY"]
        base = os.environ.get("PW_LLM_BASE_URL", "").rstrip("/").removesuffix("/v1") or None
        model = model or os.environ.get("PW_LLM_MODEL")
    if not key:
        return None
    env = {**base_env, "ANTHROPIC_API_KEY": key}
    if base:
        env["ANTHROPIC_BASE_URL"] = base
    if model:
        env["ANTHROPIC_SMALL_FAST_MODEL"] = model
    return {"env": env, "model": model or "claude-sonnet-4-5", "provider": "direct"}


def _round(d):
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}


class AgentLab:
    """The tools one agent can call. Shared by the Claude and deterministic backends."""

    def __init__(self, swarm: "Swarm", idx: int, role: tuple):
        self.s, self.idx, self.role = swarm, idx, role
        self.tool_calls = 0
        self.cases: list[dict] = []
        self.tests: list[dict] = []

    async def _event(self, kind, **kw):
        await self.s.emit({"type": "agent_event", "id": self.idx, "kind": kind, **kw})

    async def find_weather_hours(self, args: dict) -> dict:
        self.tool_calls += 1
        res = find_hours(self.s.weather, args)
        await self._event("tool_result", tool="find_weather_hours",
                          text=f"{res['matching_hours']} matching hours ({res['share_of_year_pct']}% of year)")
        return res

    async def run_physics_test(self, args: dict) -> dict:
        self.tool_calls += 1
        res = await asyncio.to_thread(evaluate_scenario, self.s.platform, self.s.params, args, 200, 11 + len(self.tests))
        self.tests.append({"scenario": args, "pass": res["pass_rate_pct"], "fail": res["dominant_failure"]})
        self.s.physics_trials += res["trials"]
        await self._event("tool_result", tool="run_physics_test", passrate=res["pass_rate_pct"],
                          text=f"{res['pass_rate_pct']}% pass of 200 trials" + (f" · {res['dominant_failure']}" if res["dominant_failure"] else ""))
        return res

    async def submit_failure_case(self, args: dict) -> dict:
        self.tool_calls += 1
        sc = args.get("scenario") or {}
        if isinstance(sc, str):
            try:
                sc = json.loads(sc)
            except Exception:
                sc = {}
        res = await asyncio.to_thread(evaluate_scenario, self.s.platform, self.s.params, sc, 400, 99)
        if res["pass_rate_pct"] > 80:
            await self._event("tool_result", tool="submit_failure_case",
                              text=f"rejected — verified {res['pass_rate_pct']}% pass, not a failure")
            return {"accepted": False, "reason": f"Verification passed {res['pass_rate_pct']}% of 400 trials; refine toward harsher conditions.", "verification": res}
        case = {"id": len(self.s.cases) + 1, "agent_id": self.idx, "agent": self.role[0],
                "title": str(args.get("title", "Failure case"))[:90], "mechanism": str(args.get("mechanism", ""))[:400],
                "severity": args.get("severity", "high"), "mitigation": str(args.get("mitigation", ""))[:300],
                "scenario": _round({k: v for k, v in sc.items() if isinstance(v, (int, float, str))}),
                "verified_pass_pct": res["pass_rate_pct"], "dominant_failure": res["dominant_failure"],
                "hours_in_year": self._hours_like(sc)}
        self.cases.append(case)
        self.s.cases.append(case)
        await self.s.emit({"type": "case", "case": case})
        await self._event("tool_result", tool="submit_failure_case",
                          text=f"accepted · verified {res['pass_rate_pct']}% pass → {res['dominant_failure']}")
        return {"accepted": True, "case_id": case["id"], "verification": res}

    def _hours_like(self, sc):
        f = {}
        sh = self.s.shear
        if isinstance(sc.get("gust_ms"), (int, float)):
            f["min_gust_ms"] = sc["gust_ms"] / sh * 0.9
        if isinstance(sc.get("rain_mmh"), (int, float)) and sc["rain_mmh"] > 0:
            f["min_rain_mmh"] = sc["rain_mmh"] * 0.8
        if isinstance(sc.get("temp_c"), (int, float)) and sc["temp_c"] < 5:
            f["max_temp_c"] = sc["temp_c"] + 2
        if isinstance(sc.get("temp_c"), (int, float)) and sc["temp_c"] > 25:
            f["min_temp_c"] = sc["temp_c"] - 2
        return find_hours(self.s.weather, f, 0)["matching_hours"] if f else None


class Swarm:
    def __init__(self, platform, params, weather, climate, location, n_agents, emit: Emit, provider: str | None = None):
        self.platform, self.params, self.weather, self.climate = platform, params, weather, climate
        self.location, self.emit = location, emit
        self.roles = ROLES[platform][:n_agents]
        self.cases: list[dict] = []
        self.physics_trials = 0
        self.cost_usd = 0.0
        self.tokens = 0
        self.shear = (max(params.get("cruise_altitude_m", 10), 10) / 10) ** 0.14 if platform == "drone" else 1.0
        self.cfg = claude_config(provider)
        self.backend = "claude-agent-sdk" if self.cfg else "deterministic"

    def roster(self):
        return [{"id": i, "name": r[0], "focus": r[1], "vars": r[2]} for i, r in enumerate(self.roles)]

    async def run(self):
        sem = asyncio.Semaphore(int(os.environ.get("SWARM_CONCURRENCY", "30")))

        async def one(i, role):
            await asyncio.sleep(0.12 * i)
            async with sem:
                lab = AgentLab(self, i, role)
                t0 = time.time()
                await self.emit({"type": "agent", "id": i, "status": "running", "backend": self.backend})
                backend = self.backend
                try:
                    if self.cfg:
                        await asyncio.wait_for(self._claude_agent(lab), timeout=float(os.environ.get("SWARM_AGENT_TIMEOUT", "300")))
                    else:
                        await self._deterministic_agent(lab)
                except Exception as e:  # keep the swarm alive
                    await lab._event("error", text=f"{type(e).__name__}: {str(e)[:160]} — switching to deterministic agent")
                    backend = "deterministic (fallback)"
                    if not lab.cases:
                        await self._deterministic_agent(lab)
                await self.emit({"type": "agent", "id": i, "status": "done", "cases": len(lab.cases),
                                 "tool_calls": lab.tool_calls, "seconds": round(time.time() - t0, 1), "backend": backend,
                                 "cost_usd": round(self.cost_usd, 4), "tokens": self.tokens})

        await asyncio.gather(*(one(i, r) for i, r in enumerate(self.roles)))

    # ---------- shared prompt context ----------
    def _context(self) -> str:
        c = self.climate
        clim = {"source": c["source"], "period": c["period"], "percentiles_at_10m": c["percentiles"],
                "counts": c["counts"], "extremes": c["extremes"], "monthly": c["monthly"]}
        fields = DRONE_FIELDS if self.platform == "drone" else ROBOT_FIELDS
        note = (f"Weather is measured at 10 m. At the cruise altitude of {self.params.get('cruise_altitude_m')} m, wind and gusts are "
                f"x{self.shear:.2f} stronger (power-law shear) — use altitude values in scenarios." if self.platform == "drone"
                else f"Terrains available: {', '.join(TERRAINS)}. Wet surfaces lose ~20% friction; ice is ~0.12-0.2.")
        return (f"VEHICLE ({self.platform}) PARAMETERS:\n{json.dumps(self.params)}\n\n"
                f"LOCATION: {self.location['name']} ({self.location['lat']}, {self.location['lon']})\n"
                f"LAST 12 MONTHS OF HOURLY WEATHER (summary):\n{json.dumps(clim)}\n\n{note}\n\n"
                f"SCENARIO FIELDS for run_physics_test / submit_failure_case: {json.dumps(fields)}")

    # ---------- Claude Agent SDK backend ----------
    async def _claude_agent(self, lab: AgentLab):
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ThinkingBlock,
                                      ToolUseBlock, create_sdk_mcp_server, query, tool)

        fields = DRONE_FIELDS if self.platform == "drone" else ROBOT_FIELDS
        props: dict[str, Any] = {k: {"type": "number", "description": v} for k, v in fields.items()}
        if self.platform == "robot":
            props["terrain"] = {"type": "string", "enum": TERRAINS}
        scen_schema = {"type": "object", "properties": props}

        def wrap(fn):
            async def h(args):
                try:
                    out = await fn(args)
                except Exception as e:
                    out = {"error": str(e)}
                return {"content": [{"type": "text", "text": json.dumps(out)}]}
            return h

        t_hours = tool("find_weather_hours", "Search the real 8,760-hour weather record (10 m values). Returns count and the worst matching hours.",
                       {"type": "object", "properties": {
                           "min_gust_ms": {"type": "number"}, "min_wind_ms": {"type": "number"}, "min_rain_mmh": {"type": "number"},
                           "max_temp_c": {"type": "number"}, "min_temp_c": {"type": "number"}, "min_humidity_pct": {"type": "number"},
                           "min_snow_cmh": {"type": "number"}, "max_pressure_hpa": {"type": "number"},
                           "sort": {"type": "string", "enum": ["gust", "rain", "cold", "heat"]}}})(wrap(lab.find_weather_hours))
        t_phys = tool("run_physics_test", "Fly/drive the vehicle 200 times in one scenario with randomised turbulence and component health. Returns pass rate, failure histogram and physical margins.",
                      scen_schema)(wrap(lab.run_physics_test))
        t_sub = tool("submit_failure_case", "Submit a verified failure case. It is re-verified with 400 trials and rejected if it passes >80%.",
                     {"type": "object", "properties": {
                         "title": {"type": "string"}, "mechanism": {"type": "string", "description": "causal chain, 1-2 sentences"},
                         "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                         "mitigation": {"type": "string"}, "scenario": scen_schema},
                      "required": ["title", "mechanism", "severity", "mitigation", "scenario"]})(wrap(lab.submit_failure_case))
        server = create_sdk_mcp_server("lab", "1.0.0", [t_hours, t_phys, t_sub])
        name, focus, _ = lab.role
        # One shared system prompt per platform: Mubit groups calls into a task by instructions + tools + model,
        # so the per-agent role goes in the user message and the whole swarm trains a single adapter.
        system = (f"You are one agent in a parallel swarm hunting failure cases for a {self.platform} before it is deployed. "
                  "Your specialty is given in the user message. Ground every scenario in the real weather record "
                  "(use find_weather_hours) and verify with run_physics_test. Search for the minimal realistic scenario that fails. "
                  "Submit 1-2 failure cases (pass rate below ~50%) with a concrete engineering mitigation. If the vehicle survives "
                  "everything realistic in your specialty, say so. Max 6 tool calls. Think briefly. Finish with one sentence.")
        opts = ClaudeAgentOptions(model=self.cfg["model"], system_prompt=system, mcp_servers={"lab": server},
                                  allowed_tools=["mcp__lab__find_weather_hours", "mcp__lab__run_physics_test", "mcp__lab__submit_failure_case"],
                                  tools=[], max_turns=14, env=self.cfg["env"], cwd=tempfile.gettempdir())
        prompt = (f"You are '{name}', agent {lab.idx + 1} of {len(self.roles)}. Your specialty: {focus}.\n\n"
                  + self._context() + "\n\nBegin your investigation now.")
        async for m in query(prompt=prompt, options=opts):
            if isinstance(m, AssistantMessage):
                for b in m.content:
                    if isinstance(b, ThinkingBlock) and b.thinking.strip():
                        await lab._event("thinking", text=b.thinking.strip()[:600])
                    elif isinstance(b, TextBlock) and b.text.strip():
                        await lab._event("text", text=b.text.strip()[:600])
                    elif isinstance(b, ToolUseBlock):
                        await lab._event("tool_call", tool=b.name.replace("mcp__lab__", ""), args=b.input)
            elif isinstance(m, ResultMessage):
                self.cost_usd += m.total_cost_usd or 0
                u = m.usage or {}
                self.tokens += int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0)

    # ---------- deterministic backend (same tools, scripted reasoning) ----------
    async def _deterministic_agent(self, lab: AgentLab):
        rnd = random.Random(lab.idx * 7919 + 3)
        name, focus, vars_ = lab.role
        pc = self.climate["percentiles"]
        sh = self.shear
        base = {"wind_ms": pc["wind"]["p50"] * sh, "gust_ms": pc["gust"]["p50"] * sh, "temp_c": pc["temp"]["p50"],
                "humidity_pct": pc["rh"]["p50"], "pressure_hpa": pc["pressure"]["p50"], "rain_mmh": 0.0,
                "payload_kg": self.params.get("payload_kg", 0)}
        if self.platform == "robot":
            base.update({"slope_deg": 8, "terrain": rnd.choice(["grass", "gravel", "dirt/mud"]), "obstacle_cm": 4})
        pay = max(self.params.get("payload_kg", 0), 0.2)

        def level(lv):
            s = dict(base)
            q = ["p90", "p99", "max"][lv]
            for v in vars_:
                if v == "gust":
                    s["gust_ms"] = pc["gust"][q] * sh * (1 + 0.12 * lv)
                    s["wind_ms"] = max(s["wind_ms"], pc["wind"]["p90"] * sh)
                elif v == "wind":
                    s["wind_ms"] = pc["wind"][q] * sh * (1 + 0.15 * lv)
                    s["gust_ms"] = max(s["gust_ms"], s["wind_ms"] * 1.4)
                elif v == "temp_low":
                    s["temp_c"] = [pc["temp"]["min"] + 6, pc["temp"]["min"], pc["temp"]["min"] - 6][lv]
                elif v == "temp_ice":
                    s["temp_c"] = [1.0, -1.5, -4.0][lv]
                    s["humidity_pct"] = 95
                elif v == "temp_high":
                    s["temp_c"] = [pc["temp"]["p99"], pc["temp"]["max"], pc["temp"]["max"] + 5][lv]
                elif v == "rain":
                    s["rain_mmh"] = [max(pc["precip"]["p99"], 1.5), max(pc["precip"]["max"], 4), max(pc["precip"]["max"] * 1.6, 9)][lv]
                    s["humidity_pct"] = 97
                elif v == "rain_light":
                    s["rain_mmh"] = [0.4, 0.8, 1.5][lv]
                    s["humidity_pct"] = 96
                elif v == "rh":
                    s["humidity_pct"] = [93, 97, 99][lv]
                elif v == "vis_low":
                    s["visibility_km"] = [1.5, 0.6, 0.2][lv]
                    s["humidity_pct"] = 98
                elif v == "snow":
                    s["snow_cmh"] = [0.3, 0.9, 2.0][lv]
                    s["temp_c"] = min(s["temp_c"], -1)
                elif v == "payload":
                    s["payload_kg"] = pay * [1.25, 1.55, 1.9][lv]
                elif v == "pressure_low":
                    s["pressure_hpa"] = pc["pressure"]["min"] - [0, 8, 20][lv]
                elif v == "slope":
                    s["slope_deg"] = [16, 23, 30][lv]
                elif v == "friction_low":
                    s["friction"] = [0.45, 0.3, 0.16][lv]
                elif v == "mud":
                    s["mud_depth_cm"] = [6, 13, 22][lv]
                    s["terrain"] = "dirt/mud"
                elif v == "snow_depth":
                    s["snow_depth_cm"] = [8, 18, 30][lv]
                    s["temp_c"] = min(s["temp_c"], -2)
                elif v == "obstacle":
                    s["obstacle_cm"] = [9, 14, 20][lv]
            return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()}

        say = lab._event
        await say("thinking", text=f"Specialty: {focus}. Pulling the {self.climate['hours']:,}-hour record for {self.location['name']} to anchor the search.")
        await asyncio.sleep(rnd.uniform(0.6, 1.4))
        q = {"gust": {"min_gust_ms": pc["gust"]["p99"], "sort": "gust"}, "temp_low": {"max_temp_c": pc["temp"]["p50"] - 10, "sort": "cold"},
             "temp_high": {"min_temp_c": pc["temp"]["p99"], "sort": "heat"}, "rain": {"min_rain_mmh": pc["precip"]["p99"], "sort": "rain"}}
        qa = next((q[v] for v in vars_ if v in q), {"min_gust_ms": pc["gust"]["p90"], "sort": "gust"})
        await say("tool_call", tool="find_weather_hours", args=qa)
        await lab.find_weather_hours(qa)
        await asyncio.sleep(rnd.uniform(0.5, 1.2))
        found = None
        for lv in range(3):
            sc = level(lv)
            await say("thinking", text=f"Hypothesis {lv + 1}: escalate {', '.join(vars_)} to the {['p90', 'p99', 'record'][lv]} level and fly 200 trials.")
            await asyncio.sleep(rnd.uniform(0.4, 1.0))
            await say("tool_call", tool="run_physics_test", args=sc)
            r = await lab.run_physics_test(sc)
            await asyncio.sleep(rnd.uniform(0.6, 1.6))
            if r["pass_rate_pct"] < 50:
                found = (sc, r)
                break
        if not found:
            await say("text", text=f"Envelope holds for {focus} up to record conditions — no failure case submitted.")
            return
        sc, r = found
        mode = next(m for m in MODES[self.platform] if m["name"] == r["dominant_failure"])
        fix = FIXES[self.platform][mode["key"]][0]
        await say("thinking", text=f"Failure reproduced: {r['dominant_failure']} at {r['pass_rate_pct']}% pass. Submitting with mitigation: {fix}.")
        args = {"title": f"{r['dominant_failure']} — {name.lower()}", "severity": "critical" if r["pass_rate_pct"] < 10 else "high",
                "mechanism": f"Under {', '.join(vars_)} stress the {mode['name'].lower()} margin is exceeded (see margins).", "mitigation": fix, "scenario": sc}
        await say("tool_call", tool="submit_failure_case", args={"title": args["title"]})
        await lab.submit_failure_case(args)
        await say("text", text=f"Done: 1 verified failure case ({r['dominant_failure']}).")
