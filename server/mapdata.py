"""Map layers for a route corridor: OpenStreetMap features, terrain, airspace and a population proxy.

OSM comes from the main OSM API (`/api/0.6/map`, small bbox tiles, cached). Terrain is the Copernicus
GLO-30 DSM (AWS open data COGs). Airspace is the openAIP daily export. Population is a proxy derived from
OSM building floor area x occupancy (GHSL is the intended source when reachable).
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import numpy as np

CACHE = Path(__file__).resolve().parent.parent / "data" / "map_cache"
OSM_API = "https://api.openstreetmap.org/api/0.6/map"
DEM_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif")
AIP_URL = "https://storage.openaip.net/openaip-system-exports/{cc}_asp.geojson"
TILE_DEG = 0.01
M_PER_DEG = 111_320.0

# openAIP airspace type codes that matter for low-level drone flight
AIP_TYPES = {0: "Other", 1: "Restricted", 2: "Danger", 3: "Prohibited", 4: "CTR", 5: "TMZ", 6: "RMZ", 7: "TMA",
             13: "ATZ", 18: "Aerodrome traffic", 21: "Gliding", 26: "CTA", 28: "Sport/rec", 29: "Low-level"}
NO_FLY = {1, 3}          # needs specific permission / prohibited
CONTROLLED = {4, 7, 13, 26}
FT = 0.3048

# people per m² of floor area (daytime) by building type; a documented proxy, not census data
OCCUPANCY = {"office": 1 / 20, "commercial": 1 / 15, "retail": 1 / 8, "residential": 1 / 35, "apartments": 1 / 30,
             "house": 1 / 45, "school": 1 / 6, "university": 1 / 10, "hospital": 1 / 12, "train_station": 1 / 4,
             "transportation": 1 / 6, "hotel": 1 / 30, "industrial": 1 / 60, "warehouse": 1 / 120, "yes": 1 / 25}
SENSITIVE = {"school", "hospital", "university", "kindergarten", "stadium", "train_station"}


def _xy(lat0, lon0):
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    return lambda lat, lon: ((lon - lon0) * kx, (lat - lat0) * M_PER_DEG)


def corridor_tiles(lats, lons, buffer_m: float) -> list:
    """OSM API tiles touched by a path plus a buffer."""
    d = buffer_m / M_PER_DEG
    out = set()
    for a, b in zip(lats, lons):
        out.update(_bbox_tiles(a - d, b - d * 1.6, a + d, b + d * 1.6))
    return sorted(out)


def _bbox_tiles(s, w, n, e):
    i0, i1 = math.floor(s / TILE_DEG), math.floor(n / TILE_DEG)
    j0, j1 = math.floor(w / TILE_DEG), math.floor(e / TILE_DEG)
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


async def _osm_tile(c: httpx.AsyncClient, i: int, j: int) -> str | None:
    f = CACHE / "osm" / f"{i}_{j}.xml"
    if f.exists():
        return f.read_text()
    s, w = i * TILE_DEG, j * TILE_DEG
    try:
        r = await c.get(OSM_API, params={"bbox": f"{w:.4f},{s:.4f},{w + TILE_DEG:.4f},{s + TILE_DEG:.4f}"})
        r.raise_for_status()
    except Exception:
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(r.text)
    return r.text


def _height(tags: dict) -> float:
    for k in ("height", "building:height"):
        try:
            return float(str(tags[k]).split()[0].replace("m", ""))
        except (KeyError, ValueError):
            pass
    try:
        return float(tags["building:levels"]) * 3.2 + 2
    except (KeyError, ValueError):
        return {"house": 8, "residential": 14, "apartments": 20, "office": 30, "commercial": 15}.get(tags.get("building"), 11)


def _parse(xml: str, feats: dict, seen: set):
    root = ET.fromstring(xml)
    nodes = {}
    for nd in root.iter("node"):
        nodes[nd.get("id")] = (float(nd.get("lat")), float(nd.get("lon")))
        tags = {t.get("k"): t.get("v") for t in nd.iter("tag")}
        if tags.get("natural") == "tree" and nd.get("id") not in seen:
            seen.add(nd.get("id"))
            feats["trees"].append(nodes[nd.get("id")])
    for way in root.iter("way"):
        wid = way.get("id")
        if wid in seen:
            continue
        tags = {t.get("k"): t.get("v") for t in way.iter("tag")}
        pts = [nodes[n.get("ref")] for n in way.iter("nd") if n.get("ref") in nodes]
        if len(pts) < 2:
            continue
        kind = None
        if "building" in tags:
            kind = "buildings"
            item = {"pts": pts, "h": _height(tags), "type": tags.get("building", "yes"),
                    "amenity": tags.get("amenity"), "name": tags.get("name")}
        elif tags.get("power") in ("line", "minor_line"):
            kind, item = "power", {"pts": pts}
        elif "highway" in tags:
            kind, item = "roads", {"pts": pts, "type": tags["highway"], "surface": tags.get("surface"),
                                   "incline": tags.get("incline"), "name": tags.get("name"),
                                   "footway": tags.get("footway"), "nodes": [n.get("ref") for n in way.iter("nd")]}
        elif tags.get("natural") == "water" or "waterway" in tags or tags.get("landuse") == "basin":
            kind, item = "water", {"pts": pts}
        elif tags.get("leisure") in ("park", "garden") or tags.get("landuse") in ("grass", "forest") or tags.get("natural") == "wood":
            kind, item = "green", {"pts": pts, "type": tags.get("leisure") or tags.get("landuse") or tags.get("natural")}
        if kind:
            seen.add(wid)
            feats[kind].append(item)


async def osm_features(s, w, n, e, tiles: list | None = None) -> dict:
    """Buildings (with heights), trees, power lines, roads/footways, water and green areas in a bbox (or tile list)."""
    tiles = sorted(set(tiles or _bbox_tiles(s, w, n, e)))
    out = CACHE / "osm" / f"feat_v2_{abs(hash(tuple(tiles))) % 10**12}.json"
    if out.exists():
        return json.loads(out.read_text())
    feats = {k: [] for k in ("buildings", "trees", "power", "roads", "water", "green")}
    seen: set = set()
    ok = 0
    async with httpx.AsyncClient(timeout=90, headers={"User-Agent": "swarm-proving-ground/0.2"}) as c:
        for i, j in tiles:
            xml = await _osm_tile(c, i, j)
            if xml:
                ok += 1
                _parse(xml, feats, seen)
    feats["source"] = "OpenStreetMap contributors (ODbL)" if ok else "unavailable"
    if ok:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(feats))
    return feats


_DEM: dict = {}


async def _dem_tile(lat_i: int, lon_i: int):
    key = (lat_i, lon_i)
    if key in _DEM:
        return _DEM[key]
    ns, ew = ("N", lat_i) if lat_i >= 0 else ("S", -lat_i), ("E", lon_i) if lon_i >= 0 else ("W", -lon_i)
    f = CACHE / f"dem_{ns[0]}{ns[1]:02d}_{ew[0]}{ew[1]:03d}.tif"
    if not f.exists():
        try:
            async with httpx.AsyncClient(timeout=180) as c:
                r = await c.get(DEM_URL.format(ns=ns[0], lat=ns[1], ew=ew[0], lon=ew[1]))
                r.raise_for_status()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(r.content)
        except Exception:
            _DEM[key] = None
            return None
    import tifffile
    _DEM[key] = tifffile.imread(f)
    return _DEM[key]


async def elevation(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, str]:
    """Surface elevation (m, Copernicus GLO-30 DSM) at points; 0 if the tile is unavailable."""
    z = np.zeros(len(lats), dtype=np.float32)
    src = "Copernicus DEM GLO-30 (DSM)"
    for li, lo in {(math.floor(a), math.floor(b)) for a, b in zip(lats, lons)}:
        a = await _dem_tile(li, lo)
        m = (np.floor(lats) == li) & (np.floor(lons) == lo)
        if a is None:
            src = "flat (DEM unavailable)"
            continue
        H, W = a.shape
        r = np.clip(((li + 1 - lats[m]) * H).astype(int), 0, H - 1)
        c = np.clip(((lons[m] - lo) * W).astype(int), 0, W - 1)
        z[m] = a[r, c]
    return z, src


async def airspace(country: str = "gb") -> list[dict]:
    f = CACHE / f"{country}_asp.geojson"
    if not f.exists():
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(AIP_URL.format(cc=country))
                r.raise_for_status()
            f.write_bytes(r.content)
        except Exception:
            return []
    out = []
    for ft in json.loads(f.read_text())["features"]:
        g, p = ft["geometry"], ft["properties"]
        if g["type"] != "Polygon":
            continue

        def lim(d):
            v = d.get("value", 0) * (FT if d.get("unit", 1) == 1 else 1)
            return v, "AGL" if d.get("referenceDatum", 0) == 0 else "MSL"
        lo, hi = lim(p.get("lowerLimit", {})), lim(p.get("upperLimit", {}))
        out.append({"name": p["name"], "type": AIP_TYPES.get(p["type"], f"type {p['type']}"), "code": p["type"],
                    "icao": p.get("icaoClass"), "lower_m": lo[0], "lower_ref": lo[1], "upper_m": hi[0], "upper_ref": hi[1],
                    "ring": [(c[1], c[0]) for c in g["coordinates"][0]]})
    return out


def point_in_ring(lat, lon, ring) -> np.ndarray:
    """Vectorised even-odd test; lat/lon arrays, ring = [(lat, lon), ...]."""
    lat, lon = np.asarray(lat), np.asarray(lon)
    inside = np.zeros(lat.shape, dtype=bool)
    ys, xs = np.array([p[0] for p in ring]), np.array([p[1] for p in ring])
    for k in range(len(ring) - 1):
        y1, x1, y2, x2 = ys[k], xs[k], ys[k + 1], xs[k + 1]
        cross = (y1 > lat) != (y2 > lat)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
        inside ^= cross & (lon < xint)
    return inside


def rasterise(feats: dict, s, w, n, e, cell_m: float = 20.0) -> dict:
    """Per-cell max obstacle height, daytime people, sensitive sites, trees, power lines, water, roads."""
    to = _xy(s, w)
    W_m, H_m = to(n, e)
    nx, ny = max(1, int(W_m / cell_m) + 1), max(1, int(H_m / cell_m) + 1)
    hmax = np.zeros((ny, nx), np.float32)
    people = np.zeros((ny, nx), np.float32)
    sensitive = np.zeros((ny, nx), bool)
    water = np.zeros((ny, nx), bool)
    green = np.zeros((ny, nx), bool)
    road = np.zeros((ny, nx), np.uint8)   # 0 none, 1 footway/path, 2 minor road, 3 major road
    trees = np.zeros((ny, nx), np.float32)
    power = np.zeros((ny, nx), bool)
    gy, gx = np.mgrid[0:ny, 0:nx]
    clat = s + (gy + 0.5) * cell_m / M_PER_DEG
    clon = w + (gx + 0.5) * cell_m / (M_PER_DEG * math.cos(math.radians(s)))

    def poly_mask(pts):
        la = [p[0] for p in pts]
        lo = [p[1] for p in pts]
        x0, y0 = to(min(la), min(lo))
        x1, y1 = to(max(la), max(lo))
        i0, i1 = max(0, int(y0 / cell_m)), min(ny, int(y1 / cell_m) + 1)
        j0, j1 = max(0, int(x0 / cell_m)), min(nx, int(x1 / cell_m) + 1)
        if i0 >= i1 or j0 >= j1:
            return None
        sub = point_in_ring(clat[i0:i1, j0:j1], clon[i0:i1, j0:j1], pts if pts[0] == pts[-1] else pts + [pts[0]])
        if not sub.any():  # footprint smaller than a cell: mark its centroid cell
            cy, cx = int(((y0 + y1) / 2) / cell_m), int(((x0 + x1) / 2) / cell_m)
            if 0 <= cy < ny and 0 <= cx < nx:
                sub = np.zeros_like(sub)
                sub[min(cy - i0, sub.shape[0] - 1), min(cx - j0, sub.shape[1] - 1)] = True
        return (slice(i0, i1), slice(j0, j1)), sub

    def area_m2(pts):
        xy = [to(*p) for p in pts]
        return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]))) / 2

    for b in feats.get("buildings", []):
        r = poly_mask(b["pts"])
        if not r:
            continue
        sl, m = r
        hmax[sl] = np.where(m, np.maximum(hmax[sl], b["h"]), hmax[sl])
        levels = max(1.0, b["h"] / 4.0)
        occ = OCCUPANCY.get(b["type"], 1 / 25)
        ncell = max(int(m.sum()), 1)
        people[sl] += m * (area_m2(b["pts"]) * levels * occ / ncell)
        if b["type"] in SENSITIVE or (b.get("amenity") in SENSITIVE):
            sensitive[sl] |= m
    for kind, arr in (("water", water), ("green", green)):
        for f in feats.get(kind, []):
            if len(f["pts"]) > 2 and f["pts"][0] == f["pts"][-1]:
                r = poly_mask(f["pts"])
                if r:
                    arr[r[0]] |= r[1]

    def stamp(pts, fn):
        for (a1, o1), (a2, o2) in zip(pts, pts[1:]):
            x1, y1 = to(a1, o1)
            x2, y2 = to(a2, o2)
            k = max(1, int(math.hypot(x2 - x1, y2 - y1) / (cell_m / 2)))
            for t in np.linspace(0, 1, k + 1):
                j, i = int((x1 + t * (x2 - x1)) / cell_m), int((y1 + t * (y2 - y1)) / cell_m)
                if 0 <= i < ny and 0 <= j < nx:
                    fn(i, j)
    major = {"motorway", "trunk", "primary", "secondary", "tertiary"}
    foot = {"footway", "path", "pedestrian", "steps", "cycleway", "living_street", "service"}
    for rd in feats.get("roads", []):
        lvl = 3 if rd["type"] in major else (1 if rd["type"] in foot else 2)
        stamp(rd["pts"], lambda i, j, lvl=lvl: road.__setitem__((i, j), max(road[i, j], lvl)))
    for pl in feats.get("power", []):
        stamp(pl["pts"], lambda i, j: power.__setitem__((i, j), True))
    for la, lo in feats.get("trees", []):
        x, y = to(la, lo)
        i, j = int(y / cell_m), int(x / cell_m)
        if 0 <= i < ny and 0 <= j < nx:
            trees[i, j] += 1
            hmax[i, j] = max(hmax[i, j], 12.0)
    # outdoor pedestrians: footways and squares near busy buildings
    outdoor = np.where(road == 1, 0.08, np.where(road > 0, 0.03, 0.0)) * cell_m ** 2 / 100
    return {"cell_m": cell_m, "nx": nx, "ny": ny, "s": s, "w": w, "n": n, "e": e, "hmax": hmax, "people": people,
            "outdoor": outdoor.astype(np.float32), "sensitive": sensitive, "water": water, "green": green,
            "road": road, "trees": trees, "power": power}
