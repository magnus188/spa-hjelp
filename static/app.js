let state = null;
let toastTimeout = null;
let actionBusy = false;

const $ = (selector) => document.querySelector(selector);
const fmt = (value, digits = 1) => new Intl.NumberFormat('nb-NO', { maximumFractionDigits: digits }).format(value);
const text = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const localDate = (value) => value ? new Intl.DateTimeFormat('nb-NO', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—';
const shortDate = (value) => value ? new Intl.DateTimeFormat('nb-NO', { day: 'numeric', month: 'short' }).format(new Date(value)) : '—';

async function api(path, body) {
  if (window.spaStandaloneApi) return window.spaStandaloneApi(path, body);
  const options = body === undefined ? { cache: 'no-store' } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Noe gikk galt.');
  return data;
}

function toast(message, isError = false) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.toggle('error', isError);
  element.hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { element.hidden = true; }, 5000);
}

async function run(action, successMessage) {
  if (actionBusy) return;
  actionBusy = true;
  try {
    await action();
    if (successMessage) toast(successMessage);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    actionBusy = false;
  }
}

async function refresh() {
  state = await api('/api/summary');
  render();
}

function renderReadings() {
  const measurement = state.measurements;
  const fields = [
    ['ph', 'ph', '', 2],
    ['alkalinity', 'alkalinity_mg_l', ' mg/L', 0],
    ['chlorine', 'chlorine_mg_l', ' mg/L', 2],
    ['oxygen', 'active_oxygen_mg_l', ' mg/L', 2],
  ];
  for (const [key, field, unit, digits] of fields) {
    const value = measurement[field];
    const change = measurement.adjustments?.[field];
    const measuredAt = measurement.field_measured_at?.[field];
    const method = measurement.field_method?.[field];
    if (change != null) {
      $(`#${key}-value`).textContent = `${change > 0 ? '+' : change < 0 ? '−' : ''}${fmt(Math.abs(change), digits)}${unit}`;
      $(`#${key}-meta`).textContent = `Ønsket endring${measuredAt !== measurement.measured_at ? ` · ${shortDate(measuredAt)}` : ''}`;
    } else {
      $(`#${key}-value`).textContent = value == null ? '—' : `${fmt(value, digits)}${unit}`;
      $(`#${key}-meta`).textContent = value == null ? 'Ikke vurdert' :
        `${method === 'machine' ? 'Måler' : 'Målt'}${measuredAt !== measurement.measured_at ? ` · ${shortDate(measuredAt)}` : ''}`;
    }
  }
  const source = measurement.method === 'strip' ? 'teststrips' : measurement.method === 'machine' ? 'måler' : 'manuelt';
  $('#last-measured').textContent = `Sist vurdert: ${localDate(measurement.measured_at)}${measurement.measured_at ? ` · ${source}` : ''} · ${fmt(state.volume_liters, 0)} L`;
  $('#adjust-open').disabled = !['machine', 'legacy'].includes(measurement.method);
}

function renderHistory() {
  const target = $('#last-additions');
  if (!state.last_additions.length) {
    target.innerHTML = '<p class="muted">Ingen tilsetninger registrert.</p>';
    return;
  }
  target.innerHTML = state.last_additions.map((item) => {
    const product = state.products[item.product]?.name || item.product;
    const spoons = item.amount_ml / item.scoop_ml;
    return `<div class="history-item"><img class="history-product-image" src="static/product-jar.png" alt=""><div class="history-main"><strong>${text(product)}</strong><small>${fmt(item.amount_ml, 2)} ml · ca. ${fmt(spoons, 2)} skjeer</small></div><time>${shortDate(item.added_at)}</time></div>`;
  }).join('');
}

function renderNext() {
  const step = state.next_step;
  const container = $('#next-content');
  const confirm = $('#confirm-step');
  const label = $('#confirm-label');
  confirm.disabled = false;
  confirm.dataset.action = 'confirm';
  if (step.type === 'dose') {
    const spoonUnit = Math.abs(step.scoops - 1) < 0.0001 ? 'skje' : 'skjeer';
    container.innerHTML = `<div class="step-product"><img class="product-image" src="static/product-jar.png" alt=""><div class="step-product-name">${text(step.product_name)}<span class="step-product-label">${text(state.products[step.product].kind)}</span></div></div>
      <div class="step-amount">${fmt(step.scoops, 3)} ${spoonUnit}</div>
      <div class="step-volume">${fmt(step.amount_ml, 3)} ml${step.product === 'mini_chlor' ? ' · ca. ' + fmt(step.amount_ml, 3) + ' g' : ''}</div>
      <p class="step-description">${text(step.description)}</p>
      <p class="step-instruction">${text(step.instruction)}</p>
      ${step.estimated ? '<p class="step-warning">Estimert dose. Mål vannet på nytt etterpå.</p>' : ''}
      ${step.hard_to_measure ? '<p class="step-warning">Dette er mindre enn ¼ av måleskjeen og vanskelig å måle nøyaktig.</p>' : ''}
      <a class="step-source" href="${text(step.source)}" target="_blank" rel="noopener">Les doseringskilden</a>`;
    label.textContent = 'Jeg har tilsatt';
  } else {
    const icon = step.type === 'wait' ? 'timer' : step.type === 'measure' ? 'water' : step.type === 'setup' ? 'settings' : 'check';
    container.innerHTML = `<div class="empty-step"><span class="icon icon-${icon}" aria-hidden="true"></span><h3>${text(step.title)}</h3><p>${text(step.description)}</p>${step.until ? '<div id="wait-countdown" class="wait-countdown"></div>' : ''}</div>`;
    if (step.type === 'measure') { label.textContent = 'Ny måling'; confirm.dataset.action = 'measure'; }
    else if (step.type === 'setup') { label.textContent = 'Innstillinger'; confirm.dataset.action = 'settings'; }
    else if (step.type === 'check') label.textContent = 'Dette er gjort';
    else if (step.type === 'done') label.textContent = 'Fullfør rutinen';
    else if (step.type === 'return') label.textContent = 'Avslutt feriemodus';
    else { label.textContent = step.type === 'wait' ? 'Venter' : 'Velg rutine'; confirm.disabled = true; }
  }
  document.querySelectorAll('[data-mode]').forEach((button) => {
    button.setAttribute('aria-current', String(state.active_flow?.kind === button.dataset.mode));
  });
  tick();
}

function countdown(until) {
  if (!until) return '';
  const seconds = Math.max(0, Math.ceil((new Date(until).getTime() - Date.now()) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function tick() {
  const banner = $('#cover-banner');
  if (state?.cover_open_until && new Date(state.cover_open_until).getTime() > Date.now()) {
    banner.hidden = false;
    $('#cover-title').textContent = `Hold lokket åpent · ${countdown(state.cover_open_until)} igjen`;
  } else {
    banner.hidden = true;
  }
  const wait = $('#wait-countdown');
  if (wait && state.next_step.until) wait.textContent = countdown(state.next_step.until);
}

function render() {
  renderReadings();
  renderHistory();
  renderNext();
}

function openDialog(selector) { $(selector).showModal(); }
function closeDialog(dialog) { dialog.close(); }
function numberOrNull(value) { return value.trim() === '' ? null : Number(value.replace(',', '.')); }

function updateMeasurementMethod() {
  const form = $('#measurement-form');
  const strip = form.elements.method.value === 'strip';
  $('#strip-fields').hidden = !strip;
  $('#machine-fields').hidden = strip;
  $('#strip-fields').querySelectorAll('input').forEach((input) => { input.disabled = !strip; });
  $('#machine-fields').querySelectorAll('input').forEach((input) => { input.disabled = strip; });
}

$('#new-measurement').addEventListener('click', () => openDialog('#measurement-dialog'));
document.querySelectorAll('[name="method"]').forEach((radio) => radio.addEventListener('change', updateMeasurementMethod));
updateMeasurementMethod();
$('#settings-open').addEventListener('click', () => openSettings());
$('#history-open').addEventListener('click', async () => {
  try {
    const history = await api('/api/history');
    $('#history-full').innerHTML = history.additions.length ? history.additions.map((item) => {
      const product = state.products[item.product]?.name || item.product;
      return `<div class="history-item"><img class="history-product-image" src="static/product-jar.png" alt=""><div class="history-main"><strong>${text(product)}</strong><small>${fmt(item.amount_ml, 2)} ml · ${text(item.context)}</small></div><time>${localDate(item.added_at)}</time></div>`;
    }).join('') : '<p class="muted">Ingen tilsetninger registrert.</p>';
    openDialog('#history-dialog');
  } catch (error) { toast(error.message, true); }
});
$('#adjust-open').addEventListener('click', () => {
  const fields = [
    ['alkalinity_mg_l', 'alkalinity'], ['ph', 'ph'],
    ['chlorine_mg_l', 'chlorine'], ['active_oxygen_mg_l', 'oxygen'],
  ];
  $('#adjust-form').reset();
  for (const [field, id] of fields) {
    const value = state.measurements[field];
    $(`#adjust-current-${id}`).textContent = value == null ? 'Sist målt: —' : `Sist målt: ${fmt(value, 2)}`;
  }
  openDialog('#adjust-dialog');
});
document.querySelectorAll('.dialog-close').forEach((button) => button.addEventListener('click', () => closeDialog(button.closest('dialog'))));
document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); }));

$('#measurement-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const method = form.elements.method.value;
  const fields = ['ph', 'alkalinity_mg_l', 'chlorine_mg_l', 'active_oxygen_mg_l'];
  const body = method === 'strip' ? {
    method, adjustments: Object.fromEntries(fields.map((key) => [key, numberOrNull(form.elements[`strip_${key}`].value)])),
  } : {
    method, ...Object.fromEntries(fields.filter((key) => key !== 'active_oxygen_mg_l')
      .map((key) => [key, numberOrNull(form.elements[key].value)])),
  };
  run(async () => { await api('/api/measurements', body); form.reset(); updateMeasurementMethod(); closeDialog($('#measurement-dialog')); }, 'Vurderingen er lagret. Velg hva du vil gjøre.');
});

function openSettings() {
  const form = $('#settings-form');
  form.elements.volume_liters.value = state.volume_liters ?? '';
  $('#scoop-fields').innerHTML = Object.entries(state.products).map(([key, product]) =>
    `<label>${text(product.name)} (ml)<input type="number" name="${text(key)}" min="0.1" max="500" step="0.1" required value="${state.scoops[key]}"></label>`).join('');
  openDialog('#settings-dialog');
}

$('#settings-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const scoops = Object.fromEntries(Object.keys(state.products).map((key) => [key, Number(form.elements[key].value)]));
  run(async () => { await api('/api/settings', { volume_liters: Number(form.elements.volume_liters.value), scoops }); closeDialog($('#settings-dialog')); }, 'Innstillingene er lagret.');
});

document.querySelectorAll('[data-mode]').forEach((button) => button.addEventListener('click', () => {
  const kind = button.dataset.mode;
  if (kind === 'holiday') {
    const today = new Date();
    const nextWeek = new Date(today); nextWeek.setDate(today.getDate() + 7);
    $('#holiday-form').elements.departure_date.value = today.toISOString().slice(0, 10);
    $('#holiday-form').elements.return_date.value = nextWeek.toISOString().slice(0, 10);
    openDialog('#holiday-dialog');
  } else if (kind === 'before_bath') openDialog('#bathers-dialog');
  else run(() => api('/api/flows', { kind }), `${state.modes[kind]} er valgt.`);
}));

$('#bathers-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const bathers = Number(event.currentTarget.elements.bathers.value);
  run(async () => { await api('/api/flows', { kind: 'before_bath', bathers }); closeDialog($('#bathers-dialog')); }, 'Bade nå er valgt.');
});

$('#holiday-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  run(async () => { await api('/api/flows', { kind: 'holiday', departure_date: form.elements.departure_date.value, return_date: form.elements.return_date.value }); closeDialog($('#holiday-dialog')); }, 'Ferieveiviseren er startet.');
});

$('#confirm-step').addEventListener('click', () => {
  const action = $('#confirm-step').dataset.action;
  if (action === 'measure') return openDialog('#measurement-dialog');
  if (action === 'settings') return openSettings();
  run(() => api('/api/confirm', {}), 'Steget er registrert.');
});

$('#adjust-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const increments = Object.fromEntries(
    ['alkalinity_mg_l', 'ph', 'chlorine_mg_l', 'active_oxygen_mg_l']
      .map((field) => [field, numberOrNull(form.elements[field].value)])
      .filter(([, value]) => value != null)
  );
  run(async () => {
    await api('/api/flows', { kind: 'adjust', increments });
    closeDialog($('#adjust-dialog'));
  }, 'Justeringen er startet. Følg neste steg.');
});

setInterval(tick, 1000);
setInterval(() => { refresh().catch(() => {}); }, 15000);
refresh().catch((error) => toast(error.message, true));
