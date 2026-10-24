# Swarm Proving Ground

Pick a **drone** or **ground robot**, set its engineering parameters, and watch a swarm of
20–30 parallel **Claude Agent SDK** agents hunt for its failure cases in a real year of hourly
weather. The swarm's findings then seed a zoomable plane of **~1 million environment cells**,
each one Monte-Carlo-tested, which you can zoom down to a single cell and watch the vehicle
fly (or crash) in its own rain / wind / snow / fog / heat.

```
1 Platform  →  2 Parameters  →  3 Agent swarm  →  4 Proving ground (1M cells)  →  fixes report
```

## Run

```bash
uv sync
uv run uvicorn server.app:app --port 8811
# open http://localhost:8811
```

Claude credentials (any one):

| env var | meaning |
|---|---|
| `ANTHROPIC_API_KEY` (+ optional `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`/`SWARM_MODEL`) | standard Anthropic / compatible proxy |
| `PW_LLM_API_KEY`, `PW_LLM_BASE_URL`, `PW_LLM_MODEL` | fallback proxy config |
| `SWARM_BACKEND=mock` | force deterministic agents (no LLM calls, free, same tool protocol) |
| `SWARM_LLM_PROVIDER=mubit` + `MUBIT_API_KEY` (+ optional `SWARM_MUBIT_MODEL`, default `claude-sonnet-5-5`) | route the Claude Agent SDK agents through the [Mubit](https://docs.mubit.ai) proxy (`https://api.mubit.ai/anthropic`), which records calls, groups them into tasks and trains adapters. `direct` (default) keeps the route above |

Tuning: `SWARM_CONCURRENCY` (default 30), `SWARM_AGENT_TIMEOUT` (s, default 300),
`GRID_REVEAL_SECONDS` (pacing of the plane fill, default 16).

The route can also be picked per run in the UI ("LLM route" chips) or with `"provider": "direct"|"mubit"` in `POST /api/runs`.
Benchmark a route without the grid: `SWARM_LLM_PROVIDER=mubit .venv/bin/python scripts/bench_swarm.py --agents 8` (results in `data/bench/`).

No key? The app runs with deterministic search agents that call the same three tools.

## How it works

| stage | what happens | code |
|---|---|---|
| Weather | 8,760 hourly records (wind, gusts, rain, snow, temp, humidity, pressure, cloud) for the last 12 months from the Open-Meteo historical archive (ERA5), cached in `data/weather_cache`. Synthetic fallback only if offline. | `server/weather.py` |
| Agent swarm | Up to 30 specialist roles per platform (gust-front hunter, cold-soak battery chemist, ingress, icing, tip-over, mud, …) run concurrently via `claude_agent_sdk.query`. Each gets in-process MCP tools: `find_weather_hours`, `run_physics_test` (200 trials), `submit_failure_case`. Every submission is re-verified with 400 trials and rejected if it passes >80%. | `server/swarm.py`, `server/roster.py` |
| Proving ground | S×S cells (default 1024² = 1,048,576). Each cell is an environment drawn from the empirical weather distribution with spatial coherence, plus payload (and for robots slope, terrain, friction, mud, snow depth, obstacles). Agent cases are painted in as "stress districts". Every cell runs K Monte-Carlo trials (default 16 → ~16.8M simulated flights), streamed to the browser as 64×64 binary tiles. | `server/grid.py`, `server/app.py` |
| Physics | Vectorised NumPy reduced-order models: thrust/weight, drag, air density, gust rejection, motor saturation, battery derating & endurance, IP rain tolerance, icing, thermal, perception; robots add traction, torque-limited climb, tip-over, bogging, obstacle strike. | `server/physics.py` |
| Fixes | Top failure modes get an engineering change (adaptive FC, bigger battery, heater, IP upgrade, tracks, wider stance…) and the plane is re-sampled (65,536 cells × 8 trials) to measure pass-rate before → after. "Apply all fixes & re-run" launches a new run with the combined design. | `server/fixes.py` |

### UI

* **Swarm screen** – live agent network (particles = tool calls/results), one card per agent with its latest thought/tool, climate charts, verified-case feed.
* **Plane** – scroll to zoom (×0.2 → ×400), drag to pan, Outcome / Weather / Failure-mode views, agent districts (click to fly), minimap. At high zoom every cell renders its own animated weather scene with the vehicle and its pass %. Click a cell for the inspector: 64 fresh trials, replay of each trial, environment, physics margins, failure breakdown.

### API

`GET /api/meta` · `POST /api/runs` · `WS /ws/runs/{id}` (JSON events + binary tiles) · `GET /api/runs/{id}/cell?x=&y=`

## Honesty notes

Results are **simulation findings** from reduced-order models seeded with measured weather —
useful for ranking risks and comparing designs, not a substitute for flight/field testing.
"Simulated flights" counts Monte-Carlo trials of the vectorised model, not full rigid-body
simulations. Throughput shown in the UI is measured live.
