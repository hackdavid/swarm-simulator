// 3D cell replay: the route corridor as a deck.gl city (OSM buildings, airspace, corridor) with the cell's 64 Monte-Carlo
// trajectories, that hour's wind / rain / snow / fog / daylight, and the failure moment.
const D = window.deck;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const HC = (h) => h < 15 ? [38, 54, 86] : h < 40 ? [46, 78, 124] : h < 90 ? [58, 108, 168] : h < 150 ? [104, 116, 226] : [214, 88, 150];
const L = (p) => [p[1], p[0]];
const MAT = { ambient: 0.4, diffuse: 0.65, shininess: 40, specularColor: [70, 80, 100] };

export class City3D {
  constructor(root) {
    this.root = root; this.el = root.querySelector('#c3-deck'); this.chart = root.querySelector('#c3-chart'); this.hudEl = root.querySelector('#c3-hud');
    this.fog = root.querySelector('#c3-fog'); this.cam = 'chase'; this.rate = 1; this.play = true; this.k = 0; this.t = 0; this.bear = 0;
  }
  async open(rid, x, y, route, at) {
    this.root.style.setProperty('--cx', `${at?.[0] ?? 70}%`); this.root.style.setProperty('--cy', `${at?.[1] ?? 40}%`);
    this.root.classList.add('show', 'dive'); setTimeout(() => this.root.classList.remove('dive'), 1300);
    this.hudEl.innerHTML = '<h3>3D cell replay</h3><div class="rt-desc">Replaying 64 Monte-Carlo trials…</div>';
    const r = await fetch(`/api/runs/${rid}/replay?x=${x}&y=${y}`); if (!r.ok) { this.hudEl.innerHTML += `<div class="rt-warn">${esc((await r.json()).detail)}</div>`; return; }
    this.R = await r.json(); this.drone = this.R.platform === 'drone';
    if (route !== this.route) { this.route = route; this.prep(route); }
    this.k = Math.max(0, this.R.trials.findIndex(t => !t.pass)); this.t = 0; this.end = this.R.T;
    this.particles(); this.sky(); this.hud();
    const target = this.drone ? { ...this.c, zoom: 15.2, pitch: 58, bearing: -25 } : { ...this.c, zoom: 16.2, pitch: 55, bearing: -20 };
    const fx = new D.LightingEffect({ amb: new D.AmbientLight({ color: [255, 255, 255], intensity: this.R.night ? 0.55 : 1.0 }),
      sun: new D.DirectionalLight({ color: this.R.night ? [120, 140, 200] : [255, 244, 225], intensity: this.R.night ? 0.5 : 2.2, direction: [-2, -6, -3] }) });
    if (!this.deck) {
      this.deck = new D.Deck({ parent: this.el, controller: true, initialViewState: { ...this.c, zoom: 12, pitch: 0, bearing: 0 }, effects: [fx], layers: [],
        onViewStateChange: ({ viewState }) => { this.vs = viewState; },
        onInteractionStateChange: (s) => { if (s.isDragging && this.cam !== 'free') this.setCam('free'); } });
      requestAnimationFrame(this.loop.bind(this));
    } else this.deck.setProps({ effects: [fx], initialViewState: { ...this.c, zoom: 12, pitch: 0, bearing: 0 } });
    this.camHold = performance.now() + 2800; this.cam = 'chase';
    setTimeout(() => this.deck.setProps({ initialViewState: { ...target, transitionDuration: 2600, transitionInterpolator: new D.FlyToInterpolator() } }), 60);
    this.last = performance.now();
  }
  close() { this.root.classList.remove('show'); }
  prep(route) {
    this.alt = route.alt_m;
    const la = route.path.map(p => p[0]), lo = route.path.map(p => p[1]);
    this.c = { longitude: (Math.min(...lo) + Math.max(...lo)) / 2, latitude: (Math.min(...la) + Math.max(...la)) / 2 };
    this.kx = 111320 * Math.cos(this.c.latitude * Math.PI / 180);
    this.ext = Math.max((Math.max(...lo) - Math.min(...lo)) * this.kx, (Math.max(...la) - Math.min(...la)) * 111320) / 2 + 350;
    const drone = route.alt_m > 5, lim = route.alt_m - 10;
    const bld = route.buildings.map(([h, ring]) => ({ h, poly: ring.map(L) }));
    const air = route.airspace.map(z => ({ ...z, poly: z.ring.map(L), col: z.type === 'Restricted' ? [255, 59, 107] : [255, 176, 32] }));
    this.air = new D.PolygonLayer({ id: 'air', data: air, extruded: true, wireframe: true, getPolygon: d => d.poly, getElevation: d => Math.min(d.upper_m, 600),
      getFillColor: d => [...d.col, 12], getLineColor: d => [...d.col, 70], material: false, parameters: { depthWriteEnabled: false } });
    this.plan = route.path.map(p => [p[1], p[0], drone ? route.alt_m : 0.6]);
    this.static = [
      new D.SolidPolygonLayer({ id: 'ground', data: [{ p: [[this.c.longitude - 0.08, this.c.latitude - 0.05], [this.c.longitude + 0.08, this.c.latitude - 0.05], [this.c.longitude + 0.08, this.c.latitude + 0.05], [this.c.longitude - 0.08, this.c.latitude + 0.05]] }], getPolygon: d => d.p, getFillColor: [10, 15, 26] }),
      new D.SolidPolygonLayer({ id: 'water', data: route.water.map(r => r.map(L)), getPolygon: d => d, getFillColor: [22, 58, 104] }),
      new D.SolidPolygonLayer({ id: 'green', data: route.green.map(r => r.map(L)), getPolygon: d => d, getFillColor: [20, 52, 38] }),
      new D.PathLayer({ id: 'roads', data: route.roads, getPath: d => d[1].map(L), getColor: d => d[0] === 'footway' ? [90, 130, 120, 120] : [96, 110, 140, 150], getWidth: d => d[0] === 'footway' ? 2 : 6, widthUnits: 'meters', widthMinPixels: 0.5 }),
      new D.PolygonLayer({ id: 'bld', data: bld, extruded: true, getPolygon: d => d.poly, getElevation: d => d.h, material: MAT, stroked: false,
        getFillColor: d => (drone && d.h > lim) ? [255, 70, 110] : HC(d.h) }),
      new D.PathLayer({ id: 'corridor', data: [{ p: this.plan }], getPath: d => d.p, getColor: [76, 242, 198, 40], getWidth: 2 * (route.alt_m > 5 ? (this.R?.corridor_m || 30) : 3), widthUnits: 'meters', billboard: false }),
      new D.PathLayer({ id: 'plan', data: [{ p: this.plan }], getPath: d => d.p, getColor: [76, 242, 198, 200], widthMinPixels: 1.5 }),
    ];
  }
  particles() {
    const e = this.R.env, w = e.wind || 0, wd = (e.wdir ?? 240) * Math.PI / 180;
    this.wv = [-Math.sin(wd) * w, -Math.cos(wd) * w];
    const N = Math.round(300 + 60 * Math.min(w, 15)), top = this.drone ? this.alt + 80 : 40;
    this.wind = Array.from({ length: N }, () => ({ x: (Math.random() * 2 - 1) * this.ext, y: (Math.random() * 2 - 1) * this.ext, z: 5 + Math.random() * top, a: Math.random() }));
    const nr = Math.min(3000, Math.round((e.rain || 0) * 400)), ns = Math.min(3000, Math.round((e.snow || 0) * 900));
    this.rain = Array.from({ length: nr }, () => ({ x: (Math.random() * 2 - 1) * 450, y: (Math.random() * 2 - 1) * 450, z: Math.random() * (top + 60) }));
    this.snow = Array.from({ length: ns }, () => ({ x: (Math.random() * 2 - 1) * 450, y: (Math.random() * 2 - 1) * 450, z: Math.random() * (top + 60) }));
    this.top = top;
  }
  sky() {
    const h = this.R.hour, n = this.R.night, dusk = !n && (Math.abs(h - 6.5) < 1.5 || Math.abs(h - 18.5) < 1.5);
    this.root.style.background = n ? 'linear-gradient(#010208,#0a1222 60%,#111a2c)' : dusk ? 'linear-gradient(#1a1d3a,#6b4a63 55%,#d68b5c)' : 'linear-gradient(#123056,#3f6f9e 55%,#8cb2d4)';
    const vis = this.R.env.vis ?? 20; this.fog.style.opacity = Math.max(0, Math.min(0.85, (8 - vis) / 8 + (this.R.env.rain > 2 ? 0.15 : 0)));
  }
  pos(tr, t) {
    const ts = tr.t, p = tr.path; if (t <= ts[0]) return { p: p[0], i: 0 };
    let i = 1; while (i < ts.length && ts[i] < t) i++; if (i >= ts.length) return { p: p[p.length - 1], i: p.length - 1, done: true };
    const u = (t - ts[i - 1]) / Math.max(ts[i] - ts[i - 1], 1e-6);
    return { p: [0, 1, 2].map(j => p[i - 1][j] + (p[i][j] - p[i - 1][j]) * u), i };
  }
  setCam(c) { this.cam = c; this.root.querySelectorAll('[data-cam]').forEach(b => b.classList.toggle('on', b.dataset.cam === c));
    if (c === 'top') this.deck.setProps({ initialViewState: { ...this.c, zoom: this.drone ? 14.3 : 15.3, pitch: 0, bearing: 0, transitionDuration: 1200, transitionInterpolator: new D.FlyToInterpolator() } });
    if (c === 'orbit') this.bear = this.vs?.bearing || 0; }
  step(d) { const n = this.R.trials.length; this.k = (this.k + d + n) % n; this.t = 0; this.hud(); }
  nextFail() { const n = this.R.trials.length; for (let j = 1; j <= n; j++) { const k = (this.k + j) % n; if (!this.R.trials[k].pass) { this.k = k; break; } } this.t = 0; this.hud(); }
  hud() {
    const R = this.R, e = R.env, tr = R.trials[this.k];
    const kv = [['Wind', `${(e.wind ?? 0).toFixed(1)} m/s <span class="warr" style="transform:rotate(${(e.wdir ?? 240) + 180}deg)">↑</span> from ${Math.round(e.wdir ?? 240)}°`], ['Gust', `${(e.gust ?? 0).toFixed(1)} m/s`],
      ['Rain', `${(e.rain ?? 0).toFixed(1)} mm/h`], ['Snow', `${(e.snow ?? 0).toFixed(1)} cm/h`], ['Visibility', `${(e.vis ?? 0).toFixed(1)} km`], ['Temp', `${(e.temp ?? 0).toFixed(1)} °C`], ['Light', R.night ? 'night' : 'daylight']];
    this.hudEl.innerHTML = `<button class="close" id="c3-x">✕</button><h3>3D cell replay · cell (${R.x}, ${R.y})</h3>
      <div class="insp-when">Departure ${esc(R.when)}</div><div class="rt-name" style="font-size:15px">${esc(this.route.name)}</div>
      <div class="c3-pass"><b style="color:${R.passed / 64 > 0.9 ? '#3bf28a' : R.passed / 64 > 0.6 ? '#ffb020' : '#ff3b6b'}">${Math.round(100 * R.passed / 64)}%</b> ${R.passed}/64 trials survived</div>
      <div class="kv">${kv.map(([a, b]) => `<span>${a}</span><b>${b}</b>`).join('')}</div>
      <div class="c3-trial ${tr.pass ? 'ok' : 'bad'}">Trial ${this.k + 1}/64 · ${tr.pass ? 'PASS' : 'FAIL · ' + esc(tr.name) + ` at ${(tr.fail_d / 1000).toFixed(2)} km`}</div>
      <div class="c3-btns"><button class="chip" id="c3-prev">◀</button><button class="chip" id="c3-play">${this.play ? '❚❚' : '▶'}</button><button class="chip" id="c3-next">▶▶</button><button class="chip" id="c3-fail">next failure</button><button class="chip" id="c3-rate">${this.rate}×</button></div>
      <div class="c3-btns">${['chase', 'orbit', 'top', 'free'].map(c => `<button class="chip ${c === this.cam ? 'on' : ''}" data-cam="${c}">${c}</button>`).join('')}</div>
      <div class="rt-legend"><span><i style="background:#3bf28a"></i>trial survived</span><span><i style="background:#ff3b6b"></i>trial failed</span><span><i style="background:#4cf2c6"></i>planned route & corridor</span>${this.drone ? '<span><i style="background:#ff466e"></i>building above cruise−10 m</span>' : ''}</div>
      <div class="rt-foot">Planned route: straight legs at a fixed cruise altitude (no obstacle-avoidance planner yet). Trajectories replay the reduced-order model: lateral drift from crosswind and gusts, failure placed on its route segment. Not a flight-dynamics simulation.</div>`;
    const $ = (id) => this.hudEl.querySelector(id);
    $('#c3-x').onclick = () => this.close(); $('#c3-prev').onclick = () => this.step(-1); $('#c3-next').onclick = () => this.step(1); $('#c3-fail').onclick = () => this.nextFail();
    $('#c3-play').onclick = () => { this.play = !this.play; this.hud(); }; $('#c3-rate').onclick = () => { this.rate = this.rate >= 4 ? 0.5 : this.rate * 2; this.hud(); };
    this.hudEl.querySelectorAll('[data-cam]').forEach(b => b.onclick = () => this.setCam(b.dataset.cam));
  }
  ll(x, y) { return [this.c.longitude + x / this.kx, this.c.latitude + y / 111320]; }
  loop(now) {
    requestAnimationFrame(this.loop.bind(this));
    if (!this.root.classList.contains('show') || !this.R) return;
    const dt = Math.min(0.05, (now - this.last) / 1000); this.last = now;
    const R = this.R, tr = R.trials[this.k], sp = R.T / 32 * this.rate;
    if (this.play && now > this.camHold - 600) { this.t += dt * sp; const endT = tr.t[tr.t.length - 1] + (tr.pass ? 0 : 6 * sp / 6); if (this.t > endT + 2.5 * sp) { this.step(1); } }
    const P = this.pos(tr, this.t), d = P.p;
    // particles
    const vx = this.wv[0] * 7, vy = this.wv[1] * 7;
    for (const q of this.wind) { q.x += vx * dt; q.y += vy * dt; q.a += dt * 0.5;
      if (Math.abs(q.x) > this.ext || Math.abs(q.y) > this.ext || q.a > 1) { q.x = (Math.random() * 2 - 1) * this.ext; q.y = (Math.random() * 2 - 1) * this.ext; q.a = 0; } }
    const dc = [(d[0] - this.c.longitude) * this.kx, (d[1] - this.c.latitude) * 111320];
    for (const q of this.rain) { q.z -= 90 * dt; q.x += this.wv[0] * 2 * dt; q.y += this.wv[1] * 2 * dt; if (q.z < 0) { q.z = this.top + 60; q.x = (Math.random() * 2 - 1) * 450; q.y = (Math.random() * 2 - 1) * 450; } }
    for (const q of this.snow) { q.z -= 4 * dt; q.x += (this.wv[0] * 0.8 + Math.sin(now / 700 + q.y) * 0.6) * dt; q.y += this.wv[1] * 0.8 * dt; if (q.z < 0) { q.z = this.top + 60; q.x = (Math.random() * 2 - 1) * 450; q.y = (Math.random() * 2 - 1) * 450; } }
    const wl = 4 + Math.hypot(...this.wv) * 1.6;
    const windSeg = this.wind.map(q => { const [lo, la] = this.ll(q.x, q.y); const n = Math.hypot(...this.wv) || 1; return { s: [lo, la, q.z], e: [lo - this.wv[0] / n * wl / this.kx, la - this.wv[1] / n * wl / 111320, q.z], a: Math.sin(q.a * Math.PI) }; });
    const rainSeg = this.rain.map(q => { const [lo, la] = this.ll(dc[0] + q.x, dc[1] + q.y); return { s: [lo, la, q.z], e: [lo, la, q.z + 7] }; });
    const snowPts = this.snow.map(q => { const [lo, la] = this.ll(dc[0] + q.x, dc[1] + q.y); return [lo, la, q.z]; });
    const failed = !tr.pass && tr.fail_i != null && this.t >= tr.t[tr.fail_i], fp = !tr.pass && tr.fail_i != null ? tr.path[tr.fail_i] : null, pulse = (now / 600) % 1;
    const layers = [...this.static,
      new D.LineLayer({ id: 'wind', data: windSeg, getSourcePosition: q => q.s, getTargetPosition: q => q.e, getColor: q => [200, 230, 255, 140 * q.a], getWidth: 1.4 }),
      new D.PathLayer({ id: 'trials', data: R.trials, getPath: t => t.path, getColor: t => t.pass ? [59, 242, 138, 60] : [255, 59, 107, 110], widthMinPixels: 1 }),
      new D.TripsLayer({ id: 'trip', data: [tr], getPath: t => t.path, getTimestamps: t => t.t, getColor: tr.pass ? [255, 255, 255] : [255, 120, 150], widthMinPixels: 4, trailLength: R.T * 0.18, currentTime: this.t, fadeTrail: true, capRounded: true, jointRounded: true }),
      new D.LineLayer({ id: 'tether', data: [d], getSourcePosition: p => p, getTargetPosition: p => [p[0], p[1], 0], getColor: [255, 255, 255, 70], getWidth: 1 }),
      new D.ScatterplotLayer({ id: 'shadow', data: [d], getPosition: p => [p[0], p[1], 0.2], getRadius: 6, radiusMinPixels: 3, getFillColor: [0, 0, 0, 140] }),
      new D.ScatterplotLayer({ id: 'drone', data: [d], getPosition: p => p, getRadius: 5, radiusMinPixels: 6, getFillColor: failed ? [255, 59, 107] : [255, 255, 255], stroked: true, getLineColor: [76, 242, 198], lineWidthMinPixels: 2 }),
      new D.LineLayer({ id: 'rain', data: rainSeg, getSourcePosition: q => q.s, getTargetPosition: q => q.e, getColor: [170, 200, 255, 120], getWidth: 1 }),
      new D.ScatterplotLayer({ id: 'snow', data: snowPts, getPosition: p => p, getRadius: 0.8, radiusMinPixels: 1.5, getFillColor: [255, 255, 255, 220] }),
    ];
    layers.push(this.air);
    if (failed) layers.push(
      new D.ScatterplotLayer({ id: 'fail', data: [fp], getPosition: p => p, getRadius: 10 + 50 * pulse, filled: false, stroked: true, getLineColor: [255, 59, 107, 255 * (1 - pulse)], lineWidthMinPixels: 3, billboard: true }),
      new D.TextLayer({ id: 'failtxt', data: [fp], getPosition: p => [p[0], p[1], p[2] + 25], getText: () => `${tr.name} · ${(tr.fail_d / 1000).toFixed(2)} km`, getSize: 15, getColor: [255, 255, 255], background: true, getBackgroundColor: [120, 10, 40, 220], backgroundPadding: [8, 4], fontFamily: 'Inter, sans-serif', fontWeight: 700 }));
    this.deck.setProps({ layers });
    if (now > this.camHold) {
      if (this.cam === 'chase') { const q = tr.path[Math.min(P.i + 2, tr.path.length - 1)], b = Math.atan2((q[0] - d[0]) * this.kx, (q[1] - d[1]) * 111320) * 180 / Math.PI;
        if (Math.hypot(q[0] - d[0], q[1] - d[1]) > 1e-7) { let db = ((b - this.bear + 540) % 360) - 180; this.bear += db * Math.min(1, dt * 1.5); }
        this.deck.setProps({ initialViewState: { longitude: d[0], latitude: d[1], zoom: this.drone ? 16.9 : 18.2, pitch: 64, bearing: this.bear, position: [0, 0, d[2]] } }); }
      if (this.cam === 'orbit') { this.bear += dt * 6; this.deck.setProps({ initialViewState: { ...this.c, zoom: this.drone ? 14.9 : 15.9, pitch: 60, bearing: this.bear } }); }
    }
    this.drawChart(tr, P);
  }
  drawChart(tr, P) {
    const c = this.chart, ctx = c.getContext('2d'), dpr = devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
    if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
    const R = this.R, D0 = R.d[R.d.length - 1] || 1, l = 56, r = W - 16, top = 22, bot = H - 22;
    const ymax = this.drone ? Math.max(R.alt_m * 1.6, ...R.obst.map(v => Math.min(v, 300))) : Math.max(5, ...R.people.map(v => v / 1e4));
    const X = (dv) => l + (r - l) * dv / D0, Y = (v) => bot - (bot - top) * Math.min(v, ymax) / ymax;
    R.nlos.forEach((v, i) => { if (v > 0.5 && i) { ctx.fillStyle = 'rgba(255,176,32,.18)'; ctx.fillRect(X(R.d[i - 1]), top, X(R.d[i]) - X(R.d[i - 1]) + 1, bot - top); } });
    ctx.fillStyle = 'rgba(255,59,107,.35)'; ctx.beginPath(); ctx.moveTo(X(0), bot);
    const ob = this.drone ? R.obst : R.people.map(v => v / 1e4); R.d.forEach((dv, i) => ctx.lineTo(X(dv), Y(ob[i]))); ctx.lineTo(X(D0), bot); ctx.fill();
    if (this.drone) { ctx.strokeStyle = 'rgba(76,242,198,.6)'; ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.moveTo(X(0), Y(R.alt_m)); ctx.lineTo(X(D0), Y(R.alt_m)); ctx.stroke(); ctx.setLineDash([]);
      ctx.strokeStyle = tr.pass ? '#fff' : '#ff7896'; ctx.lineWidth = 2; ctx.beginPath(); tr.path.forEach((p, i) => { const dv = i < R.d.length ? R.d[i] : R.d[tr.fail_i]; i ? ctx.lineTo(X(dv), Y(p[2])) : ctx.moveTo(X(dv), Y(p[2])); }); ctx.stroke(); ctx.lineWidth = 1; }
    if (!tr.pass && tr.fail_i != null) { ctx.fillStyle = '#ff3b6b'; ctx.beginPath(); ctx.arc(X(tr.fail_d), Y(this.drone ? tr.path[tr.fail_i][2] : ob[tr.fail_i]), 5, 0, 7); ctx.fill(); }
    const dnow = P.i < R.d.length ? R.d[Math.max(0, P.i - 1)] + (R.d[P.i] - R.d[Math.max(0, P.i - 1)]) * 0.5 : D0;
    ctx.strokeStyle = '#4cf2c6'; ctx.beginPath(); ctx.moveTo(X(dnow), top); ctx.lineTo(X(dnow), bot); ctx.stroke();
    ctx.font = '600 10.5px JetBrains Mono'; ctx.fillStyle = '#8796b0'; ctx.textAlign = 'left';
    ctx.fillText(this.drone ? `ALTITUDE (white) vs CRUISE ${R.alt_m} m (dashed) · TALLEST OBSTACLE NEAR PATH (red) · RADIO NLOS (amber)` : 'POPULATION PROXY ×10k/km² (red) · STREET-LEVEL ROUTE', l, 14);
    ctx.textAlign = 'right'; ctx.fillText(`${Math.round(ymax)}${this.drone ? ' m' : ''}`, l - 6, top + 8); ctx.fillText('0', l - 6, bot);
    ctx.textAlign = 'center'; for (let k = 0; k <= 4; k++) ctx.fillText(`${(D0 * k / 4 / 1000).toFixed(1)} km`, X(D0 * k / 4), H - 6);
    ctx.textAlign = 'right'; ctx.fillStyle = '#cfe'; ctx.fillText(`t+${Math.floor(this.t / 60)}:${String(Math.floor(this.t % 60)).padStart(2, '0')}`, r, 14);
  }
}
