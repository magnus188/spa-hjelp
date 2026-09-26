"""Sundance Norway / SpaCare recipes. Values are millilitres unless stated."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


SUNDANCE_GUIDE = "https://www.sundance.no/vannpleie-med-sunpurity-og-active-oxygen/"
SPACARE_MINICHLOR = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-MiniChlor.pdf"
SPACARE_ALKA_UP = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-Alka-Up-1.pdf"
SPACARE_ALKA_DOWN = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-Alka-Down-1.pdf"
SPACARE_PH_UP = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-pH-Up-Granular-1.pdf"
SPACARE_PH_DOWN = "https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-pH-Down-Granular.pdf"

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
    "weekly": "Ukentlig",
    "before_bath": "Før bad",
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


def recent_measurement(measurement: dict | None, now: datetime, hours: int = 24) -> bool:
    measured = parse_time(measurement["measured_at"]) if measurement else None
    return bool(measured and timedelta(0) <= now - measured <= timedelta(hours=hours))


def _balance_step(measurement: dict, volume_liters: float) -> dict | None:
    scale = volume_liters / 1000
    ta = measurement["alkalinity_mg_l"]
    ph = measurement["ph"]
    if ta is None:
        return message("measure", "Mål alkalinitet", "Registrer alkalinitet før pH justeres.")
    if ta < 80:
        # Label: 4 x 15 ml raises about 30 mg/L per 1000 L. Start with at most one label step.
        amount = min(80 - ta, 30) / 30 * 60 * scale
        return dose("alka_up", amount, "Hev alkaliniteten gradvis mot 80–120 mg/L.",
                    SPACARE_ALKA_UP,
                    "Løs opp i en plastbøtte. Tilsett med pumpen på. Mål på nytt etter 2 timer.",
                    estimated=True, balance=True)
    if ta > 120:
        # Label: 2 x 15 ml lowers about 20 mg/L per 1000 L.
        amount = min(ta - 120, 20) / 20 * 30 * scale
        return dose("alka_down", amount, "Senk alkaliniteten gradvis mot 80–120 mg/L.",
                    SPACARE_ALKA_DOWN,
                    "Løs opp i en plastbøtte. Pumpen skal være av i 1 time. Start deretter sirkulasjon; mål på nytt etter 2 timer.",
                    estimated=True, balance=True)
    if ph is None:
        return message("measure", "Mål pH", "Registrer pH etter at alkaliniteten er kontrollert.")
    if ph < 7.0:
        amount = min(7.0 - ph, 0.2) / 0.2 * 10 * scale
        return dose("ph_up", amount, "Hev pH gradvis mot 7,0–7,4.", SPACARE_PH_UP,
                    "Tilsett med pumpen på. Mål på nytt etter 2 timer.", estimated=True, balance=True)
    if ph > 7.4:
        amount = min(ph - 7.4, 0.2) / 0.2 * 6 * scale
        return dose("ph_down", amount, "Senk pH gradvis mot 7,0–7,4.", SPACARE_PH_DOWN,
                    "Tilsett med pumpen på. Mål på nytt etter 2 timer.", estimated=True, balance=True)
    return None


def recommendation(flow: dict | None, settings: dict, measurement: dict | None,
                   additions: list[dict], now: datetime | None = None) -> dict:
    now = now or utc_now()
    volume = settings.get("volume_liters")
    if not volume:
        return message("setup", "Angi bassengvolum", "Legg inn antall liter før vi beregner doser.")
    if not flow:
        if not measurement:
            return message("measure", "Ny måling trengs", "Registrer pH, alkalinitet og klor for å starte.")
        return message("choose", "Velg en rutine", "Velg det du skal gjøre med badet i dag.")

    kind, step = flow["kind"], flow["step"]
    flow_id = flow["id"]
    if kind not in MODES:
        return message("choose", "Velg en rutine", "Velg det du skal gjøre med badet i dag.")

    if kind == "holiday" and step == 0 and (
            not measurement or parse_time(measurement["measured_at"]) <= parse_time(flow["created_at"])):
        return message("measure", "Mål vannet før ferie", "Registrer nye teststripsverdier før du kontrollerer filteret.")

    # Sundance asks for a measurement before adding water-care products.
    if not recent_measurement(measurement, now) and not (kind == "holiday" and step >= 4):
        return message("measure", "Ny måling trengs", "Mål vannet før du tilsetter kjemikalier.")

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

    if kind == "weekly":
        if step == 0:
            correction = next((item for item in additions if item["flow_id"] == flow_id and
                               item["product"] in ("alka_up", "alka_down", "ph_up", "ph_down")), None)
            if correction:
                until = parse_time(correction["added_at"]) + timedelta(hours=2)
                if now < until:
                    return message("wait", "Vent før ny måling", "Mål alkalinitet og pH på nytt etter 2 timer.", until=iso_time(until))
                if parse_time(measurement["measured_at"]) < until:
                    return message("measure", "Mål vannet på nytt", "Registrer nye verdier før neste dose.")
            balance = _balance_step(measurement, volume)
            if balance:
                return balance
            return dose("mini_chlor", 30, "Ukentlig dose: 2 Sundance-måleskjeer à 15 ml.")
        return message("done", "Ukentlig stell ferdig", "Mål vannet igjen ved neste stell eller bading.")

    if kind == "before_bath":
        if step == 0:
            bathers = int(flow["meta"].get("bathers", 1))
            count = 3 + max(0, bathers - 3)
            return dose("active_oxygen", 15 * count,
                        f"Minst {count} Sundance-måleskjeer à 15 ml for {bathers} badende. "
                        "Tilsett ikke samtidig med MiniChlor.")
        return message("done", "Før bad er registrert", "Kontroller vannet etter behov.")

    if kind == "after_bath":
        if step == 0:
            return dose("mini_chlor", 5 * volume / 1000,
                        "Startestimat fra SpaCare-etiketten. Sundance sier at behovet avhenger av bruk; mål igjen neste dag.",
                        SPACARE_MINICHLOR, estimated=True)
        return message("done", "Etter bad er registrert", "Mål vannet igjen neste dag.")

    if kind == "holiday":
        if step == 0:
            return message("check", "Kontroller filteret", "Rengjør filteret ved behov før lengre fravær.")
        if step == 1:
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
        return_date = date.fromisoformat(flow["meta"]["return_date"])
        if now.astimezone().date() >= return_date:
            if (recent_measurement(measurement, now) and
                    parse_time(measurement["measured_at"]) > parse_time(flow["updated_at"]) and
                    parse_time(measurement["measured_at"]).astimezone().date() >= return_date):
                return message("return", "Velkommen hjem", "Ny måling er registrert. Avslutt feriemodus.")
            return message("measure", "Velkommen hjem", "Mål vannet på nytt før feriemodus avsluttes.")
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
