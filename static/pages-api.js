/* Browser-only storage and calculations for the GitHub Pages edition. */
(() => {
  'use strict';

  const KEY = 'spa-hjelp-pages-v1';
  const FIELDS = ['ph', 'alkalinity_mg_l', 'chlorine_mg_l', 'active_oxygen_mg_l'];
  const { products: PRODUCTS, modes: MODES, sources: SOURCES } = window.SPA_CONFIG;
  let lastStamp = 0;

  function stamp() {
    lastStamp = Math.max(Date.now(), lastStamp + 1);
    return new Date(lastStamp).toISOString();
  }

  function round(value, places) {
    const scale = 10 ** places;
    return Math.round((value + Number.EPSILON) * scale) / scale;
  }

  function emptyData() {
    return {
      settings: {
        volume_liters: null,
        scoops: Object.fromEntries(Object.entries(PRODUCTS).map(([key, product]) =>
          [key, product.default_scoop_ml])),
      },
      measurements: [], additions: [], flow: null, next_id: 1,
    };
  }

  function readData() {
    const saved = localStorage.getItem(KEY);
    if (!saved) return emptyData();
    let data;
    try { data = JSON.parse(saved); } catch (_) {
      throw new Error('Lagrede data kan ikke leses. Kontakt prosjektet før du nullstiller nettleserdata.');
    }
    if (!data?.settings?.scoops || !Array.isArray(data.measurements) ||
        !Array.isArray(data.additions) || !Number.isInteger(data.next_id)) {
      throw new Error('Lagrede data har et ukjent format.');
    }
    return data;
  }

  function saveData(data) {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (_) {
      throw new Error('Nettleseren kunne ikke lagre data. Sjekk lagringsinnstillingene.');
    }
  }

  function number(value, name, low, high, required = true) {
    if (value === null || value === undefined || value === '') {
      if (required) throw new Error(`${name} må fylles ut.`);
      return null;
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) throw new Error(`${name} må være et tall.`);
    if (parsed < low || parsed > high) throw new Error(`${name} må være mellom ${low} og ${high}.`);
    return parsed;
  }

  function latestMeasurement(data) {
    if (!data.measurements.length) return null;
    const rows = data.measurements.slice().reverse();
    const result = { ...rows[0] };
    const fieldTimes = Object.fromEntries(FIELDS.map((field) => [field, null]));
    for (const row of rows) {
      for (const field of FIELDS) {
        if (fieldTimes[field] === null && row[field] !== null && row[field] !== undefined) {
          result[field] = row[field];
          fieldTimes[field] = row.measured_at;
        }
      }
      if (Object.values(fieldTimes).every(Boolean)) break;
    }
    result.field_measured_at = fieldTimes;
    result.care_measured_at = [fieldTimes.ph, fieldTimes.alkalinity_mg_l,
      fieldTimes.chlorine_mg_l].filter(Boolean).sort().at(-1) || null;
    return result;
  }

  function measuredAtFor(measurement, field = null) {
    return field ? measurement?.field_measured_at[field] : measurement?.care_measured_at;
  }

  function recent(measurement, now, field = null) {
    const measuredAt = measuredAtFor(measurement, field);
    if (!measuredAt) return false;
    const age = now - Date.parse(measuredAt);
    // stamp() may advance a few milliseconds to keep rapid entries ordered.
    return age >= -1000 && age <= 24 * 60 * 60 * 1000;
  }

  function message(type, title, description, extra = {}) {
    return { type, title, description, ...extra };
  }

  function dose(product, amount, description, source = SOURCES.sundance,
                instruction = 'La pumpe 1 gå, og tilsett over filteret.',
                estimated = false, balance = false) {
    return {
      type: 'dose', title: 'Neste steg', product, product_name: PRODUCTS[product].name,
      amount_ml: round(amount, 3), description, instruction, source, estimated, balance,
    };
  }

  function balanceStep(measurement, volume, now) {
    const scale = volume / 1000;
    const ta = measurement.alkalinity_mg_l;
    const ph = measurement.ph;
    if (ta === null || !recent(measurement, now, 'alkalinity_mg_l')) {
      return message('measure', 'Mål alkalinitet', 'Registrer alkalinitet før pH justeres.');
    }
    if (ta < 80) {
      return dose('alka_up', Math.min(80 - ta, 30) / 30 * 60 * scale,
        'Hev alkaliniteten gradvis mot 80–120 mg/L.', SOURCES.alka_up,
        'Løs opp i en plastbøtte. Tilsett med pumpen på. Mål på nytt etter 2 timer.', true, true);
    }
    if (ta > 120) {
      return dose('alka_down', Math.min(ta - 120, 20) / 20 * 30 * scale,
        'Senk alkaliniteten gradvis mot 80–120 mg/L.', SOURCES.alka_down,
        'Løs opp i en plastbøtte. Pumpen skal være av i 1 time. Start deretter sirkulasjon; mål på nytt etter 2 timer.', true, true);
    }
    if (ph === null || !recent(measurement, now, 'ph')) {
      return message('measure', 'Mål pH', 'Registrer pH etter at alkaliniteten er kontrollert.');
    }
    if (ph < 7.0) {
      return dose('ph_up', Math.min(7.0 - ph, 0.2) / 0.2 * 10 * scale,
        'Hev pH gradvis mot 7,0–7,4.', SOURCES.ph_up,
        'Tilsett med pumpen på. Mål på nytt etter 2 timer.', true, true);
    }
    if (ph > 7.4) {
      return dose('ph_down', Math.min(ph - 7.4, 0.2) / 0.2 * 6 * scale,
        'Senk pH gradvis mot 7,0–7,4.', SOURCES.ph_down,
        'Tilsett med pumpen på. Mål på nytt etter 2 timer.', true, true);
    }
    return null;
  }

  function latestProductAddition(additions, product, flowId = null) {
    return additions.find((item) => item.product === product &&
      (flowId === null || item.flow_id === flowId)) || null;
  }

  function localDateISO(date) {
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function recommendation(data, measurement, additions, now) {
    const volume = data.settings.volume_liters;
    const flow = data.flow;
    if (!volume) return message('setup', 'Angi bassengvolum', 'Legg inn antall liter før vi beregner doser.');
    if (!flow) {
      if (!measurement?.care_measured_at) {
        return message('measure', 'Ny måling trengs', 'Registrer pH, alkalinitet og klor for å starte.');
      }
      return message('choose', 'Velg en rutine', 'Velg det du skal gjøre med badet i dag.');
    }
    const { kind, step } = flow;
    if (!MODES[kind]) return message('choose', 'Velg en rutine', 'Velg det du skal gjøre med badet i dag.');
    if (kind === 'holiday' && step === 0 &&
        (!measurement?.care_measured_at || Date.parse(measurement.care_measured_at) <= Date.parse(flow.created_at))) {
      return message('measure', 'Mål vannet før ferie',
        'Registrer nye teststripsverdier før du kontrollerer filteret.');
    }
    if (!recent(measurement, now) && !(kind === 'holiday' && step >= 4)) {
      return message('measure', 'Ny måling trengs', 'Mål vannet før du tilsetter kjemikalier.');
    }

    if (kind === 'new_water') {
      if (step === 0) return dose('no_scale', 50 * volume / 1000, 'Tilsett No Scale i kaldt, nytt vann.');
      if (step === 1) {
        const added = latestProductAddition(additions, 'no_scale', flow.id);
        const until = added ? Date.parse(added.added_at) + 10 * 60 * 1000 : now;
        if (now < until) return message('wait', 'La No Scale virke alene',
          'Vent 10 minutter før MiniChlor.', { until: new Date(until).toISOString() });
        return dose('mini_chlor', 30, 'Tilsett 2 Sundance-måleskjeer à 15 ml.');
      }
      if (step === 2) return message('check', 'Legg inn SunPurity', 'Sett sølvionepatronen i skimmeren.');
      return message('done', 'Nytt vann er klart for neste måling',
        'Når vannet er varmt, mål alkalinitet først og deretter pH. Velg Ukentlig for justering.');
    }
    if (kind === 'weekly') {
      if (step !== 0) return message('done', 'Ukentlig stell ferdig', 'Mål vannet igjen ved neste stell eller bading.');
      const correction = additions.find((item) => item.flow_id === flow.id &&
        ['alka_up', 'alka_down', 'ph_up', 'ph_down'].includes(item.product));
      if (correction) {
        const until = Date.parse(correction.added_at) + 2 * 60 * 60 * 1000;
        if (now < until) return message('wait', 'Vent før ny måling',
          'Mål alkalinitet og pH på nytt etter 2 timer.', { until: new Date(until).toISOString() });
        const field = correction.product.startsWith('alka_') ? 'alkalinity_mg_l' : 'ph';
        const measuredAt = measuredAtFor(measurement, field);
        if (!measuredAt || Date.parse(measuredAt) < until) {
          return message('measure', 'Mål vannet på nytt', 'Registrer nye verdier før neste dose.');
        }
      }
      return balanceStep(measurement, volume, now) ||
        dose('mini_chlor', 30, 'Ukentlig dose: 2 Sundance-måleskjeer à 15 ml.');
    }
    if (kind === 'before_bath') {
      if (step === 0) {
        const bathers = Number(flow.meta.bathers || 1);
        const count = 3 + Math.max(0, bathers - 3);
        return dose('active_oxygen', 15 * count,
          `Minst ${count} Sundance-måleskjeer à 15 ml for ${bathers} badende. Tilsett ikke samtidig med MiniChlor.`);
      }
      return message('done', 'Før bad er registrert', 'Kontroller vannet etter behov.');
    }
    if (kind === 'after_bath') {
      if (step === 0) return dose('mini_chlor', 5 * volume / 1000,
        'Startestimat fra SpaCare-etiketten. Sundance sier at behovet avhenger av bruk; mål igjen neste dag.',
        SOURCES.mini_chlor, 'La pumpe 1 gå, og tilsett over filteret.', true);
      return message('done', 'Etter bad er registrert', 'Mål vannet igjen neste dag.');
    }
    if (kind === 'holiday') {
      if (step === 0) return message('check', 'Kontroller filteret', 'Rengjør filteret ved behov før lengre fravær.');
      if (step === 1) return dose('mini_chlor', 30, 'Ferie: 2 Sundance-måleskjeer à 15 ml.');
      if (step === 2) {
        const added = latestProductAddition(additions, 'mini_chlor', flow.id);
        const until = added ? Date.parse(added.added_at) + 5 * 60 * 1000 : now;
        if (now < until) return message('wait', 'La MiniChlor virke',
          'Vent 5 minutter med pumpene på før OxyPlus.', { until: new Date(until).toISOString() });
        return dose('oxyplus', 20 * volume / 1000,
          'Ferie: OxyPlus 20 ml per 1000 liter etter MiniChlor.');
      }
      if (step === 3) return message('check', 'Vurder lavere temperatur',
        'Sundance foreslår omtrent 28 °C ved lengre fravær. La filtreringen fortsette.');
      if (localDateISO(new Date(now)) >= flow.meta.return_date) {
        const measuredAt = measurement?.care_measured_at;
        if (recent(measurement, now) && Date.parse(measuredAt) > Date.parse(flow.updated_at) &&
            localDateISO(new Date(measuredAt)) >= flow.meta.return_date) {
          return message('return', 'Velkommen hjem', 'Ny måling er registrert. Avslutt feriemodus.');
        }
        return message('measure', 'Velkommen hjem', 'Mål vannet på nytt før feriemodus avsluttes.');
      }
      return message('away', 'Feriemodus på', 'Mål vannet på nytt når du kommer hjem.');
    }
    return message('choose', 'Velg en rutine', 'Velg det du skal gjøre med badet i dag.');
  }

  function summary(data) {
    const now = Date.now();
    const measurement = latestMeasurement(data);
    const additions = data.additions.slice().reverse();
    const nextStep = recommendation(data, measurement, additions, now);
    if (nextStep.type === 'dose') {
      const scoop = data.settings.scoops[nextStep.product];
      nextStep.scoop_ml = scoop;
      nextStep.scoops = round(nextStep.amount_ml / scoop, 4);
      nextStep.hard_to_measure = nextStep.scoops < 0.25;
    }
    const last = additions[0] || null;
    const coverUntil = last ? Date.parse(last.added_at) + 20 * 60 * 1000 : null;
    const coverOpen = coverUntil !== null && coverUntil > now;
    return {
      volume_liters: data.settings.volume_liters, scoops: data.settings.scoops,
      products: PRODUCTS, modes: MODES, measurement,
      measurements: {
        ph: measurement?.ph ?? null,
        alkalinity_mg_l: measurement?.alkalinity_mg_l ?? null,
        chlorine_mg_l: measurement?.chlorine_mg_l ?? null,
        active_oxygen_mg_l: measurement?.active_oxygen_mg_l ?? null,
        measured_at: measurement?.measured_at ?? null,
        source: measurement?.source ?? null,
        field_measured_at: measurement?.field_measured_at ?? null,
      },
      last_additions: additions.slice(0, 3), last_added: last, next_step: nextStep,
      active_flow: data.flow,
      holiday_return_on: data.flow?.kind === 'holiday' ? data.flow.meta.return_date : null,
      cover_open_until: coverOpen ? new Date(coverUntil).toISOString() : null,
      cover_open: coverOpen, server_time: new Date(now).toISOString(),
    };
  }

  function chlorineEstimate(delta, volume, scoop, measuredChlorine) {
    const amount = delta * volume / (1000 * 0.55);
    const scoops = amount / scoop;
    return {
      product: 'mini_chlor', amount_ml: round(amount, 3), scoops: round(scoops, 4),
      delta_mg_l: delta, projected_mg_l: round(measuredChlorine + delta, 2),
      hard_to_measure: scoops < 0.25,
      warning: 'Kun et teoretisk estimat. Faktisk klorøkning avhenger av vannet. Mål på nytt etter tilsetning.',
    };
  }

  function enforceSeparation(product, additions) {
    const opposite = { mini_chlor: 'active_oxygen', active_oxygen: 'mini_chlor' }[product];
    if (!opposite) return;
    const last = additions.slice().reverse().find((item) => item.product === opposite);
    if (last && Date.now() - Date.parse(last.added_at) < 20 * 60 * 1000) {
      throw new Error('MiniChlor og Active Oxygen skal ikke tilsettes samtidig. Vent til sirkulasjonssyklusen er over.');
    }
  }

  function addAddition(data, product, amount, context, flowId) {
    data.additions.push({
      id: data.next_id++, product, amount_ml: amount,
      scoop_ml: data.settings.scoops[product], context, flow_id: flowId, added_at: stamp(),
    });
  }

  function validDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T12:00:00`);
    return !Number.isNaN(date.getTime()) && localDateISO(date) === value;
  }

  window.spaStandaloneApi = async (path, body) => {
    const data = readData();
    if (path === '/api/summary') return summary(data);
    if (path === '/api/history') return { additions: data.additions.slice().reverse().slice(0, 100) };
    if (path === '/api/settings') {
      const volume = number(body?.volume_liters, 'Volum', 100, 10000);
      const scoops = { ...data.settings.scoops };
      for (const [key, value] of Object.entries(body?.scoops || {})) {
        if (!PRODUCTS[key]) throw new Error('Ukjent produkt.');
        scoops[key] = number(value, `Måleskje for ${PRODUCTS[key].name}`, 0.1, 500);
      }
      data.settings = { volume_liters: volume, scoops };
      saveData(data);
      return { ok: true };
    }
    if (path === '/api/measurements') {
      const values = {
        ph: number(body?.ph, 'pH', 0, 14, false),
        alkalinity_mg_l: number(body?.alkalinity_mg_l, 'Alkalinitet', 0, 500, false),
        chlorine_mg_l: number(body?.chlorine_mg_l, 'Klor', 0, 20, false),
        active_oxygen_mg_l: number(body?.active_oxygen_mg_l, 'Aktivt oksygen', 0, 50, false),
      };
      if (FIELDS.every((field) => values[field] === null)) throw new Error('Legg inn minst én måleverdi.');
      data.measurements.push({ id: data.next_id++, measured_at: stamp(), ...values, source: 'manual' });
      saveData(data);
      return { ok: true };
    }
    if (path === '/api/flows') {
      const kind = body?.kind;
      if (!MODES[kind]) throw new Error('Velg en gyldig rutine.');
      let meta = {};
      if (kind === 'before_bath') {
        const bathers = number(body?.bathers ?? 1, 'Antall badende', 1, 20);
        if (!Number.isInteger(bathers)) throw new Error('Antall badende må være et heltall.');
        meta = { bathers };
      }
      if (kind === 'holiday') {
        if (!validDate(body?.departure_date) || !validDate(body?.return_date)) {
          throw new Error('Velg avreise- og returdato.');
        }
        if (body.return_date < body.departure_date) throw new Error('Returdato må være etter avreise.');
        meta = { departure_date: body.departure_date, return_date: body.return_date };
      }
      const now = stamp();
      data.flow = { id: data.next_id++, kind, step: 0, meta, created_at: now, updated_at: now };
      saveData(data);
      return { ok: true };
    }
    if (path === '/api/confirm') {
      if (!data.flow) throw new Error('Velg en rutine først.');
      const step = summary(data).next_step;
      if (step.type === 'dose') {
        enforceSeparation(step.product, data.additions);
        addAddition(data, step.product, step.amount_ml, data.flow.kind, data.flow.id);
        if (!step.balance) data.flow.step++;
        data.flow.updated_at = stamp();
      } else if (step.type === 'check') {
        data.flow.step++;
        data.flow.updated_at = stamp();
      } else if (step.type === 'done' || step.type === 'return') {
        data.flow = null;
      } else {
        throw new Error('Dette steget kan ikke bekreftes ennå.');
      }
      saveData(data);
      return { ok: true };
    }
    if (path === '/api/chlorine-estimate' || path === '/api/chlorine-add') {
      const delta = number(body?.delta_mg_l, 'Ønsket klorøkning', 0.01, 3);
      const measurement = latestMeasurement(data);
      if (!data.settings.volume_liters) throw new Error('Angi bassengvolum først.');
      if (!measurement || measurement.chlorine_mg_l === null ||
          !recent(measurement, Date.now(), 'chlorine_mg_l')) {
        throw new Error('Registrer en ny klormåling først.');
      }
      const estimate = chlorineEstimate(delta, data.settings.volume_liters,
        data.settings.scoops.mini_chlor, measurement.chlorine_mg_l);
      if (path === '/api/chlorine-estimate') return estimate;
      enforceSeparation('mini_chlor', data.additions);
      addAddition(data, 'mini_chlor', estimate.amount_ml, 'chlorine_adjust', null);
      saveData(data);
      return { ok: true, estimate };
    }
    throw new Error('Ukjent handling.');
  };
})();
