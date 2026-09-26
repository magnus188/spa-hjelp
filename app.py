"""Local SpaCare calculator and Home Assistant summary API."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from rules import (MODES, PRODUCTS, chlorine_estimate, iso_time, parse_time,
                   recent_measurement, recommendation, utc_now)
from storage import (active_flow, advance_flow, connect, finish_flow, get_settings,
                     init_db, latest_additions, latest_measurement, save_addition,
                     save_measurement, save_settings, start_flow)


def _number(value, name: str, low: float, high: float, required: bool = True) -> float | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{name} må fylles ut.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} må være et tall.") from None
    if not low <= number <= high:
        raise ValueError(f"{name} må være mellom {low:g} og {high:g}.")
    return number


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = os.getenv("SPA_DB_PATH", str(Path(__file__).parent / "data" / "spa.sqlite3"))
    if test_config:
        app.config.update(test_config)
    init_db(app.config["DB_PATH"])

    @app.errorhandler(ValueError)
    def bad_value(error):
        return jsonify(error=str(error)), 400

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/card")
    def card():
        return render_template("card.html", spa_url=os.getenv("SPA_HA_URL", "/"))

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/summary")
    def summary():
        with connect(app.config["DB_PATH"]) as db:
            settings = get_settings(db)
            measurement = latest_measurement(db)
            additions = latest_additions(db)
            flow = active_flow(db)
        now = utc_now()
        next_step = recommendation(flow, settings, measurement, additions, now)
        if next_step["type"] == "dose":
            scoop_ml = settings["scoops"][next_step["product"]]
            next_step["scoop_ml"] = scoop_ml
            next_step["scoops"] = round(next_step["amount_ml"] / scoop_ml, 4)
            next_step["hard_to_measure"] = next_step["scoops"] < 0.25
        last = additions[0] if additions else None
        cover_until = parse_time(last["added_at"]) + timedelta(minutes=20) if last else None
        cover_active = bool(cover_until and cover_until > now)
        payload = {
            "volume_liters": settings["volume_liters"], "scoops": settings["scoops"],
            "products": PRODUCTS, "modes": MODES,
            "measurement": measurement,
            "measurements": {
                "ph": measurement["ph"] if measurement else None,
                "alkalinity_mg_l": measurement["alkalinity_mg_l"] if measurement else None,
                "chlorine_mg_l": measurement["chlorine_mg_l"] if measurement else None,
                "active_oxygen_mg_l": measurement["active_oxygen_mg_l"] if measurement else None,
                "measured_at": measurement["measured_at"] if measurement else None,
                "source": measurement["source"] if measurement else None,
                "field_measured_at": measurement["field_measured_at"] if measurement else None,
            },
            "last_additions": additions[:3],
            "last_added": last,
            "next_step": next_step,
            "active_flow": flow,
            "holiday_return_on": flow["meta"].get("return_date") if flow and flow["kind"] == "holiday" else None,
            "cover_open_until": iso_time(cover_until) if cover_active else None,
            "cover_open": cover_active,
            "server_time": iso_time(now),
        }
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/history")
    def history():
        with connect(app.config["DB_PATH"]) as db:
            additions = latest_additions(db, 100)
        return jsonify(additions=additions)

    @app.post("/api/settings")
    def set_settings():
        body = request.get_json(silent=True) or {}
        volume = _number(body.get("volume_liters"), "Volum", 100, 10000)
        with connect(app.config["DB_PATH"]) as db:
            current = get_settings(db)
            scoops = current["scoops"]
            for key, value in (body.get("scoops") or {}).items():
                if key not in PRODUCTS:
                    raise ValueError("Ukjent produkt.")
                scoops[key] = _number(value, f"Måleskje for {PRODUCTS[key]['name']}", 0.1, 500)
            save_settings(db, volume, scoops)
        return jsonify(ok=True)

    @app.post("/api/measurements")
    def add_measurement():
        body = request.get_json(silent=True) or {}
        values = {
            "ph": _number(body.get("ph"), "pH", 0, 14, required=False),
            "alkalinity_mg_l": _number(body.get("alkalinity_mg_l"), "Alkalinitet", 0, 500, required=False),
            "chlorine_mg_l": _number(body.get("chlorine_mg_l"), "Klor", 0, 20, required=False),
            "active_oxygen_mg_l": _number(body.get("active_oxygen_mg_l"), "Aktivt oksygen", 0, 50, required=False),
            "source": "manual",
        }
        if all(values[key] is None for key in ("ph", "alkalinity_mg_l", "chlorine_mg_l", "active_oxygen_mg_l")):
            raise ValueError("Legg inn minst én måleverdi.")
        with connect(app.config["DB_PATH"]) as db:
            save_measurement(db, values)
        return jsonify(ok=True), 201

    @app.post("/api/flows")
    def begin_flow():
        body = request.get_json(silent=True) or {}
        kind = body.get("kind")
        if kind not in MODES:
            raise ValueError("Velg en gyldig rutine.")
        meta = {}
        if kind == "before_bath":
            meta["bathers"] = int(_number(body.get("bathers", 1), "Antall badende", 1, 20))
        if kind == "holiday":
            try:
                departure = date.fromisoformat(body.get("departure_date", ""))
                return_date = date.fromisoformat(body.get("return_date", ""))
            except ValueError:
                raise ValueError("Velg avreise- og returdato.") from None
            if return_date < departure:
                raise ValueError("Returdato må være etter avreise.")
            meta = {"departure_date": departure.isoformat(), "return_date": return_date.isoformat()}
        with connect(app.config["DB_PATH"]) as db:
            if kind == "adjust":
                measurement = latest_measurement(db)
                limits = {
                    "alkalinity_mg_l": ("alkalinitet", 100, 120),
                    "ph": ("pH", 1, 7.4),
                    "chlorine_mg_l": ("klor", 3, 20),
                    "active_oxygen_mg_l": ("O₂", 10, 10),
                }
                raw = body.get("increments") or {}
                if not isinstance(raw, dict) or any(key not in limits for key in raw):
                    raise ValueError("Ukjent måleverdi i justeringen.")
                targets = {}
                for field, (label, maximum_rise, maximum_target) in limits.items():
                    value = raw.get(field)
                    if value in (None, "", 0):
                        continue
                    rise = _number(value, f"Økning i {label}", 0.01, maximum_rise)
                    if not measurement or measurement[field] is None or not recent_measurement(measurement, utc_now(), field=field):
                        raise ValueError(f"Registrer en ny måling av {label} først.")
                    target = round(measurement[field] + rise, 3)
                    if target > maximum_target:
                        raise ValueError(f"Ønsket {label} må være høyst {maximum_target:g}.")
                    targets[field] = target
                if not targets:
                    raise ValueError("Velg minst én ønsket økning.")
                meta["targets"] = targets
            start_flow(db, kind, meta)
        return jsonify(ok=True), 201

    def enforce_separation(product: str, additions: list[dict]) -> None:
        opposite = {"mini_chlor": "active_oxygen", "active_oxygen": "mini_chlor"}.get(product)
        if opposite:
            last_opposite = next((item for item in additions if item["product"] == opposite), None)
            if last_opposite and utc_now() - parse_time(last_opposite["added_at"]) < timedelta(minutes=20):
                raise ValueError("MiniChlor og Active Oxygen skal ikke tilsettes samtidig. Vent til sirkulasjonssyklusen er over.")

    @app.post("/api/confirm")
    def confirm():
        with connect(app.config["DB_PATH"]) as db:
            settings = get_settings(db)
            measurement = latest_measurement(db)
            additions = latest_additions(db)
            flow = active_flow(db)
            if not flow:
                raise ValueError("Velg en rutine først.")
            step = recommendation(flow, settings, measurement, additions)
            if step["type"] == "dose":
                enforce_separation(step["product"], additions)
                save_addition(db, step["product"], step["amount_ml"],
                              settings["scoops"][step["product"]], flow["kind"], flow["id"])
                if not step.get("balance"):
                    advance_flow(db, flow["id"])
            elif step["type"] == "check":
                advance_flow(db, flow["id"])
            elif step["type"] in ("done", "return"):
                finish_flow(db, flow["id"])
            else:
                raise ValueError("Dette steget kan ikke bekreftes ennå.")
        return jsonify(ok=True)

    @app.post("/api/chlorine-estimate")
    def estimate_chlorine():
        body = request.get_json(silent=True) or {}
        delta = _number(body.get("delta_mg_l"), "Ønsket klorøkning", 0.01, 3)
        with connect(app.config["DB_PATH"]) as db:
            settings = get_settings(db)
            measurement = latest_measurement(db)
        if not settings["volume_liters"]:
            raise ValueError("Angi bassengvolum først.")
        if not measurement or measurement["chlorine_mg_l"] is None or not recent_measurement(measurement, utc_now(), field="chlorine_mg_l"):
            raise ValueError("Registrer en ny klormåling først.")
        return jsonify(chlorine_estimate(delta, settings["volume_liters"],
                                         settings["scoops"]["mini_chlor"], measurement["chlorine_mg_l"]))

    @app.post("/api/chlorine-add")
    def add_chlorine():
        body = request.get_json(silent=True) or {}
        delta = _number(body.get("delta_mg_l"), "Ønsket klorøkning", 0.01, 3)
        with connect(app.config["DB_PATH"]) as db:
            settings = get_settings(db)
            measurement = latest_measurement(db)
            additions = latest_additions(db)
            if not settings["volume_liters"] or not measurement or measurement["chlorine_mg_l"] is None:
                raise ValueError("Registrer volum og en klormåling først.")
            if not recent_measurement(measurement, utc_now(), field="chlorine_mg_l"):
                raise ValueError("Registrer en ny klormåling først.")
            enforce_separation("mini_chlor", additions)
            estimate = chlorine_estimate(delta, settings["volume_liters"],
                                         settings["scoops"]["mini_chlor"], measurement["chlorine_mg_l"])
            save_addition(db, "mini_chlor", estimate["amount_ml"], settings["scoops"]["mini_chlor"],
                          "chlorine_adjust", None)
        return jsonify(ok=True, estimate=estimate), 201

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
