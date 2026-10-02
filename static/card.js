let cardState = null;
const number = (value, digits = 1) => value == null ? '—' : new Intl.NumberFormat('nb-NO', { maximumFractionDigits: digits }).format(value);
const reading = (readings, field, digits, unit = '') => {
  const change = readings.adjustments?.[field];
  if (change != null) return `${change > 0 ? '+' : change < 0 ? '−' : ''}${number(Math.abs(change), digits)}${unit}`;
  return readings[field] == null ? '—' : `${number(readings[field], digits)}${unit}`;
};

function renderCard() {
  if (!cardState) return;
  const readings = cardState.measurements;
  document.querySelector('#card-ph').textContent = reading(readings, 'ph', 2);
  document.querySelector('#card-ta').textContent = reading(readings, 'alkalinity_mg_l', 2, ' mg/L');
  document.querySelector('#card-chlorine').textContent = reading(readings, 'chlorine_mg_l', 2, ' mg/L');
  document.querySelector('#card-oxygen').textContent = reading(readings, 'active_oxygen_mg_l', 2, ' mg/L');
  const status = document.querySelector('#card-status');
  status.textContent = readings.measured_at ?
    `${readings.method === 'strip' ? 'Ønsket endring · ' : ''}${new Intl.DateTimeFormat('nb-NO', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(readings.measured_at))}` : 'Ny måling trengs';
  status.classList.toggle('has-measurement', Boolean(readings.measured_at));
  document.querySelector('#card-last').textContent = cardState.last_added ? cardState.products[cardState.last_added.product].name : '—';
  const cover = document.querySelector('#card-cover');
  const left = cardState.cover_open_until ? Math.ceil((new Date(cardState.cover_open_until).getTime() - Date.now()) / 1000) : 0;
  cover.hidden = left <= 0;
  if (left > 0) document.querySelector('#card-timer').textContent = `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`;
}

async function refreshCard() {
  const response = await fetch('/api/summary', { cache: 'no-store' });
  if (!response.ok) throw new Error('Kunne ikke hente spa-status');
  cardState = await response.json();
  renderCard();
}

setInterval(renderCard, 1000);
setInterval(() => { refreshCard().catch(() => {}); }, 15000);
refreshCard().catch(() => { document.querySelector('#card-status').textContent = 'Spa-status utilgjengelig'; });
