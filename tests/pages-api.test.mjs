import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';

const config = readFileSync('docs/static/pages-config.js', 'utf8');
const apiSource = readFileSync('docs/static/pages-api.js', 'utf8');
const saved = new Map();
const localStorage = {
  getItem: (key) => saved.get(key) ?? null,
  setItem: (key, value) => saved.set(key, value),
};

function client() {
  const context = createContext({ window: {}, localStorage });
  runInContext(config, context);
  runInContext(apiSource, context);
  return context.window.spaStandaloneApi;
}

let api = client();
assert.equal((await api('/api/summary')).next_step.type, 'setup');
await api('/api/settings', { volume_liters: 1700, scoops: { mini_chlor: 10 } });
await api('/api/measurements', {
  ph: 7.2, alkalinity_mg_l: 100, chlorine_mg_l: 0.2, active_oxygen_mg_l: 5,
});
await api('/api/measurements', { active_oxygen_mg_l: 7 });
let summary = await api('/api/summary');
assert.equal(summary.measurements.active_oxygen_mg_l, 7);
assert.equal(summary.measurements.chlorine_mg_l, 0.2);
assert.notEqual(summary.measurements.field_measured_at.chlorine_mg_l,
  summary.measurements.measured_at);

const estimate = await api('/api/chlorine-estimate', { delta_mg_l: 0.2 });
assert.equal(estimate.amount_ml, 0.618);
assert.equal(estimate.scoops, 0.0618);
assert.equal(estimate.hard_to_measure, true);
await assert.rejects(api('/api/measurements', { active_oxygen_mg_l: 60 }),
  /Aktivt oksygen må være mellom/);

await api('/api/flows', { kind: 'weekly' });
summary = await api('/api/summary');
assert.equal(summary.next_step.product, 'mini_chlor');
assert.equal(summary.next_step.amount_ml, 30);
assert.equal(summary.next_step.scoops, 3);
await api('/api/confirm', {});
assert.equal((await api('/api/summary')).cover_open, true);

api = client(); // Simulate a reload: the timer and readings must survive.
summary = await api('/api/summary');
assert.equal(summary.cover_open, true);
assert.equal(summary.last_added.product, 'mini_chlor');
assert.equal(summary.measurements.active_oxygen_mg_l, 7);
await api('/api/flows', { kind: 'before_bath', bathers: 2 });
await assert.rejects(api('/api/confirm', {}), /ikke tilsettes samtidig/);

const today = new Date();
const nextWeek = new Date(today); nextWeek.setDate(today.getDate() + 7);
const localDay = (date) => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'),
  String(date.getDate()).padStart(2, '0')].join('-');
await api('/api/flows', {
  kind: 'holiday', departure_date: localDay(today), return_date: localDay(nextWeek),
});
assert.equal((await api('/api/summary')).next_step.type, 'measure');
await api('/api/measurements', { active_oxygen_mg_l: 6 });
assert.equal((await api('/api/summary')).next_step.type, 'measure');
await api('/api/measurements', { ph: 7.2 });
assert.equal((await api('/api/summary')).next_step.title, 'Kontroller filteret');
await api('/api/confirm', {}); // filter
assert.equal((await api('/api/summary')).next_step.amount_ml, 30);
await api('/api/confirm', {}); // MiniChlor
assert.equal((await api('/api/summary')).next_step.type, 'wait');
await assert.rejects(api('/api/confirm', {}), /kan ikke bekreftes/);

saved.clear();
api = client();
await api('/api/settings', { volume_liters: 1000 });
await api('/api/measurements', { ph: 7.8, alkalinity_mg_l: 70, chlorine_mg_l: 0.2 });
await api('/api/flows', { kind: 'weekly' });
summary = await api('/api/summary');
assert.equal(summary.next_step.product, 'alka_up');
assert.equal(summary.next_step.amount_ml, 20);
await api('/api/flows', { kind: 'new_water' });
assert.equal((await api('/api/summary')).next_step.amount_ml, 50);
await api('/api/flows', { kind: 'before_bath', bathers: 5 });
assert.equal((await api('/api/summary')).next_step.amount_ml, 75);

console.log('GitHub Pages API: målinger, doser, timer og ferie fungerer.');
