import { drawDrone, drawRobot } from './scenes.js';

const IP_RAIN = { none: 0.3, IP43: 3, IP45: 7, IP54: 10, IP55: 16, IP56: 28, IP67: 60 };
const FC = { basic: 0.85, pid: 1.0, adaptive: 1.18 };

export function renderParams(el, platform, values, onChange) {
  el.innerHTML = `<h3>${platform.name} · engineering parameters</h3>`;
  const groups = {};
  for (const p of platform.params) (groups[p.group] ||= []).push(p);
  for (const [g, ps] of Object.entries(groups)) {
    const box = document.createElement('div'); box.className = 'pgroup'; box.innerHTML = `<h4>${g}</h4>`;
    for (const p of ps) {
      const row = document.createElement('div'); row.className = 'prm'; row.title = p.help || '';
      if (p.type === 'range') {
        row.innerHTML = `<label>${p.label}</label><span class="v"></span><input type="range" min="${p.min}" max="${p.max}" step="${p.step}" value="${values[p.key]}" data-key="${p.key}">`;
        const inp = row.querySelector('input'), v = row.querySelector('.v');
        const upd = () => { v.textContent = `${values[p.key]} ${p.unit}`; inp.style.setProperty('--p', `${100 * (values[p.key] - p.min) / (p.max - p.min)}%`); };
        inp.oninput = () => { values[p.key] = +inp.value; upd(); onChange(); }; upd();
      } else if (p.type === 'bool') {
        row.innerHTML = `<label>${p.label}</label><button class="tog ${values[p.key] ? 'on' : ''}" data-key="${p.key}"></button>`;
        const b = row.querySelector('button'); b.onclick = () => { values[p.key] = !values[p.key]; b.classList.toggle('on', values[p.key]); onChange(); };
      } else {
        row.innerHTML = `<label>${p.label}</label><span></span><div class="seg" data-key="${p.key}">${p.options.map(o => `<button data-v="${o}" class="${String(o) === String(values[p.key]) ? 'on' : ''}">${o}</button>`).join('')}</div>`;
        row.querySelectorAll('.seg button').forEach(b => b.onclick = () => {
          values[p.key] = typeof p.default === 'number' ? +b.dataset.v : b.dataset.v;
          row.querySelectorAll('.seg button').forEach(x => x.classList.toggle('on', x === b)); onChange();
        });
      }
      box.appendChild(row);
    }
    el.appendChild(box);
  }
}

export function derived(platformId, v) {
  if (platformId === 'drone') {
    const m = v.frame_mass_kg + v.payload_kg, W = m * 9.81, tmax = v.motor_count * v.max_thrust_per_motor_kg * 9.81, twr = tmax / W;
    const r = 0.12 * Math.sqrt(v.max_thrust_per_motor_kg), disc = v.motor_count * Math.PI * r * r;
    const ph = W ** 1.5 / Math.sqrt(2 * 1.225 * disc) / 0.62, pm = ph * (1 + 0.075 + 0.0225) + 15;
    const endu = v.battery_wh * 0.9 / pm * 60, need = v.mission_minutes * (1 + v.reserve_pct / 100);
    const tol = 1.35 * v.wind_resistance_ms * FC[v.flight_controller] * Math.min(1.4, Math.max(0.6, twr / 2)) ** 0.35;
    return [
      { k: 'Take-off mass', v: m.toFixed(1) + ' kg', c: v.payload_kg > v.max_payload_kg ? 'bad' : '' },
      { k: 'Thrust / weight', v: twr.toFixed(2), c: twr < 1.3 ? 'bad' : twr < 1.8 ? 'warn' : 'ok' },
      { k: 'Est. endurance (calm)', v: endu.toFixed(0) + ' min', c: endu < need ? 'bad' : endu < need * 1.2 ? 'warn' : 'ok' },
      { k: 'Mission + reserve', v: need.toFixed(0) + ' min', c: '' },
      { k: 'Gust tolerance', v: tol.toFixed(1) + ' m/s', c: tol < 12 ? 'warn' : 'ok' },
      { k: 'Rain tolerance', v: IP_RAIN[v.ip_rating] + ' mm/h', c: IP_RAIN[v.ip_rating] < 5 ? 'warn' : 'ok' },
    ];
  }
  const m = v.mass_kg + v.payload_kg, rad = v.wheel_diameter_cm / 200, grip = { wheeled: 1, tracked: 1.3, legged: 1.15 }[v.locomotion];
  const slope = Math.asin(Math.min(1, v.motor_torque_nm / rad / (m * 9.81))) * 180 / Math.PI;
  const tip = Math.atan((v.track_width_cm / 2) / v.cog_height_cm) * 180 / Math.PI;
  return [
    { k: 'Gross mass', v: m.toFixed(0) + ' kg', c: v.payload_kg > v.max_payload_kg ? 'bad' : '' },
    { k: 'Torque-limited climb', v: slope.toFixed(0) + '°', c: slope < 15 ? 'bad' : slope < 25 ? 'warn' : 'ok' },
    { k: 'Static tip angle', v: tip.toFixed(0) + '°', c: tip < 30 ? 'bad' : tip < 38 ? 'warn' : 'ok' },
    { k: 'Grip factor', v: '×' + grip.toFixed(2) + (v.traction_control ? ' +TC' : ''), c: '' },
    { k: 'Obstacle clearance', v: Math.min(v.ground_clearance_cm, v.wheel_diameter_cm * 0.4).toFixed(0) + ' cm', c: '' },
    { k: 'Rain tolerance', v: IP_RAIN[v.ip_rating] + ' mm/h', c: IP_RAIN[v.ip_rating] < 5 ? 'warn' : 'ok' },
  ];
}

export function renderDerived(el, platformId, v) {
  el.innerHTML = derived(platformId, v).map(d => `<div class="dm ${d.c}"><b>${d.v}</b><span>${d.k}</span></div>`).join('');
}

export function vehicleLoop(canvas, getState) {
  const ctx = canvas.getContext('2d');
  const frame = (ts) => {
    const t = ts / 1000, st = getState();
    if (canvas.isConnected && canvas.offsetParent) {
      const W = canvas.width, H = canvas.height; ctx.clearRect(0, 0, W, H);
      // ground grid
      ctx.strokeStyle = 'rgba(76,242,198,.10)'; ctx.lineWidth = 1;
      for (let i = -12; i <= 12; i++) { ctx.beginPath(); ctx.moveTo(W / 2 + i * 30, H * 0.78); ctx.lineTo(W / 2 + i * 90, H); ctx.stroke(); }
      for (let j = 0; j < 6; j++) { const y = H * 0.78 + j * j * 4; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
      if (st.platform === 'drone') {
        const v = st.values; ctx.fillStyle = 'rgba(0,0,0,.35)'; ctx.beginPath(); ctx.ellipse(W / 2, H * 0.84, 120, 14, 0, 0, Math.PI * 2); ctx.fill();
        drawDrone(ctx, W / 2, H * 0.42 + Math.sin(t * 1.6) * 10, 120, t, { motors: v.motor_count, tilt: Math.sin(t * 0.8) * 0.05, payload: v.payload_kg / Math.max(v.max_payload_kg, 0.1) });
      } else {
        const v = st.values; ctx.fillStyle = 'rgba(0,0,0,.35)'; ctx.beginPath(); ctx.ellipse(W / 2, H * 0.84, 170, 14, 0, 0, Math.PI * 2); ctx.fill();
        drawRobot(ctx, W / 2, H * 0.62, 110 * (0.8 + v.track_width_cm / 300), t, { loco: v.locomotion, lidar: v.lidar, payload: v.payload_kg / Math.max(v.max_payload_kg, 1) });
      }
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

export function pickArt(canvas, kind) {
  const ctx = canvas.getContext('2d');
  const f = (ts) => { const t = ts / 1000; ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (kind === 'drone') drawDrone(ctx, 210, 120 + Math.sin(t * 2) * 8, 80, t, { motors: 4 });
    else drawRobot(ctx, 210, 140, 80, t, { loco: 'wheeled', lidar: true });
    requestAnimationFrame(f); };
  requestAnimationFrame(f);
}
