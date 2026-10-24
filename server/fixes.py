"""Engineering fixes per failure mode, re-tested against the plane to quantify the gain."""
from .platforms import IP_LEVELS


def _ip_up(p, steps=2):
    i = IP_LEVELS.index(p["ip_rating"])
    return {"ip_rating": IP_LEVELS[min(i + steps, len(IP_LEVELS) - 1)]}


DRONE_FIXES = {
    "gust_upset": ("Adaptive flight controller + 25% more gust rating", lambda p: {"flight_controller": "adaptive", "wind_resistance_ms": p["wind_resistance_ms"] * 1.25}),
    "wind_overpower": ("Raise max airspeed by 5 m/s (higher-KV motors)", lambda p: {"max_airspeed_ms": p["max_airspeed_ms"] + 5}),
    "motor_saturation": ("20% higher-thrust motors/props", lambda p: {"max_thrust_per_motor_kg": p["max_thrust_per_motor_kg"] * 1.2}),
    "battery_depletion": ("30% larger battery", lambda p: {"battery_wh": p["battery_wh"] * 1.3}),
    "cold_sag": ("Self-heating battery pack", lambda p: {"battery_heater": True}),
    "water_ingress": ("Seal electronics two IP levels higher", _ip_up),
    "prop_icing": ("Heated / hydrophobic-coated propellers", lambda p: {"prop_ice_protection": True}),
    "thermal": ("Upgrade ESC cooling (+8 °C operating limit)", lambda p: {"op_temp_max": p["op_temp_max"] + 8}),
    "nav_loss": ("Add RTK GPS + obstacle avoidance", lambda p: {"rtk_gps": True, "obstacle_avoidance": True}),
    "overload": ("Cap payload at 85% of rated / stronger motors", lambda p: {"max_thrust_per_motor_kg": p["max_thrust_per_motor_kg"] * 1.15, "max_payload_kg": p["max_payload_kg"] * 1.25}),
}

ROBOT_FIXES = {
    "traction_slip": ("Traction control + switch to tracks", lambda p: {"traction_control": True, "locomotion": "tracked"}),
    "motor_stall": ("35% more drive torque (gearbox ratio)", lambda p: {"motor_torque_nm": p["motor_torque_nm"] * 1.35}),
    "tip_over": ("Widen track 20% and lower CoG 15%", lambda p: {"track_width_cm": p["track_width_cm"] * 1.2, "cog_height_cm": p["cog_height_cm"] * 0.85}),
    "bogged": ("Raise ground clearance 60%", lambda p: {"ground_clearance_cm": p["ground_clearance_cm"] * 1.6}),
    "battery_depletion": ("40% larger battery", lambda p: {"battery_wh": p["battery_wh"] * 1.4}),
    "cold_sag": ("Self-heating battery pack", lambda p: {"battery_heater": True}),
    "water_ingress": ("Seal two IP levels higher", _ip_up),
    "thermal": ("Upgrade motor cooling (+8 °C)", lambda p: {"op_temp_max": p["op_temp_max"] + 8}),
    "perception_loss": ("Add LiDAR + thermal camera", lambda p: {"lidar": True, "thermal_camera": True}),
    "obstacle_strike": ("Larger wheels (+35%)", lambda p: {"wheel_diameter_cm": p["wheel_diameter_cm"] * 1.35}),
}

FIXES = {"drone": DRONE_FIXES, "robot": ROBOT_FIXES}
