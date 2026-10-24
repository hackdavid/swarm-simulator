<div align="center">

# Swarm Proving Ground

**Agentic failure discovery for drones and ground robots, before the first field test.**

A swarm of parallel Claude Agent SDK agents hunts a vehicle's failure modes in a full year of real, location-specific weather.
Their findings seed a zoomable proving ground of more than one million Monte-Carlo-tested environments, each one a different world.

`Python 3.12` · `FastAPI` · `Claude Agent SDK` · `MCP tools` · `NumPy` · `WebSocket streaming` · `Canvas 2D` · `Open-Meteo ERA5` · `Mubit.ai`

[Proving ground: 1,048,576 environment cells](docs/img/plane.jpg)

</div>

---
<div align="center">
  <a href="https://www.youtube.com/watch?v=YUvj0v6jV14">
    <img src="https://img.youtube.com/vi/YUvj0v6jV14/maxresdefault.jpg" alt="Watch Demo Video" width="100%" style="max-width:700px; border-radius: 8px 8px 0 0;">
  </a>
  <br/>
  <a href="https://www.youtube.com/watch?v=YUvj0v6jV14">
    <img src="https://img.shields.io/badge/▶%20Watch%20Full%20Video-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="Watch on YouTube">
  </a>
</div>

## Why it exists

Drones and robots are moving into delivery, agriculture, inspection and disaster response. Most of their failures happen at the edges of the operating envelope: the gust front on the return leg, the cold-soaked battery at 06:00 in January, the IP43 enclosure in a 9 mm/h downpour, the loaded robot on a wet 18° slope.

Field testing finds those edges slowly, expensively, and only in the weather you happen to get. Swarm Proving Ground inverts that workflow:

1. **Describe the machine.** Real engineering parameters (thrust, battery chemistry, IP rating, payload, sensors, temperature limits).
2. **Load the real environment.** 8,760 hours of measured weather for the exact operating site.
3. **Let an agent swarm attack it.** 20–30 specialist agents search the weather record and the physics model in parallel for minimal, realistic failure scenarios.
4. **Verify everything.** Every claimed failure is independently re-run with 400 fresh trials. Unreproducible claims are rejected.
5. **Stress the whole envelope.** A grid of up to 2 million environment cells is Monte-Carlo-tested and streamed live to the browser.
6. **Close the loop.** Engineering fixes are proposed per failure mode, re-tested, and quantified as pass-rate deltas.

> Results are **simulation findings** from reduced-order physics fed with measured weather. They rank risks and compare designs; they do not replace flight or field certification. See [Honesty notes](#honesty-notes).

## Highlights

| | |
|---|---|
| **Two platforms** | Multirotor drones (4/6/8 rotors) and wheeled/tracked/legged ground robots, each with a full engineering parameter schema. |
| **Real weather** | Hourly wind, gusts, rain, snow, temperature, humidity, pressure and cloud for the last 12 months (Open-Meteo historical archive, ERA5), with altitude wind shear. |
| **Parallel agent swarm** | Up to 30 concurrent `claude_agent_sdk` agents, each a domain specialist (gust-front hunter, cold-soak battery chemist, icing analyst, tip-over analyst...), using in-process MCP tools. |
| **Grounded, verified findings** | Agents must cite real weather hours and pass a 400-trial re-verification gate. No hallucinated crashes. |
| **Million-cell proving ground** | 1024² = 1,048,576 cells by default, 16 trials each (16.8M simulated missions), streamed as binary tiles and rendered on a zoomable canvas from ×0.2 to ×400. |
| **Single-cell forensics** | Click any cell: 64 fresh trials, replay of each trial, the exact environment, physics margins and failure breakdown. |
| **Design loop** | Per-failure-mode engineering fixes with before → after pass rates; one click re-runs the whole pipeline on the improved design. |
| **Switchable LLM route** | Direct Anthropic-compatible API or the [Mubit.ai](https://docs.mubit.ai) proxy, which records agent calls, groups them into tasks and trains task-specific adapters. |
| **Runs without keys** | Deterministic search agents use the identical tool protocol when no LLM key is configured. |

<table>
<tr>
<td><img src="docs/img/swarm.jpg" alt="Agent swarm"/><br/><sub><b>Agent swarm.</b> 24 live agents, tool-call particles, climate year, verified-case feed.</sub></td>
<td><img src="docs/img/cell.jpg" alt="Cell inspector"/><br/><sub><b>Cell inspector.</b> Per-cell scene, 64-trial replay, margins and failure modes.</sub></td>
</tr>
<tr>
<td><img src="docs/img/report.jpg" alt="Fix report"/><br/><sub><b>Engineering report.</b> Failure modes, proposed fixes and measured pass-rate gains.</sub></td>
<td><img src="docs/img/robot_cell.jpg" alt="Ground robot"/><br/><sub><b>Ground robots.</b> Slope, mud, traction, tip-over and obstacle strikes.</sub></td>
</tr>
</table>

## Architecture

```mermaid
flowchart LR
    subgraph Browser["Browser (vanilla JS, Canvas 2D)"]
        UI1[Platform + parameter studio]
        UI2[Swarm control room]
        UI3[Zoomable proving ground]
        UI4[Cell inspector + fix report]
    end

    subgraph API["FastAPI service (server/app.py)"]
        RUN[Run orchestrator]
        WS[(WebSocket event bus<br/>JSON events + binary tiles)]
        CELL[Cell inspector endpoint]
    end

    subgraph Core["Simulation core"]
        WX[Weather ingest<br/>server/weather.py]
        SW[Agent swarm<br/>server/swarm.py + roster.py]
        PHY[Vectorised physics<br/>server/physics.py]
        GRID[Environment synthesis<br/>server/grid.py]
        FIX[Fix engine<br/>server/fixes.py]
    end

    subgraph External["External services"]
        OM[(Open-Meteo<br/>ERA5 archive)]
        MUBIT[Mubit.ai proxy<br/>records · tasks · adapters]
        CLAUDE[Claude models<br/>Anthropic API]
    end

    UI1 -- POST /api/runs --> RUN
    RUN --> WX --> OM
    RUN --> SW
    SW -- "MCP tools: find_weather_hours,<br/>run_physics_test, submit_failure_case" --> PHY
    SW -- "SWARM_LLM_PROVIDER=mubit" --> MUBIT --> CLAUDE
    SW -- "direct" --> CLAUDE
    RUN --> GRID --> PHY
    RUN --> FIX --> PHY
    RUN --> WS --> UI2 & UI3
    UI4 -- GET /api/runs/{id}/cell --> CELL --> PHY
```

Full component breakdown, event protocol and tile format: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Workflow

```mermaid
sequenceDiagram
    autonumber
    participant U as Engineer (browser)
    participant R as Run orchestrator
    participant W as Weather ingest
    participant S as Agent swarm (×24)
    participant P as Physics engine
    participant G as Proving ground

    U->>R: POST /api/runs (platform, params, site, swarm size, LLM route)
    R->>W: fetch 8,760 h for lat/lon (cached)
    W-->>U: climate summary (WS "weather")
    R->>S: launch N specialist agents in parallel
    loop each agent, ≤ 6 tool calls
        S->>W: find_weather_hours(filters)
        S->>P: run_physics_test(scenario) · 200 trials
        S->>P: submit_failure_case(scenario)
        P-->>S: re-verified with 400 trials (rejected if pass > 80%)
        S-->>U: live thoughts, tool calls, verified cases
    end
    R->>G: synthesise S×S environments + agent stress districts
    G->>P: K Monte-Carlo trials per cell (64×64 tiles)
    G-->>U: binary tiles + progress (live fill)
    R->>P: re-test each fix on a 65,536-cell sample
    R-->>U: report: baseline vs per-fix vs all-fixes pass rate
    U->>R: "Apply all fixes & re-run" (new run, improved design)
```

Stage-by-stage detail, agent loop, verification gate and the developer workflow: **[docs/WORKFLOW.md](docs/WORKFLOW.md)**.

## Quick start

```bash
uv sync
uv run uvicorn server.app:app --port 8811
# open http://localhost:8811
```

### Configuration

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` (+ `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL` / `SWARM_MODEL`) | Direct route: Anthropic API or a compatible proxy. |
| `PW_LLM_API_KEY`, `PW_LLM_BASE_URL`, `PW_LLM_MODEL` | Fallback proxy configuration for the direct route. |
| `SWARM_LLM_PROVIDER` | `direct` (default) or `mubit`. Can also be chosen per run in the UI or via `provider` in `POST /api/runs`. |
| `MUBIT_API_KEY` (+ `SWARM_MUBIT_MODEL`, default `claude-sonnet-5-5`) | Mubit.ai route (`https://api.mubit.ai/anthropic`). |
| `SWARM_BACKEND=mock` | Force deterministic agents: no LLM calls, free, same tool protocol. |
| `SWARM_CONCURRENCY` (30), `SWARM_AGENT_TIMEOUT` (300 s), `GRID_REVEAL_SECONDS` (16) | Swarm concurrency, per-agent timeout, pacing of the live grid fill. |

### Benchmark an LLM route

```bash
SWARM_LLM_PROVIDER=mubit uv run python scripts/bench_swarm.py --agents 8 --platform drone
SWARM_LLM_PROVIDER=direct uv run python scripts/bench_swarm.py --agents 8 --platform drone
```

Runs the swarm only (no grid) and writes wall time, per-agent latency, time-to-first-tool, tool-call mix, verified cases, tokens, cost and fallbacks to `data/bench/`.

### API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/meta` | Platform schemas, site presets, active backend, available LLM routes. |
| `POST` | `/api/runs` | Start a run: `platform`, `params`, `location`, `agents`, `grid`, `trials`, `provider`. |
| `WS` | `/ws/runs/{id}` | Replayable event stream: JSON events plus binary 64×64 result tiles. |
| `GET` | `/api/runs/{id}/cell?x=&y=` | Re-simulate one cell with 64 fresh trials and return its forensics. |

## Mission routes (Canary Wharf demo)

Pick a demo route on the Parameters screen, or upload a QGroundControl `.plan`, GeoJSON, KML or GPX file. The run then adds a **Route corridor** stage between weather and the swarm:

1. **Corridor mapping** (`server/route.py`, `server/mapdata.py`): OSM features for every map tile the route touches, rasterised to 20 m cells (building heights, people proxy, water, green areas, roads, sensitive sites). Ground robots are routed on OSM footways with Dijkstra; drones fly straight legs. Terrain comes from the Copernicus GLO-30 surface model. Airspace comes from openAIP.
2. **Per-segment profile**: length, heading, obstacle clearance at cruise altitude, urban-canyon index, radio line-of-sight from the pad, population proxy and SORA 2.5 intrinsic GRC, airspace crossed, slope, surface and crossings.
3. **Route-aware swarm**: every agent gets the segment table, and its physics tests fly the route with `wind_dir_deg` and `hour_of_day`.
4. **Launch calendar plane** (`server/routesim.py`): x = day of the weather year, y = time of day. Each cell is a real departure flown along the corridor, with headwind/crosswind energy per leg, gusts amplified in urban canyons, lateral deviation versus corridor width, obstacle conflict, C2 link loss, plus pedestrian and office-occupancy profiles by hour.
5. **Failure heat on the map**: each failed trial is attributed to a route segment. The report adds expected people struck per million flights (proxy), max intrinsic GRC and the airspace crossed.

| Demo route | Platform | Length | Finding (mock-agent run) |
|---|---|---|---|
| Canary Wharf → Royal London Hospital (out & back) | drone | 7.8 km | 77.7% pass; inside London City CTR and EGR159 Isle of Dogs; 24% of the route is radio NLOS from the pad |
| Isle of Dogs inspection loop | drone | 4.8 km | ~32% pass; obstacle conflict next to the South Quay towers dominates |
| Canary Wharf stn → Crossharbour (out & back) | robot | 4.1 km on OSM footways | ~91% pass; 21 road crossings |
| Canary Wharf → Mudchute Park | robot | 1.5 km | park paths and grass at the end |

![Route corridor](docs/img/route_corridor.png)
![Robot corridor](docs/img/route_robot.png)
![Launch calendar](docs/img/route_calendar.png)

> Population is a **proxy** (OSM building floor area × occupancy). The DEM is a surface model, so it includes buildings. openAIP data needs licence confirmation for commercial use. Map data © OpenStreetMap contributors (ODbL). Results are engineering evidence, not an airspace authorisation or a certified SORA.

## Roadmap

Weather is the first environmental layer. The same agent → verify → grid → fix pipeline is designed to take more layers, each adding new dimensions to every cell and new tools for the swarm. **The items below are planned and not yet implemented.**

| Phase | Layer | What it adds |
|---|---|---|
| **Now** | Weather year | Wind, gusts, shear, rain, snow, icing, heat, cold, pressure, humidity. *(shipped)* |
| **Now** | LLM routing | Direct API or Mubit.ai proxy with adapter training on recurring agent tasks. *(shipped)* |
| **Now** | Mission routes (Phase 1) | Demo or uploaded QGroundControl `.plan` / GeoJSON / KML / GPX routes; OpenStreetMap buildings, trees, roads and water; Copernicus DEM; wind direction; per-leg headwind/crosswind energy and return reserve. *(shipped)* |
| **Now** | People, airspace & geofence (Phase 2) | Population proxy under the corridor with SORA 2.5 intrinsic-GRC lookup, openAIP airspace intersection, corridor/geofence drift, obstacle conflict, C2 link loss; robots get pedestrian encounters, road crossings and localisation loss. *(shipped)* |
| Next | Bring-your-own-test | Client YAML test cases with pass criteria, log-calibrated vehicle models (PX4 `.ulg`, ArduPilot `.bin`, ROS 2 MCAP). |
| Later | GNSS / RF degradation | Urban canyon multipath, GPS denial, link loss and lost-link behaviour. |
| Later | Component ageing | Battery cycle fade, motor wear, sensor drift over a fleet's service life. |
| Later | Fleet operations | Multi-vehicle missions, charging logistics, fleet-level availability. |
| Later | SITL / HIL bridge | Export agent-found scenarios to PX4 / ArduPilot SITL and Gazebo for high-fidelity confirmation. |
| Later | Evidence packs | Traceable failure-case reports for safety cases and regulatory submissions. |

Design notes for each layer: **[docs/ROADMAP.md](docs/ROADMAP.md)**.

## Repository layout

```
server/
  app.py        FastAPI app: run orchestration, WebSocket event bus, tile streaming, cell endpoint
  swarm.py      Claude Agent SDK swarm, MCP tools, LLM route switch, deterministic fallback agents
  roster.py     specialist agent roles per platform
  weather.py    Open-Meteo ingest, caching, climate summary, hour search
  physics.py    vectorised reduced-order drone and robot models
  grid.py       environment synthesis, categories, agent stress districts
  platforms.py  parameter schemas, presets, normalisation
  fixes.py      engineering fixes per failure mode
web/            single-page UI (index.html, css/, js/: config, swarm, plane, scenes, main)
scripts/        bench_swarm.py: LLM-route benchmark
docs/           architecture, workflow, roadmap, screenshots
```

## Honesty notes

- Results are **simulation findings** from reduced-order models seeded with measured weather. They are useful for ranking risks and comparing designs, not a substitute for flight or field testing.
- "Simulated flights" counts Monte-Carlo trials of the vectorised model, not full rigid-body simulations.
- Throughput and pass rates shown in the UI are measured live for each run.
- Roadmap items are plans, not current capabilities.
