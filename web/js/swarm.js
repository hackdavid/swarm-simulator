// Swarm screen: live agent network, agent cards, climate panel, verified case feed.
const TAU = Math.PI * 2;

export class SwarmView {
  constructor() {
    this.net = document.getElementById('swarm-net'); this.ctx = this.net.getContext('2d');
    this.grid = document.getElementById('agents-grid'); this.casesEl = document.getElementById('cases');
    this.agents = []; this.particles = []; this.stats = { tools: 0, trials: 0, cases: 0, done: 0, running: 0, tokens: 0, cost: 0 };
    this.t0 = performance.now(); this.active = false;
    requestAnimationFrame(this.frame.bind(this));
  }
  reset() { this.agents = []; this.particles = []; this.grid.innerHTML = ''; this.casesEl.innerHTML = ''; this.stats = { tools: 0, trials: 0, cases: 0, done: 0, running: 0, tokens: 0, cost: 0 }; this.renderStats(); document.getElementById('case-count').textContent = 0; }
  climate(c, loc) {
    document.getElementById('climate-title').textContent = `Climate ingest · ${loc.name}`;
    document.getElementById('climate-src').textContent = `${c.hours.toLocaleString()} hourly records · ${c.period}\n${c.source}`;
    const d = c.daily;
    spark('ch-gust', [d.gust_max], ['#3ddbd9']); spark('ch-rain', [d.rain_sum], ['#3a6df0'], true); spark('ch-temp', [d.temp_max, d.temp_min], ['#ff7a33', '#8be9ff']);
    const k = c.counts, p = c.percentiles;
    const items = [[p.gust.max + ' m/s', 'max gust'], [p.gust.p99 + ' m/s', 'p99 gust'], [k.rain_hours, 'rain hours'], [k.heavy_rain_hours_gt4mm, 'heavy rain h (>4mm)'],
      [p.temp.min + ' °C', 'coldest hour'], [p.temp.max + ' °C', 'hottest hour'], [k.freezing_hours, 'freezing hours'], [k.icing_condition_hours, 'icing-risk hours'],
      [k.gust_gt_15ms_hours, 'gust >15 m/s h'], [p.pressure.min + ' hPa', 'lowest pressure']];
    document.getElementById('climate-counts').innerHTML = items.map(([a, b]) => `<div class="cc"><b>${a}</b><span>${b}</span></div>`).join('');
  }
  roster(list, backend, model) {
    this.backend = backend; this.t0 = performance.now(); this.active = true;
    this.agents = list.map((r, i) => ({ ...r, status: 'queued', tools: 0, cases: 0, pulse: 0, a: i / list.length * TAU }));
    this.grid.innerHTML = list.map(r => `<div class="ag" id="ag-${r.id}"><div class="n">${r.name}</div><span class="st">QUEUED</span><div class="th">${r.focus}</div><div class="tl"></div><div class="bar"></div></div>`).join('');
    this.renderStats();
  }
  agent(e) {
    const a = this.agents[e.id]; if (!a) return; a.status = e.status;
    const el = document.getElementById('ag-' + e.id); el.className = 'ag ' + e.status + (a.cases ? ' found' : '');
    el.querySelector('.st').textContent = e.status === 'done' ? `DONE ${e.seconds}s` : 'RUNNING';
    if (e.status === 'done') { el.querySelector('.bar').style.width = '100%'; this.stats.done++; if (e.tokens) this.stats.tokens = e.tokens; if (e.cost_usd) this.stats.cost = e.cost_usd; if (e.backend && e.backend.includes('fallback')) el.querySelector('.st').textContent = 'DONE · FALLBACK'; }
    this.stats.running = this.agents.filter(x => x.status === 'running').length; this.renderStats();
  }
  event(e) {
    const a = this.agents[e.id]; if (!a) return; const el = document.getElementById('ag-' + e.id);
    const th = el.querySelector('.th'), tl = el.querySelector('.tl');
    if (e.kind === 'tool_call') {
      a.tools++; this.stats.tools++; a.pulse = 1; this.particles.push({ a: e.id, p: 0, out: true, c: '#7b8cff' });
      tl.textContent = '▶ ' + e.tool + ' ' + (e.text || compact(e.args));
      if (e.tool === 'submit_failure_case' && e.args && e.args.title) th.textContent = 'Submitting: ' + e.args.title;
      el.querySelector('.bar').style.width = Math.min(92, a.tools * 11) + '%';
    } else if (e.kind === 'tool_result') {
      if (e.tool === 'run_physics_test') this.stats.trials += 200;
      if (e.tool === 'submit_failure_case') this.stats.trials += 400;
      this.particles.push({ a: e.id, p: 0, out: false, c: e.tool === 'submit_failure_case' ? '#ff3b6b' : '#4cf2c6' });
      tl.textContent = '◀ ' + (e.text || '');
    } else if (e.kind === 'error') { tl.textContent = '⚠ ' + (e.text || ''); }
    else if (e.text) { th.textContent = e.text; }
    this.renderStats();
  }
  addCase(c) {
    this.stats.cases++; const a = this.agents[c.agent_id]; if (a) { a.cases++; a.pulse = 2; document.getElementById('ag-' + c.agent_id)?.classList.add('found'); }
    document.getElementById('case-count').textContent = this.stats.cases;
    const sc = Object.entries(c.scenario || {}).map(([k, v]) => `${k}=${v}`).join(' · ');
    const div = document.createElement('div'); div.className = 'case';
    div.innerHTML = `<div class="ct">${esc(c.title)}<span class="sev">${c.severity}</span></div><div class="ca">${esc(c.agent)} · verified ${c.verified_pass_pct}% pass /400 trials${c.hours_in_year != null ? ` · ${c.hours_in_year} similar hours last year` : ''}</div>
      <div class="cm">${esc(c.mechanism)}</div><div class="cs">${esc(sc)}</div>${c.mitigation ? `<div class="cf">Fix: ${esc(c.mitigation)}</div>` : ''}`;
    this.casesEl.prepend(div); this.renderStats();
  }
  finish(e) { this.active = false; if (e.tokens) this.stats.tokens = e.tokens; if (e.cost_usd) this.stats.cost = e.cost_usd; if (e.physics_trials) this.stats.trials = e.physics_trials; this.renderStats(); }
  renderStats() {
    const s = this.stats, el = (performance.now() - this.t0) / 1000;
    const list = [[`${s.running}/${this.agents.length}`, 'agents running'], [s.done, 'agents finished'], [s.tools, 'tool calls'], [s.trials.toLocaleString(), 'physics trials run'], [s.cases, 'verified failure cases'],
      [this.backend === 'claude-agent-sdk' ? (s.tokens ? s.tokens.toLocaleString() : '…') : '—', 'Claude tokens'], [this.active ? el.toFixed(0) + 's' : (this.elapsed || el.toFixed(0) + 's'), 'elapsed']];
    if (!this.active && !this.elapsed && this.agents.length) this.elapsed = el.toFixed(0) + 's';
    document.getElementById('swarm-stats').innerHTML = list.map(([a, b]) => `<div class="ss"><b>${a}</b><span>${b}</span></div>`).join('');
  }
  frame(ts) {
    const c = this.net, ctx = this.ctx;
    if (c.offsetParent) {
      const dpr = devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight;
      if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
      const cx = W / 2, cy = H / 2 + 8, RX = W * 0.40, RY = H * 0.36, R = Math.min(RX, RY), t = ts / 1000;
      if (this.active && ts % 1000 < 20) this.renderStats();
      // hub
      ctx.strokeStyle = 'rgba(123,140,255,.12)'; ctx.lineWidth = 1;
      for (let k = 0.25; k < 1.01; k += 0.25) { ctx.beginPath(); ctx.ellipse(cx, cy, RX * k, RY * k, 0, 0, TAU); ctx.stroke(); }
      const pos = this.agents.map((a, i) => { const ang = a.a + t * 0.04; return [cx + Math.cos(ang) * RX, cy + Math.sin(ang) * RY]; });
      this.agents.forEach((a, i) => { const [x, y] = pos[i]; ctx.strokeStyle = a.status === 'running' ? 'rgba(123,140,255,.35)' : a.status === 'done' ? 'rgba(76,242,198,.18)' : 'rgba(120,140,170,.08)';
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke(); });
      // particles
      this.particles = this.particles.filter(p => p.p < 1);
      for (const p of this.particles) { p.p += 0.022; const [x, y] = pos[p.a] || [cx, cy]; const k = p.out ? p.p : 1 - p.p;
        const px = cx + (x - cx) * k, py = cy + (y - cy) * k; ctx.fillStyle = p.c; ctx.shadowColor = p.c; ctx.shadowBlur = 12; ctx.beginPath(); ctx.arc(px, py, 3, 0, TAU); ctx.fill(); }
      ctx.shadowBlur = 0;
      const g = ctx.createRadialGradient(cx, cy, 4, cx, cy, 70); g.addColorStop(0, 'rgba(76,242,198,.55)'); g.addColorStop(1, 'rgba(76,242,198,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, 70, 0, TAU); ctx.fill();
      ctx.fillStyle = '#04110d'; ctx.beginPath(); ctx.arc(cx, cy, 34 + Math.sin(t * 3) * 2, 0, TAU); ctx.fill(); ctx.strokeStyle = '#4cf2c6'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#e6edf7'; ctx.font = '700 11px Inter'; ctx.textAlign = 'center'; ctx.fillText('PHYSICS', cx, cy - 2); ctx.fillStyle = '#8796b0'; ctx.font = '10px Inter'; ctx.fillText('+ weather lab', cx, cy + 12);
      this.agents.forEach((a, i) => { const [x, y] = pos[i]; a.pulse = Math.max(0, a.pulse - 0.02);
        const col = a.cases ? '#ff3b6b' : a.status === 'running' ? '#7b8cff' : a.status === 'done' ? '#4cf2c6' : '#3a4560';
        if (a.pulse > 0) { ctx.strokeStyle = col; ctx.globalAlpha = Math.min(1, a.pulse); ctx.beginPath(); ctx.arc(x, y, 12 + (2 - a.pulse) * 10, 0, TAU); ctx.stroke(); ctx.globalAlpha = 1; }
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = a.status === 'running' ? 14 : 4; ctx.beginPath(); ctx.arc(x, y, 7 + Math.min(a.tools, 10) * 0.5, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
        ctx.fillStyle = '#aab6cc'; ctx.font = '10px Inter'; ctx.fillText(a.name.length > 22 ? a.name.slice(0, 21) + '…' : a.name, x, y + 22);
        if (a.cases) { ctx.fillStyle = '#ff3b6b'; ctx.font = '700 10px JetBrains Mono'; ctx.fillText('✕' + a.cases, x, y - 13); } });
      ctx.textAlign = 'left';
      ctx.fillStyle = '#8796b0'; ctx.font = '11px JetBrains Mono';
      ctx.fillText(this.backend === 'claude-agent-sdk' ? `● LIVE · ${this.agents.length} Claude Agent SDK agents in parallel · tools: find_weather_hours / run_physics_test / submit_failure_case` : `● ${this.agents.length} deterministic search agents (no Claude key) · same tool protocol`, 14, 20);
    }
    requestAnimationFrame(this.frame.bind(this));
  }
}

function spark(id, series, cols, bars) {
  const c = document.getElementById(id), ctx = c.getContext('2d'), W = c.width, H = c.height; ctx.clearRect(0, 0, W, H);
  const all = series.flat(), lo = Math.min(0, ...all), hi = Math.max(...all) || 1;
  series.forEach((s, j) => { ctx.strokeStyle = cols[j]; ctx.fillStyle = cols[j]; ctx.lineWidth = 1;
    if (bars) { s.forEach((v, i) => { const h = (v - lo) / (hi - lo) * (H - 4); ctx.fillRect(i / s.length * W, H - h, Math.max(1, W / s.length - 0.2), h); }); return; }
    ctx.beginPath(); s.forEach((v, i) => { const x = i / (s.length - 1) * W, y = H - 2 - (v - lo) / (hi - lo) * (H - 4); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke(); });
}
export function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function compact(a) { if (!a) return ''; const o = a.scenario && typeof a.scenario === 'object' ? a.scenario : a;
  return Object.entries(o).filter(([k, v]) => typeof v !== 'object').slice(0, 5).map(([k, v]) => `${k}=${typeof v === 'number' ? +v.toFixed(2) : String(v).slice(0, 24)}`).join(' '); }
