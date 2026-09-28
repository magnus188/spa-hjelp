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
assert.equal((await api('/api/summary')).volume_liters, 1500);
assert.equal((await api('/api/summary')).next_step.type, 'measure');
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
assert.equal((await api('/api/summary')).next_step.type, 'wait');
await assert.rejects(api('/api/confirm', {}), /ikke bekreftes/);

const today = new Date();
const nextWeek = new Date(today); nextWeek.setDate(today.getDate() + 7);
const localDay = (date) => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'),
  String(date.getDate()).padStart(2, '0')].join('-');
await api('/api/flows', {
  kind: 'holiday', departure_date: localDay(today), return_date: localDay(nextWeek),
});
assert.equal((await api('/api/summary')).next_step.title, 'Kontroller filteret');
await api('/api/measurements', { active_oxygen_mg_l: 6 });
assert.equal((await api('/api/summary')).next_step.title, 'Kontroller filteret');
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
assert.equal((await api('/api/summary')).measurements.measured_at, null);
await api('/api/measurements', { alkalinity_mg_l: 100, ph: 7.2, chlorine_mg_l: 1.2 });
await api('/api/flows', { kind: 'before_bath', bathers: 5 });
assert.equal((await api('/api/summary')).next_step.amount_ml, 75);

saved.clear();
api = client();
await api('/api/measurements', {
  alkalinity_mg_l: 100, ph: 7.2, chlorine_mg_l: 0.2, active_oxygen_mg_l: 2,
});
await api('/api/flows', { kind: 'adjust', increments: {
  chlorine_mg_l: 0.2, active_oxygen_mg_l: 4,
} });
assert.equal((await api('/api/summary')).next_step.product, 'mini_chlor');
assert.equal((await api('/api/summary')).next_step.amount_ml, 0.545);
await api('/api/confirm', {});
assert.equal((await api('/api/summary')).next_step.type, 'wait');
let stored = JSON.parse(saved.get('spa-hjelp-pages-v1'));
stored.additions.at(-1).added_at = new Date(Date.now() - 21 * 60 * 1000).toISOString();
saved.set('spa-hjelp-pages-v1', JSON.stringify(stored));
await api('/api/measurements', { chlorine_mg_l: 0.4, active_oxygen_mg_l: 3 });
assert.equal((await api('/api/summary')).next_step.product, 'active_oxygen');
assert.equal((await api('/api/summary')).next_step.amount_ml, 45);

saved.clear();
api = client();
await api('/api/flows', { kind: 'after_bath' });
assert.equal((await api('/api/summary')).next_step.product, 'mini_chlor');
await api('/api/flows', { kind: 'new_water' });
assert.equal((await api('/api/summary')).next_step.product, 'no_scale');
await api('/api/measurements', { method: 'strip', adjustments: {
  ph: -0.2, alkalinity_mg_l: 10, chlorine_mg_l: 0.2, active_oxygen_mg_l: 2,
} });
api = client();
summary = await api('/api/summary');
assert.equal(summary.measurements.method, 'strip');
assert.equal(summary.measurements.alkalinity_mg_l, null);
assert.equal(summary.measurements.adjustments.alkalinity_mg_l, 10);
assert.equal(summary.measurements.adjustments.active_oxygen_mg_l, 2);
await api('/api/flows', { kind: 'before_bath' });
assert.equal((await api('/api/summary')).next_step.product, 'alka_up');
await assert.rejects(api('/api/measurements', { method: 'machine', ph: 7.2,
  alkalinity_mg_l: 100, chlorine_mg_l: 4, active_oxygen_mg_l: 6 }), /ikke O₂-verdi/);
await api('/api/measurements', { method: 'machine', ph: 7.2,
  alkalinity_mg_l: 100, chlorine_mg_l: 4 });
summary = await api('/api/summary');
assert.equal(summary.next_step.title, 'For mye klor');
assert.equal(summary.measurements.active_oxygen_mg_l, null);
assert.equal(summary.measurements.adjustments.active_oxygen_mg_l, 2);

saved.clear();
api = client();
await api('/api/measurements', { method: 'machine', ph: 7.2,
  alkalinity_mg_l: 100, chlorine_mg_l: 1.2 });
await api('/api/flows', { kind: 'before_bath' });
assert.equal((await api('/api/summary')).next_step.product, 'active_oxygen');
await api('/api/confirm', {});
await api('/api/flows', { kind: 'after_bath' });
assert.equal((await api('/api/summary')).next_step.type, 'wait');

console.log('GitHub Pages API: målinger, doser, timer og ferie fungerer.');
