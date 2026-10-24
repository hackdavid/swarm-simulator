import { renderParams, renderDerived, vehicleLoop, pickArt } from './config.js';
import { SwarmView } from './swarm.js';
import { PlaneView } from './plane.js';

const $ = (s) => document.querySelector(s);
const S = { meta: null, platform: 'drone', values: {}, location: 'london', run: null, ws: null };
const swarm = new SwarmView(), plane = new PlaneView();
const ORDER = ['select', 'config', 'swarm', 'plane'];

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
  const body = { platform: S.platform, params: S.values, location: { id: S.location }, agents: +$('#agents').value, grid: +$('#gridsize').value };
  const r = await (await fetch('/api/runs', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })).json();
  S.run = r; plane.runId = r.id; plane.doneAt = null;
  show('swarm');
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/runs/${r.id}`);
  ws.binaryType = 'arraybuffer'; S.ws = ws;
  ws.onmessage = (m) => { if (typeof m.data !== 'string') return plane.tile(m.data); handle(JSON.parse(m.data)); };
}

function handle(e) {
  switch (e.type) {
    case 'phase':
      if (e.phase === 'swarm') swarm.roster(e.roster, e.backend, e.model);
      if (e.phase === 'grid_build') { show('plane'); overlay('PHASE 2 · PROVING GROUND', `Building ${e.cells.toLocaleString()} environments`, 'every cell = a distinct hour of weather × terrain × payload, seeded from the measured year + agent stress districts'); }
      if (e.phase === 'grid_test') { overlay('PHASE 3 · MONTE-CARLO', `Testing ${e.cells.toLocaleString()} cells × ${e.trials} trials`, `${(e.cells * e.trials).toLocaleString()} simulated ${S.platform === 'drone' ? 'flights' : 'missions'}`); setTimeout(() => overlay('', '', '', true), 1800); }
      if (e.phase === 'report') overlay('PHASE 4', 'Engineering fixes', e.text, false), setTimeout(() => overlay('', '', '', true), 1400);
      break;
    case 'weather': swarm.climate(e.climate, e.location); break;
    case 'agent': swarm.agent(e); break;
    case 'agent_event': swarm.event(e); break;
    case 'case': swarm.addCase(e.case); break;
    case 'swarm_done': swarm.finish(e); break;
    case 'grid_meta': plane.init(e, S.platform, S.values); break;
    case 'grid_progress': plane.progress(e); break;
    case 'fix': plane.addFix(e.fix); break;
    case 'report': plane.report(e, (params) => { S.values = { ...params }; launch(); }); window.SPG.reported = true; break;
    case 'error': $('#backend-badge').textContent = 'error: ' + e.text; $('#backend-badge').style.color = '#ff3b6b'; break;
  }
}

async function boot() {
  S.meta = await (await fetch('/api/meta')).json();
  const b = $('#backend-badge');
  b.textContent = S.meta.backend === 'claude-agent-sdk' ? `● Claude Agent SDK · ${S.meta.model}` : '● deterministic agents (set ANTHROPIC_API_KEY for Claude)';
  b.classList.toggle('live', S.meta.backend === 'claude-agent-sdk');
  document.querySelectorAll('.pick-art').forEach(c => pickArt(c, c.dataset.art));
  document.querySelectorAll('.pick-card').forEach(c => c.onclick = () => choose(c.dataset.platform));
  $('#locations').innerHTML = S.meta.presets.map(p => `<button class="chip ${p.id === S.location ? 'on' : ''}" data-id="${p.id}">${p.name}</button>`).join('');
  $('#locations').querySelectorAll('.chip').forEach(c => c.onclick = () => { S.location = c.dataset.id; $('#locations').querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x === c)); });
  $('#agents').oninput = () => { $('#agents-val').textContent = $('#agents').value; $('#agents').style.setProperty('--p', `${100 * ($('#agents').value - 8) / 22}%`); $('#launch').textContent = `Launch ${$('#agents').value}-agent swarm`; };
  $('#agents').oninput();
  $('#launch').onclick = launch;
  document.querySelectorAll('#stepper li').forEach(li => li.onclick = () => { const s = li.dataset.step; if (s === 'select' || s === 'config' || (S.run && s !== 'select')) show(s); });
  vehicleLoop($('#vehicle-art'), () => S);
  show('select');
}

window.SPG = { S, plane, swarm, choose, launch, show, setLocation: (id) => document.querySelector(`#locations .chip[data-id="${id}"]`)?.click() };
boot();
