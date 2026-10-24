"""3D obstacle-avoiding route planner for drones.

A* over the 20 m corridor raster in (row, col, altitude-layer) space. Buildings are inflated by a lateral buffer and must
sit `vclear_m` below the layer to be overflown; restricted airspace is a soft no-fly (high cost, so the route leaves it when
a detour exists inside the corridor). The raw A* path is string-pulled into straight legs. Client waypoints are kept as
must-pass points (each leg is planned separately)."""
import heapq
import math

import numpy as np

M_PER_DEG = 111_320.0
MOVES = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


def _dilate(a, r):
    out = a.copy()
    ny, nx = a.shape
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            if di * di + dj * dj > r * r + r:
                continue
            sh = np.zeros_like(a)
            sh[max(0, di):ny + min(0, di), max(0, dj):nx + min(0, dj)] = a[max(0, -di):ny - max(0, di), max(0, -dj):nx - max(0, dj)]
            out = np.maximum(out, sh)
    return out


class Planner:
    def __init__(self, hmax, s, w, cell_m, alt, max_alt, nofly=None, lat_buf_m=30.0, vclear_m=20.0, layer_m=20.0):
        self.s, self.w, self.cm = s, w, cell_m
        self.kx = M_PER_DEG * math.cos(math.radians(s))
        self.ny, self.nx = hmax.shape
        top = max(alt, max_alt)
        self.alts = [alt] + [a for a in np.arange(alt + layer_m, top + 0.1, layer_m)]
        hd = _dilate(hmax.astype(np.float32), max(1, int(math.ceil(lat_buf_m / cell_m))))
        self.block = np.stack([hd > (a - vclear_m) for a in self.alts])
        self.hmax = hmax
        self.nofly = nofly if nofly is not None else np.zeros_like(hmax, bool)

    def cell(self, lat, lon):
        return (int(np.clip((lat - self.s) * M_PER_DEG / self.cm, 0, self.ny - 1)),
                int(np.clip((lon - self.w) * self.kx / self.cm, 0, self.nx - 1)))

    def ll(self, i, j):
        return (self.s + (i + 0.5) * self.cm / M_PER_DEG, self.w + (j + 0.5) * self.cm / self.kx)

    def _free(self, i, j, L, ends):
        return (i, j) in ends or not self.block[L, i, j]

    def leg(self, a, b):
        si, sj = self.cell(*a)
        gi, gj = self.cell(*b)
        ends = {(si, sj), (gi, gj)}
        NL = len(self.alts)
        climb = 3.0 * (self.alts[1] - self.alts[0]) if NL > 1 else 0
        h = lambda i, j: math.hypot(i - gi, j - gj) * self.cm
        start, goal = (si, sj, 0), (gi, gj, 0)
        g = {start: 0.0}
        prev = {}
        pq = [(h(si, sj), 0.0, start)]
        n = 0
        while pq:
            f, gc, u = heapq.heappop(pq)
            if u == goal:
                break
            if gc > g.get(u, 1e18):
                continue
            n += 1
            if n > 600_000:
                return None
            i, j, L = u
            nb = [(i + di, j + dj, L, math.hypot(di, dj) * self.cm) for di, dj in MOVES]
            if L + 1 < NL:
                nb.append((i, j, L + 1, climb))
            if L > 0:
                nb.append((i, j, L - 1, climb * 0.3))
            for vi, vj, vL, c in nb:
                if not (0 <= vi < self.ny and 0 <= vj < self.nx) or not self._free(vi, vj, vL, ends):
                    continue
                if c and vL == L:
                    c *= (1 + 0.004 * (self.alts[L] - self.alts[0])) * (15.0 if self.nofly[vi, vj] else 1.0)
                v = (vi, vj, vL)
                ng = gc + c
                if ng < g.get(v, 1e18):
                    g[v], prev[v] = ng, u
                    heapq.heappush(pq, (ng + 1.15 * h(vi, vj), ng, v))
        if goal not in prev and goal != start:
            return None
        path, u = [goal], goal
        while u != start:
            u = prev[u]
            path.append(u)
        return self._smooth(path[::-1], ends)

    def _line(self, p, q):
        n = int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) * 2 + 2
        return np.linspace(p[0], q[0], n).round().astype(int), np.linspace(p[1], q[1], n).round().astype(int)

    def _smooth(self, path, ends):
        out, k = [path[0]], 0
        while k < len(path) - 1:
            best = k + 1
            for m in range(len(path) - 1, k + 1, -1):
                L = max(path[x][2] for x in range(k, m + 1))
                ii, jj = self._line(path[k], path[m])
                ok = all((a, b) in ends or not self.block[L, a, b] for a, b in zip(ii, jj))
                if ok and self.nofly[ii, jj].sum() <= sum(self.nofly[path[x][0], path[x][1]] for x in range(k, m + 1)) * 2 + 1:
                    best = m
                    if path[m][2] != L:
                        out.append((path[m][0], path[m][1], L))
                    break
            out.append(path[best])
            k = best
        return out

    def plan(self, wps):
        verts, ok = [], True
        for a, b in zip(wps, wps[1:]):
            r = self.leg(a, b)
            if r is None:
                ok = False
                r = [(*self.cell(*a), 0), (*self.cell(*b), 0)]
            pts = [(*self.ll(i, j), float(self.alts[L])) for i, j, L in r]
            pts[0] = (a[0], a[1], pts[0][2])
            pts[-1] = (b[0], b[1], pts[-1][2])
            verts += pts if not verts else pts[1:]
        return verts, ok

    def line_stats(self, pts, alt_of):
        """Min lateral clearance (m) to inflated-free obstacles above alt-10 and count of tall cells crossed."""
        hits, nf, n = 0, 0, 0
        for (a1, o1, z1), (a2, o2, z2) in zip(pts, pts[1:]):
            p, q = self.cell(a1, o1), self.cell(a2, o2)
            ii, jj = self._line(p, q)
            z = alt_of(z1, z2)
            hits += int((self.hmax[ii, jj] > z - 10).sum())
            nf += int(self.nofly[ii, jj].sum())
            n += len(ii)
        return {"tall_cells_crossed": hits, "nofly_frac": round(nf / max(n, 1), 3)}
