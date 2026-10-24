"""Mission routes: import (QGC .plan, GeoJSON, KML, GPX), demo routes, and a per-segment corridor profile.

The profile joins the route to map layers (OSM obstacles, population proxy, terrain, airspace) so the physics can
test the mission that will actually be flown, not a generic one.
"""
from __future__ import annotations

import heapq
import json
import math
import re
import xml.etree.ElementTree as ET

import numpy as np

from . import mapdata as M

DEMO_ROUTES = [
    {"id": "cw-hospital", "platform": "drone", "name": "Canary Wharf → Royal London Hospital",
     "desc": "Medical sample delivery from a Blackwall Basin pad, out and back over Poplar, Limehouse and Stepney", "return": True,
     "waypoints": [(51.5052, -0.0085), (51.5100, -0.0150), (51.5125, -0.0300), (51.5150, -0.0480), (51.5185, -0.0590)]},
    {"id": "cw-loop", "platform": "drone", "name": "Isle of Dogs inspection loop",
     "desc": "Dock-edge survey loop from Canary Wharf round Millwall and Island Gardens", "return": False,
     "waypoints": [(51.5052, -0.0085), (51.4960, -0.0055), (51.4875, -0.0095), (51.4893, -0.0110), (51.4975, -0.0230), (51.5005, -0.0175), (51.5052, -0.0085)]},
    {"id": "cw-crossharbour", "platform": "robot", "name": "Canary Wharf stn → Crossharbour",
     "desc": "Sidewalk parcel delivery routed on OpenStreetMap footways", "return": True,
     "waypoints": [(51.5036, -0.0187), (51.4958, -0.0143)]},
    {"id": "cw-mudchute", "platform": "robot", "name": "Canary Wharf → Mudchute Park",
     "desc": "Last-mile route ending on park paths and grass", "return": False,
     "waypoints": [(51.5036, -0.0187), (51.4905, -0.0130)]},
]

IGRC = [[1, 1, 2, 3, 3], [2, 3, 4, 5, 6], [3, 4, 5, 6, 7], [4, 5, 6, 7, 8], [5, 6, 7, 8, 9], [6, 7, 8, 9, 10], [7, 8, 9, 10, 11]]
IGRC_ROWS = [0, 5, 50, 500, 5000, 50000]
SURF = {"asphalt": 0, "paved": 0, "concrete": 0, "paving_stones": 0, "sett": 0, "concrete:plates": 0, "metal": 0, "wood": 0,
        "grass": 1, "gravel": 2, "fine_gravel": 2, "compacted": 2, "pebblestone": 2, "sand": 3, "dirt": 4, "ground": 4,
        "earth": 4, "mud": 4, "unpaved": 4}
WALK = {"footway", "pedestrian", "path", "living_street", "residential", "service", "unclassified", "tertiary",
        "secondary", "primary", "cycleway", "steps", "track", "corridor"}


def parse_route(text: str, filename: str = "") -> dict:
    """Waypoints [(lat, lon, alt|None)] + optional geofence rings from a mission/route file."""
    name = filename.rsplit("/", 1)[-1] or "Uploaded route"
    t = text.strip()
    if t.startswith("{"):
        d = json.loads(t)
        if d.get("fileType") == "Plan" or "mission" in d:  # QGroundControl .plan
            wps = []
            for it in d.get("mission", {}).get("items", []):
                for sub in it.get("TransectStyleComplexItem", {}).get("Items", []) if it.get("type") == "ComplexItem" else [it]:
                    pr = sub.get("params") or []
                    if len(pr) >= 7 and pr[4] and pr[5] and sub.get("command") in (16, 21, 22, 82, 84, 85):
                        wps.append((float(pr[4]), float(pr[5]), float(pr[6]) if pr[6] else None))
            home = d.get("mission", {}).get("plannedHomePosition")
            if home and (not wps or (abs(wps[0][0] - home[0]) + abs(wps[0][1] - home[1])) > 1e-5):
                wps.insert(0, (home[0], home[1], None))
            fences = [[(p[0], p[1]) for p in poly.get("polygon", [])] for poly in d.get("geoFence", {}).get("polygons", []) if poly.get("inclusion", True)]
            return {"name": name, "format": "QGroundControl .plan", "waypoints": wps, "geofence": [f for f in fences if len(f) > 2]}
        feats = d.get("features") or ([d] if d.get("type") == "Feature" else [{"geometry": d}])
        wps, fences = [], []
        for f in feats:
            g = f.get("geometry") or {}
            if g.get("type") == "LineString":
                wps += [(c[1], c[0], c[2] if len(c) > 2 else None) for c in g["coordinates"]]
            elif g.get("type") == "MultiLineString":
                wps += [(c[1], c[0], None) for line in g["coordinates"] for c in line]
            elif g.get("type") == "Point":
                c = g["coordinates"]
                wps.append((c[1], c[0], c[2] if len(c) > 2 else None))
            elif g.get("type") == "Polygon":
                fences.append([(c[1], c[0]) for c in g["coordinates"][0]])
        return {"name": name, "format": "GeoJSON", "waypoints": wps, "geofence": fences}
    root = ET.fromstring(re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", t, count=0))
    if root.tag.lower().endswith("gpx"):
        pts = root.findall(".//trkpt") or root.findall(".//rtept") or root.findall(".//wpt")
        wps = [(float(p.get("lat")), float(p.get("lon")), None) for p in pts]
        return {"name": name, "format": "GPX", "waypoints": wps, "geofence": []}
    wps, fences = [], []
    for pm in root.iter("Placemark"):
        for ls in pm.iter("LineString"):
            wps += [_kml_pt(c) for c in ls.findtext("coordinates", "").split()]
        for pg in pm.iter("Polygon"):
            ring = pg.findtext(".//coordinates", "").split()
            fences.append([_kml_pt(c)[:2] for c in ring])
        if not wps:
            for pt in pm.iter("Point"):
                wps.append(_kml_pt(pt.findtext("coordinates", "").strip()))
    return {"name": name, "format": "KML", "waypoints": wps, "geofence": fences}


def _kml_pt(c):
    v = [float(x) for x in c.split(",")]
    return (v[1], v[0], v[2] if len(v) > 2 and v[2] else None)


def resolve(req: dict | None, platform: str) -> dict | None:
    if not req:
        return None
    if req.get("id"):
        d = next((r for r in DEMO_ROUTES if r["id"] == req["id"]), None)
        if not d:
            raise ValueError(f"unknown demo route {req['id']}")
        return {"name": d["name"], "format": "demo", "desc": d["desc"], "return": d["return"],
                "waypoints": [(a, b, None) for a, b in d["waypoints"]], "geofence": [], "id": d["id"]}
    r = parse_route(req.get("text", ""), req.get("name", ""))
    if len(r["waypoints"]) < 2:
        raise ValueError("route needs at least 2 waypoints")
    r["return"] = bool(req.get("return", False))
    r["desc"] = f"{r['format']} upload · {len(r['waypoints'])} waypoints"
    return r


def _hav(a1, o1, a2, o2):
    R = 6371000.0
    p1, p2 = math.radians(a1), math.radians(a2)
    dp, dl = p2 - p1, math.radians(o2 - o1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _walk_route(feats: dict, wps: list, wheeled: bool):
    """Shortest walkable path through OSM ways between consecutive waypoints (Dijkstra)."""
    adj: dict = {}
    info = {}
    for rd in feats["roads"]:
        if rd["type"] not in WALK or (wheeled and rd["type"] == "steps"):
            continue
        surf = rd.get("surface")
        pts = [tuple(q) for q in rd["pts"]]
        for a, b in zip(pts, pts[1:]):
            L = _hav(*a, *b)
            cost = L * (1.0 if rd["type"] in ("footway", "pedestrian", "path", "living_street", "cycleway") else 1.25)
            adj.setdefault(a, []).append((b, cost))
            adj.setdefault(b, []).append((a, cost))
            info[(a, b)] = info[(b, a)] = (rd["type"], surf, rd.get("footway"), rd.get("incline"))
    if not adj:
        return None
    comp, best = {}, []
    for n0 in adj:  # keep the largest connected component so snapping never lands on an isolated path
        if n0 in comp:
            continue
        stack, cur = [n0], []
        comp[n0] = True
        while stack:
            u = stack.pop()
            cur.append(u)
            for v, _ in adj[u]:
                if v not in comp:
                    comp[v] = True
                    stack.append(v)
        if len(cur) > len(best):
            best = cur
    nodes = best
    arr = np.array(nodes)

    def near(p):
        return nodes[int(np.argmin((arr[:, 0] - p[0]) ** 2 + ((arr[:, 1] - p[1]) * 0.62) ** 2))]
    path, attrs = [], []
    for s, e in zip(wps, wps[1:]):
        src, dst = near(s), near(e)
        dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dst:
                break
            if d > dist.get(u, 1e18):
                continue
            for v, c in adj[u]:
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd, v))
        if dst not in dist:
            return None
        seg = [dst]
        while seg[-1] != src:
            seg.append(prev[seg[-1]])
        seg.reverse()
        path += seg if not path else seg[1:]
    attrs = [info.get((a, b), ("footway", None, None, None)) for a, b in zip(path, path[1:])]
    return path, attrs


async def build_profile(route: dict, platform: str, params: dict, emit=None) -> dict:
    wps = [(w[0], w[1]) for w in route["waypoints"]]
    alt = float(params.get("cruise_altitude_m", 60)) if platform == "drone" else 0.0
    if platform == "drone":
        alt = min(alt, 120.0) if params.get("cruise_altitude_m", 60) > 120 else alt
    buf_m = max(alt, 60.0) + 150
    lats0, lons0 = zip(*wps)
    tiles = M.corridor_tiles(np.interp(np.linspace(0, len(lats0) - 1, 60), range(len(lats0)), lats0),
                             np.interp(np.linspace(0, len(lons0) - 1, 60), range(len(lons0)), lons0), buf_m)
    if emit:
        await emit({"type": "route_progress", "text": f"Fetching OpenStreetMap features for {len(tiles)} map tiles"})
    s, n = min(t[0] for t in tiles) * M.TILE_DEG, (max(t[0] for t in tiles) + 1) * M.TILE_DEG
    w, e = min(t[1] for t in tiles) * M.TILE_DEG, (max(t[1] for t in tiles) + 1) * M.TILE_DEG
    feats = await M.osm_features(s, w, n, e, tiles)
    edge_attr = None
    path = wps
    routed = "straight legs between waypoints"
    if platform == "robot" and feats.get("roads"):
        r = _walk_route(feats, wps, params.get("locomotion", "wheeled") == "wheeled")
        if r:
            path, edge_attr = r
            routed = "shortest walkable path on OpenStreetMap ways"
    if route.get("return"):
        back = path[::-1]
        if edge_attr is not None:
            edge_attr = edge_attr + edge_attr[::-1]
        path = path + back[1:]
    if emit:
        await emit({"type": "route_progress", "text": "Rasterising buildings, people, water and roads (20 m cells)"})
    R = M.rasterise(feats, s, w, n, e, 20.0)
    # resample every ~15 m
    step = 15.0
    la, lo, dd, hd, ea = [], [], [], [], []
    tot = 0.0
    for k, ((a1, o1), (a2, o2)) in enumerate(zip(path, path[1:])):
        L = _hav(a1, o1, a2, o2)
        hdg = (math.degrees(math.atan2((o2 - o1) * math.cos(math.radians(a1)), a2 - a1)) + 360) % 360
        nk = max(1, int(L / step))
        for t in np.arange(nk) / nk:
            la.append(a1 + t * (a2 - a1)); lo.append(o1 + t * (o2 - o1)); dd.append(tot + t * L); hd.append(hdg)
            ea.append(edge_attr[k] if edge_attr else None)
        tot += L
    la.append(path[-1][0]); lo.append(path[-1][1]); dd.append(tot); hd.append(hd[-1] if hd else 0); ea.append(ea[-1] if ea else None)
    la, lo, dd, hd = map(np.array, (la, lo, dd, hd))
    cm = R["cell_m"]
    ci = np.clip(((la - s) * M.M_PER_DEG / cm).astype(int), 0, R["ny"] - 1)
    cj = np.clip(((lo - w) * M.M_PER_DEG * math.cos(math.radians(s)) / cm).astype(int), 0, R["nx"] - 1)

    def window(arr, rad_m, fn):
        r = max(1, int(rad_m / cm))
        return np.array([fn(arr[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]) for i, j in zip(ci, cj)])
    hmax = R["hmax"]
    if emit:
        await emit({"type": "route_progress", "text": "Sampling terrain (Copernicus DEM) and airspace (openAIP)"})
    elev, dem_src = await M.elevation(la, lo)
    zones = await M.airspace("gb") if 49 < la.mean() < 61 and -9 < lo.mean() < 2.5 else []
    # obstacle clearance: distance to the nearest cell taller than cruise altitude - 10 m (drone) / kerb-level for robot
    tall = hmax > (alt - 10) if platform == "drone" else np.zeros_like(hmax, bool)
    ty, tx = np.nonzero(tall)
    clear = np.full(len(la), 150.0)
    if len(ty):
        for k, (i, j) in enumerate(zip(ci, cj)):
            m = (np.abs(ty - i) < 9) & (np.abs(tx - j) < 9)
            if m.any():
                clear[k] = max(0.0, float(np.min(np.hypot(ty[m] - i, tx[m] - j))) * cm - cm / 2)
    canyon = window(hmax, 60, lambda a: float((a > 30).mean()))
    gbuf = max(alt, 30.0)
    people = window(R["people"], gbuf, lambda a: float(a.mean())) / (cm * cm) * 1e6
    outdoor = window(R["outdoor"], gbuf, lambda a: float(a.mean())) / (cm * cm) * 1e6
    sens = window(R["sensitive"], gbuf, lambda a: bool(a.any()))
    water = R["water"][ci, cj]
    # line of sight from the take-off point (ground station) at cruise altitude
    nlos = np.zeros(len(la), bool)
    if platform == "drone":
        for k in range(0, len(la)):
            ii = np.linspace(ci[0], ci[k], 24).astype(int)
            jj = np.linspace(cj[0], cj[k], 24).astype(int)
            hline = np.concatenate([[2.0], np.full(22, alt), [alt]])
            hline[1:4] = np.linspace(2, alt, 3)
            nlos[k] = bool((hmax[ii, jj][1:-1] > hline[1:-1] + 2).any())
    # airspace at the flight altitude
    zone_hits = []
    for z in zones:
        if z["lower_m"] > alt + 5:
            continue
        inside = M.point_in_ring(la, lo, z["ring"])
        if inside.any():
            zone_hits.append({"name": z["name"], "type": z["type"], "code": z["code"], "icao": z["icao"],
                              "lower_m": round(z["lower_m"]), "upper_m": round(z["upper_m"]), "upper_ref": z["upper_ref"],
                              "frac": round(float(inside.mean()), 3), "mask": inside,
                              "ring": [(round(a, 5), round(b, 5)) for a, b in z["ring"][::max(1, len(z["ring"]) // 240)]]})
    # robot: slope from smoothed surface model, surfaces, crossings
    slope = np.zeros(len(la))
    surf = np.zeros(len(la), int)
    crossing = np.zeros(len(la), bool)
    if platform == "robot":
        z = elev.astype(float)
        zs = np.array([np.median(z[max(0, i - 7):i + 8]) for i in range(len(z))])
        dz = np.gradient(zs) / np.maximum(np.gradient(dd), 1.0) if len(zs) > 2 else np.zeros(len(zs))
        slope = np.clip(np.nan_to_num(np.degrees(np.arctan(np.abs(dz)))), 0, 8)
        for k, a in enumerate(ea):
            if not a:
                continue
            typ, sf, fw, inc = a
            if sf in SURF:
                surf[k] = SURF[sf]
            elif typ in ("path", "track") and R["green"][ci[k], cj[k]]:
                surf[k] = 1
            if fw == "crossing":
                crossing[k] = True
            mm = re.match(r"(-?\d+(\.\d+)?)%", str(inc or ""))
            if mm:
                slope[k] = math.degrees(math.atan(abs(float(mm.group(1))) / 100))
        rc = R["road"][ci, cj]
        crossing |= (rc == 3)
        crossing &= ~np.roll(crossing, 1)
    seg_len = 200.0 if platform == "drone" else 100.0
    nseg = int(min(40, max(4, math.ceil(tot / seg_len))))
    edges = np.linspace(0, tot, nseg + 1)
    sid = np.clip(np.searchsorted(edges, dd, side="right") - 1, 0, nseg - 1)
    segs = []
    for k in range(nseg):
        m = sid == k
        if not m.any():
            m = np.zeros(len(la), bool); m[min(len(la) - 1, int(k * len(la) / nseg))] = True
        pd = float(people[m].mean())
        row = int(np.searchsorted(IGRC_ROWS, pd, side="right"))
        segs.append({
            "i": k, "from_m": round(float(edges[k])), "to_m": round(float(edges[k + 1])), "length_m": round(float(edges[k + 1] - edges[k]), 1),
            "heading_deg": round(float(np.median(hd[m])), 1), "lat": round(float(la[m].mean()), 6), "lon": round(float(lo[m].mean()), 6),
            "clearance_m": round(float(clear[m].min()), 1), "max_obstacle_m": round(float(hmax[ci[m], cj[m]].max()), 1),
            "people_per_km2": round(pd), "outdoor_per_km2": round(float(outdoor[m].mean())), "igrc_row": row,
            "sensitive": bool(sens[m].any()), "over_water": round(float(water[m].mean()), 2), "canyon": round(float(canyon[m].max()), 2),
            "nlos": round(float(nlos[m].mean()), 2), "ground_m": round(float(np.median(elev[m])), 1),
            "airspace": [z["name"] for z in zone_hits if z["mask"][m].any()],
            "slope_deg": round(float(np.percentile(slope[m], 90)), 1), "surface": int(np.bincount(surf[m], minlength=5).argmax()),
            "crossings": int(crossing[m].sum()),
        })
    return {"name": route["name"], "desc": route.get("desc", ""), "format": route.get("format"), "id": route.get("id"),
            "platform": platform, "routed": routed, "length_m": round(tot, 1), "return": bool(route.get("return")),
            "alt_m": alt, "path": [(round(a, 6), round(b, 6)) for a, b in path],
            "samples": {"lat": la, "lon": lo, "d": dd, "seg": sid}, "segments": segs,
            "airspace": [{k: v for k, v in z.items() if k != "mask"} for z in zone_hits],
            "geofence": route.get("geofence") or [], "bbox": [s, w, n, e], "raster": R, "feats": feats,
            "sources": {"osm": feats.get("source"), "dem": dem_src, "airspace": "openAIP daily export" if zones else "none",
                        "population": "proxy: OSM building floor area × occupancy (daytime)"}}
