"""Run many small screenings so the flight-ops review task in Mubit collects kept examples.

Point it at a server started with SWARM_BACKEND=mock (offline agents, no swarm LLM calls) and MUBIT_API_KEY set:
the only LLM call per run is the flight-ops review, which goes through Mubit.

  .venv/bin/python scripts/seed_review.py --url http://localhost:8813 --runs 30
"""
import argparse, asyncio, itertools, json, random, urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
DRONE = [{"id": "cw-hospital"}, {"id": "cw-loop"},
         {"name": "guys_to_royal_london.plan", "text": (ROOT / "docs/samples/guys_to_royal_london.plan").read_text(), "return": True}]
ROBOT = [{"id": "cw-crossharbour"}, {"id": "cw-mudchute"}]
DRONE_VAR = [{}, {"battery_wh": 160}, {"payload_kg": 1.9}, {"ip_rating": "IP55", "wind_resistance_ms": 15}, {"flight_controller": "adaptive"},
             {"reserve_pct": 10}, {"cruise_altitude_m": 60}, {"battery_heater": True, "battery_wh": 300}, {"lte_backup_link": True, "rtk_gps": True}]
ROBOT_VAR = [{}, {"locomotion": "tracked"}, {"payload_kg": 24}, {"ip_rating": "IP67"}, {"battery_wh": 400}]


def post(url, body):
    req = urllib.request.Request(url + "/api/runs", json.dumps(body).encode(), {"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req))["id"]


async def one(url, body, sem):
    async with sem:
        rid = await asyncio.to_thread(post, url, body)
        async with websockets.connect(url.replace("http", "ws") + f"/ws/runs/{rid}", max_size=None) as ws:
            async for m in ws:
                if isinstance(m, bytes):
                    continue
                e = json.loads(m)
                if e["type"] == "review":
                    print(body["platform"], body["route"].get("id") or body["route"]["name"], body["params"], "→", e.get("verdict") or e.get("error"), e.get("request_id"), flush=True)
                if e["type"] == "error" or (e["type"] == "phase" and e["phase"] == "done"):
                    return


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8813")
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--parallel", type=int, default=4)
    a = ap.parse_args()
    combos = [("drone", r, v) for r, v in itertools.product(DRONE, DRONE_VAR)] + [("robot", r, v) for r, v in itertools.product(ROBOT, ROBOT_VAR)]
    random.Random(7).shuffle(combos)
    sem = asyncio.Semaphore(a.parallel)
    await asyncio.gather(*[one(a.url, {"platform": p, "params": v, "route": r, "agents": 4, "grid": 256, "trials": 8}, sem) for p, r, v in combos[:a.runs]])


asyncio.run(main())
