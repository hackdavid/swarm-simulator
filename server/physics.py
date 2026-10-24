"""Vectorised Monte-Carlo physics for drones and ground robots.

Every environment cell is flown/driven K times with randomised turbulence,
component health and sensor noise. Each trial returns 0 (pass) or a failure
mode id. All maths is NumPy so a million cells x 16 trials runs in seconds.
"""
from __future__ import annotations

import numpy as np

from .platforms import IP_RAIN_TOLERANCE_MMH, IP_WADE_DEPTH_CM

G = 9.81

DRONE_MODES = [
    {"id": 1, "key": "gust_upset", "name": "Gust upset / loss of control", "color": "#ff3b6b"},
    {"id": 2, "key": "wind_overpower", "name": "Wind overpowers airspeed (flyaway)", "color": "#ff8a3d"},
    {"id": 3, "key": "motor_saturation", "name": "Motor saturation", "color": "#ffd23f"},
    {"id": 4, "key": "battery_depletion", "name": "Battery depleted before landing", "color": "#c77dff"},
    {"id": 5, "key": "cold_sag", "name": "Cold battery voltage sag", "color": "#7ae7ff"},
    {"id": 6, "key": "water_ingress", "name": "Water ingress / ESC short", "color": "#3a86ff"},
    {"id": 7, "key": "prop_icing", "name": "Propeller icing", "color": "#e0fbfc"},
    {"id": 8, "key": "thermal", "name": "Thermal shutdown", "color": "#f94144"},
    {"id": 9, "key": "nav_loss", "name": "Navigation / vision loss", "color": "#adb5bd"},
    {"id": 10, "key": "overload", "name": "Overload — cannot climb", "color": "#9d4edd"},
    {"id": 11, "key": "obstacle_conflict", "name": "Obstacle conflict (building / tree)", "color": "#ff006e"},
    {"id": 12, "key": "geofence_breach", "name": "Geofence / corridor breach", "color": "#fb5607"},
    {"id": 13, "key": "link_loss", "name": "C2 link loss → lost-link failure", "color": "#8ecae6"},
]

ROBOT_MODES = [
    {"id": 1, "key": "traction_slip", "name": "Traction slip on slope", "color": "#ff3b6b"},
    {"id": 2, "key": "motor_stall", "name": "Drive motor stall", "color": "#ffd23f"},
    {"id": 3, "key": "tip_over", "name": "Tip-over", "color": "#ff8a3d"},
    {"id": 4, "key": "bogged", "name": "Bogged in mud / snow", "color": "#a47148"},
    {"id": 5, "key": "battery_depletion", "name": "Battery depleted mid-mission", "color": "#c77dff"},
    {"id": 6, "key": "cold_sag", "name": "Cold battery voltage sag", "color": "#7ae7ff"},
    {"id": 7, "key": "water_ingress", "name": "Water ingress", "color": "#3a86ff"},
    {"id": 8, "key": "thermal", "name": "Thermal shutdown", "color": "#f94144"},
    {"id": 9, "key": "perception_loss", "name": "Perception loss (fog/rain)", "color": "#adb5bd"},
    {"id": 10, "key": "obstacle_strike", "name": "Obstacle strike / high-centre", "color": "#9d4edd"},
    {"id": 11, "key": "pedestrian_conflict", "name": "Pedestrian conflict (cannot stop in time)", "color": "#ff006e"},
    {"id": 12, "key": "crossing_failure", "name": "Road crossing / kerb failure", "color": "#fb5607"},
    {"id": 13, "key": "localisation_loss", "name": "Localisation loss (urban canyon)", "color": "#8ecae6"},
]

MODES = {"drone": DRONE_MODES, "robot": ROBOT_MODES}

COLD_COEF = {"lipo": 0.012, "li-ion": 0.016, "solid-state": 0.006}
FC_FACTOR = {"basic": 0.85, "pid": 1.0, "adaptive": 1.18}
LOCO_GRIP = {"wheeled": 1.0, "tracked": 1.3, "legged": 1.15}
LOCO_CLEAR = {"wheeled": 1.0, "tracked": 1.6, "legged": 2.2}
LOCO_STEP = {"wheeled": 0.4, "tracked": 0.75, "legged": 0.9}
LOCO_STAB = {"wheeled": 1.0, "tracked": 1.1, "legged": 0.85}
LOCO_EFF = {"wheeled": 0.62, "tracked": 0.48, "legged": 0.38}
TERRAINS = ["asphalt", "grass", "gravel", "sand", "dirt/mud"]
TERRAIN_FRICTION = np.array([0.85, 0.6, 0.65, 0.5, 0.55], dtype=np.float32)
TERRAIN_RR = np.array([0.015, 0.07, 0.04, 0.16, 0.1], dtype=np.float32)

DRONE_ENV_KEYS = ["wind", "gust", "rain", "snow", "temp", "rh", "pressure", "vis", "payload"]
ROBOT_ENV_KEYS = DRONE_ENV_KEYS + ["slope", "terrain", "friction", "mud", "snow_depth", "obstacle"]


def _c(a):
    return np.asarray(a, dtype=np.float32).reshape(-1, 1)


def _battery_factor(p, T):
    cold = 1 - COLD_COEF[p["battery_chemistry"]] * np.maximum(0.0, 15 - T)
    if p["battery_heater"]:
        cold = np.where(T < 15, np.maximum(cold, 0.93), cold)
    heat = np.where(T > 40, 0.95, 1.0)
    return np.clip(cold, 0.2, 1.0) * heat


def _pick(conds):
    """First true condition wins (ordered by root-cause priority)."""
    out = np.zeros(conds[0][1].shape, dtype=np.uint8)
    for mode_id, c in reversed(conds):
        out = np.where(c, np.uint8(mode_id), out)
    return out


def drone_trials(p: dict, env: dict, K: int, rng: np.random.Generator, detail=False):
    wind, gust, rain, snow = _c(env["wind"]), _c(env["gust"]), _c(env["rain"]), _c(env["snow"])
    T, rh, P, vis, payload = _c(env["temp"]), _c(env["rh"]), _c(env["pressure"]), _c(env["vis"]), _c(env["payload"])
    n = (wind.shape[0], K)
    rho = P * 100 / (287.05 * (T + 273.15))
    rr = rho / 1.225
    m = p["frame_mass_kg"] + payload
    W = m * G
    health = 1 - np.abs(rng.normal(0, 0.03, n))
    health = np.where(rng.random(n) < 0.01, health * 0.8, health)
    motors = int(p["motor_count"])
    tmax = motors * p["max_thrust_per_motor_kg"] * G * rr * (1 - 0.06 * np.minimum(rain / 10, 1)) * health
    twr = tmax / W
    gt = np.maximum(gust * (1 + 0.15 * rng.standard_normal(n)), wind)
    tol = 1.35 * p["wind_resistance_ms"] * FC_FACTOR[p["flight_controller"]] * np.clip(twr / 2.0, 0.6, 1.4) ** 0.35
    f_gust = gt > tol * (1 + 0.05 * rng.standard_normal(n))
    f_wind = wind * (1 + 0.05 * rng.standard_normal(n)) > 0.75 * p["max_airspeed_ms"]
    area = 0.06 * m ** (2 / 3)
    drag = 0.5 * rho * 1.05 * area * gt ** 2
    req = np.sqrt(W ** 2 + drag ** 2) * 1.3
    f_sat = req > tmax
    f_over = (W * 1.3 > tmax) | (payload > p["max_payload_kg"] * 1.05)
    bf = _battery_factor(p, T)
    usable = p["battery_wh"] * 0.9 * bf * (1 + 0.04 * rng.standard_normal(n))
    r = 0.12 * np.sqrt(p["max_thrust_per_motor_kg"])
    disc = motors * np.pi * r * r
    p_hover = W ** 1.5 / np.sqrt(2 * rho * disc) / 0.62
    p_mission = p_hover * (1 + 0.025 * wind + 0.0025 * wind ** 2) * (1 + 0.1 * (rain > 2)) + 15
    endurance = usable / p_mission * 60
    need = _c(env["mission_min"]) * (1 + p["reserve_pct"] / 100) if "mission_min" in env else p["mission_minutes"] * (1 + p["reserve_pct"] / 100)
    f_batt = endurance < need
    cold_limit = p["op_temp_min"] - (8 if p["battery_heater"] else 0)
    f_cold = (f_batt & (bf < 0.88)) | (T < cold_limit)
    wet = rain + snow / 0.7
    ip_tol = IP_RAIN_TOLERANCE_MMH[p["ip_rating"]]
    f_water = wet * (1 + 0.25 * rng.standard_normal(n)) > ip_tol
    icing = (T > -10) & (T < 2) & (rh > 85) & ((wet > 0.05) | (vis < 1.0))
    f_ice = icing & (rng.random(n) < (0.05 if p["prop_ice_protection"] else 0.75))
    f_heat = (T > p["op_temp_max"]) | ((T > p["op_temp_max"] - 6) & (req / tmax > 0.75))
    nav_p = (0.25 if p["obstacle_avoidance"] else 0.6) * (0.6 if p["rtk_gps"] else 1.0)
    vis_lim = 0.4 if p["obstacle_avoidance"] else 1.2
    f_nav = (vis < vis_lim) & (rng.random(n) < nav_p)
    mode = _pick([(10, f_over), (6, f_water), (7, f_ice), (8, f_heat), (5, f_cold), (3, f_sat),
                  (1, f_gust), (2, f_wind), (4, f_batt), (9, f_nav)])
    if not detail:
        return mode
    return mode, {
        "thrust_to_weight": float(np.mean(twr)),
        "gust_tolerance_ms": float(np.mean(tol)),
        "gust_peak_ms": float(np.mean(gt)),
        "airspeed_limit_ms": 0.75 * p["max_airspeed_ms"],
        "thrust_required_pct": float(np.mean(req / tmax) * 100),
        "endurance_min": float(np.mean(endurance)),
        "endurance_needed_min": float(np.mean(need)),
        "battery_derate_pct": float((1 - np.mean(bf)) * 100),
        "rain_tolerance_mmh": ip_tol,
        "air_density": float(np.mean(rho)),
        "icing_conditions": bool(np.any(icing)),
    }


def robot_trials(p: dict, env: dict, K: int, rng: np.random.Generator, detail=False):
    wind, gust, rain, snow = _c(env["wind"]), _c(env["gust"]), _c(env["rain"]), _c(env["snow"])
    T, vis, payload = _c(env["temp"]), _c(env["vis"]), _c(env["payload"])
    slope = np.radians(_c(env["slope"]))
    mu0, mud, sdepth, obst = _c(env["friction"]), _c(env["mud"]), _c(env["snow_depth"]), _c(env["obstacle"])
    terrain = np.asarray(env["terrain"]).astype(int).reshape(-1, 1)
    n = (wind.shape[0], K)
    loco = p["locomotion"]
    m = p["mass_kg"] + payload
    W = m * G
    mu = mu0 * LOCO_GRIP[loco] * (1.1 if p["traction_control"] else 1.0) * (1 + 0.08 * rng.standard_normal(n))
    f_slip = np.tan(slope) > mu
    crr = TERRAIN_RR[terrain] + 0.012 * mud + 0.01 * sdepth
    force = W * (np.sin(slope) + crr * np.cos(slope))
    r_wheel = p["wheel_diameter_cm"] / 200
    torque_need = force * r_wheel * (1 + 0.1 * np.abs(rng.standard_normal(n)))
    health = 1 - np.abs(rng.normal(0, 0.04, n))
    f_stall = torque_need > p["motor_torque_nm"] * health
    rho = 1.225
    side_area = (p["cog_height_cm"] * 2 / 100) * 0.45
    gt = 0.75 * np.maximum(gust * (1 + 0.15 * rng.standard_normal(n)), wind)
    wind_acc = 0.5 * rho * 1.2 * side_area * gt ** 2 / m
    bump = 0.08 * (obst / p["wheel_diameter_cm"]) * np.abs(rng.standard_normal(n))
    stab = (p["track_width_cm"] / 2) / p["cog_height_cm"] * LOCO_STAB[loco]
    f_tip = np.tan(slope) + wind_acc / G + bump > stab
    clearance = p["ground_clearance_cm"] * LOCO_CLEAR[loco]
    f_bog = (mud + 0.6 * sdepth) * (1 + 0.15 * rng.standard_normal(n)) > clearance
    bf = _battery_factor(p, T)
    usable = p["battery_wh"] * 0.9 * bf * (1 + 0.04 * rng.standard_normal(n))
    dist = _c(env["mission_km"]) * 1000 if "mission_km" in env else p["mission_km"] * 1000
    speed = p["max_speed_ms"] * 0.7 / (1 + 2 * crr)
    hours = dist / np.maximum(speed, 0.05) / 3600
    energy = W * (crr * np.cos(slope) + 0.5 * np.sin(slope)) * dist / LOCO_EFF[loco] / 3600 + 45 * hours
    f_batt = energy > usable
    cold_limit = p["op_temp_min"] - (8 if p["battery_heater"] else 0)
    f_cold = (f_batt & (bf < 0.88)) | (T < cold_limit)
    ip_tol = IP_RAIN_TOLERANCE_MMH[p["ip_rating"]]
    wade = IP_WADE_DEPTH_CM[p["ip_rating"]]
    wet = rain + snow / 0.7
    f_water = (wet * (1 + 0.25 * rng.standard_normal(n)) > ip_tol) | (mud * (rain > 0.5) > wade)
    load = torque_need / p["motor_torque_nm"]
    f_heat = (T > p["op_temp_max"]) | ((T > p["op_temp_max"] - 8) & (load > 0.8))
    blind = (vis < 0.3) | (wet > 12)
    perc_p = 0.6 if not p["lidar"] else 0.18
    if p["thermal_camera"]:
        perc_p *= 0.5
    f_perc = blind & (rng.random(n) < perc_p)
    f_obst = obst * (1 + 0.2 * rng.standard_normal(n)) > p["wheel_diameter_cm"] * LOCO_STEP[loco]
    f_obst |= payload > p["max_payload_kg"] * 1.1
    mode = _pick([(7, f_water), (8, f_heat), (6, f_cold), (3, f_tip), (1, f_slip), (4, f_bog),
                  (2, f_stall), (10, f_obst), (5, f_batt), (9, f_perc)])
    if not detail:
        return mode
    return mode, {
        "effective_friction": float(np.mean(mu)),
        "slope_grip_needed": float(np.mean(np.tan(slope))),
        "torque_needed_nm": float(np.mean(torque_need)),
        "torque_available_nm": p["motor_torque_nm"],
        "stability_index": float(stab),
        "tip_demand": float(np.mean(np.tan(slope) + wind_acc / G + bump)),
        "sink_depth_cm": float(np.mean(mud + 0.6 * sdepth)),
        "clearance_cm": float(clearance),
        "energy_needed_wh": float(np.mean(energy)),
        "energy_available_wh": float(np.mean(usable)),
        "battery_derate_pct": float((1 - np.mean(bf)) * 100),
        "rain_tolerance_mmh": ip_tol,
        "terrain": TERRAINS[int(terrain[0, 0])],
    }


TRIALS = {"drone": drone_trials, "robot": robot_trials}


def summarise_modes(mode: np.ndarray, n_modes: int = 10):
    """Per-row pass count and dominant failure mode."""
    K = mode.shape[1]
    counts = np.stack([(mode == k).sum(axis=1) for k in range(1, n_modes + 1)], axis=1)
    passes = K - counts.sum(axis=1)
    dom = np.where(counts.sum(axis=1) > 0, counts.argmax(axis=1) + 1, 0).astype(np.uint8)
    return passes, dom, counts


def evaluate_scenario(platform: str, params: dict, scenario: dict, trials: int = 200, seed: int = 7):
    """Single-scenario test used by the agents' run_physics_test tool."""
    env = scenario_env(platform, params, scenario)
    rng = np.random.default_rng(seed)
    mode, margins = TRIALS[platform](params, env, trials, rng, detail=True)
    passes, dom, counts = summarise_modes(mode)
    names = {m["id"]: m["name"] for m in MODES[platform]}
    hist = {names[i + 1]: int(c) for i, c in enumerate(counts[0]) if c}
    return {
        "pass_rate_pct": round(100 * float(passes[0]) / trials, 1),
        "trials": trials,
        "dominant_failure": names.get(int(dom[0]), None),
        "failure_histogram": hist,
        "margins": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in margins.items()},
        "scenario": {k: (round(float(v[0]), 2) if k != "terrain" else TERRAINS[int(v[0])]) for k, v in env.items()},
    }


def scenario_env(platform: str, params: dict, s: dict) -> dict:
    def g(k, d):
        v = s.get(k)
        return float(v) if isinstance(v, (int, float)) else d
    wind = g("wind_ms", 4.0)
    rain = g("rain_mmh", 0.0)
    temp = g("temp_c", 12.0)
    env = {
        "wind": wind, "gust": max(g("gust_ms", wind * 1.5), wind), "rain": rain, "snow": g("snow_cmh", 0.0),
        "temp": temp, "rh": g("humidity_pct", 75.0), "pressure": g("pressure_hpa", 1013.0),
        "vis": g("visibility_km", 20.0), "payload": g("payload_kg", params.get("payload_kg", 0.0)),
    }
    if platform == "robot":
        terr = s.get("terrain", "grass")
        ti = TERRAINS.index(terr) if terr in TERRAINS else 1
        fr = TERRAIN_FRICTION[ti] * (0.8 if rain > 0.2 else 1.0)
        if temp < 0 and (rain > 0 or env["snow"] > 0):
            fr = 0.15
        env.update({"slope": g("slope_deg", 5.0), "terrain": ti, "friction": g("friction", float(fr)),
                    "mud": g("mud_depth_cm", 0.0), "snow_depth": g("snow_depth_cm", 0.0), "obstacle": g("obstacle_cm", 3.0)})
    return {k: np.array([v], dtype=np.float32) for k, v in env.items()}
