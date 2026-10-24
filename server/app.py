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
from .grid import CATEGORIES, PLANES, build_environments, categorise, quantise, tile_order
from .physics import MODES, TERRAINS, TRIALS, summarise_modes
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
        n = max(4, min(int(self.req.agents), 30))
        self.swarm = Swarm(self.platform, self.params, self.weather, self.climate, self.location, n, self.emit)
        cfg = self.swarm.cfg
        await self.phase("swarm", backend=self.swarm.backend, model=cfg["model"] if cfg else None,
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
                         "cat_counts": np.bincount(cat.ravel(), minlength=len(CATEGORIES)).tolist()})
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
            mode = await asyncio.to_thread(TRIALS[self.platform], self.params, e, K, rng)
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
                                 "cat_cells": cat_cells.tolist(), "cat_pass": cat_pass.tolist()})
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
            m = TRIALS[self.platform](p, sub, K, np.random.default_rng(9))
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
        await self.emit({"type": "report", "pass_rate": round(self.stats["pass_rate"] * 100, 2), "fixes": fixes,
                         "combined_after": round(comb * 100, 2),
                         "combined_params": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in combined.items()},
                         "cases": len(self.swarm.cases), "elapsed_s": round(time.time() - self.started, 1)})

    def cell(self, x, y):
        if self.env is None:
            raise HTTPException(409, "grid not built yet")
        x, y = int(np.clip(x, 0, self.S - 1)), int(np.clip(y, 0, self.S - 1))
        e = {k: v[y, x:x + 1] for k, v in self.env.items()}
        mode, margins = TRIALS[self.platform](self.params, e, 64, np.random.default_rng(y * 100003 + x), detail=True)
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
                "case": case}


@app.get("/api/meta")
def meta():
    cfg = claude_config()
    return {"platforms": PLATFORMS, "presets": PRESETS, "backend": "claude-agent-sdk" if cfg else "deterministic",
            "model": cfg["model"] if cfg else None}


@app.post("/api/runs")
async def create_run(req: RunRequest):
    if req.platform not in PLATFORMS:
        raise HTTPException(400, "unknown platform")
    run = Run(req)
    RUNS[run.id] = run
    asyncio.create_task(run.go())
    return {"id": run.id, "params": run.params, "location": run.location}


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
