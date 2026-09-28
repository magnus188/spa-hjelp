"""Small SQLite store for one household spa."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from itertools import chain
from pathlib import Path
from typing import Iterator

from rules import PRODUCTS, utc_now


def stamp() -> str:
    return utc_now().isoformat(timespec="microseconds")


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              volume_liters REAL,
              scoops_json TEXT NOT NULL,
              water_changed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS measurements (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              measured_at TEXT NOT NULL,
              ph REAL,
              alkalinity_mg_l REAL,
              chlorine_mg_l REAL,
              active_oxygen_mg_l REAL,
              method TEXT NOT NULL DEFAULT 'legacy',
              adjustments_json TEXT,
              source TEXT NOT NULL CHECK (source IN ('manual', 'labcom'))
            );
            CREATE TABLE IF NOT EXISTS flows (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              step INTEGER NOT NULL DEFAULT 0,
              meta_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS additions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              product TEXT NOT NULL,
              amount_ml REAL NOT NULL,
              scoop_ml REAL NOT NULL,
              context TEXT NOT NULL,
              flow_id INTEGER REFERENCES flows(id),
              added_at TEXT NOT NULL
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(measurements)")}
        if "active_oxygen_mg_l" not in columns:
            db.execute("ALTER TABLE measurements ADD COLUMN active_oxygen_mg_l REAL")
        if "method" not in columns:
            db.execute("ALTER TABLE measurements ADD COLUMN method TEXT NOT NULL DEFAULT 'legacy'")
        if "adjustments_json" not in columns:
            db.execute("ALTER TABLE measurements ADD COLUMN adjustments_json TEXT")
        settings_columns = {row["name"] for row in db.execute("PRAGMA table_info(settings)")}
        if "water_changed_at" not in settings_columns:
            db.execute("ALTER TABLE settings ADD COLUMN water_changed_at TEXT")
        db.execute("INSERT OR IGNORE INTO settings (id, volume_liters, scoops_json) VALUES (1, 1500, ?)",
                   (json.dumps({key: item["default_scoop_ml"] for key, item in PRODUCTS.items()}),))
        db.execute("UPDATE settings SET volume_liters = 1500 WHERE id = 1 AND volume_liters IS NULL")


def get_settings(db: sqlite3.Connection) -> dict:
    row = db.execute("SELECT volume_liters, scoops_json FROM settings WHERE id = 1").fetchone()
    return {"volume_liters": row["volume_liters"], "scoops": json.loads(row["scoops_json"])}


def save_settings(db: sqlite3.Connection, volume_liters: float, scoops: dict) -> None:
    db.execute("UPDATE settings SET volume_liters = ?, scoops_json = ? WHERE id = 1",
               (volume_liters, json.dumps(scoops)))


def latest_measurement(db: sqlite3.Connection) -> dict | None:
    fields = ("ph", "alkalinity_mg_l", "chlorine_mg_l", "active_oxygen_mg_l")
    water_changed_at = db.execute("SELECT water_changed_at FROM settings WHERE id = 1").fetchone()[0]
    rows = db.execute("SELECT * FROM measurements WHERE ? IS NULL OR measured_at > ? ORDER BY measured_at DESC, id DESC",
                      (water_changed_at, water_changed_at))
    first = rows.fetchone()
    if not first:
        return None
    result = dict(first)
    field_measured_at = {field: None for field in fields}
    adjustments = {field: None for field in fields}
    field_method = {field: None for field in fields}
    for row in chain((first,), rows):
        strip = json.loads(row["adjustments_json"] or "{}")
        for field in fields:
            if field_measured_at[field] is None and (row[field] is not None or field in strip):
                result[field] = row[field]
                adjustments[field] = strip.get(field)
                field_measured_at[field] = row["measured_at"]
                field_method[field] = row["method"]
        if all(field_measured_at.values()):
            break
    result["field_measured_at"] = field_measured_at
    result["adjustments"] = adjustments
    result["field_method"] = field_method
    result["care_measured_at"] = max(
        (field_measured_at[field] for field in fields[:3] if field_measured_at[field]),
        default=None,
    )
    return result


def save_measurement(db: sqlite3.Connection, values: dict) -> None:
    db.execute("""INSERT INTO measurements
                  (measured_at, ph, alkalinity_mg_l, chlorine_mg_l, active_oxygen_mg_l,
                   method, adjustments_json, source)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
               (stamp(), values.get("ph"), values.get("alkalinity_mg_l"),
                values.get("chlorine_mg_l"), values.get("active_oxygen_mg_l"),
                values.get("method", "legacy"), json.dumps(values.get("adjustments")) if values.get("adjustments") is not None else None,
                values.get("source", "manual")))


def latest_additions(db: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = db.execute("SELECT * FROM additions ORDER BY added_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def save_addition(db: sqlite3.Connection, product: str, amount_ml: float,
                  scoop_ml: float, context: str, flow_id: int | None) -> None:
    db.execute("""INSERT INTO additions
                  (product, amount_ml, scoop_ml, context, flow_id, added_at)
                  VALUES (?, ?, ?, ?, ?, ?)""",
               (product, amount_ml, scoop_ml, context, flow_id, stamp()))


def _flow(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    value = dict(row)
    value["meta"] = json.loads(value.pop("meta_json"))
    return value


def active_flow(db: sqlite3.Connection) -> dict | None:
    row = db.execute("SELECT * FROM flows WHERE completed_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return _flow(row)


def start_flow(db: sqlite3.Connection, kind: str, meta: dict) -> None:
    now = stamp()
    if kind == "new_water":
        db.execute("UPDATE settings SET water_changed_at = ? WHERE id = 1", (now,))
    db.execute("UPDATE flows SET completed_at = ?, updated_at = ? WHERE completed_at IS NULL", (now, now))
    db.execute("""INSERT INTO flows (kind, step, meta_json, created_at, updated_at)
                  VALUES (?, 0, ?, ?, ?)""", (kind, json.dumps(meta), now, now))


def advance_flow(db: sqlite3.Connection, flow_id: int) -> None:
    db.execute("UPDATE flows SET step = step + 1, updated_at = ? WHERE id = ?", (stamp(), flow_id))


def finish_flow(db: sqlite3.Connection, flow_id: int) -> None:
    now = stamp()
    db.execute("UPDATE flows SET completed_at = ?, updated_at = ? WHERE id = ?", (now, now, flow_id))
