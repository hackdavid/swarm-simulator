"""FastAPI app: run lifecycle, WebSocket event stream, cell inspector."""
from __future__ import annotations

import asyncio
import os
import struct
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .fixes import FIXES
from .grid import CATEGORIES, build_environments, categorise, quantise, tile_order
from .physics import MODES, TERRAINS, TRIALS, summarise_modes
from . import route as RT, routesim as RS
from .platforms import PLATFORMS, normalise
from .swarm import Swarm, claude_config
from .weather import PRESETS, fetch_year, summarise

WEB = Path(__file__).resolve().parent.parent / "web"
MAGIC = 0x50475244
app = FastAPI(title="Swarm Proving Ground")
RUNS: dict[str, "Run"] = {}


class RunRequest(BaseModel):
    platform: str = "drone"
    params: dict = {}
    location: dict = {"id": "london"}
    agents: int = 24
    grid: int = 1024
    trials: int = 16
    provider: str | None = None  # "direct" | "mubit"; default from SWARM_LLM_PROVIDER
    route: dict | None = None  # {"id": demo route} | {"name", "text", "return"} uploaded mission file


class Run:
    def __init__(self, req: RunRequest):
        self.id = uuid.uuid4().hex[:10]
        self.req = req
        self.platform = req.platform
        self.params = normalise(req.platform, req.params)
        loc = req.location or {}
        preset = next((p for p in PRESETS if p["id"] == loc.get("id")), None)
        self.location = preset or {"id": "custom", "name": loc.get("name") or "Custom site",
                                   "lat": float(loc.get("lat", 51.5)), "lon": float(loc.get("lon", -0.12))}
        self.route = RT.resolve(req.route, req.platform) if req.route else None
        self.prof = None
        if self.route:
            a, b = self.route["waypoints"][0][:2]
            self.location = {"id": "route", "name": self.route["name"], "lat": round(a, 3), "lon": round(b, 3)}
        self.events: list = []
        self.subs: set[asyncio.Queue] = set()
        self.started = time.time()
        self.env = None

    async def emit(self, ev):
        if isinstance(ev, dict):
            ev.setdefault("t", round(time.time() - self.started, 2))
        self.events.append(ev)
        for q in list(self.subs):
            q.put_nowait(ev)

    async def phase(self, name, **kw):
        await self.emit({"type": "phase", "phase": name, **kw})

    async def go(self):
        try:
            await self._go()
        except Exception as e:
            import traceback
            traceback.print_exc()
            await self.emit({"type": "error", "text": f"{type(e).__name__}: {e}"})

    async def _go(self):
        await self.phase("weather", text=f"Pulling 8,760 hours of real weather for {self.location['name']}")
        self.weather = await fetch_year(self.location["lat"], self.location["lon"])
        self.climate = summarise(self.weather)
        await self.emit({"type": "weather", "climate": self.climate, "location": self.location})
        await asyncio.sleep(1.2)
        if self.route:
            await self.phase("route", text=f"Mapping the mission corridor: {self.route['name']}")
            self.prof = await RT.build_profile(self.route, self.platform, self.params, self.emit)
            await self.emit({"type": "route", "route": self._route_payload()})
            await asyncio.sleep(float(os.environ.get("ROUTE_HOLD_SECONDS", "4")))
        n = max(4, min(int(self.req.agents), 30))
        self.swarm = Swarm(self.platform, self.params, self.weather, self.climate, self.location, n, self.emit, self.req.provider, self.prof)
        cfg = self.swarm.cfg
        await self.phase("swarm", backend=self.swarm.backend, model=cfg["model"] if cfg else None, provider=cfg["provider"] if cfg else None,
                         roster=self.swarm.roster())
        await self.swarm.run()
        await self.emit({"type": "swarm_done", "cases": len(self.swarm.cases), "physics_trials": self.swarm.physics_trials,
                         "cost_usd": round(self.swarm.cost_usd, 3), "tokens": self.swarm.tokens})
        await asyncio.sleep(1.0)
        await self._grid()
        await self._report()
        await self.phase("done")

    async def _grid(self):
        S = max(256, min(int(self.req.grid), 2048))
        K = max(4, min(int(self.req.trials), 64))
        self.S, self.K = S, K
        await self.phase("grid_build", text="Synthesising environment cells from the weather record + agent stress districts",
                         cells=S * S, trials=K)
        if self.prof:
            env = await asyncio.to_thread(RS.calendar_env, self.platform, self.params, self.weather, self.prof, S, 7)
            hotspot, regions = np.zeros((S, S), np.uint8), []
            self.seg_heat = np.zeros((len(MODES[self.platform]) + 1, len(self.prof["segments"])), np.int64)
        else:
            env, hotspot, regions = await asyncio.to_thread(build_environments, self.platform, self.params, self.weather, S, S,
                                                            int(time.time()) % 100000, self.swarm.cases)
        cat = categorise(env)
        self.env, self.hotspot, self.cat, self.regions = env, hotspot, cat, regions
        pay_max = max(float(env["payload"].max()), 0.1)
        q = quantise(self.platform, env, pay_max)
        self.passes = np.zeros((S, S), dtype=np.uint8)
        self.dom = np.zeros((S, S), dtype=np.uint8)
        await self.emit({"type": "grid_meta", "size": S, "trials": K, "tile": 64,
                         "planes": [{"name": n, "scale": float(sc), "offset": float(off)} for n, _, sc, off in q],
                         "categories": CATEGORIES, "modes": MODES[self.platform], "regions": regions, "terrains": TERRAINS,
                         "cat_counts": np.bincount(cat.ravel(), minlength=len(CATEGORIES)).tolist(),
                         "calendar": {"start": self.weather["start"], "days": len(self.weather["wind"]) // 24} if self.prof else None})
        await self.phase("grid_test", cells=S * S, trials=K)
        T = 64
        tiles = tile_order(S, S, T)
        reveal = float(os.environ.get("GRID_REVEAL_SECONDS", "16"))
        delay = reveal / len(tiles)
        rng = np.random.default_rng(42)
        nm = len(MODES[self.platform])
        mode_cells = np.zeros(nm + 1, dtype=np.int64)
        mode_flights = np.zeros(nm, dtype=np.int64)
        cat_cells = np.zeros(len(CATEGORIES), dtype=np.int64)
        cat_pass = np.zeros(len(CATEGORIES), dtype=np.int64)
        tested = flights_pass = 0
        for i, (ty, tx) in enumerate(tiles):
            t0 = time.time()
            sl = (slice(ty, ty + T), slice(tx, tx + T))
            e = {k: v[sl].ravel() for k, v in env.items()}
            mode = await asyncio.to_thread(self.trials, self.params, e, K, rng)
            if self.prof:
                self.seg_heat += await asyncio.to_thread(RS.failure_segments, self.platform, self.params, e, mode, self.prof, rng)
            passes, dom, counts = summarise_modes(mode, nm)
            self.passes[sl] = passes.reshape(T, T)
            self.dom[sl] = dom.reshape(T, T)
            c = cat[sl].ravel()
            tested += passes.size
            flights_pass += int(passes.sum())
            mode_cells += np.bincount(dom, minlength=nm + 1)
            mode_flights += counts.sum(axis=0)
            cat_cells += np.bincount(c, minlength=len(CATEGORIES))
            cat_pass += np.bincount(c, weights=passes, minlength=len(CATEGORIES)).astype(np.int64)
            buf = [struct.pack("<5i", MAGIC, tx, ty, T, T), cat[sl].tobytes(), self.passes[sl].tobytes(),
                   self.dom[sl].tobytes(), hotspot[sl].tobytes()] + [arr[sl].tobytes() for _, arr, _, _ in q]
            await self.emit(b"".join(buf))
            if i % 4 == 3 or i == len(tiles) - 1:
                await self.emit({"type": "grid_progress", "tested": tested, "total": S * S, "flights": tested * K,
                                 "flights_pass": flights_pass, "mode_cells": mode_cells.tolist(), "mode_flights": mode_flights.tolist(),
                                 "cat_cells": cat_cells.tolist(), "cat_pass": cat_pass.tolist(),
                                 **({"seg_fail": self.seg_heat.sum(0).tolist(), "seg_mode": self.seg_heat.argmax(0).tolist(),
                                     "seg_flights": tested * K} if self.prof else {})})
            await asyncio.sleep(max(0.0, delay - (time.time() - t0)))
        self.stats = {"pass_rate": flights_pass / (tested * K), "mode_flights": mode_flights}

    async def _report(self):
        await self.phase("report", text="Re-testing the plane with engineering fixes")
        modes = MODES[self.platform]
        order = np.argsort(-self.stats["mode_flights"])
        idx = np.random.default_rng(5).choice(self.S * self.S, 65536, replace=False)
        sub = {k: v.ravel()[idx] for k, v in self.env.items()}
        K = 8

        def rate(p):
            m = self.trials(p, sub, K, np.random.default_rng(9))
            return float((m == 0).mean())

        base = await asyncio.to_thread(rate, self.params)
        fixes, combined = [], dict(self.params)
        for j in order[:5]:
            if self.stats["mode_flights"][j] == 0:
                continue
            mode = modes[j]
            label, fn = FIXES[self.platform][mode["key"]]
            change = fn(self.params)
            r = await asyncio.to_thread(rate, {**self.params, **change})
            combined.update(fn(combined))
            fixes.append({"mode": mode["name"], "color": mode["color"], "fix": label, "change": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in change.items()},
                          "pass_before": round(base * 100, 2), "pass_after": round(r * 100, 2)})
            await self.emit({"type": "fix", "fix": fixes[-1]})
        comb = await asyncio.to_thread(rate, combined)
        route_risk = None
        if self.prof:
            mm = self.trials(self.params, sub, K, np.random.default_rng(3))
            exp = RS._rows(self.platform, self.params, sub, self.prof)["exposure"]
            risk = float(((mm > 0).mean(1) * exp).mean())
            route_risk = {"per_flight": risk, "per_million_flights": round(risk * 1e6, 1),
                          "max_igrc": max(sg["igrc"] for sg in self._route_payload()["segments"]),
                          "airspace": [z["name"] + " (" + z["type"] + ")" for z in self.prof["airspace"]]}
        await self.emit({"type": "report", "pass_rate": round(self.stats["pass_rate"] * 100, 2), "fixes": fixes,
                         "combined_after": round(comb * 100, 2),
                         "combined_params": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in combined.items()},
                         "cases": len(self.swarm.cases), "elapsed_s": round(time.time() - self.started, 1), "route_risk": route_risk})

    def cell(self, x, y):
        if self.env is None:
            raise HTTPException(409, "grid not built yet")
        x, y = int(np.clip(x, 0, self.S - 1)), int(np.clip(y, 0, self.S - 1))
        e = {k: v[y, x:x + 1] for k, v in self.env.items()}
        mode, margins = self.trials(self.params, e, 64, np.random.default_rng(y * 100003 + x), detail=True)
        passes, dom, counts = summarise_modes(mode, len(MODES[self.platform]))
        names = {m["id"]: m for m in MODES[self.platform]}
        hs = int(self.hotspot[y, x])
        region = next((r for r in self.regions if r["id"] == hs), None)
        case = next((c for c in self.swarm.cases if region and c["agent_id"] == region["agent_id"] and c["title"] == region["title"]), None)
        envv = {k: round(float(v[0]), 2) for k, v in e.items()}
        if "terrain" in envv:
            envv["terrain"] = TERRAINS[int(envv["terrain"])]
        return {"x": x, "y": y, "id": y * self.S + x, "category": CATEGORIES[int(self.cat[y, x])], "env": envv,
                "grid_pass": int(self.passes[y, x]), "grid_trials": self.K,
                "trials": 64, "pass": int(passes[0]), "trial_modes": mode[0].tolist(),
                "dominant": names.get(int(dom[0])), "histogram": {names[i + 1]["name"]: int(c) for i, c in enumerate(counts[0]) if c},
                "margins": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in margins.items()},
                "case": case, "when": self._when(x, y)}

    def trials(self, p, e, K, rng, detail=False):
        if self.prof:
            return RS.route_trials(self.platform, p, e, K, rng, self.prof, detail)
        return TRIALS[self.platform](p, e, K, rng, detail=detail)

    def _when(self, x, y):
        if not self.prof:
            return None
        import datetime as dt
        days = len(self.weather["wind"]) // 24
        d = dt.date.fromisoformat(self.weather["start"]) + dt.timedelta(days=int(x * days // self.S))
        h = y * 24 / self.S
        return f"{d.strftime('%a %d %b %Y')} · {int(h):02d}:{int((h % 1) * 60):02d} UTC"

    def _route_payload(self):
        if getattr(self, "_rp", None):
            return self._rp
        pr, f = self.prof, self.prof["feats"]
        la, lo = pr["samples"]["lat"][::3], pr["samples"]["lon"][::3]
        kx = 111320 * np.cos(np.radians(la.mean()))

        def near(pts, lim):
            a = np.array(pts[0])
            return float(np.min(np.hypot((la - a[0]) * 111320, (lo - a[1]) * kx))) < lim
        rp = lambda pts: [[round(p[0], 5), round(p[1], 5)] for p in pts]
        dim = 0.5 * (self.params.get("frame_mass_kg", 2) + self.params.get("payload_kg", 0)) ** (1 / 3) if self.platform == "drone" else 1
        col = 0 if dim <= 1 else 1 if dim <= 3 else 2
        segs = [{**sg, "igrc": RT.IGRC[sg["igrc_row"]][col]} for sg in pr["segments"]]
        major = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "footway", "pedestrian", "path"}
        self._rp = {"name": pr["name"], "desc": pr["desc"], "routed": pr["routed"], "length_m": pr["length_m"], "return": pr["return"],
                    "alt_m": pr["alt_m"], "bbox": pr["bbox"], "path": pr["path"], "segments": segs, "sources": pr["sources"],
                    "airspace": [{k: z[k] for k in ("name", "type", "code", "lower_m", "upper_m", "frac", "ring")} for z in pr["airspace"]],
                    "geofence": pr["geofence"],
                    "buildings": [[round(b["h"], 1), rp(b["pts"])] for b in f["buildings"] if near(b["pts"], 650)][:6000],
                    "roads": [[r["type"], rp(r["pts"])] for r in f["roads"] if r["type"] in major and near(r["pts"], 650)][:5000],
                    "water": [rp(w["pts"]) for w in f["water"] if len(w["pts"]) > 2 and near(w["pts"], 1500)][:400],
                    "green": [rp(g["pts"]) for g in f["green"] if len(g["pts"]) > 2 and near(g["pts"], 900)][:800]}
        return self._rp


@app.get("/api/meta")
def meta():
    cfg = claude_config()
    routes = {p: (c["model"] if (c := claude_config(p)) else None) for p in ("direct", "mubit")}
    return {"platforms": PLATFORMS, "presets": PRESETS, "backend": "claude-agent-sdk" if cfg else "deterministic",
            "model": cfg["model"] if cfg else None, "provider": cfg["provider"] if cfg else None, "routes": routes}


@app.post("/api/runs")
async def create_run(req: RunRequest):
    if req.platform not in PLATFORMS:
        raise HTTPException(400, "unknown platform")
    try:
        run = Run(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    RUNS[run.id] = run
    asyncio.create_task(run.go())
    return {"id": run.id, "params": run.params, "location": run.location}


@app.get("/api/routes")
def routes():
    return {"routes": RT.DEMO_ROUTES, "formats": ["QGroundControl .plan", "GeoJSON", "KML", "GPX"]}


class RouteFile(BaseModel):
    name: str = "route"
    text: str


@app.post("/api/routes/parse")
def parse_route(f: RouteFile):
    try:
        r = RT.parse_route(f.text, f.name)
    except Exception as e:
        raise HTTPException(400, f"could not parse route: {e}")
    if len(r["waypoints"]) < 2:
        raise HTTPException(400, "route needs at least 2 waypoints")
    return {"name": r["name"], "format": r["format"], "waypoints": r["waypoints"], "geofence": r["geofence"]}


@app.get("/api/runs/{rid}/cell")
def get_cell(rid: str, x: int, y: int):
    run = RUNS.get(rid)
    if not run:
        raise HTTPException(404)
    return run.cell(x, y)


@app.websocket("/ws/runs/{rid}")
async def ws_run(ws: WebSocket, rid: str):
    run = RUNS.get(rid)
    await ws.accept()
    if not run:
        await ws.close(code=4404)
        return
    q: asyncio.Queue = asyncio.Queue()
    for ev in list(run.events):
        q.put_nowait(ev)
    run.subs.add(q)
    try:
        while True:
            ev = await q.get()
            if isinstance(ev, bytes):
                await ws.send_bytes(ev)
            else:
                await ws.send_json(ev)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        run.subs.discard(q)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
