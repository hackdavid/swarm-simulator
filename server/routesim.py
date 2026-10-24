"""Route-aware Monte Carlo: a calendar of real departure hours flown along a real mission corridor.

Plane layout in route mode: x = day of the weather year, y = hour of day. Every cell is a departure at that real
hour (blended to the minute) flown along the imported route, so the plane reads as a year-long launch calendar.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np

from .grid import _rank, fbm
from .physics import FC_FACTOR, MODES, TERRAIN_FRICTION, TERRAINS, TRIALS, scenario_env, summarise_modes

G = 9.81


def _phi(x):
    return 1.0 / (1.0 + np.exp(-1.702 * x))


def ped_profile(hour, weekend):
    h = np.asarray(hour, dtype=np.float32)
    peaks = 0.15 + 0.85 * np.exp(-((h - 8.6) / 1.1) ** 2) + 0.65 * np.exp(-((h - 12.8) / 1.2) ** 2) + 0.9 * np.exp(-((h - 17.7) / 1.3) ** 2)
    night = np.where((h < 6) | (h > 22.5), 0.25, 1.0)
    return (peaks * night * np.where(weekend, 0.6, 1.0)).astype(np.float32)


def occ_profile(hour, weekend):
    h = np.asarray(hour, dtype=np.float32)
    return np.where(weekend, 0.2, np.where((h >= 8) & (h <= 18.5), 1.0, 0.15)).astype(np.float32)


def solar_night(doy, hour_utc, lat, lon):
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    ha = np.radians(15 * (hour_utc + lon / 15 - 12))
    la = math.radians(lat)
    el = np.sin(la) * np.sin(decl) + np.cos(la) * np.cos(decl) * np.cos(ha)
    return (el < -0.05).astype(np.float32)


def seg_arrays(prof):
    sg = prof["segments"]
    a = lambda k: np.array([s[k] for s in sg], dtype=np.float32)
    return {"L": a("length_m"), "hdg": a("heading_deg"), "clear": a("clearance_m"), "canyon": a("canyon"), "nlos": a("nlos"),
            "outdoor": a("outdoor_per_km2"), "people": a("people_per_km2"), "slope": a("slope_deg"), "cross": a("crossings"),
            "surface": np.array([s["surface"] for s in sg])}


def calendar_env(platform, params, weather, prof, S, seed):
    rng = np.random.default_rng(seed)
    n = len(weather["wind"])
    days = n // 24
    x = np.arange(S)
    y = np.arange(S)
    day = (x * days // S).astype(int)
    hf = y * 24.0 / S
    h0 = np.floor(hf).astype(int)
    frac = (hf - h0)[:, None]
    i0 = np.clip(day[None, :] * 24 + h0[:, None], 0, n - 1)
    i1 = np.clip(i0 + 1, 0, n - 1)
    noise = lambda base=9: (_rank(fbm(rng, S, S, base=base, octaves=4)) - 0.5).astype(np.float32)

    def bl(k):
        a = np.asarray(weather[k], dtype=np.float32)
        return a[i0] * (1 - frac) + a[i1] * frac
    alt = max(prof["alt_m"], 10) if platform == "drone" else 2.0
    shear = (alt / 10) ** 0.14 if platform == "drone" else 1.0
    wind = np.maximum(bl("wind") * shear * (1 + 0.08 * noise()), 0)
    gust = np.maximum(bl("gust") * shear * (1 + 0.1 * noise()), wind * 1.1)
    rain = np.maximum(bl("precip") * (1 + 0.3 * noise()), 0)
    temp = bl("temp") + 0.6 * noise()
    snow = np.where(temp < 1.0, np.maximum(bl("snow"), 0) + np.where(temp < 0.5, rain * 0.7, 0), 0)
    rain = np.where(snow > 0, 0, rain)
    rh = np.clip(bl("rh") + 3 * noise(), 5, 100)
    pressure = bl("pressure")
    wd = np.radians(np.asarray(weather.get("wdir", np.full(n, 240.0)), dtype=np.float32))
    u = np.cos(wd)[i0] * (1 - frac) + np.cos(wd)[i1] * frac
    v = np.sin(wd)[i0] * (1 - frac) + np.sin(wd)[i1] * frac
    wdir = (np.degrees(np.arctan2(v, u)) + 360 + 8 * noise()) % 360
    vis = np.full((S, S), 25.0, np.float32)
    vis = np.where((rh > 96) & (wind < 4 * shear), 0.2 + 1.5 * (noise() + 0.5), vis)
    vis = np.minimum(vis, np.where(rain > 0.05, 12 / (1 + rain * 0.6), 99))
    vis = np.minimum(vis, np.where(snow > 0, 1.6 / (1 + snow * 2), 99))
    start = dt.date.fromisoformat(weather["start"])
    dates = [start + dt.timedelta(days=int(d)) for d in day]
    doy = np.array([d.timetuple().tm_yday for d in dates])[None, :].repeat(S, 0).astype(np.float32)
    weekend = np.array([d.weekday() >= 5 for d in dates])[None, :].repeat(S, 0)
    hour = np.repeat(hf[:, None], S, 1).astype(np.float32)
    night = solar_night(doy, hour, prof["path"][0][0], prof["path"][0][1])
    pay0 = float(params.get("payload_kg", 0))
    payload = (pay0 * (0.6 + 0.8 * (noise(4) + 0.5))).astype(np.float32)
    env = {"wind": wind, "gust": gust, "rain": rain, "snow": snow, "temp": temp, "rh": rh, "pressure": pressure, "vis": vis,
           "payload": payload, "wdir": wdir, "hour": hour, "doy": doy, "night": night, "weekend": weekend.astype(np.float32),
           "ped": ped_profile(hour, weekend), "occ": occ_profile(hour, weekend)}
    if platform == "robot":
        sa = seg_arrays(prof)
        k = int(np.argmax(sa["slope"]))
        slope = np.float32(sa["slope"][k]) * (0.85 + 0.3 * (noise(6) + 0.5))
        terr = int(np.max(sa["surface"])) if len(sa["surface"]) else 0
        a = np.asarray(weather["precip"], dtype=np.float32)
        wet24 = np.convolve(a, np.ones(24), "full")[:n]
        wet = wet24[i0]
        fr = TERRAIN_FRICTION[terr] * np.where((rain > 0.1) | (wet > 2), 0.78, 1.0)
        icy = (temp < 0) & ((snow > 0) | (wet > 1))
        fr = np.where(icy, 0.15, fr)
        sn = np.asarray(weather["snow"], dtype=np.float32)
        sdepth = np.convolve(sn, np.ones(48), "full")[:n][i0] * np.where(temp < 1, 1, 0.3)
        mud = np.where(terr in (1, 4), 18 * np.clip((wet - 4) / 20, 0, 1), 0)
        env.update({"slope": slope.astype(np.float32), "terrain": np.full((S, S), terr, np.float32), "friction": fr.astype(np.float32),
                    "mud": mud.astype(np.float32), "snow_depth": sdepth.astype(np.float32),
                    "obstacle": np.full((S, S), 8.0 if sa["cross"].sum() else 3.0, np.float32)})
    return {k: np.asarray(v, dtype=np.float32) for k, v in env.items()}


def _rows(platform, p, env, prof):
    """Per-row (per departure) route terms, independent of the Monte Carlo trials."""
    sa = seg_arrays(prof)
    wind, gust = np.asarray(env["wind"])[:, None], np.asarray(env["gust"])[:, None]
    night = np.asarray(env.get("night", np.zeros(len(env["wind"]))))[:, None]
    vis = np.asarray(env["vis"])[:, None]
    rain = np.asarray(env["rain"])[:, None]
    ped = np.asarray(env.get("ped", np.ones(len(env["wind"]))))[:, None]
    occ = np.asarray(env.get("occ", np.ones(len(env["wind"]))))[:, None]
    L = sa["L"][None, :]
    out = {}
    if platform == "drone":
        va = 0.65 * p["max_airspeed_ms"]
        to = np.radians(np.asarray(env.get("wdir", np.full(len(env["wind"]), 240)))[:, None] + 180 - sa["hdg"][None, :])
        along, cross = wind * np.cos(to), wind * np.sin(to)
        gs = np.clip(np.sqrt(np.maximum(va ** 2 - cross ** 2, 0.25)) + along, 1.0, None)
        out["mission_min"] = (L / gs).sum(1) / 60 + 2.5
        out["headwind_max"] = (-along).max(1)
        tol = 1.35 * p["wind_resistance_ms"] * FC_FACTOR[p["flight_controller"]]
        geff = gust * (1 + 0.25 * sa["canyon"][None, :])
        out["gust_eff"] = geff.max(1)
        sg = (0.3 if p["rtk_gps"] else 1.8) * (1 + 3 * sa["canyon"][None, :])
        drift = 5.0 * np.clip(geff / tol, 0, 2.5) ** 2
        sig = np.sqrt(sg ** 2 + drift ** 2)
        avoid = p["obstacle_avoidance"] & (night < 0.5) & (vis > 0.4)
        ce = sa["clear"][None, :] + np.where(avoid, 8.0, 0.0)
        p_seg = np.where(sa["clear"][None, :] < 149, 2 * (1 - _phi(ce / sig)), 0.0)
        out["p_obstacle"] = 1 - np.prod(1 - np.clip(p_seg, 0, 1), axis=1)
        out["obstacle_seg"] = np.argmax(p_seg, axis=1)
        corr = float(p.get("corridor_m", 30))
        n_ind = max(1.0, float(L.sum()) / 200)
        out["p_geofence"] = np.clip(n_ind * 2 * (1 - _phi(corr / sig.max(1))), 0, 1)
        out["deviation_m"] = sig.max(1)
        nl = float((sa["nlos"] * sa["L"]).sum() / sa["L"].sum())
        out["p_link"] = np.clip(nl * (0.03 if p.get("lte_backup_link") else 0.45) * (1 + rain[:, 0] / 8), 0, 1) * \
            (0.08 + 0.5 * (gust[:, 0] > 0.8 * tol))
        dim = 0.5 * (p["frame_mass_kg"] + p.get("payload_kg", 0)) ** (1 / 3)
        ac = 4 * (dim + 0.6) ** 2
        w = L / L.sum()
        out["exposure"] = ac * (w * (sa["outdoor"][None, :] * ped + 0.02 * sa["people"][None, :] * occ)).sum(1) / 1e6
    else:
        v = min(p["max_speed_ms"], 1.8)
        fr = np.asarray(env["friction"])[:, None]
        out["mission_km"] = np.full(len(env["wind"]), float(L.sum()) / 1000)
        rng_det = (25.0 if p["lidar"] else 12.0) * np.clip(vis / 0.3, 0.2, 1) * np.where((night > 0.5) & ~(p["lidar"] or p["thermal_camera"]), 0.5, 1) \
            * np.where(rain > 4, 0.7, 1)
        stop = v * 0.4 + v ** 2 / (2 * np.maximum(fr, 0.08) * G)
        out["stop_m"], out["detect_m"] = stop[:, 0], rng_det[:, 0]
        enc = (L * sa["outdoor"][None, :] / 1e6 * 20).sum(1) * ped[:, 0]
        p_enc = np.where(stop[:, 0] < 0.5 * rng_det[:, 0], 0.0004, 0.02)
        out["encounters"] = enc
        out["p_ped"] = 1 - (1 - p_enc) ** enc
        C = float(sa["cross"].sum())
        pc = 0.0008 + 0.012 * (vis[:, 0] < 1) + 0.02 * (fr[:, 0] < 0.3) + 0.004 * night[:, 0] + 0.0015 * ped[:, 0]
        out["p_cross"] = 1 - (1 - pc) ** C
        cmax = float(sa["canyon"].max()) if len(sa["canyon"]) else 0
        snow = np.asarray(env["snow"])
        out["p_loc"] = np.clip(cmax * (0.03 if p["lidar"] else 0.2) * (1 + (rain[:, 0] > 2) + (snow > 0)), 0, 1)
        out["exposure"] = out["p_ped"]
    return out


def route_trials(platform, p, env, K, rng, prof, detail=False):
    rows = _rows(platform, p, env, prof)
    e2 = dict(env)
    if platform == "drone":
        e2["mission_min"] = rows["mission_min"]
        e2["gust"] = rows["gust_eff"]
    else:
        e2["mission_km"] = rows["mission_km"]
    res = TRIALS[platform](p, e2, K, rng, detail=detail)
    mode, margins = (res if detail else (res, None))
    n = (len(env["wind"]), K)
    u = rng.random(n)
    if platform == "drone":
        extra = [(11, rows["p_obstacle"]), (12, rows["p_geofence"]), (13, rows["p_link"])]
    else:
        extra = [(11, rows["p_ped"]), (12, rows["p_cross"]), (13, rows["p_loc"])]
    acc = np.zeros(len(env["wind"]))
    for code, pr in extra:
        hit = (u >= acc[:, None]) & (u < (acc + pr)[:, None])
        mode = np.where((mode == 0) & hit, code, mode)
        acc = acc + pr
    if not detail:
        return mode
    if platform == "drone":
        margins.update({"route_minutes": float(rows["mission_min"][0]), "max_headwind_ms": float(rows["headwind_max"][0]),
                        "gust_in_canyon_ms": float(rows["gust_eff"][0]), "lateral_dev_sigma_m": float(rows["deviation_m"][0]),
                        "p_obstacle_pct": float(rows["p_obstacle"][0] * 100), "p_geofence_pct": float(rows["p_geofence"][0] * 100),
                        "p_link_loss_pct": float(rows["p_link"][0] * 100), "people_at_risk_if_fail": float(rows["exposure"][0])})
    else:
        margins.update({"route_km": float(rows["mission_km"][0]), "stop_distance_m": float(rows["stop_m"][0]),
                        "detection_range_m": float(rows["detect_m"][0]), "pedestrian_encounters": float(rows["encounters"][0]),
                        "p_pedestrian_conflict_pct": float(rows["p_ped"][0] * 100), "p_crossing_pct": float(rows["p_cross"][0] * 100),
                        "p_localisation_pct": float(rows["p_loc"][0] * 100)})
    return mode, margins


def failure_segments(platform, p, env, mode, prof, rng):
    """Attribute each failed trial to a route segment (for the corridor heat map)."""
    sa = seg_arrays(prof)
    nseg = len(sa["L"])
    w = sa["L"] / sa["L"].sum()
    counts = np.zeros((14, nseg), np.int64)
    fails = mode > 0
    if not fails.any():
        return counts
    rows = _rows(platform, p, env, prof) if platform == "drone" else None
    r_idx, _ = np.nonzero(fails)
    m = mode[fails]
    seg = rng.choice(nseg, size=len(m), p=w)
    if platform == "drone":
        seg = np.where(m == 11, rows["obstacle_seg"][r_idx], seg)
        nl = sa["nlos"] * sa["L"]
        if nl.sum() > 0:
            seg = np.where(m == 13, rng.choice(nseg, size=len(m), p=nl / nl.sum()), seg)
        seg = np.where(m == 4, np.clip((nseg * (0.75 + 0.25 * rng.random(len(m)))).astype(int), 0, nseg - 1), seg)
    else:
        if sa["cross"].sum() > 0:
            seg = np.where(m == 12, rng.choice(nseg, size=len(m), p=sa["cross"] / sa["cross"].sum()), seg)
        if sa["slope"].max() > 0:
            ss = sa["slope"] ** 2 + 1e-3
            seg = np.where(np.isin(m, [1, 2, 3]), rng.choice(nseg, size=len(m), p=ss / ss.sum()), seg)
    np.add.at(counts, (m, seg), 1)
    return counts


def scenario_on_route(platform, params, s, prof):
    env = scenario_env(platform, params, s)
    hour = float(s.get("hour_of_day", 12)) if isinstance(s.get("hour_of_day"), (int, float)) else 12.0
    wk = np.array([False])
    env.update({"wdir": np.array([float(s.get("wind_dir_deg", 240))], np.float32), "hour": np.array([hour], np.float32),
                "night": np.array([1.0 if (hour < 6.5 or hour > 19.5) else 0.0], np.float32),
                "ped": ped_profile([hour], wk), "occ": occ_profile([hour], wk)})
    if platform == "robot" and not isinstance(s.get("slope_deg"), (int, float)):
        env["slope"] = np.array([max(sg["slope_deg"] for sg in prof["segments"])], np.float32)
    return env


def evaluate_route_scenario(platform, params, scenario, prof, trials=200, seed=7):
    env = scenario_on_route(platform, params, scenario, prof)
    rng = np.random.default_rng(seed)
    mode, margins = route_trials(platform, params, env, trials, rng, prof, detail=True)
    passes, dom, counts = summarise_modes(mode, len(MODES[platform]))
    names = {m["id"]: m["name"] for m in MODES[platform]}
    hist = {names[i + 1]: int(c) for i, c in enumerate(counts[0]) if c}
    return {"pass_rate_pct": round(100 * float(passes[0]) / trials, 1), "trials": trials,
            "dominant_failure": names.get(int(dom[0])), "failure_histogram": hist,
            "margins": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in margins.items()},
            "scenario": {k: (round(float(v[0]), 2) if k != "terrain" else TERRAINS[int(v[0])]) for k, v in env.items()
                         if k in ("wind", "gust", "rain", "snow", "temp", "vis", "payload", "wdir", "hour", "slope", "friction")}}
