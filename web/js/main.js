import { renderParams, renderDerived, vehicleLoop, pickArt } from './config.js';
import { SwarmView, esc } from './swarm.js';
import { PlaneView } from './plane.js';
import { MapView } from './map.js';
import { City3D } from './city3d.js';

const $ = (s) => document.querySelector(s);
const S = { meta: null, platform: 'drone', values: {}, location: 'london', run: null, ws: null, route: null, routes: [], routeData: null };
const swarm = new SwarmView(), plane = new PlaneView();
const ORDER = ['select', 'config', 'route', 'swarm', 'plane'];
let map, mini;

function show(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('show', s.id === 'screen-' + name));
  const k = ORDER.indexOf(name);
  document.querySelectorAll('#stepper li').forEach((li, i) => { li.classList.toggle('on', i === k); li.classList.toggle('done', i < k); });
  S.screen = name;
}

function choose(platform, values) {
  S.platform = platform;
  const p = S.meta.platforms[platform];
  S.values = values ? { ...values } : Object.fromEntries(p.params.map(x => [x.key, x.default]));
  const upd = () => renderDerived($('#derived'), platform, S.values);
  renderParams($('#params'), p, S.values, upd); upd();
  renderRoutes();
  $('#launch').textContent = `Launch ${$('#agents').value}-agent swarm on ${platform === 'drone' ? 'the drone' : 'the robot'}`;
  show('config');
}

function overlay(k, t, s, hide) {
  $('#ov-k').textContent = k; $('#ov-t').textContent = t; $('#ov-s').textContent = s || '';
  $('#plane-overlay').classList.toggle('hide', !!hide);
}

async function launch() {
  if (S.ws) S.ws.close();
  swarm.reset();
  S.routeData = null; document.body.classList.toggle('has-route', !!S.route);
  const body = { platform: S.platform, params: S.values, location: { id: S.location }, agents: +$('#agents').value, grid: +$('#gridsize').value, route: S.route };
  const r = await (await fetch('/api/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })).json();
  if (r.detail) { $('#route-note').textContent = 'Route error: ' + r.detail; return; }
  S.run = r; plane.runId = r.id; plane.doneAt = null;
  if (S.route) { $('#route-status').textContent = 'Pulling the weather year at the route start…'; show('route'); } else show('swarm');
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/runs/${r.id}`);
  ws.binaryType = 'arraybuffer'; S.ws = ws;
  ws.onmessage = (m) => { if (typeof m.data !== 'string') return plane.tile(m.data); handle(JSON.parse(m.data)); };
}

function handle(e) {
  switch (e.type) {
    case 'phase':
      if (e.phase === 'route') { show('route'); $('#route-status').textContent = e.text; }
      if (e.phase === 'swarm') show('swarm');
      if (e.phase === 'swarm') swarm.roster(e.roster, e.backend, e.model, e.provider);
      if (e.phase === 'grid_build') { show('plane'); overlay('PHASE 2 · PROVING GROUND', `Building ${e.cells.toLocaleString()} environments`, S.routeData ? `every cell = one real departure (day of year × time of day) flown along ${S.routeData.name}` : 'every cell = a distinct hour of weather × terrain × payload, seeded from the measured year + agent stress districts'); }
      if (e.phase === 'grid_test') { overlay('PHASE 3 · MONTE-CARLO', `Testing ${e.cells.toLocaleString()} cells × ${e.trials} trials`, `${(e.cells * e.trials).toLocaleString()} simulated ${S.platform === 'drone' ? 'flights' : 'missions'}`); setTimeout(() => overlay('', '', '', true), 1800); }
      if (e.phase === 'report') overlay('PHASE 4', 'Engineering fixes', e.text, false), setTimeout(() => overlay('', '', '', true), 1400);
      break;
    case 'weather': swarm.climate(e.climate, e.location); break;
    case 'route_progress': $('#route-status').textContent = e.text; break;
    case 'route': S.routeData = e.route; map.set(e.route); mini.set(e.route); map.panel($('#route-side')); $('#cb-name').textContent = e.route.name;
      $('#route-status').textContent = `${e.route.segments.length} segments · ${e.route.buildings.length.toLocaleString()} buildings · ${e.route.airspace.length} airspace volumes — briefing the swarm…`; break;
    case 'agent': swarm.agent(e); break;
    case 'agent_event': swarm.event(e); break;
    case 'case': swarm.addCase(e.case); break;
    case 'swarm_done': swarm.finish(e); break;
    case 'grid_meta': plane.init(e, S.platform, S.values); break;
    case 'grid_progress': plane.progress(e); if (e.seg_fail && S.routeData) { map.setHeat(e.seg_fail, e.seg_flights, e.seg_mode); mini.setHeat(e.seg_fail, e.seg_flights, e.seg_mode); map.panel($('#route-side')); } break;
    case 'fix': plane.addFix(e.fix); break;
    case 'report': plane.report(e, (params) => { S.values = { ...params }; launch(); }); window.SPG.reported = true; break;
    case 'review': renderReview(e); break;
    case 'error': $('#backend-badge').textContent = 'error: ' + e.text; $('#backend-badge').style.color = '#ff3b6b'; break;
  }
}

async function boot() {
  S.meta = await (await fetch('/api/meta')).json();
  const b = $('#backend-badge');
  b.textContent = S.meta.model ? `● Claude Agent SDK · ${S.meta.model} · every call via Mubit.ai` : '● offline deterministic agents (set MUBIT_API_KEY to run the Claude swarm via Mubit.ai)';
  b.classList.toggle('live', !!S.meta.model);
  document.querySelectorAll('.pick-art').forEach(c => pickArt(c, c.dataset.art));
  document.querySelectorAll('.pick-card').forEach(c => c.onclick = () => choose(c.dataset.platform));
  $('#locations').innerHTML = S.meta.presets.map(p => `<button class="chip ${p.id === S.location ? 'on' : ''}" data-id="${p.id}">${p.name}</button>`).join('');
  $('#locations').querySelectorAll('.chip').forEach(c => c.onclick = () => { S.location = c.dataset.id; $('#locations').querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x === c)); });
  $('#agents').oninput = () => { $('#agents-val').textContent = $('#agents').value; $('#agents').style.setProperty('--p', `${100 * ($('#agents').value - 8) / 22}%`); $('#launch').textContent = `Launch ${$('#agents').value}-agent swarm`; };
  $('#agents').oninput();
  $('#launch').onclick = launch;
  const city = new City3D($('#city3d')); window.SPG_CITY = city;
  document.addEventListener('click', (ev) => { if (ev.target.id === 'fly3d' && plane.sel?.data) city.open(S.run.id, plane.sel.data.x, plane.sel.data.y, S.routeData, [100 * ev.clientX / innerWidth, 100 * ev.clientY / innerHeight]); });
  addEventListener('keydown', (ev) => { if (ev.key === 'Escape') city.close(); });
  map = new MapView($('#routemap')); mini = new MapView($('#corridor'), { interactive: false, mini: true });
  $('#corridor-box').onclick = () => S.routeData && show('route');
  S.routes = (await (await fetch('/api/routes')).json()).routes;
  $('#route-file').onchange = async (ev) => { const f = ev.target.files[0]; if (!f) return; const text = await f.text();
    const r = await fetch('/api/routes/parse', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: f.name, text }) });
    ev.target.value = '';
    const d = await r.json().catch(() => ({ detail: `server error ${r.status}` })); if (!r.ok) { const n = $('#route-note'); n.textContent = '⚠ ' + d.detail; n.classList.add('err'); return; }
    $('#route-note').classList.remove('err');
    S.upload = { name: f.name, text, n: d.waypoints.length, format: d.format }; S.route = { name: f.name, text, return: false }; renderRoutes(); };
  document.querySelectorAll('#stepper li').forEach(li => li.onclick = () => { const s = li.dataset.step; if (s === 'select' || s === 'config' || (S.run && s !== 'select' && (s !== 'route' || S.routeData))) show(s); });
  vehicleLoop($('#vehicle-art'), () => S);
  show('select');
}

function renderRoutes() {
  const list = S.routes.filter(r => r.platform === S.platform);
  if (S.route?.id && !list.some(r => r.id === S.route.id)) S.route = list[0] ? { id: list[0].id } : null;
  const cur = S.route?.id || (S.route ? 'upload' : 'none');
  const chips = [['none', 'Weather only'], ...list.map(r => [r.id, r.name]), ['upload', S.upload ? `⬆ ${S.upload.name}` : '⬆ Upload .plan / KML / GeoJSON / GPX']];
  $('#route-chips').innerHTML = chips.map(([k, v]) => `<button class="chip ${k === cur ? 'on' : ''}" data-id="${k}">${v}</button>`).join('');
  $('#route-chips').querySelectorAll('.chip').forEach(c => c.onclick = () => { const k = c.dataset.id;
    if (k === 'upload') { if (S.upload && cur !== 'upload') S.route = { name: S.upload.name, text: S.upload.text, return: false }; else return $('#route-file').click(); }
    else S.route = k === 'none' ? null : { id: k }; renderRoutes(); });
  const d = list.find(r => r.id === S.route?.id);
  $('#route-note').textContent = d ? `${d.desc} · weather is pulled at the route start` : S.route ? `${S.upload.format} · ${S.upload.n} waypoints · weather is pulled at the route start` : 'Abstract weather plane (no map). Pick a route to fly the real corridor.';
  $('#locations').classList.toggle('dim', !!S.route);
}

window.SPG = { S, plane, swarm, choose, launch, show, setLocation: (id) => document.querySelector(`#locations .chip[data-id="${id}"]`)?.click() };
boot();

function renderReview(v) {
  const el = document.getElementById('review'); if (!el) return;
  if (!v.ok) { el.innerHTML = `<div class="rv-h">Flight-ops review · Mubit.ai</div><div class="rv-err">${esc(v.error)}</div>`; return; }
  const cls = (x) => x === 'GO' ? 'go' : x === 'NO-GO' ? 'nogo' : 'cond';
  const p = v.previous, changed = p && (p.verdict !== v.verdict || JSON.stringify(p.conditions) !== JSON.stringify(v.conditions));
  el.innerHTML = `<div class="rv-h">Flight-ops review · via Mubit.ai <span>${esc(v.model_served || v.model_asked)} · ${esc(v.request_id || '')}</span></div>
    <div class="rv-v ${cls(v.verdict)}">${esc(v.verdict)}</div>
    <ul>${(v.reasons || []).map(r => `<li>${esc(r)}</li>`).join('')}</ul>
    ${(v.conditions || []).length ? `<div class="rv-c"><b>Conditions</b> ${v.conditions.map(esc).join(' · ')}</div>` : ''}
    ${v.fix_first ? `<div class="rv-c"><b>Fix first</b> ${esc(v.fix_first)}</div>` : ''}
    ${p ? `<div class="rv-p ${changed ? 'chg' : ''}"><b>${changed ? 'Changed since the last review of this route' : 'Same as the last review of this route'}</b> (${esc(p.at)}, ${esc(p.model_served || p.model_asked)}): <span class="rv-v ${cls(p.verdict)}">${esc(p.verdict)}</span> ${(p.conditions || []).map(esc).join(' · ')}</div>` : ''}
    <button class="chip" id="rv-again">Ask the reviewer again</button>`;
  document.getElementById('rv-again').onclick = async () => { el.querySelector('#rv-again').textContent = 'Asking Mubit…'; renderReview(await (await fetch(`/api/runs/${S.run.id}/review`, { method: 'POST' })).json()); };
}
