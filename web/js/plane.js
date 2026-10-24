// Proving-ground plane: million-cell zoomable canvas fed by binary tiles.
import { drawCell } from './scenes.js';
import { esc } from './swarm.js';

const MAGIC = 0x50475244;
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

export class PlaneView {
  constructor() {
    this.c = document.getElementById('plane'); this.ctx = this.c.getContext('2d');
    this.mm = document.getElementById('minimap'); this.mctx = this.mm.getContext('2d');
    this.insp = document.getElementById('inspector'); this.left = document.getElementById('hud-left');
    this.view = 'outcome'; this.cam = { x: 512, y: 512, z: 0.5 }; this.S = 0; this.anim = null; this.sel = null; this.hover = null;
    this.bindInput(); requestAnimationFrame(this.frame.bind(this));
  }
  init(meta, platform, params) {
    const S = meta.size, N = S * S; this.meta = meta; this.S = S; this.K = meta.trials; this.platform = platform; this.params = params;
    this.cat = new Uint8Array(N); this.pass = new Uint8Array(N); this.dom = new Uint8Array(N); this.hot = new Uint8Array(N); this.tested = new Uint8Array(N);
    this.planes = meta.planes.map(p => ({ ...p, a: new Uint8Array(N) }));
    this.pidx = Object.fromEntries(this.planes.map((p, i) => [p.name, i]));
    this.catRGB = meta.categories.map(c => hex(c.color)); this.modeRGB = [[40, 200, 120], ...meta.modes.map(m => hex(m.color))];
    this.off = document.createElement('canvas'); this.off.width = S; this.off.height = S; this.octx = this.off.getContext('2d');
    this.img = this.octx.createImageData(S, S); this.img.data.fill(0); for (let i = 3; i < this.img.data.length; i += 4) this.img.data[i] = 255;
    this.octx.putImageData(this.img, 0, 0);
    this.prog = null; this.recent = []; this.fixes = []; this.tStart = performance.now(); this.sel = null; this.insp.classList.remove('show');
    document.getElementById('report').classList.remove('show'); document.getElementById('rep-open').style.display = 'none';
    this.fit(); this.renderLeft(); this.renderTop();
  }
  fit() { const W = this.c.clientWidth || innerWidth, H = this.c.clientHeight || innerHeight - 56; this.cam = { x: this.S / 2, y: this.S / 2, z: Math.min(W, H) / this.S * 0.86 }; }
  tile(buf) {
    const h = new Int32Array(buf, 0, 5); if (h[0] !== MAGIC || !this.S) return;
    const [, tx, ty, tw, th] = h, n = tw * th, S = this.S; let o = 20;
    const take = () => { const a = new Uint8Array(buf, o, n); o += n; return a; };
    const cat = take(), pass = take(), dom = take(), hot = take(), pl = this.planes.map(() => take());
    for (let j = 0; j < th; j++) { const row = (ty + j) * S + tx;
      this.cat.set(cat.subarray(j * tw, j * tw + tw), row); this.pass.set(pass.subarray(j * tw, j * tw + tw), row);
      this.dom.set(dom.subarray(j * tw, j * tw + tw), row); this.hot.set(hot.subarray(j * tw, j * tw + tw), row); this.tested.fill(1, row, row + tw);
      pl.forEach((a, k) => this.planes[k].a.set(a.subarray(j * tw, j * tw + tw), row)); }
    this.paint(tx, ty, tw, th); this.recent.push({ tx, ty, tw, th, t: performance.now() });
  }
  colour(i) {
    if (!this.tested[i]) return [4, 6, 12];
    const r = this.pass[i] / this.K, d = this.dom[i], c = this.catRGB[this.cat[i]];
    const tex = 0.75 + 0.25 * (this.planes[1].a[i] / 255);
    if (this.view === 'weather') return [c[0] * tex, c[1] * tex, c[2] * tex];
    if (this.view === 'failure') { if (r >= 0.8 || !d) return [10 + c[0] * 0.06, 14 + c[1] * 0.06, 24 + c[2] * 0.06]; const m = this.modeRGB[d], k = 0.45 + 0.55 * (1 - r); return [m[0] * k, m[1] * k, m[2] * k]; }
    const f = Math.min(1, (1 - r) * 1.7), m = d ? this.modeRGB[d] : this.modeRGB[0], g = [22, 170, 105];
    const b = 0.55 + 0.45 * tex;
    return [(g[0] + (m[0] - g[0]) * f) * b * 0.8 + c[0] * 0.12, (g[1] + (m[1] - g[1]) * f) * b * 0.8 + c[1] * 0.12, (g[2] + (m[2] - g[2]) * f) * b * 0.8 + c[2] * 0.12];
  }
  paint(x0 = 0, y0 = 0, w = this.S, h = this.S) {
    const S = this.S, d = this.img.data;
    for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) { const i = y * S + x, c = this.colour(i), p = i * 4; d[p] = c[0]; d[p + 1] = c[1]; d[p + 2] = c[2]; }
    this.octx.putImageData(this.img, 0, 0, x0, y0, w, h);
  }
  setView(v) { this.view = v; if (this.S) this.paint(); this.renderLeft(); }
  progress(p) { this.prog = p; this.renderTop(); if (!this._lt || performance.now() - this._lt > 500) { this._lt = performance.now(); this.renderLeft(); } }
  renderTop() {
    const p = this.prog || { tested: 0, total: this.S * this.S, flights: 0, flights_pass: 0 };
    const el = (performance.now() - this.tStart) / 1000, pr = p.flights ? 100 * p.flights_pass / p.flights : 0;
    const k = [[`${p.tested.toLocaleString()}<small> / ${(p.total / 1e6).toFixed(2)}M</small>`, 'environments tested'],
      [p.flights.toLocaleString(), `simulated ${this.platform === 'drone' ? 'flights' : 'missions'} (${this.K}/cell)`],
      [`<span style="color:${pr >= 80 ? '#3bf28a' : pr >= 60 ? '#ffb020' : '#ff3b6b'}">${pr.toFixed(1)}%</span>`, 'pass rate'],
      [`<span style="color:#ff3b6b">${(p.flights - p.flights_pass).toLocaleString()}</span>`, 'failures'],
      [this.doneAt ? (p.flights / this.doneAt).toLocaleString(undefined, { maximumFractionDigits: 0 }) : (p.flights / Math.max(el, 0.1)).toLocaleString(undefined, { maximumFractionDigits: 0 }), 'sims / second']];
    document.getElementById('hud-top').innerHTML = k.map(([a, b]) => `<div class="kpi"><b>${a}</b><span>${b}</span></div>`).join('');
  }
  renderLeft() {
    if (!this.meta) return; const p = this.prog, m = this.meta;
    const tabs = `<div class="modes-tabs">${[['outcome', 'Outcome'], ['weather', 'Weather'], ['failure', 'Failure mode']].map(([k, l]) => `<button data-v="${k}" class="${this.view === k ? 'on' : ''}">${l}</button>`).join('')}</div>`;
    let body = '';
    if (this.view === 'weather') {
      body = `<h3>Environment mix · pass rate</h3>` + m.categories.map((c, i) => { const n = p ? p.cat_cells[i] : m.cat_counts[i], pr = p && p.cat_cells[i] ? 100 * p.cat_pass[i] / (p.cat_cells[i] * this.K) : null;
        return `<div class="lg"><i style="background:${c.color}"></i>${c.name}<span class="q">${n.toLocaleString()}${pr != null ? ' · ' + pr.toFixed(0) + '%' : ''}</span></div><div class="mbar"><i style="width:${pr ?? 0}%;background:${pr >= 80 ? '#3bf28a' : pr >= 50 ? '#ffb020' : '#ff3b6b'}"></i></div>`; }).join('');
    } else {
      const tot = p ? p.flights - p.flights_pass : 0;
      body = `<h3>Failures by cause</h3>` + (this.view === 'outcome' ? `<div class="lg"><i style="background:#16aa69"></i>Passed<span class="q">${p ? (100 * p.flights_pass / p.flights).toFixed(1) + '%' : ''}</span></div>` : '') +
        m.modes.map((md, i) => { const f = p ? p.mode_flights[i] : 0, pc = tot ? 100 * f / tot : 0;
          return `<div class="lg"><i style="background:${md.color}"></i>${md.name}<span class="q">${f.toLocaleString()}</span></div><div class="mbar"><i style="width:${pc}%;background:${md.color}"></i></div>`; }).join('');
    }
    const regs = (m.regions || []).slice(0, 12).map(r => `<div class="lg reg" data-x="${r.cx}" data-y="${r.cy}" style="cursor:pointer"><i style="background:transparent;border:1.5px dashed #ff3b6b"></i>${esc(r.agent)}<span class="q" style="max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.title.split(' — ')[0])}</span></div>`).join('');
    this.left.innerHTML = tabs + body + (regs ? `<h3 style="margin-top:14px">Agent stress districts (click to fly)</h3>${regs}` : '') +
      `<div style="font-size:10.5px;color:#61708c;margin-top:12px;line-height:1.4">Simulation findings from a reduced-order vectorised physics model seeded with the measured weather year — not field-test proof.</div>`;
    this.left.querySelectorAll('.modes-tabs button').forEach(b => b.onclick = () => this.setView(b.dataset.v));
    this.left.querySelectorAll('.reg').forEach(b => b.onclick = () => { this.flyTo(+b.dataset.x, +b.dataset.y, 90); setTimeout(() => this.select(+b.dataset.x, +b.dataset.y), 1700); });
  }
  envAt(i) {
    const e = {}; for (const p of this.planes) e[p.name] = p.a[i] / p.scale - p.offset;
    if (this.platform === 'robot') e.terrainName = this.meta.terrains[this.planes[this.pidx.terrain].a[i]];
    return e;
  }
  bindInput() {
    const c = this.c; let drag = null;
    c.addEventListener('wheel', (e) => { e.preventDefault(); this.anim = null; const r = c.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const wx = this.cam.x + (mx - r.width / 2) / this.cam.z, wy = this.cam.y + (my - r.height / 2) / this.cam.z;
      const z = Math.max(0.2, Math.min(400, this.cam.z * Math.exp(-e.deltaY * 0.0016)));
      this.cam = { x: wx - (mx - r.width / 2) / z, y: wy - (my - r.height / 2) / z, z }; }, { passive: false });
    c.addEventListener('mousedown', (e) => { drag = { x: e.clientX, y: e.clientY, cx: this.cam.x, cy: this.cam.y, moved: 0 }; this.anim = null; });
    addEventListener('mousemove', (e) => { const r = c.getBoundingClientRect();
      if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy)); this.cam.x = drag.cx - dx / this.cam.z; this.cam.y = drag.cy - dy / this.cam.z; }
      this.hover = this.toCell(e.clientX - r.left, e.clientY - r.top); });
    addEventListener('mouseup', (e) => { if (drag && drag.moved < 5 && e.target === c) { const r = c.getBoundingClientRect(), h = this.toCell(e.clientX - r.left, e.clientY - r.top); if (h) this.select(h.x, h.y); } drag = null; });
  }
  toCell(mx, my) { if (!this.S) return null; const W = this.c.clientWidth, H = this.c.clientHeight; const x = Math.floor(this.cam.x + (mx - W / 2) / this.cam.z), y = Math.floor(this.cam.y + (my - H / 2) / this.cam.z);
    return x >= 0 && y >= 0 && x < this.S && y < this.S ? { x, y } : null; }
  flyTo(x, y, z, ms = 1600) { this.anim = { from: { ...this.cam }, to: { x: x + 0.5, y: y + 0.5, z }, t0: performance.now(), ms }; }
  async select(x, y) {
    if (!this.runId) return; x = Math.floor(x); y = Math.floor(y); this.sel = { x, y, t0: performance.now() };
    const res = await fetch(`/api/runs/${this.runId}/cell?x=${x}&y=${y}`); if (!res.ok) return; const d = await res.json(); this.sel.data = d; this.renderInspector(d);
  }
  renderInspector(d) {
    const pct = Math.round(100 * d.pass / d.trials), col = pct >= 80 ? '#3bf28a' : pct >= 50 ? '#ffb020' : '#ff3b6b';
    const mcol = Object.fromEntries(this.meta.modes.map(m => [m.id, m.color]));
    const unit = { wind: 'm/s', gust: 'm/s', rain: 'mm/h', snow: 'cm/h', temp: '°C', rh: '%', pressure: 'hPa', vis: 'km', payload: 'kg', slope: '°', friction: 'μ', mud: 'cm', snow_depth: 'cm', obstacle: 'cm' };
    const env = Object.entries(d.env).map(([k, v]) => `<span>${k.replace('_', ' ')}</span><b>${v}${unit[k] ? ' ' + unit[k] : ''}</b>`).join('');
    const mg = Object.entries(d.margins).map(([k, v]) => `<span>${k.replaceAll('_', ' ')}</span><b>${v}</b>`).join('');
    const hist = Object.entries(d.histogram).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<span>${esc(k)}</span><b style="color:#ff3b6b">${v}/${d.trials}</b>`).join('');
    this.insp.innerHTML = `<button class="close" id="insp-x">✕</button><h3>Cell #${d.id.toLocaleString()} · (${d.x}, ${d.y})</h3>${d.when ? `<div class="insp-when">Departure ${esc(d.when)} · flown along the route</div><button class="fly3d" id="fly3d">▶ Fly this cell in the 3D city</button>` : ''}
      <div class="insp-h"><span class="pp" style="color:${col}">${pct}%</span><div><div style="font-weight:700">${pct >= 80 ? 'PASS' : 'FAIL'} · ${d.category.name}</div><div style="font-size:11px;color:#8796b0">${d.pass}/${d.trials} Monte-Carlo ${this.platform === 'drone' ? 'flights' : 'missions'} survived${d.dominant ? ' · ' + esc(d.dominant.name) : ''}</div></div></div>
      <canvas id="insp-scene" width="680" height="380" style="width:100%;border-radius:10px;margin:10px 0 4px"></canvas>
      <div style="font-size:10.5px;color:#8796b0" id="insp-trial"></div>
      <div class="trials">${d.trial_modes.map(m => `<i style="background:${m ? mcol[m] : '#16aa69'}"></i>`).join('')}</div>
      <h3>Environment</h3><div class="kv">${env}</div>${hist ? `<h3>Failure breakdown</h3><div class="kv">${hist}</div>` : ''}<h3>Physics margins</h3><div class="kv">${mg}</div>
      ${d.case ? `<h3>Agent finding</h3><div class="case"><div class="ct">${esc(d.case.title)}</div><div class="ca">${esc(d.case.agent)}</div><div class="cm">${esc(d.case.mechanism)}</div></div>` : ''}`;
    this.insp.classList.add('show'); document.getElementById('insp-x').onclick = () => { this.insp.classList.remove('show'); this.sel = null; };
  }
  when(x, y) {
    const c = this.meta?.calendar; if (!c) return '';
    const d = new Date(Date.parse(c.start + 'T00:00:00Z') + Math.floor(x * c.days / this.S) * 864e5), h = y * 24 / this.S;
    return `${d.toUTCString().slice(0, 11)} ${String(Math.floor(h)).padStart(2, '0')}:${String(Math.floor((h % 1) * 60)).padStart(2, '0')} UTC · `;
  }
  drawCalendar(ctx, W, H, sx, sy) {
    const c = this.meta?.calendar; if (!c) return;
    ctx.font = '600 10px JetBrains Mono'; ctx.fillStyle = 'rgba(160,180,215,.75)'; ctx.textAlign = 'center';
    const t0 = Date.parse(c.start + 'T00:00:00Z'), top = Math.max(sy(0) - 8, 176);
    for (let m = 0; m < 13; m++) { const d = new Date(t0); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + m); const day = (d - t0) / 864e5; if (day < 0 || day > c.days) continue;
      const X = sx(day * this.S / c.days); if (X < 320 || X > W - 20) continue; ctx.fillText(d.toUTCString().slice(8, 11).toUpperCase(), X, top); }
    ctx.textAlign = 'right'; const L = Math.max(sx(0) - 6, 360);
    for (let h = 0; h <= 24; h += 3) { const Y = sy(h * this.S / 24); if (Y < 30 || Y > H - 10) continue; ctx.fillText(`${String(h).padStart(2, '0')}:00`, L, Y + 3); }
  }
  addFix(f) { this.fixes.push(f); }
  report(r, onApply) {
    this.doneAt = (performance.now() - this.tStart) / 1000;
    const el = document.getElementById('report'), p = this.prog;
    el.innerHTML = `<button class="close" id="rep-x">✕</button><h3>Proving-ground report · ${r.elapsed_s}s end-to-end</h3>
      <div style="display:flex;gap:10px;margin-bottom:10px">${[[this.meta.size ** 2, 'environments'], [p.flights, 'Monte-Carlo sims'], [r.cases, 'agent-verified cases'], [r.pass_rate + '%', 'baseline pass'], [r.combined_after + '%', 'with all fixes']]
        .map(([a, b], i) => `<div class="kpi" style="min-width:0;flex:1"><b style="font-size:19px;${i === 4 ? 'color:#3bf28a' : ''}">${typeof a === 'number' ? a.toLocaleString() : a}</b><span>${b}</span></div>`).join('')}</div>
      ${r.route_risk ? `<div class="rr"><div><b>${r.route_risk.per_million_flights.toLocaleString()}</b><span>expected people struck per million ${this.platform === 'drone' ? 'flights' : 'missions'} (proxy)</span></div><div><b>${r.route_risk.max_igrc}</b><span>max intrinsic GRC</span></div><div class="rr-a">${r.route_risk.airspace.map(esc).join('<br>') || 'no controlled airspace'}</div></div>` : ''}
      ${r.fixes.map(f => `<div class="fx"><div><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${f.color};margin-right:6px"></i>${esc(f.mode)}</div><div style="color:#b7c1d6">${esc(f.fix)}</div><div class="d">${f.pass_before}% → <b>${f.pass_after}%</b></div></div>`).join('')}
      <div style="display:flex;gap:10px;margin-top:12px"><button class="launch" id="apply-fixes" style="margin:0;padding:11px;font-size:14px">Apply all fixes & re-run the swarm</button></div>
      <div style="font-size:10.5px;color:#61708c;margin-top:8px">Fix impact measured by re-simulating 65,536 sampled cells × 8 trials. Simulation findings, not certification.</div>`;
    el.classList.add('show'); const op = document.getElementById('rep-open'); op.style.display = 'none';
    document.getElementById('rep-x').onclick = () => { el.classList.remove('show'); op.style.display = 'block'; };
    op.onclick = () => { el.classList.add('show'); op.style.display = 'none'; };
    document.getElementById('apply-fixes').onclick = () => onApply(r.combined_params);
    this.renderTop();
  }
  frame(ts) {
    requestAnimationFrame(this.frame.bind(this));
    const c = this.c; if (!c.offsetParent || !this.S) return;
    const dpr = devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
    if (c.width !== W * dpr || c.height !== H * dpr) { c.width = W * dpr; c.height = H * dpr; }
    if (this.anim) { const a = this.anim, k = Math.min(1, (ts - a.t0) / a.ms), e = k < 0.5 ? 4 * k ** 3 : 1 - (-2 * k + 2) ** 3 / 2;
      const lz = Math.log(a.from.z) + (Math.log(a.to.z) - Math.log(a.from.z)) * e; this.cam = { x: a.from.x + (a.to.x - a.from.x) * e, y: a.from.y + (a.to.y - a.from.y) * e, z: Math.exp(lz) }; if (k >= 1) this.anim = null; }
    const ctx = this.ctx, { x, y, z } = this.cam, t = ts / 1000;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.fillStyle = '#03050a'; ctx.fillRect(0, 0, W, H);
    ctx.save(); ctx.translate(W / 2 - x * z, H / 2 - y * z); ctx.scale(z, z); ctx.imageSmoothingEnabled = false;
    ctx.shadowColor = 'rgba(76,242,198,.25)'; ctx.shadowBlur = 40; ctx.drawImage(this.off, 0, 0); ctx.shadowBlur = 0;
    ctx.restore();
    const x0 = Math.max(0, Math.floor(x - W / 2 / z)), x1 = Math.min(this.S - 1, Math.ceil(x + W / 2 / z)), y0 = Math.max(0, Math.floor(y - H / 2 / z)), y1 = Math.min(this.S - 1, Math.ceil(y + H / 2 / z));
    const sx = (cx) => W / 2 + (cx - x) * z, sy = (cy) => H / 2 + (cy - y) * z;
    if (z >= 36 && (x1 - x0 + 1) * (y1 - y0 + 1) < 900) {
      for (let cy = y0; cy <= y1; cy++) for (let cx = x0; cx <= x1; cx++) { const i = cy * this.S + cx; if (!this.tested[i]) continue;
        const r = this.pass[i] / this.K, d = this.dom[i];
        drawCell(ctx, sx(cx) + 1, sy(cy) + 1, z - 2, z - 2, this.envAt(i), this.meta.categories[this.cat[i]].key, this.platform, this.params, t + (i % 97) * 0.13,
          { pass: this.pass[i], trials: this.K, mode: r < 0.5 ? d : 0, label: d ? this.meta.modes[d - 1].name : 'nominal' }, i); }
    } else if (z >= 6) {
      ctx.strokeStyle = `rgba(0,0,0,${Math.min(0.6, (z - 6) / 20)})`; ctx.lineWidth = 1; ctx.beginPath();
      for (let cx = x0; cx <= x1 + 1; cx++) { ctx.moveTo(sx(cx), sy(y0)); ctx.lineTo(sx(cx), sy(y1 + 1)); }
      for (let cy = y0; cy <= y1 + 1; cy++) { ctx.moveTo(sx(x0), sy(cy)); ctx.lineTo(sx(x1 + 1), sy(cy)); } ctx.stroke();
    }
    // scan glow on recent tiles
    this.recent = this.recent.filter(r => ts - r.t < 900);
    for (const r of this.recent) { const a = 1 - (ts - r.t) / 900; ctx.strokeStyle = `rgba(76,242,198,${a})`; ctx.lineWidth = 2; ctx.strokeRect(sx(r.tx), sy(r.ty), r.tw * z, r.th * z); ctx.fillStyle = `rgba(76,242,198,${a * 0.12})`; ctx.fillRect(sx(r.tx), sy(r.ty), r.tw * z, r.th * z); }
    // agent stress districts
    const placed = []; if (z < 30) for (const r of this.meta.regions || []) { if (!this.tested[r.cy * this.S + r.cx]) continue; const R = r.r * z;
      ctx.strokeStyle = 'rgba(255,59,107,.75)'; ctx.setLineDash([6, 5]); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(sx(r.cx), sy(r.cy), R, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
      if (R > 18) { ctx.font = '600 11px Inter'; const lab = r.agent + ' · ' + r.title.split(' — ')[0], tw = ctx.measureText(lab).width, bx = sx(r.cx) - tw / 2 - 5, by = sy(r.cy) - R - 20;
        if (placed.some(q => bx < q[0] + q[2] && q[0] < bx + tw + 10 && by < q[1] + 16 && q[1] < by + 16)) continue; placed.push([bx, by, tw + 10]); ctx.fillStyle = 'rgba(3,5,10,.7)'; ctx.fillRect(sx(r.cx) - tw / 2 - 5, sy(r.cy) - R - 20, tw + 10, 16); ctx.fillStyle = '#ff9fb6'; ctx.fillText(lab, sx(r.cx) - tw / 2, sy(r.cy) - R - 8); } }
    if (this.sel) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; const pad = Math.max(3, 8 - z); ctx.strokeRect(sx(this.sel.x) - pad, sy(this.sel.y) - pad, z + pad * 2, z + pad * 2); }
    if (this.hover && z > 2) { ctx.strokeStyle = 'rgba(255,255,255,.6)'; ctx.lineWidth = 1; ctx.strokeRect(sx(this.hover.x), sy(this.hover.y), z, z); }
    // inspector scene
    const sc = document.getElementById('insp-scene');
    if (sc && this.sel && this.sel.data) { const d = this.sel.data, k = Math.floor((ts - this.sel.t0) / 2200) % d.trial_modes.length, m = d.trial_modes[k], sctx = sc.getContext('2d');
      const e = { ...d.env, terrainName: d.env.terrain };
      drawCell(sctx, 0, 0, sc.width, sc.height, e, d.category.key, this.platform, this.params, ((ts - this.sel.t0) % 2200) / 1000 + 0.2, { pass: m ? 0 : 1, trials: 1, mode: m, label: m ? this.meta.modes[m - 1].name : 'trial passed' }, k * 31 + 7);
      const lab = document.getElementById('insp-trial'); const txt = `Replaying trial ${k + 1}/${d.trial_modes.length} — ${m ? 'FAIL: ' + this.meta.modes[m - 1].name : 'pass'}`; if (lab.textContent !== txt) lab.textContent = txt; }
    // bottom bar
    const hb = document.getElementById('hud-bottom');
    let txt = `zoom ×${z.toFixed(z < 10 ? 2 : 0)} · ${((x1 - x0 + 1) * (y1 - y0 + 1)).toLocaleString()} cells in view · scroll to zoom, drag to pan, click a cell`;
    if (this.hover) { const i = this.hover.y * this.S + this.hover.x; if (this.tested[i]) { const e = this.envAt(i); txt = `${this.when(this.hover.x, this.hover.y)}(${this.hover.x}, ${this.hover.y}) ${this.meta.categories[this.cat[i]].name} · wind ${e.wind.toFixed(1)} gust ${e.gust.toFixed(1)} m/s · rain ${e.rain.toFixed(1)} mm/h · ${e.temp.toFixed(0)}°C · ${Math.round(100 * this.pass[i] / this.K)}% pass`; } }
    if (hb.textContent !== txt) hb.textContent = txt;
    this.drawCalendar(ctx, W, H, sx, sy);
    // minimap
    if (!this._mmT || ts - this._mmT > 120) { this._mmT = ts; const m = this.mctx, M = this.mm.width; m.imageSmoothingEnabled = true; m.drawImage(this.off, 0, 0, M, M);
      const k = M / this.S; m.strokeStyle = '#4cf2c6'; m.lineWidth = 1.5; m.strokeRect((x - W / 2 / z) * k, (y - H / 2 / z) * k, W / z * k, H / z * k); }
  }
}
