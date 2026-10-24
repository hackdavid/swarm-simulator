// Mission-corridor map: OSM buildings / roads / water, openAIP airspace, the route coloured by risk or live failure heat.
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const HB = [[15, '#16223a'], [40, '#1d3557'], [90, '#255d8f'], [150, '#5f6fe0'], [1e9, '#d94f8c']];
const lerp = (a, b, t) => a + (b - a) * t;
export const riskColor = (t) => { t = Math.max(0, Math.min(1, t)); const s = [[59, 242, 138], [255, 176, 32], [255, 59, 107]];
  const k = t < 0.5 ? 0 : 1, u = t < 0.5 ? t * 2 : (t - 0.5) * 2; return `rgb(${s[k].map((v, i) => Math.round(lerp(v, s[k + 1][i], u))).join(',')})`; };

export class MapView {
  constructor(canvas, { interactive = true, mini = false } = {}) {
    this.c = canvas; this.ctx = canvas.getContext('2d'); this.mini = mini; this.cam = { z: 1, x: 0, y: 0 }; this.heat = null;
    if (interactive) this.bind();
    const loop = (t) => { this.draw(t); requestAnimationFrame(loop); }; requestAnimationFrame(loop);
  }
  bind() {
    let d = null;
    this.c.addEventListener('wheel', (e) => { e.preventDefault(); const r = this.c.getBoundingClientRect(), z = Math.max(0.5, Math.min(40, this.cam.z * Math.exp(-e.deltaY * 0.0015)));
      const mx = e.clientX - r.left - r.width / 2, my = e.clientY - r.top - r.height / 2, k = z / this.cam.z;
      this.cam.x = mx - (mx - this.cam.x) * k; this.cam.y = my - (my - this.cam.y) * k; this.cam.z = z; }, { passive: false });
    this.c.addEventListener('mousedown', (e) => { d = { x: e.clientX, y: e.clientY, cx: this.cam.x, cy: this.cam.y }; });
    addEventListener('mousemove', (e) => { if (d) { this.cam.x = d.cx + e.clientX - d.x; this.cam.y = d.cy + e.clientY - d.y; } });
    addEventListener('mouseup', () => { d = null; });
  }
  set(r) {
    this.r = r; this.heat = null; this.cam = { z: 1, x: 0, y: 0 };
    const la = r.path.map(p => p[0]), lo = r.path.map(p => p[1]);
    this.lat0 = (Math.min(...la) + Math.max(...la)) / 2; this.lon0 = (Math.min(...lo) + Math.max(...lo)) / 2; this.kx = 111320 * Math.cos(this.lat0 * Math.PI / 180);
    const P = (p) => [(p[1] - this.lon0) * this.kx, -(p[0] - this.lat0) * 111320];
    const pts = r.path.map(P), xs = pts.map(p => p[0]), ys = pts.map(p => p[1]), m = 260;
    this.bb = [Math.min(...xs) - m, Math.min(...ys) - m, Math.max(...xs) + m, Math.max(...ys) + m];
    const poly = (ring, close = true) => { const p = new Path2D(); ring.forEach((q, i) => { const [x, y] = P(q); i ? p.lineTo(x, y) : p.moveTo(x, y); }); if (close) p.closePath(); return p; };
    this.water = new Path2D(); r.water.forEach(w => this.water.addPath(poly(w)));
    this.green = new Path2D(); r.green.forEach(g => this.green.addPath(poly(g)));
    this.roads = new Path2D(); this.foot = new Path2D();
    r.roads.forEach(([t, pts]) => ((t === 'footway' || t === 'path' || t === 'pedestrian') ? this.foot : this.roads).addPath(poly(pts, false)));
    this.bld = HB.map(() => new Path2D()); this.tall = new Path2D();
    const lim = r.alt_m - 10;
    r.buildings.forEach(([h, ring]) => { const p = poly(ring); this.bld[HB.findIndex(b => h < b[0])].addPath(p); if (r.alt_m > 5 && h > lim) this.tall.addPath(p); });
    this.air = r.airspace.map(z => ({ ...z, p: poly(z.ring) }));
    this.fence = (r.geofence || []).map(g => poly(g));
    // split path into segments by distance
    const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    this.pts = pts; this.cum = cum; this.total = cum[cum.length - 1];
    const sc = r.length_m / Math.max(this.total, 1);
    this.segs = r.segments.map(s => { const p = new Path2D(); let first = true;
      const a = s.from_m / sc, b = s.to_m / sc;
      for (let i = 0; i < pts.length; i++) { if (cum[i] < a && (i + 1 >= pts.length || cum[i + 1] < a)) continue; if (cum[i] > b) { const q = this.at(b); p.lineTo(q[0], q[1]); break; }
        if (first) { const q = this.at(Math.max(a, 0)); p.moveTo(q[0], q[1]); first = false; } p.lineTo(pts[i][0], pts[i][1]); }
      return { ...s, p }; });
  }
  at(d) { const c = this.cum, p = this.pts; let i = 1; while (i < c.length - 1 && c[i] < d) i++; const t = (d - c[i - 1]) / Math.max(c[i] - c[i - 1], 1e-6);
    return [lerp(p[i - 1][0], p[i][0], Math.min(1, t)), lerp(p[i - 1][1], p[i][1], Math.min(1, t))]; }
  setHeat(fail, flights, mode) { this.heat = { fail, flights, mode }; }
  segRisk(s, i) { if (this.heat && this.heat.flights) { const f = this.heat.fail, mx = Math.max(...f), mn = Math.min(...f); return mx > mn ? (f[i] - mn) / (mx - mn) : 0; } return (s.igrc - 2) / 6; }
  draw(t) {
    const c = this.c, ctx = this.ctx, dpr = devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
    if (!W || !H) return; if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = '#060a14'; ctx.fillRect(0, 0, W, H);
    if (!this.r) return;
    const [x0, y0, x1, y1] = this.bb, VW = this.mini ? W : W - 400, s = Math.min(VW / (x1 - x0), H / (y1 - y0)) * this.cam.z;
    const tx = VW / 2 + this.cam.x - s * (x0 + x1) / 2, ty = H / 2 + this.cam.y - s * (y0 + y1) / 2;
    ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * tx, dpr * ty); const px = 1 / s;
    ctx.fillStyle = 'rgba(40,110,190,.32)'; ctx.fill(this.water, 'evenodd');
    ctx.fillStyle = 'rgba(40,140,80,.18)'; ctx.fill(this.green);
    ctx.lineCap = ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(140,160,200,.20)'; ctx.lineWidth = 1.6 * px; ctx.stroke(this.roads);
    ctx.strokeStyle = 'rgba(140,200,180,.16)'; ctx.lineWidth = 0.9 * px; ctx.stroke(this.foot);
    this.bld.forEach((p, i) => { ctx.fillStyle = HB[i][1]; ctx.fill(p); });
    if (this.r.alt_m > 5) { ctx.strokeStyle = `rgba(255,59,107,${0.55 + 0.35 * Math.sin(t / 300)})`; ctx.lineWidth = 1.6 * px; ctx.stroke(this.tall); }
    for (const z of this.air) { const col = z.type === 'Restricted' || z.type === 'Prohibited' || z.type === 'Danger' ? '255,59,107' : '255,176,32';
      ctx.fillStyle = `rgba(${col},.045)`; ctx.fill(z.p); ctx.setLineDash([8 * px, 6 * px]); ctx.strokeStyle = `rgba(${col},.85)`; ctx.lineWidth = 1.8 * px; ctx.stroke(z.p); ctx.setLineDash([]); }
    for (const f of this.fence) { ctx.strokeStyle = 'rgba(76,242,198,.8)'; ctx.lineWidth = 1.5 * px; ctx.stroke(f); }
    // corridor buffer + route
    ctx.strokeStyle = 'rgba(76,242,198,.07)'; ctx.lineWidth = 2 * Math.max(this.r.alt_m, 30); this.segs.forEach(sg => ctx.stroke(sg.p));
    this.segs.forEach((sg, i) => { const col = riskColor(this.segRisk(sg, i)); ctx.shadowColor = col; ctx.shadowBlur = 12; ctx.strokeStyle = col; ctx.lineWidth = (this.mini ? 3 : 5) * px; ctx.stroke(sg.p); });
    ctx.shadowBlur = 0;
    // waypoints + moving vehicle
    const P = (p) => [(p[1] - this.lon0) * this.kx, -(p[0] - this.lat0) * 111320];
    const st = P(this.r.path[0]); ctx.fillStyle = '#4cf2c6'; ctx.beginPath(); ctx.arc(st[0], st[1], 7 * px, 0, 7); ctx.fill();
    const en = P(this.r.path[Math.floor((this.r.path.length - 1) / (this.r.return ? 2 : 1))]); ctx.fillStyle = '#7b8cff'; ctx.beginPath(); ctx.arc(en[0], en[1], 7 * px, 0, 7); ctx.fill();
    const u = ((t / 1000) % 14) / 14, q = this.at(u * this.total);
    for (let k = 1; k < 14; k++) { const qq = this.at(Math.max(0, (u - k * 0.004)) * this.total); ctx.fillStyle = `rgba(255,255,255,${0.35 - k * 0.025})`; ctx.beginPath(); ctx.arc(qq[0], qq[1], (4 - k * 0.2) * px, 0, 7); ctx.fill(); }
    ctx.fillStyle = '#fff'; ctx.shadowColor = '#4cf2c6'; ctx.shadowBlur = 18; ctx.beginPath(); ctx.arc(q[0], q[1], 5.5 * px, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!this.mini) {
      ctx.font = '600 11px Inter'; ctx.textAlign = 'left';
      ctx.fillStyle = '#4cf2c6'; ctx.fillText('PAD / HOME', tx + s * st[0] + 10, ty + s * st[1] - 8);
      ctx.fillStyle = '#9aa8ff'; ctx.fillText(this.r.return ? 'DROP-OFF · turn' : 'END', tx + s * en[0] + 10, ty + s * en[1] - 8);
      const m = 500, L = m * s; ctx.strokeStyle = '#8796b0'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(20, H - 24); ctx.lineTo(20 + L, H - 24); ctx.stroke();
      ctx.fillStyle = '#8796b0'; ctx.font = '11px JetBrains Mono'; ctx.fillText('500 m', 20, H - 30);
      ctx.fillText('N ↑', W - 40, 26);
      ctx.fillStyle = '#61708c'; ctx.font = '10px Inter'; ctx.textAlign = 'right';
      ctx.fillText('© OpenStreetMap contributors (ODbL) · Copernicus DEM GLO-30 · openAIP', W - 12, H - 10);
    }
  }
  panel(el) {
    const r = this.r, sg = r.segments, n = (v) => Math.round(v).toLocaleString();
    const minClr = Math.min(...sg.map(s => s.clearance_m)), maxObs = Math.max(...sg.map(s => s.max_obstacle_m)), nlos = sg.reduce((a, s) => a + s.nlos * s.length_m, 0) / r.length_m;
    const pmax = Math.max(...sg.map(s => s.people_per_km2)), igrc = Math.max(...sg.map(s => s.igrc)), cross = sg.reduce((a, s) => a + s.crossings, 0), slope = Math.max(...sg.map(s => s.slope_deg));
    const drone = r.alt_m > 5;
    const kv = drone ? [['Cruise altitude', `${r.alt_m} m AGL`], ['Min obstacle clearance', minClr >= 149 ? '> 150 m' : `${minClr.toFixed(0)} m`], ['Tallest structure in corridor', `${maxObs.toFixed(0)} m`],
      ['Radio NLOS share', `${(100 * nlos).toFixed(0)}% of route`]] : [['Crossings on route', cross], ['Max grade (DEM)', `${slope.toFixed(1)}°`], ['Tallest building beside path', `${maxObs.toFixed(0)} m`]];
    kv.push(['Peak population proxy', `${n(pmax)} /km²`], ['Max intrinsic GRC (SORA 2.5 table)', `<b style="color:${igrc >= 7 ? '#ff3b6b' : igrc >= 5 ? '#ffb020' : '#3bf28a'}">${igrc}</b>`]);
    const top = this.heat && this.heat.flights ? sg.map((s, i) => [s, this.heat.fail[i]]).sort((a, b) => b[1] - a[1]).slice(0, 5) : null;
    el.innerHTML = `<h3>Mission corridor</h3><div class="rt-name">${esc(r.name)}</div><div class="rt-desc">${esc(r.desc)}</div>
      <div class="rt-kpis"><div><b>${(r.length_m / 1000).toFixed(2)} km</b><span>${r.return ? 'out & back' : 'one way'}</span></div><div><b>${sg.length}</b><span>segments</span></div><div><b>${n(r.buildings.length)}</b><span>OSM buildings</span></div></div>
      <div class="rt-src">${esc(r.routed)}</div>
      <div class="kv">${kv.map(([a, b]) => `<span>${a}</span><b>${b}</b>`).join('')}</div>
      <h3 style="margin-top:14px">Airspace crossed at ${drone ? r.alt_m + ' m' : 'ground level'}</h3>
      ${r.airspace.length ? r.airspace.map(z => `<div class="az ${z.type === 'Restricted' ? 'bad' : 'warn'}"><b>${esc(z.name)}</b><span>${esc(z.type)} · ${z.lower_m ? n(z.lower_m) + ' m' : 'SFC'}–${n(z.upper_m)} m · ${(100 * z.frac).toFixed(0)}% of route</span></div>`).join('') : '<div class="rt-desc">none found</div>'}
      ${r.airspace.length && drone ? `<div class="rt-warn">Route needs airspace permission (e.g. ATC / FRZ authorisation) before any real flight.</div>` : ''}
      ${top ? `<h3 style="margin-top:14px">Hottest segments (live)</h3>${top.map(([s, f]) => `<div class="lg"><i style="background:${riskColor(f / Math.max(top[0][1], 1))}"></i>#${s.i} · ${s.from_m}–${s.to_m} m<span class="q">${n(f)} fails</span></div>`).join('')}` : ''}
      <div class="rt-legend"><span><i style="background:#3bf28a"></i>low</span><span><i style="background:#ffb020"></i>medium</span><span><i style="background:#ff3b6b"></i>high ${this.heat ? 'failure density' : 'ground risk'}</span>${drone ? '<span><i style="background:transparent;border:1.5px solid #ff3b6b"></i>taller than cruise−10 m</span>' : ''}</div>
      <div class="rt-foot">Population is a proxy (OSM building floor area × occupancy), terrain is a surface model (DSM). Engineering evidence only — not an authorisation or a certified SORA.</div>`;
  }
}
