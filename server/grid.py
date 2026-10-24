"""The proving-ground plane: a million environment cells built from a real year of weather."""
from __future__ import annotations

import numpy as np

from .physics import TERRAIN_FRICTION, TERRAINS, TRIALS, summarise_modes

CATEGORIES = [
    {"id": 0, "key": "sunny", "name": "Sunny / clear", "color": "#ffcb47"},
    {"id": 1, "key": "overcast", "name": "Overcast / mild", "color": "#7d8ba6"},
    {"id": 2, "key": "windy", "name": "High wind", "color": "#3ddbd9"},
    {"id": 3, "key": "rain", "name": "Rain", "color": "#3a6df0"},
    {"id": 4, "key": "storm", "name": "Storm (rain + gusts)", "color": "#8f3df5"},
    {"id": 5, "key": "snow", "name": "Snow", "color": "#e9f5ff"},
    {"id": 6, "key": "fog", "name": "Fog", "color": "#b8c0cc"},
    {"id": 7, "key": "heat", "name": "Heatwave", "color": "#ff7a33"},
    {"id": 8, "key": "freezing", "name": "Freezing / icy", "color": "#8be9ff"},
]

# (name, source key, scale, offset) -> byte = clip((value + offset) * scale)
PLANES = {
    "drone": [("wind", 4, 0), ("gust", 4, 0), ("rain", 10, 0), ("temp", 2, 60), ("rh", 2.5, 0),
              ("vis", 10, 0), ("snow", 50, 0), ("payload", None, 0), ("pressure", 1, -880)],
    "robot": [("wind", 4, 0), ("gust", 4, 0), ("rain", 10, 0), ("temp", 2, 60), ("rh", 2.5, 0),
              ("vis", 10, 0), ("snow", 50, 0), ("payload", None, 0), ("slope", 6, 0), ("terrain", 1, 0),
              ("friction", 250, 0), ("mud", 8, 0), ("snow_depth", 8, 0), ("obstacle", 6, 0)],
}


def _bilinear(small: np.ndarray, H: int, W: int) -> np.ndarray:
    r0, r1 = small.shape
    ys = np.linspace(0, r0 - 1, H)
    xs = np.linspace(0, r1 - 1, W)
    y0 = np.clip(np.floor(ys).astype(int), 0, r0 - 2)
    x0 = np.clip(np.floor(xs).astype(int), 0, r1 - 2)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    a = small[y0][:, x0]
    b = small[y0][:, x0 + 1]
    c = small[y0 + 1][:, x0]
    d = small[y0 + 1][:, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def fbm(rng, H, W, base=6, octaves=6, gain=0.55):
    out = np.zeros((H, W), dtype=np.float32)
    amp, res = 1.0, base
    for _ in range(octaves):
        out += amp * _bilinear(rng.standard_normal((res + 1, res + 1)).astype(np.float32), H, W)
        amp *= gain
        res *= 2
    return out


def _rank(f: np.ndarray) -> np.ndarray:
    flat = f.ravel()
    r = np.empty(flat.size, dtype=np.float32)
    r[np.argsort(flat, kind="stable")] = np.linspace(0, 1, flat.size, dtype=np.float32)
    return r.reshape(f.shape)


def _qmap(u, data, tail=1.15):
    """Map uniform u through the empirical quantiles of data, extending the top 0.5% tail."""
    s = np.sort(np.asarray(data, dtype=np.float64))
    q = np.interp(u, np.linspace(0, 1, s.size), s)
    hi = u > 0.995
    if hi.any():
        q = np.where(hi, s[-1] + (s[-1] * tail - s[-1]) * (u - 0.995) / 0.005, q)
    return q.astype(np.float32)


def build_environments(platform: str, params: dict, weather: dict, H: int, W: int, seed: int, cases: list[dict]):
    rng = np.random.default_rng(seed)
    storm = fbm(rng, H, W, base=5)
    n1, n2, n3, n4, n5 = (fbm(rng, H, W, base=8) for _ in range(5))
    seasonal = fbm(rng, H, W, base=3, octaves=5)
    shear = (max(params.get("cruise_altitude_m", 10), 10) / 10) ** 0.14 if platform == "drone" else 1.0
    u_wind = _rank(0.75 * storm + 0.35 * n1)
    wind = _qmap(u_wind, weather["wind"]) * shear
    gust = np.maximum(_qmap(_rank(0.75 * storm + 0.3 * n1 + 0.15 * n2), weather["gust"]) * shear, wind * 1.15)
    u_wet = _rank(0.65 * storm + 0.45 * n2)
    p = weather["precip"]
    rain_frac = max(float((p > 0.1).mean()), 0.03)
    pos = p[p > 0.1] if (p > 0.1).any() else np.array([0.2, 1.0, 3.0])
    rain = np.where(u_wet > 1 - rain_frac, _qmap(np.clip((u_wet - (1 - rain_frac)) / rain_frac, 0, 1), pos, 1.6), 0).astype(np.float32)
    temp = _qmap(_rank(0.8 * seasonal + 0.25 * n3), weather["temp"], 1.08)
    rh = _qmap(_rank(0.5 * (0.65 * storm + 0.45 * n2) - 0.35 * seasonal + 0.25 * n4), weather["rh"], 1.0)
    rh = np.where(rain > 0, np.maximum(rh, 90), rh).clip(5, 100)
    snow = np.where((temp < 0.8) & (rain > 0), rain * 0.7, 0).astype(np.float32)
    rain = np.where(snow > 0, 0, rain).astype(np.float32)
    pressure = _qmap(_rank(-storm + 0.3 * n5), weather["pressure"])
    vis = np.full((H, W), 25.0, dtype=np.float32)
    fog = (rh > 95) & (wind < 4.5 * shear)
    vis = np.where(fog, 0.15 + 1.2 * _rank(n5), vis)
    vis = np.minimum(vis, np.where(rain > 0, 12 / (1 + rain * 0.6), 99))
    vis = np.minimum(vis, np.where(snow > 0, 1.6 / (1 + snow * 2), 99)).astype(np.float32)
    pay0 = float(params.get("payload_kg", 0))
    payload = (pay0 * (0.35 + 1.25 * _rank(fbm(rng, H, W, base=4, octaves=4)) ** 1.3)).astype(np.float32)
    env = {"wind": wind, "gust": gust, "rain": rain, "snow": snow, "temp": temp, "rh": rh.astype(np.float32),
           "pressure": pressure, "vis": vis, "payload": payload}
    if platform == "robot":
        slope = (32 * _rank(fbm(rng, H, W, base=7)) ** 2.3).astype(np.float32)
        terrain = np.clip((_rank(fbm(rng, H, W, base=10, octaves=4)) * 5).astype(np.int32), 0, 4)
        wet_hist = _rank(0.6 * storm + 0.5 * n2)
        fr = TERRAIN_FRICTION[terrain] * np.where((rain > 0.1) | (wet_hist > 0.8), 0.78, 1.0)
        icy = (temp < 0) & ((snow > 0) | (wet_hist > 0.75))
        fr = np.where(icy, 0.12 + 0.1 * _rank(n4), fr)
        mud_ok = np.isin(terrain, [1, 4])
        mud = np.where(mud_ok, 22 * np.clip(wet_hist - 0.55, 0, 1) ** 1.2 * (1 + (terrain == 4)), 0)
        sdepth = np.where(temp < 1, 35 * np.clip(_rank(0.5 * storm - 0.6 * seasonal) - 0.8, 0, 1) * 5, 0)
        obstacle = (19 * _rank(fbm(rng, H, W, base=16, octaves=4)) ** 5).astype(np.float32)
        env.update({"slope": slope, "terrain": terrain.astype(np.float32), "friction": fr.astype(np.float32),
                    "mud": mud.astype(np.float32), "snow_depth": sdepth.astype(np.float32), "obstacle": obstacle})
    hotspot = np.zeros((H, W), dtype=np.uint8)
    regions = place_hotspots(env, hotspot, cases, H, W, rng)
    env = {k: v.astype(np.float32) for k, v in env.items()}
    return env, hotspot, regions


CASE_KEYS = {"wind_ms": "wind", "gust_ms": "gust", "rain_mmh": "rain", "snow_cmh": "snow", "temp_c": "temp",
             "humidity_pct": "rh", "pressure_hpa": "pressure", "visibility_km": "vis", "payload_kg": "payload",
             "slope_deg": "slope", "friction": "friction", "mud_depth_cm": "mud", "snow_depth_cm": "snow_depth",
             "obstacle_cm": "obstacle"}


def place_hotspots(env, hotspot, cases, H, W, rng):
    """Paint each agent-found failure case into the plane as a 'stress district'."""
    regions = []
    yy, xx = np.mgrid[0:H, 0:W]
    golden = 0.61803398875
    for i, case in enumerate(cases[:250]):
        sc = case.get("scenario", {})
        r = float(rng.uniform(0.018, 0.04) * min(H, W))
        cx = W * (0.08 + 0.84 * ((i * golden + 0.13) % 1))
        cy = H * (0.08 + 0.84 * ((i * golden * golden + 0.37) % 1))
        x0, x1 = int(max(cx - 3 * r, 0)), int(min(cx + 3 * r, W))
        y0, y1 = int(max(cy - 3 * r, 0)), int(min(cy + 3 * r, H))
        d2 = (xx[y0:y1, x0:x1] - cx) ** 2 + (yy[y0:y1, x0:x1] - cy) ** 2
        w = np.exp(-d2 / (2 * r * r)).astype(np.float32)
        jitter = 1 + 0.12 * rng.standard_normal(w.shape).astype(np.float32)
        for ck, ek in CASE_KEYS.items():
            v = sc.get(ck)
            if isinstance(v, (int, float)) and ek in env:
                blk = env[ek][y0:y1, x0:x1]
                tgt = float(v) * (jitter if ek != "temp" else 1) + (0 if ek != "temp" else 1.5 * (jitter - 1) * 8)
                env[ek][y0:y1, x0:x1] = blk * (1 - w) + tgt * w
        if "terrain" in env and isinstance(sc.get("terrain"), str) and sc["terrain"] in TERRAINS:
            env["terrain"][y0:y1, x0:x1] = np.where(w > 0.35, TERRAINS.index(sc["terrain"]), env["terrain"][y0:y1, x0:x1])
        if "gust" in env:
            env["gust"][y0:y1, x0:x1] = np.maximum(env["gust"][y0:y1, x0:x1], env["wind"][y0:y1, x0:x1])
        hotspot[y0:y1, x0:x1] = np.where(w > 0.3, np.uint8((i % 254) + 1), hotspot[y0:y1, x0:x1])
        regions.append({"id": (i % 254) + 1, "cx": int(cx), "cy": int(cy), "r": round(r, 1), "title": case.get("title", ""),
                        "agent": case.get("agent", ""), "agent_id": case.get("agent_id", 0)})
    return regions


def categorise(env: dict) -> np.ndarray:
    wind, gust, rain, snow, temp, vis = env["wind"], env["gust"], env["rain"], env["snow"], env["temp"], env["vis"]
    cat = np.ones(wind.shape, dtype=np.uint8)
    cat = np.where((rain == 0) & (env["rh"] < 72) & (wind < 7) & (temp > 4) & (temp < 30), 0, cat)
    cat = np.where(temp <= 0, 8, cat)
    cat = np.where(temp >= 30, 7, cat)
    cat = np.where((gust >= 14) | (wind >= 9), 2, cat)
    cat = np.where(rain >= 0.3, 3, cat)
    cat = np.where(vis < 1.0, 6, cat)
    cat = np.where(snow > 0.02, 5, cat)
    cat = np.where((rain >= 1.5) & (gust >= 13), 4, cat)
    return cat.astype(np.uint8)


def quantise(platform: str, env: dict, pay_max: float) -> list[tuple[str, np.ndarray, float, float]]:
    out = []
    for name, scale, off in PLANES[platform]:
        if scale is None:
            scale = 255 / max(pay_max, 1e-3)
        out.append((name, np.clip((env[name] + off) * scale, 0, 255).astype(np.uint8), scale, off))
    return out


def evaluate_tile(platform, params, env_flat_slice: dict, K: int, rng):
    mode = TRIALS[platform](params, env_flat_slice, K, rng)
    passes, dom, counts = summarise_modes(mode)
    return passes, dom, counts


def tile_order(H, W, T):
    tiles = [(ty, tx) for ty in range(0, H, T) for tx in range(0, W, T)]
    cy, cx = H / 2, W / 2
    tiles.sort(key=lambda t: (t[0] + T / 2 - cy) ** 2 + (t[1] + T / 2 - cx) ** 2)
    return tiles
