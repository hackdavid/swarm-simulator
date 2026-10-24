// Procedural canvas art: vehicles + per-cell weather scenes.
const TAU = Math.PI * 2;

function rnd(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

export function drawDrone(ctx, cx, cy, s, t, o = {}) {
  const n = o.motors || 4, tilt = o.tilt || 0, col = o.color || '#4cf2c6', fail = o.fail;
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(tilt);
  const arm = s * 0.95;
  ctx.lineCap = 'round';
  for (let i = 0; i < n; i++) {
    const a = (i + 0.5) / n * TAU;
    const x = Math.cos(a) * arm, y = Math.sin(a) * arm * 0.36;
    ctx.strokeStyle = '#2b3a55'; ctx.lineWidth = Math.max(1, s * 0.11);
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(x, y); ctx.stroke();
    // rotor disc
    const spin = fail ? 0.2 : 1;
    ctx.fillStyle = fail ? 'rgba(255,59,107,.18)' : 'rgba(150,220,255,.13)';
    ctx.beginPath(); ctx.ellipse(x, y - s * 0.12, s * 0.42, s * 0.11, 0, 0, TAU); ctx.fill();
    ctx.strokeStyle = fail ? 'rgba(255,59,107,.8)' : 'rgba(210,240,255,.75)'; ctx.lineWidth = Math.max(1, s * 0.035);
    const b = t * 30 * spin + i;
    ctx.beginPath(); ctx.moveTo(x - Math.cos(b) * s * 0.4, y - s * 0.12 - Math.sin(b) * s * 0.1);
    ctx.lineTo(x + Math.cos(b) * s * 0.4, y - s * 0.12 + Math.sin(b) * s * 0.1); ctx.stroke();
    ctx.fillStyle = '#1a2335'; ctx.fillRect(x - s * 0.07, y - s * 0.14, s * 0.14, s * 0.16);
  }
  // body
  const g = ctx.createLinearGradient(0, -s * 0.3, 0, s * 0.3);
  g.addColorStop(0, '#2c3c5c'); g.addColorStop(1, '#101828');
  ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(0, 0, s * 0.42, s * 0.22, 0, 0, TAU); ctx.fill();
  ctx.strokeStyle = col; ctx.lineWidth = Math.max(1, s * 0.04); ctx.stroke();
  ctx.fillStyle = fail ? '#ff3b6b' : col; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = s * 0.4;
  ctx.beginPath(); ctx.arc(s * 0.2, 0, s * 0.06, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
  if (o.payload) { ctx.strokeStyle = '#5b6b88'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, s * 0.2); ctx.lineTo(0, s * 0.55); ctx.stroke();
    ctx.fillStyle = '#c9a26b'; const p = s * (0.18 + Math.min(o.payload, 1) * 0.16); ctx.fillRect(-p / 2, s * 0.55, p, p * 0.8); }
  ctx.restore();
}

export function drawRobot(ctx, cx, cy, s, t, o = {}) {
  const loco = o.loco || 'wheeled', col = o.color || '#4cf2c6', tilt = o.tilt || 0, fail = o.fail;
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(tilt);
  const w = s * 1.5, h = s * 0.5, base = s * 0.35;
  if (loco === 'legged') {
    for (let i = 0; i < 4; i++) {
      const x = (-0.6 + i * 0.4) * w * 0.9, ph = t * 6 + i * Math.PI * 0.5;
      const kx = x + Math.sin(ph) * s * 0.1, fy = base + s * 0.4;
      ctx.strokeStyle = '#3a4a68'; ctx.lineWidth = s * 0.09; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(x * 0.8, 0); ctx.lineTo(kx + s * 0.08, base * 0.7); ctx.lineTo(kx + Math.sin(ph) * s * 0.15, fy - Math.max(0, Math.cos(ph)) * s * 0.12); ctx.stroke();
    }
  } else if (loco === 'tracked') {
    ctx.fillStyle = '#1b2230'; roundRect(ctx, -w / 2 - s * 0.05, base * 0.6, w + s * 0.1, s * 0.42, s * 0.21); ctx.fill();
    ctx.strokeStyle = '#3a4a68'; ctx.lineWidth = Math.max(1, s * 0.04); ctx.setLineDash([s * 0.08, s * 0.06]); ctx.lineDashOffset = -t * s * 2; ctx.stroke(); ctx.setLineDash([]);
    for (let i = 0; i < 4; i++) { ctx.fillStyle = '#2b3445'; ctx.beginPath(); ctx.arc(-w / 2 + s * 0.18 + i * (w - s * 0.36) / 3, base * 0.6 + s * 0.21, s * 0.13, 0, TAU); ctx.fill(); }
  } else {
    for (const x of [-w * 0.33, w * 0.33]) {
      ctx.fillStyle = '#151b27'; ctx.beginPath(); ctx.arc(x, base + s * 0.12, s * 0.3, 0, TAU); ctx.fill();
      ctx.strokeStyle = '#3a4a68'; ctx.lineWidth = Math.max(1, s * 0.05); ctx.stroke();
      const a = t * 5; ctx.beginPath(); ctx.moveTo(x, base + s * 0.12); ctx.lineTo(x + Math.cos(a) * s * 0.25, base + s * 0.12 + Math.sin(a) * s * 0.25); ctx.stroke();
    }
  }
  const g = ctx.createLinearGradient(0, -h, 0, h);
  g.addColorStop(0, '#2c3c5c'); g.addColorStop(1, '#101828');
  ctx.fillStyle = g; roundRect(ctx, -w / 2, -h / 2, w, h, s * 0.12); ctx.fill();
  ctx.strokeStyle = col; ctx.lineWidth = Math.max(1, s * 0.04); ctx.stroke();
  // sensor mast
  ctx.fillStyle = '#26324a'; ctx.fillRect(w * 0.22, -h / 2 - s * 0.3, s * 0.12, s * 0.3);
  ctx.fillStyle = fail ? '#ff3b6b' : col; ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = s * 0.5;
  ctx.beginPath(); ctx.arc(w * 0.28, -h / 2 - s * 0.32, s * 0.09, 0, TAU); ctx.fill(); ctx.shadowBlur = 0;
  if (o.lidar && !fail) { ctx.strokeStyle = 'rgba(76,242,198,.25)'; ctx.lineWidth = 1; const a = t * 4;
    ctx.beginPath(); ctx.moveTo(w * 0.28, -h / 2 - s * 0.32); ctx.lineTo(w * 0.28 + Math.cos(a) * s * 2, -h / 2 - s * 0.32 + Math.sin(a) * s * 0.5); ctx.stroke(); }
  if (o.payload) { ctx.fillStyle = '#c9a26b'; const p = s * (0.3 + Math.min(o.payload, 1) * 0.3); ctx.fillRect(-w * 0.3, -h / 2 - p * 0.7, p, p * 0.7); }
  ctx.restore();
}

function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

const SKY = {
  sunny: ['#1d4f8a', '#7fb8e6'], overcast: ['#3b4556', '#69768c'], windy: ['#24506b', '#5f9db5'], rain: ['#1d2a44', '#3c5274'],
  storm: ['#120c24', '#33244f'], snow: ['#5c6f86', '#b9c8d8'], fog: ['#7d8794', '#aab3be'], heat: ['#8a3b14', '#f0a35e'], freezing: ['#2d5170', '#9fd3ea'],
};
const GROUND = { asphalt: '#2a2d33', grass: '#2c5a2a', gravel: '#6b665c', dirt: '#6b4a2e', mud: '#4a3320', sand: '#c2a56b', snow: '#e8eef5', ice: '#bfe3f2', rock: '#5a5a5f' };

// Draw one environment cell as a mini world. `env` holds decoded values; `res` = {pass, trials, mode}
export function drawCell(ctx, x, y, w, h, env, cat, platform, vp, t, res, seed) {
  const sky = SKY[cat] || SKY.overcast;
  ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  const g = ctx.createLinearGradient(0, y, 0, y + h); g.addColorStop(0, sky[0]); g.addColorStop(1, sky[1]);
  ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
  if (cat === 'sunny' || cat === 'heat') { ctx.fillStyle = cat === 'heat' ? 'rgba(255,190,90,.9)' : 'rgba(255,240,180,.9)'; ctx.beginPath(); ctx.arc(x + w * 0.82, y + h * 0.18, Math.min(w, h) * 0.08, 0, TAU); ctx.fill(); }
  if (cat === 'storm' && ((t * 1.3 + seed) % 3) < 0.08) { ctx.fillStyle = 'rgba(255,255,255,.35)'; ctx.fillRect(x, y, w, h); }
  const gy = y + h * 0.8;
  const slope = platform === 'robot' ? (env.slope || 0) : 0;
  const ter = platform === 'robot' ? (env.terrainName || 'grass') : 'grass';
  ctx.fillStyle = (env.snow > 0.05 && platform === 'drone') ? '#dfe8f0' : (GROUND[ter] || '#2c5a2a');
  const sl = Math.tan(slope * Math.PI / 180) * w * 0.5;
  ctx.beginPath(); ctx.moveTo(x, gy + sl); ctx.lineTo(x + w, gy - sl); ctx.lineTo(x + w, y + h); ctx.lineTo(x, y + h); ctx.fill();
  if (platform === 'robot' && env.obstacle > 4) { ctx.fillStyle = '#4b4f58'; const r = Math.min(env.obstacle / 40, 1) * h * 0.12; ctx.beginPath(); ctx.arc(x + w * 0.72, gy - sl * 0.44 - r * 0.3, r, Math.PI, 0); ctx.fill(); }
  if (platform === 'robot' && env.mud > 2) { ctx.fillStyle = 'rgba(60,40,20,.7)'; ctx.fillRect(x, gy - 2, w, h * 0.05); }
  // wind streaks
  const rr = rnd(seed);
  const wind = env.gust || env.wind || 0;
  if (wind > 6) { ctx.strokeStyle = 'rgba(220,240,255,.35)'; ctx.lineWidth = 1; const n = Math.min(10, wind / 2);
    for (let i = 0; i < n; i++) { const py = y + rr() * h * 0.7, px = x + ((rr() * w + t * wind * w * 0.05) % w); ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + w * 0.12, py); ctx.stroke(); } }
  // rain / snow
  if (env.rain > 0.1) { ctx.strokeStyle = 'rgba(170,200,255,.55)'; ctx.lineWidth = 1; const n = Math.min(70, 8 + env.rain * 6);
    for (let i = 0; i < n; i++) { const px = x + rr() * w, py = y + ((rr() * h + t * h * 1.6) % h), dx = wind * 0.4; ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + dx, py + h * 0.06); ctx.stroke(); } }
  if (env.snow > 0.02) { ctx.fillStyle = 'rgba(255,255,255,.85)'; const n = Math.min(60, 10 + env.snow * 60);
    for (let i = 0; i < n; i++) { const px = x + ((rr() * w + Math.sin(t + i) * 4 + t * wind) % w), py = y + ((rr() * h + t * h * 0.25) % h); ctx.beginPath(); ctx.arc(px, py, Math.max(0.7, w * 0.006), 0, TAU); ctx.fill(); } }
  // vehicle
  const fail = res && res.mode > 0;
  const s = Math.min(w, h) * 0.14;
  const gust = (env.gust || 0) / 20;
  if (platform === 'drone') {
    let dy = y + h * 0.42 + Math.sin(t * 2 + seed) * h * 0.02, dx = x + w * 0.45 + Math.sin(t * 1.3 + seed) * w * gust * 0.08, tilt = Math.sin(t * 3 + seed) * gust * 0.35;
    if (fail) { const ph = ((t * 0.35 + rr()) % 1); dy = y + h * (0.32 + 0.45 * ph * ph); tilt = ph * 2.5 * (seed % 2 ? 1 : -1); dx += ph * w * 0.15 * (wind > 8 ? 1 : 0.3); }
    drawDrone(ctx, dx, dy, s, t, { motors: vp.motor_count, tilt, fail, payload: (env.payload || 0) / Math.max(vp.max_payload_kg || 1, 0.1) });
  } else {
    const fx = ((t * 0.08 + rr()) % 1);
    let rx = x + w * (0.15 + 0.7 * fx), ry = gy - (rx - x - w / 2) / (w / 2) * sl - s * 0.85, tilt = -Math.atan(sl / (w / 2));
    if (fail) { rx = x + w * 0.5; ry = gy - s * 0.85; if (res.mode === 3) tilt += Math.PI * 0.45 * Math.min(1, (t % 3)); }
    drawRobot(ctx, rx, ry, s * 0.75, fail ? 0 : t, { loco: vp.locomotion, tilt, fail, lidar: vp.lidar, payload: (env.payload || 0) / Math.max(vp.max_payload_kg || 1, 0.1) });
  }
  if (env.vis < 2) { ctx.fillStyle = `rgba(200,205,215,${Math.min(0.75, (2 - env.vis) / 2.4)})`; ctx.fillRect(x, y, w, h); }
  if (cat === 'heat') { ctx.fillStyle = 'rgba(255,120,40,.08)'; ctx.fillRect(x, y, w, h); }
  // verdict
  if (res) {
    const pct = Math.round(100 * res.pass / res.trials), ok = pct >= 80, mid = pct >= 50;
    const c = ok ? '#3bf28a' : mid ? '#ffb020' : '#ff3b6b';
    ctx.strokeStyle = c; ctx.lineWidth = Math.max(1, w * 0.012); ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
    if (w > 70) {
      const fs = Math.max(10, Math.min(28, w * 0.1));
      ctx.font = `700 ${fs}px JetBrains Mono, monospace`; ctx.fillStyle = 'rgba(3,5,10,.65)';
      ctx.fillRect(x + 4, y + 4, fs * 3.4, fs * 1.4); ctx.fillStyle = c; ctx.fillText(pct + '%', x + 8, y + 4 + fs * 1.1);
      if (w > 160 && res.label) { ctx.font = `600 ${fs * 0.5}px Inter, sans-serif`; ctx.fillStyle = 'rgba(3,5,10,.65)'; const tw = ctx.measureText(res.label).width;
        ctx.fillRect(x + 4, y + h - fs * 1.1 - 4, tw + 10, fs * 0.9); ctx.fillStyle = '#fff'; ctx.fillText(res.label, x + 9, y + h - fs * 0.45 - 4); }
    }
  }
  ctx.restore();
}
