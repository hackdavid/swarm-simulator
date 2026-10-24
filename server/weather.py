"""One year of real hourly weather from the Open-Meteo archive (no key needed)."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import httpx
import numpy as np

CACHE = Path(__file__).resolve().parent.parent / "data" / "weather_cache"

PRESETS = [
    {"id": "london", "name": "London, UK", "lat": 51.5072, "lon": -0.1276},
    {"id": "edinburgh", "name": "Edinburgh, UK", "lat": 55.9533, "lon": -3.1883},
    {"id": "reykjavik", "name": "Reykjavík, Iceland", "lat": 64.1466, "lon": -21.9426},
    {"id": "oslo", "name": "Oslo, Norway", "lat": 59.9139, "lon": 10.7522},
    {"id": "denver", "name": "Denver, USA", "lat": 39.7392, "lon": -104.9903},
    {"id": "dubai", "name": "Dubai, UAE", "lat": 25.2048, "lon": 55.2708},
    {"id": "mumbai", "name": "Mumbai, India", "lat": 19.0760, "lon": 72.8777},
    {"id": "singapore", "name": "Singapore", "lat": 1.3521, "lon": 103.8198},
    {"id": "sydney", "name": "Sydney, Australia", "lat": -33.8688, "lon": 151.2093},
]

HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation", "rain", "snowfall",
          "surface_pressure", "wind_speed_10m", "wind_gusts_10m", "cloud_cover", "wind_direction_10m"]
KEYMAP = {"temperature_2m": "temp", "relative_humidity_2m": "rh", "precipitation": "precip", "rain": "rain",
          "snowfall": "snow", "surface_pressure": "pressure", "wind_speed_10m": "wind",
          "wind_gusts_10m": "gust", "cloud_cover": "cloud", "wind_direction_10m": "wdir"}


def _window():
    end = dt.date.today() - dt.timedelta(days=6)
    start = end - dt.timedelta(days=364)
    return start, end


async def fetch_year(lat: float, lon: float) -> dict:
    start, end = _window()
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{lat:.3f}_{lon:.3f}_{start}_v2.json"
    if f.exists():
        raw = json.loads(f.read_text())
    else:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get("https://archive-api.open-meteo.com/v1/archive", params={
                    "latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
                    "hourly": ",".join(HOURLY), "wind_speed_unit": "ms", "timezone": "UTC"})
                r.raise_for_status()
                raw = r.json()
            f.write_text(json.dumps(raw))
        except Exception as e:  # offline fallback keeps the demo alive
            return _synthetic(lat, lon, start, str(e))
    h = raw["hourly"]
    data = {"time": h["time"], "source": "Open-Meteo historical archive (ERA5 reanalysis)",
            "start": str(start), "end": str(end), "lat": lat, "lon": lon}
    for k, v in KEYMAP.items():
        arr = np.array([x if x is not None else np.nan for x in h[k]], dtype=np.float64)
        if np.isnan(arr).all():
            arr = np.zeros_like(arr)
        arr = np.where(np.isnan(arr), np.nanmedian(arr), arr)
        data[v] = arr
    data["gust"] = np.maximum(data["gust"], data["wind"])
    return data


def _synthetic(lat, lon, start, err):
    n = 365 * 24
    t = np.arange(n)
    rng = np.random.default_rng(int(abs(lat * 1000 + lon)))
    season = np.cos(2 * math.pi * (t / n - 0.55)) * (1 if lat >= 0 else -1)
    temp = 11 + 9 * season + 4 * np.sin(2 * math.pi * t / 24) + rng.normal(0, 2.5, n)
    wind = np.abs(rng.gamma(2.2, 2.0, n))
    precip = np.where(rng.random(n) < 0.12, rng.gamma(1.2, 1.2, n), 0)
    return {"time": [(dt.datetime.combine(start, dt.time()) + dt.timedelta(hours=int(i))).isoformat()[:16] for i in t],
            "source": f"synthetic climate (Open-Meteo unreachable: {err[:60]})", "start": str(start),
            "end": str(start + dt.timedelta(days=364)), "lat": lat, "lon": lon,
            "temp": temp, "rh": np.clip(70 + 25 * (precip > 0) + rng.normal(0, 10, n), 20, 100), "precip": precip,
            "rain": np.where(temp > 0.5, precip, 0), "snow": np.where(temp <= 0.5, precip * 0.7, 0),
            "pressure": 1013 + rng.normal(0, 9, n), "wind": wind, "gust": wind * (1.4 + rng.random(n) * 0.6),
            "cloud": np.clip(rng.normal(60, 30, n), 0, 100), "wdir": (240 + rng.normal(0, 60, n)) % 360}


def summarise(w: dict) -> dict:
    n = len(w["temp"])
    days = n // 24
    def daily(key, fn):
        return [round(float(fn(w[key][d * 24:(d + 1) * 24])), 2) for d in range(days)]
    months = {}
    for i, ts in enumerate(w["time"]):
        months.setdefault(ts[:7], []).append(i)
    monthly = []
    for m, idx in months.items():
        idx = np.array(idx)
        monthly.append({"month": m, "mean_wind_ms": round(float(w["wind"][idx].mean()), 1),
                        "max_gust_ms": round(float(w["gust"][idx].max()), 1),
                        "rain_total_mm": round(float(w["precip"][idx].sum()), 1),
                        "rain_hours": int((w["precip"][idx] > 0.1).sum()),
                        "min_temp_c": round(float(w["temp"][idx].min()), 1),
                        "max_temp_c": round(float(w["temp"][idx].max()), 1)})
    T, rh, p = w["temp"], w["rh"], w["precip"]
    icing = (T > -10) & (T < 2) & (rh > 85) & (p > 0.05)
    def pct(k, q):
        return round(float(np.percentile(w[k], q)), 2)
    def at(i):
        return {"time": w["time"][i], "temp_c": round(float(T[i]), 1), "wind_ms": round(float(w["wind"][i]), 1),
                "gust_ms": round(float(w["gust"][i]), 1), "rain_mmh": round(float(p[i]), 2),
                "humidity_pct": round(float(rh[i])), "pressure_hpa": round(float(w["pressure"][i]), 1)}
    return {
        "source": w["source"], "period": f"{w['start']} → {w['end']}", "hours": n,
        "percentiles": {k: {"p50": pct(k, 50), "p90": pct(k, 90), "p99": pct(k, 99), "max": pct(k, 100), "min": pct(k, 0)}
                        for k in ["wind", "gust", "precip", "temp", "rh", "pressure", "snow"]},
        "counts": {"rain_hours": int((p > 0.1).sum()), "heavy_rain_hours_gt4mm": int((p > 4).sum()),
                   "gust_gt_10ms_hours": int((w["gust"] > 10).sum()), "gust_gt_15ms_hours": int((w["gust"] > 15).sum()),
                   "gust_gt_20ms_hours": int((w["gust"] > 20).sum()), "freezing_hours": int((T <= 0).sum()),
                   "hot_hours_gt30c": int((T > 30).sum()), "icing_condition_hours": int(icing.sum()),
                   "snow_hours": int((w["snow"] > 0.01).sum())},
        "extremes": {"max_gust": at(int(np.argmax(w["gust"]))), "max_rain": at(int(np.argmax(p))),
                     "min_temp": at(int(np.argmin(T))), "max_temp": at(int(np.argmax(T)))},
        "monthly": monthly,
        "daily": {"gust_max": daily("gust", np.max), "wind_mean": daily("wind", np.mean),
                  "rain_sum": daily("precip", np.sum), "temp_min": daily("temp", np.min), "temp_max": daily("temp", np.max)},
    }


def find_hours(w: dict, f: dict, limit: int = 6) -> dict:
    m = np.ones(len(w["temp"]), dtype=bool)
    rules = [("min_gust_ms", "gust", ">="), ("min_wind_ms", "wind", ">="), ("min_rain_mmh", "precip", ">="),
             ("max_temp_c", "temp", "<="), ("min_temp_c", "temp", ">="), ("min_humidity_pct", "rh", ">="),
             ("min_snow_cmh", "snow", ">="), ("max_pressure_hpa", "pressure", "<=")]
    for key, col, op in rules:
        if isinstance(f.get(key), (int, float)):
            m &= (w[col] >= f[key]) if op == ">=" else (w[col] <= f[key])
    idx = np.nonzero(m)[0]
    sort_key = {"gust": w["gust"], "rain": w["precip"], "cold": -w["temp"], "heat": w["temp"]}.get(f.get("sort", "gust"), w["gust"])
    top = idx[np.argsort(-sort_key[idx])][:limit]
    return {"matching_hours": int(len(idx)), "share_of_year_pct": round(100 * len(idx) / len(m), 2),
            "examples": [{"time": w["time"][i], "temp_c": round(float(w["temp"][i]), 1), "wind_ms": round(float(w["wind"][i]), 1),
                          "gust_ms": round(float(w["gust"][i]), 1), "rain_mmh": round(float(w["precip"][i]), 2),
                          "snow_cmh": round(float(w["snow"][i]), 2), "humidity_pct": round(float(w["rh"][i])),
                          "pressure_hpa": round(float(w["pressure"][i]), 1)} for i in top]}
