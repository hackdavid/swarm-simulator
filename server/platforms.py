"""Parameter schemas for the two platform families the UI can configure."""

IP_RAIN_TOLERANCE_MMH = {"none": 0.3, "IP43": 3.0, "IP45": 7.0, "IP54": 10.0, "IP55": 16.0, "IP56": 28.0, "IP67": 60.0}
IP_WADE_DEPTH_CM = {"none": 1.0, "IP43": 2.0, "IP45": 4.0, "IP54": 6.0, "IP55": 9.0, "IP56": 14.0, "IP67": 40.0}
IP_LEVELS = list(IP_RAIN_TOLERANCE_MMH)


def _r(key, label, group, default, lo, hi, step, unit="", help=""):
    return {"key": key, "label": label, "group": group, "type": "range", "default": default,
            "min": lo, "max": hi, "step": step, "unit": unit, "help": help}


def _s(key, label, group, default, options, help=""):
    return {"key": key, "label": label, "group": group, "type": "select", "default": default,
            "options": options, "help": help}


def _b(key, label, group, default, help=""):
    return {"key": key, "label": label, "group": group, "type": "bool", "default": default, "help": help}


DRONE_PARAMS = [
    _r("frame_mass_kg", "Airframe mass (no payload)", "Airframe", 2.4, 0.3, 25, 0.1, "kg", "Take-off mass without payload, incl. battery."),
    _s("motor_count", "Rotor configuration", "Propulsion", 4, [4, 6, 8], "Quad / hexa / octo."),
    _r("max_thrust_per_motor_kg", "Max thrust per motor", "Propulsion", 1.7, 0.2, 15, 0.1, "kg", "Static thrust per motor at sea level."),
    _r("max_airspeed_ms", "Motor max speed (airspeed)", "Propulsion", 18, 5, 40, 0.5, "m/s", "Top horizontal airspeed."),
    _s("flight_controller", "Flight controller", "Propulsion", "pid", ["basic", "pid", "adaptive"], "Gust-rejection quality."),
    _r("battery_wh", "Battery capacity", "Power", 230, 10, 1500, 5, "Wh"),
    _s("battery_chemistry", "Battery chemistry", "Power", "lipo", ["lipo", "li-ion", "solid-state"], "Cold derating differs."),
    _b("battery_heater", "Self-heating battery", "Power", False, "Keeps cells warm below 15 °C."),
    _r("reserve_pct", "Landing reserve", "Power", 20, 0, 50, 1, "%"),
    _r("wind_resistance_ms", "Rated wind/gust resistance", "Airframe", 12, 3, 25, 0.5, "m/s"),
    _s("ip_rating", "Water proofing (IP rating)", "Protection", "IP43", IP_LEVELS),
    _b("prop_ice_protection", "Propeller ice protection", "Protection", False),
    _r("op_temp_min", "Min operating temp", "Protection", -10, -40, 10, 1, "°C"),
    _r("op_temp_max", "Max operating temp", "Protection", 45, 25, 70, 1, "°C"),
    _b("obstacle_avoidance", "Vision obstacle avoidance", "Sensors", True),
    _b("rtk_gps", "RTK GPS", "Sensors", False),
    _r("max_payload_kg", "Rated max payload", "Mission", 2.0, 0, 30, 0.1, "kg"),
    _r("payload_kg", "Mission payload (weight it carries)", "Mission", 1.2, 0, 30, 0.1, "kg"),
    _r("mission_minutes", "Mission duration", "Mission", 18, 2, 90, 1, "min"),
    _r("cruise_altitude_m", "Cruise altitude AGL", "Mission", 120, 10, 500, 10, "m"),
    _r("max_altitude_m", "Planner altitude ceiling", "Mission", 120, 30, 500, 10, "m", "Highest layer the 3D route planner may climb to (UK/EU open category limit is 120 m)."),
    _r("obstacle_buffer_m", "Obstacle lateral buffer", "Mission", 30, 10, 100, 5, "m", "Minimum horizontal gap the planner keeps from buildings."),
    _b("avoid_obstacles", "3D obstacle-avoiding route planner", "Mission", True, "Plan around or over buildings and restricted airspace instead of flying straight legs between waypoints."),
    _r("corridor_m", "Route corridor half-width", "Mission", 30, 5, 200, 5, "m", "Geofence tolerance either side of the planned route."),
    _b("lte_backup_link", "4G/LTE backup C2 link", "Sensors", False, "Keeps command & control when radio line-of-sight is blocked."),
]

ROBOT_PARAMS = [
    _s("locomotion", "Locomotion", "Drivetrain", "wheeled", ["wheeled", "tracked", "legged"]),
    _r("mass_kg", "Robot mass (no payload)", "Chassis", 45, 2, 400, 1, "kg"),
    _r("motor_torque_nm", "Total drive torque at wheel/leg", "Drivetrain", 42, 2, 600, 1, "N·m"),
    _r("max_speed_ms", "Motor max speed", "Drivetrain", 2.0, 0.2, 8, 0.1, "m/s"),
    _r("wheel_diameter_cm", "Wheel diameter / step height x2", "Drivetrain", 30, 6, 120, 1, "cm"),
    _b("traction_control", "Traction control", "Drivetrain", True),
    _r("ground_clearance_cm", "Ground clearance", "Chassis", 12, 2, 60, 1, "cm"),
    _r("cog_height_cm", "Centre of gravity height", "Chassis", 40, 5, 150, 1, "cm"),
    _r("track_width_cm", "Track width", "Chassis", 60, 15, 200, 1, "cm"),
    _r("battery_wh", "Battery capacity", "Power", 600, 20, 10000, 10, "Wh"),
    _s("battery_chemistry", "Battery chemistry", "Power", "li-ion", ["lipo", "li-ion", "solid-state"]),
    _b("battery_heater", "Self-heating battery", "Power", False),
    _s("ip_rating", "Water proofing (IP rating)", "Protection", "IP54", IP_LEVELS),
    _r("op_temp_min", "Min operating temp", "Protection", -10, -40, 10, 1, "°C"),
    _r("op_temp_max", "Max operating temp", "Protection", 45, 25, 70, 1, "°C"),
    _b("lidar", "3D LiDAR", "Sensors", True),
    _b("thermal_camera", "Thermal camera", "Sensors", False),
    _r("max_payload_kg", "Rated max payload", "Mission", 25, 0, 300, 1, "kg"),
    _r("payload_kg", "Mission payload (weight it carries)", "Mission", 15, 0, 300, 1, "kg"),
    _r("mission_km", "Mission distance", "Mission", 6, 0.5, 60, 0.5, "km"),
]

PLATFORMS = {
    "drone": {"id": "drone", "name": "Aerial drone", "tagline": "Multirotor UAV — 6 DOF, 4–8 rotor inputs", "params": DRONE_PARAMS},
    "robot": {"id": "robot", "name": "Ground robot", "tagline": "UGV — wheeled, tracked or legged", "params": ROBOT_PARAMS},
}


def defaults(platform: str) -> dict:
    return {p["key"]: p["default"] for p in PLATFORMS[platform]["params"]}


def normalise(platform: str, params: dict | None) -> dict:
    out = defaults(platform)
    for spec in PLATFORMS[platform]["params"]:
        k = spec["key"]
        if params and k in params:
            v = params[k]
            if spec["type"] == "range":
                v = min(max(float(v), spec["min"]), spec["max"])
            elif spec["type"] == "bool":
                v = bool(v)
            elif spec["type"] == "select":
                v = type(spec["default"])(v) if v in [str(o) for o in spec["options"]] or v in spec["options"] else spec["default"]
            out[k] = v
    return out
