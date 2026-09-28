"""Sundance Norway / SpaCare recipes. Values are millilitres unless stated."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


SUNDANCE_GUIDE = "https://www.sundance.no/vannpleie-med-sunpurity-og-active-oxygen/"
SPACARE_MINICHLOR = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-MiniChlor.pdf"
SPACARE_ALKA_UP = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-Alka-Up-1.pdf"
SPACARE_ALKA_DOWN = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-Alka-Down-1.pdf"
SPACARE_PH_UP = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-pH-Up-Granular-1.pdf"
SPACARE_PH_DOWN = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-pH-Down-Granular.pdf"
SPACARE_ACTIVE_OXYGEN = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-Active-Oxygen-Granular-1.pdf"

PRODUCTS = {
    "mini_chlor": {"name": "SpaCare MiniChlor", "default_scoop_ml": 15, "kind": "granulat"},
    "active_oxygen": {"name": "SpaCare Active Oxygen Granular", "default_scoop_ml": 15, "kind": "granulat"},
    "oxyplus": {"name": "SpaCare OxyPlus Activator Liquid", "default_scoop_ml": 15, "kind": "væske"},
    "no_scale": {"name": "SpaCare No Scale", "default_scoop_ml": 15, "kind": "væske"},
    "alka_up": {"name": "SpaCare Alka Up", "default_scoop_ml": 15, "kind": "granulat"},
    "alka_down": {"name": "SpaCare Alka Down", "default_scoop_ml": 15, "kind": "granulat"},
    "ph_up": {"name": "SpaCare pH Up", "default_scoop_ml": 15, "kind": "granulat"},
    "ph_down": {"name": "SpaCare pH Down", "default_scoop_ml": 15, "kind": "granulat"},
}

MODES = {
    "adjust": "Juster verdier",
    "weekly": "Ukentlig",
    "before_bath": "Bade nå",
    "after_bath": "Etter bad",
    "new_water": "Nytt vann",
    "holiday": "Ferie",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def dose(product: str, amount_ml: float, description: str, source: str = SUNDANCE_GUIDE,
         instruction: str = "La pumpe 1 gå, og tilsett over filteret.",
         estimated: bool = False, balance: bool = False) -> dict:
    return {
        "type": "dose", "product": product, "product_name": PRODUCTS[product]["name"],
        "amount_ml": round(amount_ml, 3), "description": description,
        "instruction": instruction, "source": source, "estimated": estimated,
        "balance": balance, "title": "Neste steg",
    }


def message(kind: str, title: str, description: str, **extra: object) -> dict:
    return {"type": kind, "title": title, "description": description, **extra}


def latest_product_addition(additions: list[dict], product: str, flow_id: int | None = None) -> dict | None:
    return next((item for item in additions if item["product"] == product and
                 (flow_id is None or item["flow_id"] == flow_id)), None)


def measured_at_for(measurement: dict, field: str | None = None) -> str | None:
    if field:
        return measurement.get("field_measured_at", {}).get(field, measurement["measured_at"])
    return measurement.get("care_measured_at", measurement["measured_at"])


def recent_measurement(measurement: dict | None, now: datetime, hours: int = 24,
                       field: str | None = None) -> bool:
    measured = parse_time(measured_at_for(measurement, field)) if measurement else None
    return bool(measured and timedelta(0) <= now - measured <= timedelta(hours=hours))


def strip_change(measurement: dict | None, field: str, now: datetime) -> float | None:
    if not measurement or not recent_measurement(measurement, now, field=field):
        return None
    return (measurement.get("adjustments") or {}).get(field)


def too_high(measurement: dict | None, field: str, limit: float, now: datetime) -> bool:
    if not measurement or not recent_measurement(measurement, now, field=field):
        return False
    change = strip_change(measurement, field, now)
    return (change < 0 if change is not None else
            measurement.get(field) is not None and
            (measurement[field] >= limit if field == "active_oxygen_mg_l" else measurement[field] > limit))


def _wait_after_oxygen(additions: list[dict], now: datetime) -> dict | None:
    previous = latest_product_addition(additions, "active_oxygen")
    if previous:
        until = parse_time(previous["added_at"]) + timedelta(minutes=20)
        if now < until:
            return message("wait", "Vent før MiniChlor", "Active Oxygen og MiniChlor skal ikke tilsettes samtidig. La pumpe 1 gå ut 20-minuttersyklusen.", until=iso_time(until))
    return None


def _balance_recheck(flow_id: int, measurement: dict, additions: list[dict], now: datetime) -> dict | None:
    correction = next((item for item in additions if item["flow_id"] == flow_id and
                       item["product"] in ("alka_up", "alka_down", "ph_up", "ph_down")), None)
    if not correction:
        return None
    until = parse_time(correction["added_at"]) + timedelta(hours=2)
    if now < until:
        return message("wait", "Vent før ny måling", "Mål alkalinitet og pH på nytt etter 2 timer.", until=iso_time(until))
    fields = ("alkalinity_mg_l", "ph") if correction["product"].startswith("alka_") else ("ph",)
    if any(not measured_at_for(measurement, field) or
           parse_time(measured_at_for(measurement, field)) < until for field in fields):
        return message("measure", "Mål vannet på nytt", "Registrer nye verdier før neste dose.")
    return None


def _balance_step(measurement: dict, volume_liters: float, now: datetime) -> dict | None:
    scale = volume_liters / 1000
    ta = measurement["alkalinity_mg_l"]
    ph = measurement["ph"]
    ta_change = strip_change(measurement, "alkalinity_mg_l", now)
    ph_change = strip_change(measurement, "ph", now)
    if (ta is None and ta_change is None) or not recent_measurement(measurement, now, field="alkalinity_mg_l"):
        return message("measure", "Mål alkalinitet", "Registrer alkalinitet før pH justeres.")
    if ta_change is not None and ta_change > 0 or ta_change is None and ta < 80:
        # Label: 4 x 15 ml raises about 30 mg/L per 1000 L. Start with at most one label step.
        amount = min(ta_change if ta_change is not None else 80 - ta, 30) / 30 * 60 * scale
        return dose("alka_up", amount, "Hev alkaliniteten gradvis. Teststrips viser ønsket endring, ikke faktisk verdi." if ta_change is not None else "Hev alkaliniteten gradvis mot 80–120 mg/L.",
                    SPACARE_ALKA_UP,
                    "Løs opp i en plastbøtte. Tilsett med pumpen på. Mål på nytt etter 2 timer.",
                    estimated=True, balance=True)
    if ta_change is not None and ta_change < 0 or ta_change is None and ta > 120:
        # Label: 2 x 15 ml lowers about 20 mg/L per 1000 L.
        amount = min(-ta_change if ta_change is not None else ta - 120, 20) / 20 * 30 * scale
        return dose("alka_down", amount, "Senk alkaliniteten gradvis. Teststrips viser ønsket endring, ikke faktisk verdi." if ta_change is not None else "Senk alkaliniteten gradvis mot 80–120 mg/L.",
                    SPACARE_ALKA_DOWN,
                    "Løs opp i en plastbøtte. Pumpen skal være av i 1 time. Start deretter sirkulasjon; mål på nytt etter 2 timer.",
                    estimated=True, balance=True)
    if (ph is None and ph_change is None) or not recent_measurement(measurement, now, field="ph"):
        return message("measure", "Mål pH", "Registrer pH etter at alkaliniteten er kontrollert.")
    if ph_change is not None and ph_change > 0 or ph_change is None and ph < 7.0:
        amount = min(ph_change if ph_change is not None else 7.0 - ph, 0.2) / 0.2 * 10 * scale
        return dose("ph_up", amount, "Hev pH gradvis etter teststrips." if ph_change is not None else "Hev pH gradvis mot 7,0–7,4.", SPACARE_PH_UP,
                    "Tilsett med pumpen på. Mål på nytt etter 2 timer.", estimated=True, balance=True)
    if ph_change is not None and ph_change < 0 or ph_change is None and ph > 7.4:
        amount = min(-ph_change if ph_change is not None else ph - 7.4, 0.2) / 0.2 * 6 * scale
        return dose("ph_down", amount, "Senk pH gradvis etter teststrips." if ph_change is not None else "Senk pH gradvis mot 7,0–7,4.", SPACARE_PH_DOWN,
                    "Tilsett med pumpen på. Mål på nytt etter 2 timer.", estimated=True, balance=True)
    return None


def _adjustment_step(flow: dict, measurement: dict, additions: list[dict],
                     volume: float, now: datetime) -> dict:
    """Guide requested rises in Sundance order, with a new reading after each dose."""
    targets = flow["meta"]["targets"]
    flow_additions = [item for item in additions if item["flow_id"] == flow["id"]]
    scale = volume / 1000
    oxygen_added = latest_product_addition(flow_additions, "active_oxygen")
    if oxygen_added:
        until = parse_time(oxygen_added["added_at"]) + timedelta(minutes=20)
        if now < until:
            return message("wait", "La Active Oxygen sirkulere",
                           "Vent til pumpesyklusen er ferdig før ny O₂-måling.", until=iso_time(until))
        if (measurement.get("active_oxygen_mg_l") is None or
                parse_time(measured_at_for(measurement, "active_oxygen_mg_l")) < until):
            return message("measure", "Mål O₂ på nytt", "Registrer faktisk O₂-verdi etter tilsetningen.")
        result = measurement["active_oxygen_mg_l"]
        return message("done", "O₂ er kontrollmålt",
                       f"Målt {result:g} mg/L mot ønsket {targets['active_oxygen_mg_l']:g} mg/L. "
                       "Sundance oppgir ingen doseformel for en bestemt O₂-økning. Vurder ny rutine ved behov.")
    for field, label, products, hours in (
        ("alkalinity_mg_l", "alkalinitet", ("alka_up", "alka_down"), 2),
        ("ph", "pH", ("ph_up", "ph_down"), 2),
    ):
        if measurement.get(field) is None or not recent_measurement(measurement, now, field=field):
            return message("measure", f"Mål {label}", f"Registrer {label} før neste kjemikalie.")
        previous = next((item for item in flow_additions if item["product"] in products), None)
        if previous:
            until = parse_time(previous["added_at"]) + timedelta(hours=hours)
            if now < until:
                return message("wait", f"La {label} stabilisere seg",
                               f"Vent 2 timer og mål {label} på nytt før neste produkt.", until=iso_time(until))
            if parse_time(measured_at_for(measurement, field)) < until:
                return message("measure", f"Mål {label} på nytt",
                               f"Registrer en ny {label}-verdi før neste produkt.")
        current = measurement[field]
        target = targets.get(field)
        if field == "ph":
            previous_ta = next((item for item in flow_additions if item["product"] in ("alka_up", "alka_down")), None)
            if previous_ta and parse_time(measured_at_for(measurement, "ph")) < parse_time(previous_ta["added_at"]) + timedelta(hours=2):
                return message("measure", "Mål pH på nytt", "Alkalinitetsjustering kan endre pH. Registrer en ny pH-verdi.")
        if field == "alkalinity_mg_l":
            if current < 80:
                target = max(target or 80, 80)
            elif current > 120:
                target = 120
        elif current < 7.0:
            target = max(target or 7.0, 7.0)
        elif current > 7.4:
            target = 7.4
        if target is not None and current >= target and field in targets and current <= (120 if field == "alkalinity_mg_l" else 7.4):
            continue
        if target is None or abs(current - target) < (1 if field == "alkalinity_mg_l" else 0.05):
            continue
        if field == "alkalinity_mg_l":
            if current < target:
                amount = min(target - current, 30) / 30 * 60 * scale
                return dose("alka_up", amount, f"Hev alkalinitet fra {current:g} mot {target:g} mg/L, ett trinn av gangen.",
                            SPACARE_ALKA_UP, "Løs opp i plastbøtte. Tilsett med pumpen på; mål på nytt etter 2 timer.", True, True)
            amount = min(current - target, 20) / 20 * 30 * scale
            return dose("alka_down", amount, f"Senk alkalinitet fra {current:g} mot {target:g} mg/L, ett trinn av gangen.",
                        SPACARE_ALKA_DOWN, "Løs opp i plastbøtte. Pumper av i 1 time; start sirkulasjon og mål etter 2 timer.", True, True)
        if current < target:
            amount = min(target - current, 0.2) / 0.2 * 10 * scale
            return dose("ph_up", amount, f"Hev pH fra {current:g} mot {target:g}, ett trinn av gangen.",
                        SPACARE_PH_UP, "Tilsett med pumpen på. Mål på nytt etter 2 timer.", True, True)
        amount = min(current - target, 0.2) / 0.2 * 6 * scale
        return dose("ph_down", amount, f"Senk pH fra {current:g} mot {target:g}, ett trinn av gangen.",
                    SPACARE_PH_DOWN, "Tilsett med pumpen på. Mål på nytt etter 2 timer.", True, True)

    last_balance = next((item for item in flow_additions if item["product"] in
                         ("alka_up", "alka_down", "ph_up", "ph_down")), None)
    chlorine_target = targets.get("chlorine_mg_l")
    if chlorine_target is not None:
        if measurement.get("chlorine_mg_l") is None or not recent_measurement(measurement, now, field="chlorine_mg_l"):
            return message("measure", "Mål klor", "Registrer fritt klor før MiniChlor beregnes.")
        if last_balance and parse_time(measured_at_for(measurement, "chlorine_mg_l")) < parse_time(last_balance["added_at"]) + timedelta(hours=2):
            return message("measure", "Mål klor på nytt", "Mål etter justering av alkalinitet og pH.")
        if too_high(measurement, "chlorine_mg_l", 3, now):
            return message("measure", "For mye klor", "Ikke tilsett mer MiniChlor. Vent til fritt klor er høyst 3 mg/L og mål på nytt før bading.")
        previous = latest_product_addition(flow_additions, "mini_chlor")
        if previous:
            until = parse_time(previous["added_at"]) + timedelta(minutes=20)
            if now < until:
                return message("wait", "La MiniChlor sirkulere", "Vent 20 minutter med pumpe 1 på før ny klormåling.", until=iso_time(until))
            if parse_time(measured_at_for(measurement, "chlorine_mg_l")) < until:
                return message("measure", "Mål klor på nytt", "Registrer faktisk klorverdi før neste produkt.")
        if measurement["chlorine_mg_l"] + 0.05 < chlorine_target:
            last_oxygen = latest_product_addition(additions, "active_oxygen")
            if last_oxygen and now < parse_time(last_oxygen["added_at"]) + timedelta(minutes=20):
                until = parse_time(last_oxygen["added_at"]) + timedelta(minutes=20)
                return message("wait", "Vent før MiniChlor", "Active Oxygen og MiniChlor skal ikke tilsettes samtidig.", until=iso_time(until))
            delta = chlorine_target - measurement["chlorine_mg_l"]
            amount = chlorine_estimate(delta, volume, 15, measurement["chlorine_mg_l"])["amount_ml"]
            return dose("mini_chlor", amount,
                        f"Teoretisk dose for klor fra {measurement['chlorine_mg_l']:g} mot {chlorine_target:g} mg/L. "
                        "Vannet kan forbruke klor; mål på nytt etterpå.",
                        SPACARE_MINICHLOR, estimated=True, balance=True)

    oxygen_target = targets.get("active_oxygen_mg_l")
    if oxygen_target is not None:
        if too_high(measurement, "active_oxygen_mg_l", 8, now):
            return message("measure", "For mye aktivt oksygen", "Ikke tilsett mer Active Oxygen. Vent og mål på nytt før bading.")
        last_chlorine = latest_product_addition(additions, "mini_chlor")
        if last_chlorine:
            until = parse_time(last_chlorine["added_at"]) + timedelta(minutes=20)
            if now < until:
                return message("wait", "Vent før Active Oxygen",
                               "MiniChlor og Active Oxygen skal ikke tilsettes samtidig. La pumpe 1 gå ut 20-minuttersyklusen.",
                               until=iso_time(until))
        if measurement.get("active_oxygen_mg_l") is None or not recent_measurement(measurement, now, field="active_oxygen_mg_l"):
            return message("measure", "Mål O₂", "Registrer aktivt oksygen før dosering.")
        if last_chlorine and parse_time(measured_at_for(measurement, "active_oxygen_mg_l")) < parse_time(last_chlorine["added_at"]) + timedelta(minutes=20):
            return message("measure", "Mål O₂ etter klor", "Registrer O₂ etter at MiniChlor har sirkulert i 20 minutter.")
        if measurement["active_oxygen_mg_l"] + 0.05 < oxygen_target:
            return dose("active_oxygen", 45,
                        f"Ønsket O₂: {oxygen_target:g} mg/L. Sundance anbefaler minst 3 skjeer før bad. "
                        "Det finnes ingen dokumentert omregning fra ml til O₂-økning; mål igjen etterpå.",
                        SUNDANCE_GUIDE, "Tilsett over filteret med pumpe 1 på. Hold lokket åpent i 20 minutter.",
                        estimated=False, balance=True)
    return message("done", "Justeringen er ferdig", "Verdiene er kontrollert. Mål igjen ved neste stell.")


def recommendation(flow: dict | None, settings: dict, measurement: dict | None,
                   additions: list[dict], now: datetime | None = None) -> dict:
    now = now or utc_now()
    volume = settings.get("volume_liters")
    if not volume:
        return message("setup", "Angi bassengvolum", "Legg inn antall liter før vi beregner doser.")
    if not flow:
        if not measurement or not measured_at_for(measurement):
            return message("measure", "Mål og velg", "Bruk teststrips eller måler, og velg deretter Bade nå eller Ferie. Etter bad og Nytt vann kan startes direkte.")
        return message("choose", "Hva vil du gjøre?", "Velg Bade nå eller Ferie etter målingen. Etter bad og Nytt vann trenger ikke måling først.")

    kind, step = flow["kind"], flow["step"]
    flow_id = flow["id"]
    if kind not in MODES:
        return message("choose", "Velg en rutine", "Velg det du skal gjøre med badet i dag.")

    if kind == "new_water":
        if step == 0:
            return dose("no_scale", 50 * volume / 1000, "Tilsett No Scale i kaldt, nytt vann.")
        if step == 1:
            added = latest_product_addition(additions, "no_scale", flow_id)
            until = parse_time(added["added_at"]) + timedelta(minutes=10) if added else now
            if now < until:
                return message("wait", "La No Scale virke alene", "Vent 10 minutter før MiniChlor.", until=iso_time(until))
        if step == 1:
            return dose("mini_chlor", 30, "Tilsett 2 Sundance-måleskjeer à 15 ml.")
        if step == 2:
            return message("check", "Legg inn SunPurity", "Sett sølvionepatronen i skimmeren.")
        return message("done", "Nytt vann er klart for neste måling",
                       "Når vannet er varmt, mål alkalinitet først og deretter pH. Velg Ukentlig for justering.")

    if kind == "after_bath":
        if step == 0:
            if too_high(measurement, "chlorine_mg_l", 3, now):
                return message("done", "Ikke tilsett mer klor", "Siste test tyder på høyt klor. Vent og mål på nytt før mer MiniChlor.")
            separation = _wait_after_oxygen(additions, now)
            if separation:
                return separation
            return dose("mini_chlor", 5 * volume / 1000,
                        "Startestimat fra SpaCare-etiketten. Sundance sier at behovet avhenger av bruk; mål igjen neste dag.",
                        SPACARE_MINICHLOR, estimated=True)
        return message("done", "Etter bad er registrert", "Mål vannet igjen neste dag.")

    if kind == "holiday" and step >= 4:
        return_date = date.fromisoformat(flow["meta"]["return_date"])
        if now.astimezone().date() >= return_date:
            if (recent_measurement(measurement, now) and
                    parse_time(measured_at_for(measurement)) > parse_time(flow["updated_at"]) and
                    parse_time(measured_at_for(measurement)).astimezone().date() >= return_date):
                return message("return", "Velkommen hjem", "Ny måling er registrert. Avslutt feriemodus.")
            return message("measure", "Velkommen hjem", "Mål vannet på nytt før feriemodus avsluttes.")
        return message("away", "Feriemodus på", "Mål vannet på nytt når du kommer hjem.")

    if not recent_measurement(measurement, now):
        return message("measure", "Ny måling trengs", "Mål vannet med teststrips eller måler før denne rutinen.")

    if kind == "adjust":
        return _adjustment_step(flow, measurement, additions, volume, now)

    if kind == "weekly":
        if step == 0:
            recheck = _balance_recheck(flow_id, measurement, additions, now)
            if recheck:
                return recheck
            balance = _balance_step(measurement, volume, now)
            if balance:
                return balance
            if too_high(measurement, "chlorine_mg_l", 3, now):
                return message("measure", "For mye klor", "Ikke tilsett ukentlig MiniChlor. Vent og mål klor på nytt.")
            separation = _wait_after_oxygen(additions, now)
            if separation:
                return separation
            return dose("mini_chlor", 30, "Ukentlig dose: 2 Sundance-måleskjeer à 15 ml.")
        return message("done", "Ukentlig stell ferdig", "Mål vannet igjen ved neste stell eller bading.")

    if kind == "before_bath":
        if step == 0:
            if too_high(measurement, "chlorine_mg_l", 3, now):
                return message("measure", "For mye klor", "Ikke tilsett mer MiniChlor eller bad nå. Vent til fritt klor er høyst 3 mg/L, og mål på nytt.")
            if too_high(measurement, "active_oxygen_mg_l", 8, now):
                return message("measure", "For mye aktivt oksygen", "Ikke tilsett mer Active Oxygen eller bad nå. Vent og mål på nytt.")
            recheck = _balance_recheck(flow_id, measurement, additions, now)
            if recheck:
                return recheck
            balance = _balance_step(measurement, volume, now)
            if balance:
                return balance
            if not recent_measurement(measurement, now, field="chlorine_mg_l"):
                return message("measure", "Mål klor", "Registrer klor med teststrips eller måler før bading.")
            chlorine_added = latest_product_addition(additions, "mini_chlor")
            if chlorine_added:
                until = parse_time(chlorine_added["added_at"]) + timedelta(minutes=20)
                if now < until:
                    return message("wait", "La MiniChlor sirkulere", "Vent 20 minutter med pumpe 1 på før ny klormåling.", until=iso_time(until))
                if not measured_at_for(measurement, "chlorine_mg_l") or parse_time(measured_at_for(measurement, "chlorine_mg_l")) < until:
                    return message("measure", "Mål klor på nytt", "Registrer en ny klorvurdering etter MiniChlor før neste produkt.")
            change = strip_change(measurement, "chlorine_mg_l", now)
            chlorine = measurement.get("chlorine_mg_l")
            delta = change if change is not None else max(0, 1 - chlorine) if chlorine is not None else 0
            if delta > 0:
                previous_oxygen = latest_product_addition(additions, "active_oxygen")
                if previous_oxygen:
                    until = parse_time(previous_oxygen["added_at"]) + timedelta(minutes=20)
                    if now < until:
                        return message("wait", "Vent før MiniChlor", "Active Oxygen og MiniChlor skal ikke tilsettes samtidig.", until=iso_time(until))
                amount = chlorine_estimate(delta, volume, 15, chlorine)["amount_ml"]
                return dose("mini_chlor", amount, f"Teoretisk estimat for ønsket klorøkning på {delta:g} mg/L. Vannet kan forbruke klor; mål på nytt etterpå.",
                            SPACARE_MINICHLOR, estimated=True, balance=True)
            previous = latest_product_addition(additions, "mini_chlor")
            if previous:
                until = parse_time(previous["added_at"]) + timedelta(minutes=20)
                if now < until:
                    return message("wait", "Vent før Active Oxygen",
                                   "MiniChlor og Active Oxygen skal ikke tilsettes samtidig. La pumpe 1 gå ut 20-minuttersyklusen.",
                                   until=iso_time(until))
            bathers = int(flow["meta"].get("bathers", 1))
            count = 3 + max(0, bathers - 3)
            oxygen_change = strip_change(measurement, "active_oxygen_mg_l", now)
            oxygen_note = (f" Ønsket O₂-økning er {oxygen_change:g} mg/L, men ingen dokumentert omregning til skjeer finnes; mål på nytt etterpå."
                           if oxygen_change and oxygen_change > 0 else "")
            return dose("active_oxygen", 15 * count,
                        f"Minst {count} Sundance-måleskjeer à 15 ml for {bathers} badende. "
                        "Tilsett ikke samtidig med MiniChlor." + oxygen_note)
        return message("done", "Før bad er registrert", "Beregnede doser bekrefter ikke at vannet er klart for bading. Kontroller vannet etter behov.")

    if kind == "holiday":
        if step == 0:
            recheck = _balance_recheck(flow_id, measurement, additions, now)
            if recheck:
                return recheck
            balance = _balance_step(measurement, volume, now)
            if balance:
                return balance
            return message("check", "Kontroller filteret", "Rengjør filteret ved behov før lengre fravær.")
        if step == 1:
            if too_high(measurement, "chlorine_mg_l", 3, now):
                return message("measure", "For mye klor", "Ikke tilsett mer MiniChlor. Vent og mål klor på nytt før feriedosen.")
            separation = _wait_after_oxygen(additions, now)
            if separation:
                return separation
            return dose("mini_chlor", 30, "Ferie: 2 Sundance-måleskjeer à 15 ml.")
        if step == 2:
            added = latest_product_addition(additions, "mini_chlor", flow_id)
            until = parse_time(added["added_at"]) + timedelta(minutes=5) if added else now
            if now < until:
                return message("wait", "La MiniChlor virke", "Vent 5 minutter med pumpene på før OxyPlus.", until=iso_time(until))
        if step == 2:
            return dose("oxyplus", 20 * volume / 1000,
                        "Ferie: OxyPlus 20 ml per 1000 liter etter MiniChlor.")
        if step == 3:
            return message("check", "Vurder lavere temperatur",
                           "Sundance foreslår omtrent 28 °C ved lengre fravær. La filtreringen fortsette.")
        return message("away", "Feriemodus på", "Mål vannet på nytt når du kommer hjem.")

    return message("choose", "Velg en rutine", "Velg det du skal gjøre med badet i dag.")


def chlorine_estimate(delta_mg_l: float, volume_liters: float, scoop_ml: float,
                      measured_chlorine: float | None) -> dict:
    """Ideal free-chlorine yield. Dichlor dihydrate is ~55% available chlorine."""
    amount_ml = delta_mg_l * volume_liters / (1000 * 0.55)
    scoops = amount_ml / scoop_ml
    return {
        "product": "mini_chlor", "amount_ml": round(amount_ml, 3),
        "scoops": round(scoops, 4), "delta_mg_l": delta_mg_l,
        "projected_mg_l": round(measured_chlorine + delta_mg_l, 2) if measured_chlorine is not None else None,
        "hard_to_measure": scoops < 0.25,
        "warning": "Kun et teoretisk estimat. Faktisk klorøkning avhenger av vannet. Mål på nytt etter tilsetning.",
    }
